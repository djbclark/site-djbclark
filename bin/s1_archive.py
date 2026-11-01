#!/usr/bin/env python3
"""S1 archive: per-source zstd JSONL files, a drop-in replacement for EvidenceStore.

Design contract: docs/plans/s1-archive-ugrep.md (sections 2-5 and 7). One file per
(producer, source_uri) under ``<root>/sessions/<producer>/<h2>/<slug>-<h12>.jsonl.zst``;
each flush appends one zstd frame (a file is a concatenation of frames, read as one
stream by ``compression.zstd``, ``zstd -d`` and ``ugrep -z``). Small state (checkpoints,
gaps, per-producer heads) lives under ``<root>/state/``.

Invariants this module keeps:

- raw bytes are stored exactly: JSON string when they are valid UTF-8, else base64;
  ``sha256`` is always of the bytes, so any reader can verify losslessness itself;
- a frame is durable (``fsync``) before the checkpoint that depends on it is written;
- a torn tail frame (crash mid-write) is repaired when the file is next loaded for a
  write; damage anywhere else raises ``ArchiveCorrupt`` and the file is left untouched;
- concurrency: every writer of a source file (and of a state file) holds an advisory
  ``fcntl.flock(LOCK_EX)`` on that file around "load index + append", then re-checks
  that the path still names the locked inode (compaction replaces files). A flush
  re-reads the file whenever its (inode, size) differs from what this process last
  saw, and drops pending records another writer already stored, so two stores on one
  root lose no event and write no duplicate. ``put_event`` may still report
  ``created=True`` for a record a concurrent writer stored first; the file never
  holds it twice.

Nothing derived from log content ever becomes a path component: the file name is
``slug + sha256`` hex, the slug restricted to ``[A-Za-z0-9._-]``.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from compression import zstd
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("s1_archive")

DEFAULT_ROOT = Path(
    os.environ.get("S1_ARCHIVE_ROOT") or Path.home() / ".local" / "share" / "s1-archive"
)
RECORD_VERSION = 1
SUFFIX = ".jsonl.zst"
TMP_SUFFIX = ".compact-tmp"
APPEND_LEVEL = 3
COMPACT_LEVEL = 12
COMPACT_MIN_AGE_SECONDS = 6 * 3600
FLUSH_BYTES = 4 * 1024 * 1024
FLUSH_TOTAL_BYTES = 64 * 1024 * 1024
SLUG_LIMIT = 48
_CHUNK = 256 * 1024

TS_SOURCES = ("producer", "filesystem", "ingest", "inferred")
ROLES = ("user", "assistant", "system", "tool", "unknown")
ORIGINS = ("human", "model", "tool", "web", "system", "derived")

_SEP = "\x1f"
_SLUG_DROP = re.compile(r"[^A-Za-z0-9._-]")
_P = zstd.CompressionParameter


def now_iso() -> str:
    """RFC 3339 UTC with a literal Z."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def format_age(seconds: int) -> str:
    if seconds < 60:
        return f"{max(seconds, 0)}s"
    minutes, hours, days = seconds // 60, seconds // 3600, seconds // 86400
    if days:
        return f"{days}d{hours % 24}h"
    if hours:
        return f"{hours}h{minutes % 60}m"
    return f"{minutes}m"


def derive_event_id(
    producer: str, source_uri: str, source_locator: str, raw_sha256: str
) -> str:
    """producer | source_uri | source_locator | raw_sha256, same as EvidenceStore."""
    joined = _SEP.join((producer, source_uri, source_locator, raw_sha256))
    return hashlib.sha256(joined.encode("utf-8", "surrogatepass")).hexdigest()


class SourceMutated(RuntimeError):
    """Same source coordinates, different bytes: the source was not immutable."""


class ArchiveCorrupt(RuntimeError):
    """A source file is damaged somewhere other than a torn tail frame."""

    def __init__(self, path: Path | str, detail: str) -> None:
        super().__init__(f"{path}: {detail}")
        self.path = Path(path)
        self.detail = detail


class MaintenanceLocked(RuntimeError):
    """maintenance.lock exists: compaction must not run."""


# -- paths ---------------------------------------------------------------


def _slug(source_uri: str) -> str:
    parts = [p for p in source_uri.split("/") if p]
    base = parts[-1] if parts else ""
    return _SLUG_DROP.sub("", base)[:SLUG_LIMIT] or "session"


def _producer_dir(producer: str) -> str:
    # Leading dots are dropped so "." / ".." can never name a directory.
    return _SLUG_DROP.sub("", producer)[:SLUG_LIMIT].lstrip(".") or "producer"


def source_hash(producer: str, source_uri: str) -> str:
    return hashlib.sha256(
        f"{producer}\0{source_uri}".encode("utf-8", "surrogatepass")
    ).hexdigest()


def _mkdir_private(path: Path) -> None:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        return
    os.chmod(path, 0o700)  # umask can only remove bits, but be explicit


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# -- zstd framing ----------------------------------------------------------


def _compress_frame(payload: bytes, level: int = APPEND_LEVEL) -> bytes:
    # The content checksum makes a flipped byte inside a frame a hard error on read.
    return zstd.compress(payload, options={_P.compression_level: level, _P.checksum_flag: 1})


class _FrameError(Exception):
    def __init__(self, offset: int, detail: str) -> None:
        super().__init__(detail)
        self.offset = offset


_MAGIC = b"\x28\xb5\x2f\xfd"


def _decode_frames(data: bytes) -> tuple[list[bytes], int, bool]:
    """Decode concatenated zstd frames.

    Returns (decoded frames, offset of the end of the last complete frame, torn).
    ``torn`` means the data ends inside a frame (a prefix of a valid frame). Bytes
    that are not a valid frame raise _FrameError: that is corruption, not a torn tail.
    """
    view = memoryview(data)
    total = len(view)
    frames: list[bytes] = []
    pos = 0
    while pos < total:
        decoder = zstd.ZstdDecompressor()
        parts: list[bytes] = []
        cursor = pos
        while True:
            chunk = view[cursor : cursor + _CHUNK]
            try:
                parts.append(decoder.decompress(chunk))
            except zstd.ZstdError as exc:
                raise _FrameError(pos, str(exc)) from exc
            if decoder.eof:
                cursor += len(chunk) - len(decoder.unused_data)
                break
            cursor += len(chunk)
            if cursor >= total:
                if data.find(_MAGIC, pos + 1) != -1:
                    # A real torn tail is one partial frame. Another frame header inside
                    # it means damage earlier than the tail swallowed later frames:
                    # never truncate that away.
                    raise _FrameError(pos, "incomplete frame followed by another frame header")
                return frames, pos, True
        frames.append(b"".join(parts))
        pos = cursor
    return frames, pos, False


def count_frames(data: bytes) -> int:
    return len(_decode_frames(data)[0])


# -- record encoding ---------------------------------------------------------


def _dumps(obj: dict[str, Any]) -> bytes:
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:  # a lone surrogate in some metadata string
        return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _event_record(
    *,
    event_id: str,
    producer: str,
    source_uri: str,
    source_locator: str,
    ts_utc: str,
    role: str,
    event_type: str,
    origin: str,
    account_id: str,
    scope: str,
    sensitivity: str,
    ingest_batch: str,
    ts_source: str,
    content_encoding: str,
    producer_version: str | None,
    producer_session_id: str | None,
    source_seq: int | None,
    tool_name: str | None,
    tool_call_id: str | None,
    media_type: str | None,
    digest: str,
    raw: bytes,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "v": RECORD_VERSION,
        "t": "ev",
        "id": event_id,
        "producer": producer,
        "source_uri": source_uri,
        "source_locator": source_locator,
        "ts": ts_utc,
        "role": role,
        "event_type": event_type,
        "origin": origin,
        "account_id": account_id,
        "scope": scope,
        "sensitivity": sensitivity,
        "ingest_batch": ingest_batch,
        "ts_source": ts_source,
        "content_encoding": content_encoding,
        "producer_version": producer_version,
        "producer_session_id": producer_session_id,
        "source_seq": source_seq,
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "media_type": media_type,
        "sha256": digest,
        "size": len(raw),
        "ingested": now_iso(),
    }
    try:
        record["raw"] = raw.decode("utf-8")
    except UnicodeDecodeError:
        record["raw_b64"] = base64.b64encode(raw).decode("ascii")
    return record


def _raw_of(record: dict[str, Any]) -> bytes:
    if "raw" in record:
        return record["raw"].encode("utf-8")
    return base64.b64decode(record["raw_b64"])


def _event_dict(record: dict[str, Any]) -> dict[str, Any]:
    """Decoded event with the column names EvidenceStore rows had, plus raw bytes."""
    return {
        "event_id": record["id"],
        "producer": record["producer"],
        "producer_version": record.get("producer_version"),
        "account_id": record.get("account_id"),
        "source_uri": record["source_uri"],
        "source_locator": record["source_locator"],
        "producer_session_id": record.get("producer_session_id"),
        "source_seq": record.get("source_seq"),
        "ts_utc": record["ts"],
        "ts_source": record.get("ts_source"),
        "role": record.get("role"),
        "event_type": record.get("event_type"),
        "tool_name": record.get("tool_name"),
        "tool_call_id": record.get("tool_call_id"),
        "raw_sha256": record["sha256"],
        "raw_size": record["size"],
        "content_encoding": record.get("content_encoding"),
        "origin": record.get("origin"),
        "scope": record.get("scope"),
        "sensitivity": record.get("sensitivity"),
        "ingest_batch": record.get("ingest_batch"),
        "media_type": record.get("media_type"),
        "ingested": record.get("ingested"),
        "raw": _raw_of(record),
    }


class _Scan:
    """Index of one source file: what a writer needs to stay idempotent."""

    __slots__ = ("locators", "conv", "ids", "frames", "valid_end", "torn", "records")

    def __init__(self) -> None:
        self.locators: dict[str, tuple[str, str]] = {}
        self.conv: dict[tuple[str, str], tuple[str, float | None]] = {}
        self.ids: list[str] = []
        self.frames = 0
        self.valid_end = 0
        self.torn = False
        self.records = 0


def _frames(path: Path, data: bytes) -> tuple[list[bytes], int, bool]:
    """_decode_frames, with corruption reported as ArchiveCorrupt naming the file."""
    try:
        return _decode_frames(data)
    except _FrameError as exc:
        raise ArchiveCorrupt(path, f"corrupt frame at byte {exc.offset}: {exc}") from exc


def _frame_records(
    path: Path, frames: list[bytes]
) -> Iterator[tuple[dict[str, Any], int]]:
    """Yield (record, frame_index) for decoded frames; raise ArchiveCorrupt."""
    for index, frame in enumerate(frames):
        if not frame.endswith(b"\n"):
            raise ArchiveCorrupt(path, f"frame {index} does not end with a newline")
        for line in frame.split(b"\n")[:-1]:
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise ArchiveCorrupt(path, f"frame {index}: bad JSON line: {exc}") from exc
            if not isinstance(record, dict):
                raise ArchiveCorrupt(path, f"frame {index}: record is not an object")
            yield record, index


def _iter_records(path: Path, data: bytes) -> Iterator[tuple[dict[str, Any], int]]:
    """Records of every complete frame; a torn tail is skipped (write in flight)."""
    yield from _frame_records(path, _frames(path, data)[0])


def _scan(
    path: Path, data: bytes, expected: tuple[str, str] | None = None
) -> _Scan:
    frames, end, torn = _frames(path, data)
    scan = _Scan()
    scan.frames, scan.valid_end, scan.torn = len(frames), end, torn
    for record, _index in _frame_records(path, frames):
        kind = record.get("t")
        if kind == "ev":
            if expected is not None and (
                record.get("producer"),
                record.get("source_uri"),
            ) != expected:
                raise ArchiveCorrupt(
                    path, "file holds another source (hash prefix collision)"
                )
            scan.locators[record["source_locator"]] = (record["id"], record["sha256"])
            scan.ids.append(record["id"])
            scan.records += 1
        elif kind == "conv":
            scan.conv[(record["id"], record["conversation_id"])] = (
                record.get("assigned_by"),
                record.get("confidence"),
            )
    return scan


def _read_fd(fd: int) -> bytes:
    size = os.fstat(fd).st_size
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        chunk = os.pread(fd, min(size - offset, 8 * 1024 * 1024), offset)
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
    return b"".join(chunks)


def _read_file(path: Path) -> tuple[bytes, tuple[int, int]]:
    fd = os.open(path, os.O_RDONLY)
    try:
        data = _read_fd(fd)
        return data, (os.fstat(fd).st_ino, len(data))
    finally:
        os.close(fd)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


def _open_locked(path: Path, *, create: bool = True) -> int:
    """Open `path` O_APPEND with LOCK_EX held and verified to still be the path's inode."""
    flags = os.O_RDWR | os.O_APPEND | (os.O_CREAT if create else 0)
    while True:
        fd = os.open(path, flags, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            held = os.fstat(fd)
            try:
                current = os.stat(path)
            except FileNotFoundError:
                current = None
            if (
                current is not None
                and current.st_ino == held.st_ino
                and current.st_dev == held.st_dev
            ):
                if held.st_size == 0 and held.st_mode & 0o777 != 0o600:
                    os.fchmod(fd, 0o600)
                return fd
        except BaseException:
            os.close(fd)
            raise
        os.close(fd)  # replaced (compaction) or unlinked while we waited: retry


class _Pending:
    __slots__ = ("line", "kind", "locator", "event_id", "digest", "conv_key", "conv_val",
                 "producer", "ts")

    def __init__(self, line: bytes, kind: str) -> None:
        self.line = line
        self.kind = kind
        self.locator = self.event_id = self.digest = self.producer = self.ts = ""
        self.conv_key: tuple[str, str] | None = None
        self.conv_val: tuple[str, float | None] | None = None


class _Source:
    __slots__ = ("path", "producer", "source_uri", "locators", "conv", "frames", "sig",
                 "pending", "pending_bytes")

    def __init__(self, path: Path, producer: str, source_uri: str) -> None:
        self.path = path
        self.producer = producer
        self.source_uri = source_uri
        self.locators: dict[str, tuple[str, str]] = {}
        self.conv: dict[tuple[str, str], tuple[str, float | None]] = {}
        self.frames = 0
        self.sig: tuple[int, int] | None = None  # (inode, size) this view matches
        self.pending: list[_Pending] = []
        self.pending_bytes = 0


class _Log:
    """Incremental reader of an append-only JSONL state file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.ino: int | None = None
        self.offset = 0


class ArchiveStore:
    def __init__(
        self,
        root: str | Path = DEFAULT_ROOT,
        *,
        maintenance_lock_path: str | Path | None = None,
    ) -> None:
        self.root = Path(root).expanduser()
        self.sessions = self.root / "sessions"
        self.state = self.root / "state"
        self.maintenance_lock_path = (
            Path(maintenance_lock_path)
            if maintenance_lock_path is not None
            else self.root / "maintenance.lock"
        )
        self._lock = threading.RLock()
        self._ugrep: str | None = shutil.which("ugrep")
        self._sources: dict[Path, _Source] = {}
        self._event_path: dict[str, Path] = {}
        self._pending_total = 0
        self._head_delta: dict[str, dict[str, Any]] = {}
        self.repairs: list[dict[str, Any]] = []
        self._checkpoints: dict[tuple[str, str], dict[str, Any]] = {}
        self._gaps: set[tuple[str, str, str, str | None, str | None]] = set()
        self._cp_log = _Log(self.state / "checkpoints.jsonl")
        self._gap_log = _Log(self.state / "gaps.jsonl")
        self.root.parent.mkdir(parents=True, exist_ok=True)
        for directory in (self.root, self.sessions, self.state):
            _mkdir_private(directory)

    # -- paths ---------------------------------------------------------------

    def source_path(self, producer: str, source_uri: str) -> Path:
        digest = source_hash(producer, source_uri)
        return (
            self.sessions
            / _producer_dir(producer)
            / digest[:2]
            / f"{_slug(source_uri)}-{digest[:12]}{SUFFIX}"
        )

    def _iter_files(self) -> Iterator[Path]:
        if not self.sessions.is_dir():
            return
        for directory, dirs, names in os.walk(self.sessions):
            dirs.sort()
            for name in sorted(names):
                if name.endswith(SUFFIX):
                    yield Path(directory) / name

    # -- loading and writing ---------------------------------------------------

    def _register(self, path: Path, scan: _Scan) -> None:
        for event_id in scan.ids:
            self._event_path[event_id] = path

    def _load_source(self, producer: str, source_uri: str) -> _Source:
        path = self.source_path(producer, source_uri)
        source = self._sources.get(path)
        if source is not None:
            return source
        source = _Source(path, producer, source_uri)
        try:
            data, sig = _read_file(path)
        except FileNotFoundError:
            data, sig = b"", None
        if data:
            scan = _scan(path, data, (producer, source_uri))
            if scan.torn:
                scan, sig = self._repair(path, producer, source_uri)
            source.locators, source.conv = scan.locators, scan.conv
            source.frames, source.sig = scan.frames, sig
            self._register(path, scan)
        self._sources[path] = source
        return source

    def _repair(
        self, path: Path, producer: str, source_uri: str
    ) -> tuple[_Scan, tuple[int, int]]:
        """Truncate a torn tail frame under the file lock; corrupt files are never touched."""
        fd = _open_locked(path, create=False)
        try:
            data = _read_fd(fd)
            scan = _scan(path, data, (producer, source_uri))
            if scan.torn:
                os.ftruncate(fd, scan.valid_end)
                os.fsync(fd)
                info = {
                    "path": str(path),
                    "size_before": len(data),
                    "size_after": scan.valid_end,
                }
                self.repairs.append(info)
                log.warning(
                    "repaired torn tail frame: %s truncated %d -> %d bytes",
                    path,
                    len(data),
                    scan.valid_end,
                )
                scan.torn = False
            return scan, (os.fstat(fd).st_ino, scan.valid_end)
        finally:
            os.close(fd)

    def put_event(
        self,
        *,
        producer: str,
        source_uri: str,
        source_locator: str,
        raw: bytes,
        ts_utc: str,
        role: str = "unknown",
        event_type: str = "message",
        origin: str = "model",
        account_id: str = "local",
        scope: str = "private",
        sensitivity: str = "normal",
        ingest_batch: str = "manual",
        ts_source: str = "producer",
        content_encoding: str = "utf-8",
        producer_version: str | None = None,
        producer_session_id: str | None = None,
        source_seq: int | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        media_type: str | None = None,
    ) -> tuple[str, bool]:
        """Idempotently record one event. Returns (event_id, created).

        Same locator and bytes: (existing id, False). Same locator, different
        bytes: SourceMutated. The event is buffered; flush()/close() or a
        checkpoint makes it durable.
        """
        if ts_source not in TS_SOURCES:
            raise ValueError(f"ts_source must be one of {TS_SOURCES}")
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if origin not in ORIGINS:
            raise ValueError(f"origin must be one of {ORIGINS}")
        if not producer:
            raise ValueError("producer must not be empty")
        digest = sha256_bytes(raw)
        event_id = derive_event_id(producer, source_uri, source_locator, digest)
        with self._lock:
            source = self._load_source(producer, source_uri)
            existing = source.locators.get(source_locator)
            if existing is not None:
                if existing[1] != digest:
                    raise SourceMutated(
                        f"{producer}:{source_uri}:{source_locator} previously held "
                        f"{existing[1][:12]}…, now {digest[:12]}…"
                    )
                return existing[0], False
            record = _event_record(
                event_id=event_id,
                producer=producer,
                source_uri=source_uri,
                source_locator=source_locator,
                ts_utc=ts_utc,
                role=role,
                event_type=event_type,
                origin=origin,
                account_id=account_id,
                scope=scope,
                sensitivity=sensitivity,
                ingest_batch=ingest_batch,
                ts_source=ts_source,
                content_encoding=content_encoding,
                producer_version=producer_version,
                producer_session_id=producer_session_id,
                source_seq=source_seq,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                media_type=media_type,
                digest=digest,
                raw=raw,
            )
            item = _Pending(_dumps(record) + b"\n", "ev")
            item.locator, item.event_id, item.digest = source_locator, event_id, digest
            item.producer, item.ts = producer, ts_utc
            self._enqueue(source, item)
            source.locators[source_locator] = (event_id, digest)
            self._event_path[event_id] = source.path
            return event_id, True

    def assign_conversation(
        self,
        event_id: str,
        conversation_id: str,
        *,
        assigned_by: str = "adapter",
        confidence: float | None = None,
    ) -> None:
        """Group an event into a conversation; the last record per pair wins."""
        with self._lock:
            path = self._event_path.get(event_id)
            if path is None:
                raise KeyError(event_id)
            source = self._sources[path]
            key = (event_id, conversation_id)
            value = (assigned_by, confidence)
            if source.conv.get(key) == value:
                return  # unchanged: re-assigning each scan must not grow the file
            record = {
                "v": RECORD_VERSION,
                "t": "conv",
                "id": event_id,
                "conversation_id": conversation_id,
                "assigned_by": assigned_by,
                "confidence": confidence,
                "at": now_iso(),
            }
            item = _Pending(_dumps(record) + b"\n", "conv")
            item.conv_key, item.conv_val = key, value
            self._enqueue(source, item)
            source.conv[key] = value

    def _enqueue(self, source: _Source, item: _Pending) -> None:
        source.pending.append(item)
        source.pending_bytes += len(item.line)
        self._pending_total += len(item.line)
        if source.pending_bytes >= FLUSH_BYTES:
            self._flush_source(source)
        elif self._pending_total >= FLUSH_TOTAL_BYTES:
            self.flush()

    def _flush_source(self, source: _Source) -> dict[str, Any] | None:
        """Append `source.pending` as one frame. Returns this flush's head delta."""
        if not source.pending:
            return None
        path = source.path
        for parent in (path.parent.parent, path.parent):
            _mkdir_private(parent)
        fd = _open_locked(path)
        conflict: SourceMutated | None = None
        try:
            held = os.fstat(fd)
            rescanned = source.sig != (held.st_ino, held.st_size)
            if rescanned:
                # Someone else wrote (or compacted) since we looked: re-read under the lock.
                data = _read_fd(fd)
                scan = _scan(path, data, (source.producer, source.source_uri))
                if scan.torn:
                    os.ftruncate(fd, scan.valid_end)
                    os.fsync(fd)
                    self.repairs.append(
                        {"path": str(path), "size_before": len(data),
                         "size_after": scan.valid_end}
                    )
                    log.warning("repaired torn tail frame: %s", path)
                source.locators, source.conv = scan.locators, scan.conv
                source.frames = scan.frames
                self._register(path, scan)
                size = scan.valid_end
            else:
                size = held.st_size
            lines: list[bytes] = []
            delta: dict[str, Any] = {}
            for item in source.pending:
                if item.kind == "ev":
                    if rescanned:
                        # Pending events were optimistic; the file is the truth now.
                        on_disk = source.locators.get(item.locator)
                        if on_disk is not None:
                            if on_disk[1] != item.digest and conflict is None:
                                conflict = SourceMutated(
                                    f"{item.producer}:{source.source_uri}:{item.locator} "
                                    f"previously held {on_disk[1][:12]}…, now {item.digest[:12]}…"
                                )
                            continue
                        source.locators[item.locator] = (item.event_id, item.digest)
                    entry = delta.setdefault(
                        item.producer, {"count": 0, "newest_ts": item.ts}
                    )
                    entry["count"] += 1
                    entry["newest_ts"] = max(entry["newest_ts"], item.ts)
                elif rescanned:
                    if source.conv.get(item.conv_key) == item.conv_val:
                        continue  # already stored by the writer we raced with
                    source.conv[item.conv_key] = item.conv_val
                lines.append(item.line)
            if lines:
                frame = _compress_frame(b"".join(lines))
                source.sig = None
                _write_all(fd, frame)
                os.fsync(fd)
                if size == 0:
                    _fsync_dir(path.parent)
                source.frames += 1
                source.sig = (held.st_ino, size + len(frame))
            else:
                source.sig = (held.st_ino, size)
        finally:
            os.close(fd)
        self._pending_total -= source.pending_bytes
        source.pending, source.pending_bytes = [], 0
        if conflict is not None:
            self._merge_heads(delta)
            raise conflict
        return delta

    def flush(self) -> None:
        """Make every buffered record durable, then update state/heads.json."""
        with self._lock:
            first: BaseException | None = None
            for source in list(self._sources.values()):
                if not source.pending:
                    continue
                try:
                    delta = self._flush_source(source)
                except BaseException as exc:  # keep flushing others, raise the first
                    if first is None:
                        first = exc
                    continue
                if delta:
                    self._merge_heads(delta)
            if self._head_delta:
                self._apply_heads()
            if first is not None:
                raise first

    def _merge_heads(self, delta: dict[str, Any]) -> None:
        for producer, entry in delta.items():
            have = self._head_delta.setdefault(
                producer, {"count": 0, "newest_ts": entry["newest_ts"]}
            )
            have["count"] += entry["count"]
            have["newest_ts"] = max(have["newest_ts"], entry["newest_ts"])

    # -- heads ---------------------------------------------------------------

    def _heads_path(self) -> Path:
        return self.state / "heads.json"

    def _read_heads(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self._heads_path().read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except ValueError:
            log.warning("state/heads.json unreadable; run `verify --rebuild-heads`")
            return {}
        return data if isinstance(data, dict) else {}

    def _write_heads(self, heads: dict[str, dict[str, Any]]) -> None:
        target = self._heads_path()
        temp = target.with_name(f"heads.json.{os.getpid()}.{threading.get_ident()}.tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            _write_all(fd, json.dumps(heads, sort_keys=True, indent=1).encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp, target)

    def _heads_locked(self) -> int:
        fd = os.open(self.state / "heads.lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def _apply_heads(self) -> None:
        """Merge this process's deltas into heads.json atomically (read-merge-replace)."""
        fd = self._heads_locked()
        try:
            heads = self._read_heads()
            stamp = now_iso()
            for producer, entry in self._head_delta.items():
                head = heads.setdefault(
                    producer, {"newest_ts": entry["newest_ts"], "count": 0, "last_ingest": stamp}
                )
                head["count"] = int(head.get("count", 0)) + entry["count"]
                head["newest_ts"] = max(head.get("newest_ts") or "", entry["newest_ts"])
                head["last_ingest"] = stamp
            self._write_heads(heads)
            self._head_delta = {}
        finally:
            os.close(fd)

    def heads(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            self.flush()
            return self._read_heads()

    def rebuild_heads(self) -> dict[str, dict[str, Any]]:
        """Recompute heads.json from the files (heads are derived, files are truth)."""
        with self._lock:
            self.flush()
            heads: dict[str, dict[str, Any]] = {}
            for path in self._iter_files():
                data, _sig = _read_file(path)
                for record, _i in _iter_records(path, data):
                    if record.get("t") != "ev":
                        continue
                    head = heads.setdefault(
                        record["producer"],
                        {"newest_ts": record["ts"], "count": 0, "last_ingest": ""},
                    )
                    head["count"] += 1
                    head["newest_ts"] = max(head["newest_ts"], record["ts"])
                    head["last_ingest"] = max(
                        head["last_ingest"], record.get("ingested") or ""
                    )
            fd = self._heads_locked()
            try:
                self._write_heads(heads)
            finally:
                os.close(fd)
            return heads

    # -- state logs: checkpoints and gaps ----------------------------------------

    def _append_state(self, name: str, record: dict[str, Any]) -> None:
        line = _dumps(record) + b"\n"
        path = self.state / name
        fd = _open_locked(path)
        try:
            size = os.fstat(fd).st_size
            if size and os.pread(fd, 1, size - 1) != b"\n":
                line = b"\n" + line  # a crash left a torn last line: do not glue onto it
            _write_all(fd, line)
            os.fsync(fd)
            if size == 0:
                _fsync_dir(self.state)
        finally:
            os.close(fd)

    def _refresh(self, tracker: _Log, apply: Any, reset: Any) -> None:
        try:
            st = os.stat(tracker.path)
        except FileNotFoundError:
            return
        if tracker.ino != st.st_ino or st.st_size < tracker.offset:
            reset()
            tracker.ino, tracker.offset = st.st_ino, 0
        if st.st_size == tracker.offset:
            return
        with open(tracker.path, "rb") as handle:
            handle.seek(tracker.offset)
            chunk = handle.read(st.st_size - tracker.offset)
        end = chunk.rfind(b"\n") + 1  # only complete lines; a torn tail waits
        for line in chunk[:end].split(b"\n"):
            if not line:
                continue
            try:
                apply(json.loads(line))
            except (ValueError, KeyError, TypeError):
                log.warning("ignoring unreadable line in %s", tracker.path)
        tracker.offset += end

    def _refresh_checkpoints(self) -> None:
        def apply(rec: dict[str, Any]) -> None:
            self._checkpoints[(rec["producer"], rec["source_uri"])] = rec

        self._refresh(self._cp_log, apply, self._checkpoints.clear)

    def _refresh_gaps(self) -> None:
        def apply(rec: dict[str, Any]) -> None:
            self._gaps.add(
                (rec["producer"], rec["source_uri"], rec["reason"],
                 rec.get("from_locator"), rec.get("to_locator"))
            )

        self._refresh(self._gap_log, apply, self._gaps.clear)

    def record_gap(
        self,
        producer: str,
        source_uri: str,
        reason: str,
        *,
        from_locator: str | None = None,
        to_locator: str | None = None,
    ) -> None:
        """Record an interval we know we lack. The same tuple is stored once."""
        key = (producer, source_uri, reason, from_locator, to_locator)
        with self._lock:
            self._refresh_gaps()
            if key in self._gaps:
                return
            self._append_state(
                "gaps.jsonl",
                {"producer": producer, "source_uri": source_uri, "reason": reason,
                 "from_locator": from_locator, "to_locator": to_locator, "at": now_iso()},
            )
            self._gaps.add(key)

    def has_gap(
        self,
        producer: str,
        source_uri: str,
        reason: str,
        from_locator: str | None,
        to_locator: str | None,
    ) -> bool:
        with self._lock:
            self._refresh_gaps()
            return (producer, source_uri, reason, from_locator, to_locator) in self._gaps

    def set_checkpoint(
        self,
        producer: str,
        source_uri: str,
        *,
        source_fingerprint: str,
        committed_locator: str | None,
        adapter_version: str,
    ) -> None:
        """Record how far a source is consumed. Events are made durable first.

        An unchanged checkpoint is not rewritten (its updated_at keeps the time it
        last changed), so a re-scan of an idle source does not grow the state file.
        """
        with self._lock:
            self.flush()  # a checkpoint must never outrun its events
            self._refresh_checkpoints()
            current = self._checkpoints.get((producer, source_uri))
            if (
                current is not None
                and current["fingerprint"] == source_fingerprint
                and current["committed_locator"] == committed_locator
                and current["adapter_version"] == adapter_version
            ):
                return
            record = {
                "producer": producer,
                "source_uri": source_uri,
                "fingerprint": source_fingerprint,
                "committed_locator": committed_locator,
                "adapter_version": adapter_version,
                "at": now_iso(),
            }
            self._append_state("checkpoints.jsonl", record)
            self._checkpoints[(producer, source_uri)] = record

    def checkpoint(self, producer: str, source_uri: str) -> dict[str, Any] | None:
        with self._lock:
            self._refresh_checkpoints()
            rec = self._checkpoints.get((producer, source_uri))
            if rec is None:
                return None
            return {
                "producer": producer,
                "source_uri": source_uri,
                "source_fingerprint": rec["fingerprint"],
                "committed_locator": rec["committed_locator"],
                "adapter_version": rec["adapter_version"],
                "updated_at": rec["at"],
            }

    def checkpoint_source_uris(self, producer: str) -> list[str]:
        with self._lock:
            self._refresh_checkpoints()
            return sorted(uri for (p, uri) in self._checkpoints if p == producer)

    # -- source queries (replace adapters' direct SQL) ------------------------------

    def _first_record(self, path: Path) -> dict[str, Any] | None:
        decoder = zstd.ZstdDecompressor()
        buffered = b""
        with open(path, "rb") as handle:
            while b"\n" not in buffered:
                chunk = handle.read(64 * 1024)
                if not chunk:
                    break
                try:
                    buffered += decoder.decompress(chunk)
                except zstd.ZstdError:
                    return None
                if decoder.eof:
                    break
        line = buffered.split(b"\n", 1)[0]
        try:
            record = json.loads(line)
        except ValueError:
            return None
        return record if isinstance(record, dict) else None

    def source_uris(self, producer: str, prefix: str | None = None) -> list[str]:
        """Distinct source_uri of `producer` that have events (optional startswith filter)."""
        with self._lock:
            self.flush()
            found: set[str] = set()
            directory = self.sessions / _producer_dir(producer)
            if not directory.is_dir():
                return []
            for path in self._iter_files_under(directory):
                record = self._first_record(path)
                if record and record.get("t") == "ev" and record.get("producer") == producer:
                    found.add(record["source_uri"])
            return sorted(u for u in found if prefix is None or u.startswith(prefix))

    def _iter_files_under(self, directory: Path) -> Iterator[Path]:
        for current, dirs, names in os.walk(directory):
            dirs.sort()
            for name in sorted(names):
                if name.endswith(SUFFIX):
                    yield Path(current) / name

    def source_locators(self, producer: str, source_uri: str) -> set[str]:
        with self._lock:
            return set(self._load_source(producer, source_uri).locators)

    def has_locator_prefix(self, producer: str, source_uri: str, prefix: str) -> bool:
        with self._lock:
            return any(
                loc.startswith(prefix)
                for loc in self._load_source(producer, source_uri).locators
            )

    # -- reads -------------------------------------------------------------------------

    def iter_source(self, producer: str, source_uri: str) -> Iterator[dict[str, Any]]:
        """Event dicts of one source in file order, `raw` as bytes."""
        with self._lock:
            self.flush()
            path = self.source_path(producer, source_uri)
        try:
            data, _sig = _read_file(path)
        except FileNotFoundError:
            return
        for record, _i in self._records_of(path, data):
            if record.get("t") == "ev":
                yield _event_dict(record)

    @staticmethod
    def _records_of(path: Path, data: bytes) -> Iterator[tuple[dict[str, Any], int]]:
        # A torn tail is a write in flight (or awaiting repair): readers skip it.
        return _iter_records(path, data)

    def _find_files(self, needles: list[str]) -> list[Path]:
        """Files whose decoded text contains any needle: ugrep when present, else Python."""
        with self._lock:
            self.flush()
        if not self.sessions.is_dir():
            return []
        if self._ugrep:
            argv = [self._ugrep, "-z", "-F", "-l", "-0", "-s", "-r",
                    f"--include=*{SUFFIX}"]
            for needle in needles:
                argv += ["-e", needle]
            argv += ["--", str(self.sessions)]
            try:
                result = subprocess.run(argv, capture_output=True, timeout=900)
            except (OSError, subprocess.SubprocessError) as exc:
                log.warning("ugrep failed (%s); scanning in Python", exc)
            else:
                if result.returncode in (0, 1):
                    return [Path(os.fsdecode(p)) for p in result.stdout.split(b"\0") if p]
                log.warning("ugrep exit %d; scanning in Python", result.returncode)
        encoded = [n.encode("utf-8", "surrogatepass") for n in needles]
        hits: list[Path] = []
        for path in self._iter_files():
            try:
                data, _sig = _read_file(path)
                frames, _end, _torn = _decode_frames(data)
            except (OSError, _FrameError) as exc:
                log.warning("skipping unreadable %s: %s", path, exc)
                continue
            text = b"".join(frames)
            if any(n in text for n in encoded):
                hits.append(path)
        return hits

    def _locate_event(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            self.flush()
            known = self._event_path.get(event_id)
        paths = [known] if known is not None else self._find_files([event_id])
        for path in paths:
            try:
                data, _sig = _read_file(path)
            except FileNotFoundError:
                continue
            for record, _i in self._records_of(path, data):
                if record.get("t") == "ev" and record["id"] == event_id:
                    return record
        return None

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        record = self._locate_event(event_id)
        return None if record is None else _event_dict(record)

    def raw_for(self, event_id: str) -> bytes:
        """Exact producer bytes for an event, hash-verified."""
        record = self._locate_event(event_id)
        if record is None:
            raise KeyError(event_id)
        payload = _raw_of(record)
        if sha256_bytes(payload) != record["sha256"]:
            raise SourceMutated(f"archive record for {event_id} does not match its recorded hash")
        return payload

    def conversation(self, conversation_id: str) -> Iterator[dict[str, Any]]:
        """Events of a conversation ordered by (ts, producer, source_uri, source_seq, file order)."""
        needles = [json.dumps(conversation_id, ensure_ascii=False)]
        ascii_form = json.dumps(conversation_id)
        if ascii_form != needles[0]:
            needles.append(ascii_form)
        needles = ['"conversation_id":' + n for n in needles]
        rows: list[tuple[Any, ...]] = []
        for path in self._find_files(needles):
            try:
                data, _sig = _read_file(path)
            except FileNotFoundError:
                continue
            members: set[str] = set()
            events: list[tuple[int, dict[str, Any]]] = []
            for order, (record, _i) in enumerate(self._records_of(path, data)):
                if record.get("t") == "conv" and record["conversation_id"] == conversation_id:
                    members.add(record["id"])
                elif record.get("t") == "ev":
                    events.append((order, record))
            for order, record in events:
                if record["id"] in members:
                    seq = record.get("source_seq")
                    rows.append(
                        (record["ts"], record["producer"], record["source_uri"],
                         seq is not None, seq or 0, str(path), order, record)
                    )
        rows.sort(key=lambda r: r[:7])
        for row in rows:
            yield _event_dict(row[7])

    # -- integrity and stats ----------------------------------------------------------------

    def verify(self, *, sample: int | None = None, rebuild_heads: bool = False) -> dict[str, Any]:
        """Decode every file and recompute each sha256. Read-only except `rebuild_heads`.

        `sample` stops after that many events. A torn tail or a corrupt file makes
        `healthy` False. heads.json drift is reported (`heads_ok`) but does not.
        """
        self.flush()
        report: dict[str, Any] = {"checked_at": now_iso()}
        torn_files: list[dict[str, Any]] = []
        corrupt_files: list[dict[str, str]] = []
        hash_mismatched: list[str] = []
        id_mismatched: list[str] = []
        duplicates: list[str] = []
        per_producer: dict[str, int] = {}
        files = events = ok = conv_records = 0
        done = False
        for path in self._iter_files():
            if done:
                break
            files += 1
            try:
                data, _sig = _read_file(path)
                frames, end, torn = _decode_frames(data)
            except _FrameError as exc:
                corrupt_files.append({"path": str(path), "error": str(exc)})
                continue
            if torn:
                torn_files.append({"path": str(path), "valid_end": end, "size": len(data)})
            seen: set[tuple[str, str]] = set()
            try:
                for record, _i in _frame_records(path, frames):
                    if record.get("t") == "conv":
                        conv_records += 1
                        continue
                    if record.get("t") != "ev":
                        continue
                    events += 1
                    per_producer[record["producer"]] = per_producer.get(record["producer"], 0) + 1
                    payload = _raw_of(record)
                    if sha256_bytes(payload) != record["sha256"] or len(payload) != record["size"]:
                        hash_mismatched.append(record["id"])
                    else:
                        ok += 1
                    if record["id"] != derive_event_id(
                        record["producer"], record["source_uri"],
                        record["source_locator"], record["sha256"]):
                        id_mismatched.append(record["id"])
                    key = (record["source_uri"], record["source_locator"])
                    if key in seen:
                        duplicates.append(record["id"])
                    seen.add(key)
                    if sample and events >= sample:
                        done = True
                        break
            except ArchiveCorrupt as exc:
                corrupt_files.append({"path": str(path), "error": exc.detail})
        heads_ok = None
        if rebuild_heads and not sample:
            self.rebuild_heads()
        if not sample and not corrupt_files:
            have = {p: int(h.get("count", 0)) for p, h in self._read_heads().items()}
            heads_ok = have == per_producer
        self._refresh_gaps()
        report.update(
            files=files,
            events=events,
            conversation_records=conv_records,
            hash_ok=ok,
            hash_mismatched=hash_mismatched,
            id_mismatched=id_mismatched,
            duplicate_locators=duplicates,
            torn_files=torn_files,
            corrupt_files=corrupt_files,
            producers=per_producer,
            heads_ok=heads_ok,
            gaps=len(self._gaps),
        )
        report["healthy"] = not (
            torn_files or corrupt_files or hash_mismatched or id_mismatched or duplicates
        )
        return report

    def stats(self, *, full: bool = False) -> dict[str, Any]:
        """Counts from heads.json (flushed first). `full` also scans files for sizes/sessions."""
        with self._lock:
            self.flush()
            heads = self._read_heads()
            self._refresh_gaps()
            self._refresh_checkpoints()
            files = disk = 0
            for path in self._iter_files():
                files += 1
                disk += path.stat().st_size
            result: dict[str, Any] = {
                "root": str(self.root),
                "events": sum(int(h.get("count", 0)) for h in heads.values()),
                "producers": len(heads),
                "files": files,
                "disk_bytes": disk,
                "gaps": len(self._gaps),
                "checkpoints": len(self._checkpoints),
                "schema_version": RECORD_VERSION,
                "newest_by_producer": self.newest_by_producer(),
            }
            if full:
                raw_bytes = 0
                sessions: set[tuple[str, str]] = set()
                conversations: set[str] = set()
                for path in self._iter_files():
                    data, _sig = _read_file(path)
                    for record, _i in self._records_of(path, data):
                        if record.get("t") == "ev":
                            raw_bytes += record["size"]
                            if record.get("producer_session_id") is not None:
                                sessions.add((record["producer"], record["producer_session_id"]))
                        elif record.get("t") == "conv":
                            conversations.add(record["conversation_id"])
                result.update(
                    raw_bytes=raw_bytes, sessions=len(sessions), conversations=len(conversations)
                )
            return result

    def newest_by_producer(self, now: int | None = None) -> dict[str, dict[str, Any]]:
        """Newest event ts per producer and its age (same shape as EvidenceStore)."""
        now = int(datetime.now(timezone.utc).timestamp()) if now is None else now
        newest: dict[str, dict[str, Any]] = {}
        with self._lock:
            self.flush()
            heads = self._read_heads()
        for producer in sorted(heads):
            ts = heads[producer].get("newest_ts")
            entry: dict[str, Any] = {"newest_ts_utc": ts, "age_seconds": None, "age": None}
            try:
                epoch = int(datetime.fromisoformat(ts).timestamp()) if ts else None
            except ValueError:
                epoch = None
            if epoch is not None:
                entry["age_seconds"] = now - epoch
                entry["age"] = format_age(now - epoch)
            newest[producer] = entry
        return newest

    # -- compaction ---------------------------------------------------------------------------------

    def _check_maintenance(self) -> None:
        if self.maintenance_lock_path.exists():
            raise MaintenanceLocked(
                f"{self.maintenance_lock_path} exists: refusing to compact"
            )

    def _verify_compacted(self, temp: Path, original: bytes) -> None:
        """Re-read the rewritten file: one frame, same bytes, every sha256 recomputed."""
        data, _sig = _read_file(temp)
        frames, end, torn = _decode_frames(data)
        if torn or end != len(data) or len(frames) != 1:
            raise ArchiveCorrupt(temp, "compacted file is not exactly one complete frame")
        if frames[0] != original:
            raise ArchiveCorrupt(temp, "compacted content differs from the original")
        before = original.count(b"\n")
        after = 0
        for record, _i in _frame_records(temp, frames):
            after += 1
            if record.get("t") == "ev" and sha256_bytes(_raw_of(record)) != record["sha256"]:
                raise ArchiveCorrupt(temp, f"sha256 mismatch for {record['id']}")
        if before != after:
            raise ArchiveCorrupt(temp, f"record count {after} != original {before}")

    def _compact_file(self, path: Path, cutoff: float) -> tuple[str, int, int]:
        """Returns (outcome, bytes_before, bytes_after)."""
        try:
            if os.stat(path).st_mtime > cutoff:
                return "young", 0, 0
            fd = _open_locked(path, create=False)
        except FileNotFoundError:
            return "gone", 0, 0
        temp = path.with_name(path.name + TMP_SUFFIX)
        try:
            held = os.fstat(fd)
            if held.st_mtime > cutoff:
                return "young", 0, 0
            data = _read_fd(fd)
            frames, end, torn = _decode_frames(data)
            if torn:
                raise ArchiveCorrupt(path, "torn tail frame; not compacting")
            if len(frames) <= 1:
                return "single", 0, 0
            joined = b"".join(frames)
            if not joined.endswith(b"\n"):
                raise ArchiveCorrupt(path, "decoded content does not end with a newline")
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                _write_all(out, _compress_frame(joined, COMPACT_LEVEL))
                os.fsync(out)
            finally:
                os.close(out)
            try:
                self._verify_compacted(temp, joined)
                self._check_maintenance()
            except BaseException:
                temp.unlink(missing_ok=True)
                raise
            os.replace(temp, path)
            _fsync_dir(path.parent)
            self._sources.pop(path, None)
            return "compacted", len(data), os.stat(path).st_size
        finally:
            os.close(fd)

    def compact(self, *, min_age_seconds: float = COMPACT_MIN_AGE_SECONDS) -> dict[str, Any]:
        """Rewrite multi-frame files older than `min_age_seconds` as one level-12 frame.

        Runs under the caller's ingest lock (the cycle's). Refuses while
        maintenance.lock exists; never touches a young file; the original stays
        in place unless the rewrite verified.
        """
        with self._lock:
            self._check_maintenance()
            self.flush()
            cutoff = time.time() - min_age_seconds
            report: dict[str, Any] = {
                "files": 0, "compacted": 0, "young": 0, "single": 0,
                "bytes_before": 0, "bytes_after": 0, "errors": [],
            }
            for path in self._iter_files():
                self._check_maintenance()
                report["files"] += 1
                try:
                    outcome, before, after = self._compact_file(path, cutoff)
                except MaintenanceLocked:
                    raise
                except (ArchiveCorrupt, OSError, _FrameError) as exc:
                    report["errors"].append({"path": str(path), "error": str(exc)})
                    continue
                if outcome in report:
                    report[outcome] += 1
                report["bytes_before"] += before
                report["bytes_after"] += after
            for current, _dirs, names in os.walk(self.sessions):
                for name in names:
                    if name.endswith(TMP_SUFFIX):
                        Path(current, name).unlink(missing_ok=True)
            report["state"] = self.compact_state()
            return report

    def compact_state(self) -> dict[str, int]:
        """Rewrite checkpoints.jsonl / gaps.jsonl keeping the last record per key."""
        result: dict[str, int] = {}
        for name, key_of in (
            ("checkpoints.jsonl", lambda r: (r["producer"], r["source_uri"])),
            ("gaps.jsonl", lambda r: (r["producer"], r["source_uri"], r["reason"],
                                      r.get("from_locator"), r.get("to_locator"))),
        ):
            path = self.state / name
            if not path.exists():
                continue
            fd = _open_locked(path, create=False)
            try:
                latest: dict[Any, bytes] = {}
                total = 0
                for line in _read_fd(fd).split(b"\n"):
                    if not line:
                        continue
                    total += 1
                    try:
                        latest[key_of(json.loads(line))] = line
                    except (ValueError, KeyError, TypeError):
                        continue
                if len(latest) == total:
                    result[name] = 0
                    continue
                temp = path.with_name(name + ".tmp")
                out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                try:
                    _write_all(out, b"".join(v + b"\n" for v in latest.values()))
                    os.fsync(out)
                finally:
                    os.close(out)
                os.replace(temp, path)
                result[name] = total - len(latest)
            finally:
                os.close(fd)
        return result

    # -- lifecycle ----------------------------------------------------------------------------------------

    def close(self) -> None:
        self.flush()

    def __enter__(self) -> "ArchiveStore":
        return self

    def __exit__(self, *exc: object) -> None:
        if exc[0] is None:
            self.close()
        else:  # still persist what was accepted, but never mask the original error
            try:
                self.close()
            except Exception:
                log.exception("flush on exit failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1 archive (zstd JSONL per source)")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--maintenance-lock", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    stats_cmd = sub.add_parser("stats", help="counts and sizes")
    stats_cmd.add_argument("--full", action="store_true", help="also scan every file")
    verify_cmd = sub.add_parser("verify", help="decode every file, recompute every sha256")
    verify_cmd.add_argument("--sample", type=int, default=None)
    verify_cmd.add_argument("--rebuild-heads", action="store_true")
    compact_cmd = sub.add_parser("compact", help="merge multi-frame files older than 6 h")
    compact_cmd.add_argument(
        "--min-age-hours", type=float, default=COMPACT_MIN_AGE_SECONDS / 3600
    )
    args = parser.parse_args(argv)
    store = ArchiveStore(args.root, maintenance_lock_path=args.maintenance_lock)
    try:
        if args.command == "stats":
            print(json.dumps(store.stats(full=args.full), indent=2))
            return 0
        if args.command == "verify":
            report = store.verify(sample=args.sample, rebuild_heads=args.rebuild_heads)
            print(json.dumps(report, indent=2))
            return 0 if report["healthy"] else 1
        try:
            report = store.compact(min_age_seconds=args.min_age_hours * 3600)
        except MaintenanceLocked as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(report, indent=2))
        return 1 if report["errors"] else 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
