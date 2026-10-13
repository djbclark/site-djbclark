#!/usr/bin/env python3
"""Lossless Cursor agent CLI history adapter for S1.

Only session-local store.db, meta.json and prompt_history.json are inputs.
The Cursor IDE state.vscdb and neighboring tool/credential files are out of
scope. SQLite sources are opened read-only so live WAL contents remain visible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s1_evidence import EvidenceStore, SourceMutated, now_iso

PRODUCER = "cursor-cli"
ADAPTER_VERSION = "cursor-cli-scan-1"
CHAT_ROOT = Path.home() / ".cursor" / "chats"
ACP_ROOT = Path.home() / ".cursor" / "acp-sessions"
CONFIG_CHAT_ROOT = Path.home() / ".config" / "cursor" / "chats"
SESSION_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
BUCKET_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)
ALLOWED_FILES = frozenset({"store.db", "meta.json", "prompt_history.json"})


@dataclass(frozen=True)
class Session:
    session_id: str
    directory: Path
    layout: str

    @property
    def store(self) -> Path:
        return self.directory / "store.db"


def source_uri(session_id: str) -> str:
    """Stable identity: session UUID, never its movable directory path."""
    return f"cursor-cli:{session_id}"


def discover_sessions(
    chats: Path, acp_sessions: Path, config_chats: Path
) -> list[Session]:
    found: list[Session] = []
    for root, layout in ((chats, "chats"), (config_chats, "config-chats")):
        if not root.is_dir():
            continue
        for bucket in sorted(root.iterdir()):
            if (
                bucket.is_symlink()
                or not bucket.is_dir()
                or not BUCKET_RE.fullmatch(bucket.name)
            ):
                continue
            for directory in sorted(bucket.iterdir()):
                if (
                    directory.is_symlink()
                    or not directory.is_dir()
                    or not SESSION_RE.fullmatch(directory.name)
                ):
                    continue
                found.append(Session(directory.name, directory, layout))
    if acp_sessions.is_dir():
        for directory in sorted(acp_sessions.iterdir()):
            if (
                directory.is_symlink()
                or not directory.is_dir()
                or not SESSION_RE.fullmatch(directory.name)
            ):
                continue
            found.append(Session(directory.name, directory, "acp-sessions"))
    return found


def _is_allowlisted(session: Session, path: Path) -> bool:
    if (
        path.name not in ALLOWED_FILES
        or path.parent != session.directory
        or path.is_symlink()
    ):
        return False
    if session.directory.is_symlink() or not session.directory.is_dir():
        return False
    try:
        path.resolve(strict=False).relative_to(session.directory.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def read_allowed_file(session: Session, name: str) -> bytes:
    """Read one allow-listed session file; refuse all neighboring paths first."""
    path = session.directory / name
    if not _is_allowlisted(session, path):
        raise PermissionError("source path is outside the Cursor session allow-list")
    return path.read_bytes()


def _safe_source(path: Path, session: Session) -> bool:
    if (
        path != session.store
        or not _is_allowlisted(session, path)
        or not path.is_file()
    ):
        return False
    for suffix in ("-wal", "-shm"):
        sidecar = path.with_name(path.name + suffix)
        if sidecar.is_symlink():
            return False
    return True


def _readonly_connection(path: Path) -> sqlite3.Connection:
    # Deliberately not immutable=1: SQLite must read a live WAL.
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    con.row_factory = sqlite3.Row
    return con


@contextmanager
def open_store_readonly(session: Session) -> Iterator[sqlite3.Connection]:
    """Read live SQLite/WAL directly; copy only the allowed trio on open failure."""
    if not _safe_source(session.store, session):
        raise PermissionError("store.db is outside the Cursor session allow-list")
    try:
        con = _readonly_connection(session.store)
    except sqlite3.Error:
        # SQLite may be unable to open a live/inaccessible WAL set read-only.
        # The fallback is a disposable copy containing no neighboring files.
        with tempfile.TemporaryDirectory(prefix="s1-cursor-") as temporary:
            copied = Path(temporary) / "store.db"
            for name in ("store.db", "store.db-wal", "store.db-shm"):
                original = session.directory / name
                if original.exists():
                    if original.is_symlink() or not _is_allowlisted(
                        session, original if name == "store.db" else session.store
                    ):
                        raise PermissionError(
                            "SQLite sidecar is outside the Cursor session allow-list"
                        )
                    shutil.copyfile(
                        original,
                        copied
                        if name == "store.db"
                        else copied.with_name("store.db" + name[len("store.db") :]),
                    )
            con = _readonly_connection(copied)
            try:
                yield con
            finally:
                con.close()
        return
    try:
        yield con
    finally:
        con.close()


def _record_gap(
    store: EvidenceStore,
    uri: str,
    reason: str,
    *,
    from_locator: str | None = None,
    to_locator: str | None = None,
    dry_run: bool = False,
) -> int:
    if dry_run:
        return 0
    exists = store.db.execute(
        "SELECT 1 FROM ingest_gap WHERE producer=? AND source_uri=? AND reason=? "
        "AND from_locator IS ? AND to_locator IS ? LIMIT 1",
        (PRODUCER, uri, reason, from_locator, to_locator),
    ).fetchone()
    if exists:
        return 0
    store.record_gap(
        PRODUCER, uri, reason, from_locator=from_locator, to_locator=to_locator
    )
    return 1


def _put_raw(
    store: EvidenceStore,
    session: Session,
    locator: str,
    raw: bytes,
    *,
    event_type: str,
    role: str = "system",
    origin: str = "derived",
    source_seq: int | None = None,
    media_type: str = "application/octet-stream",
    batch: str,
    dry_run: bool,
) -> bool:
    if dry_run:
        return False
    event_id, created = store.put_event(
        producer=PRODUCER,
        source_uri=source_uri(session.session_id),
        source_locator=locator,
        raw=raw,
        ts_utc=now_iso(),
        ts_source="ingest",
        role=role,
        event_type=event_type,
        origin=origin,
        producer_session_id=session.session_id,
        source_seq=source_seq,
        scope=PRODUCER,
        ingest_batch=batch,
        content_encoding="binary" if media_type != "application/json" else "utf-8",
        media_type=media_type,
        sensitivity="sensitive",
    )
    store.assign_conversation(
        event_id,
        f"{PRODUCER}:{session.session_id}",
        assigned_by=ADAPTER_VERSION,
        confidence=1.0,
    )
    return created


def _metadata_events(
    store: EvidenceStore, session: Session, *, batch: str, dry_run: bool
) -> tuple[int, int, int]:
    created = skipped = gaps = 0
    for name, event_type in (
        ("meta.json", "session_meta"),
        ("prompt_history.json", "prompt_history"),
    ):
        path = session.directory / name
        if not path.exists():
            continue
        try:
            raw = read_allowed_file(session, name)
        except (OSError, PermissionError):
            gaps += _record_gap(
                store,
                source_uri(session.session_id),
                "allow-listed session metadata unavailable",
                dry_run=dry_run,
            )
            continue
        digest = hashlib.sha256(raw).hexdigest()
        locator = f"{name}:{digest}"
        if _put_raw(
            store,
            session,
            locator,
            raw,
            event_type=event_type,
            batch=batch,
            dry_run=dry_run,
            media_type="application/json",
        ):
            created += 1
        elif not dry_run:
            skipped += 1

    if not session.store.exists():
        return created, skipped, gaps
    try:
        with open_store_readonly(session) as con:
            tables = {
                str(row[0])
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "meta" not in tables:
                return (
                    created,
                    skipped,
                    gaps
                    + _record_gap(
                        store,
                        source_uri(session.session_id),
                        "meta table absent",
                        dry_run=dry_run,
                    ),
                )
            row = con.execute("SELECT value FROM meta WHERE key='0'").fetchone()
            if row is not None:
                value = row["value"]
                raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
                digest = hashlib.sha256(raw).hexdigest()
                if _put_raw(
                    store,
                    session,
                    f"meta-row:0:{digest}",
                    raw,
                    event_type="session_meta_row",
                    batch=batch,
                    dry_run=dry_run,
                    media_type="application/json",
                ):
                    created += 1
                elif not dry_run:
                    skipped += 1
    except (sqlite3.Error, OSError, PermissionError):
        gaps += _record_gap(
            store,
            source_uri(session.session_id),
            "session metadata row unavailable",
            dry_run=dry_run,
        )
    return created, skipped, gaps


def _event_projection(
    obj: dict[str, Any], session_id: str, rowid: int
) -> tuple[str, str, str, str | None, str | None, str, str]:
    role_text = str(obj.get("role") or "unknown")
    role, origin = {
        "user": ("user", "human"),
        "assistant": ("assistant", "model"),
        "tool": ("tool", "tool"),
        "system": ("system", "system"),
    }.get(role_text, ("unknown", "derived"))
    event_type = "tool_result" if role_text == "tool" else "message"
    tool_name: str | None = None
    tool_call_id: str | None = None
    content = obj.get("content")
    candidates = content if isinstance(content, list) else []
    for index, block in enumerate(candidates):
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type in ("reasoning", "thinking", "redacted-reasoning"):
            event_type = "reasoning"
        elif block_type == "tool-call":
            event_type = "tool_call"
            tool_name = (
                str(block.get("toolName"))
                if block.get("toolName") is not None
                else None
            )
            tool_call_id = (
                str(block.get("toolCallId"))
                if block.get("toolCallId") is not None
                else None
            )
            if not tool_call_id:
                tool_call_id = f"{session_id}:{rowid}:{index}:{tool_name or 'unknown'}"
            break
        elif block_type == "tool-result":
            event_type = "tool_result"
            tool_name = (
                str(block.get("toolName"))
                if block.get("toolName") is not None
                else None
            )
            tool_call_id = (
                str(block.get("toolCallId"))
                if block.get("toolCallId") is not None
                else None
            )
            break
    if tool_call_id is None and isinstance(obj.get("toolCallId"), str):
        tool_call_id = obj["toolCallId"]
        tool_name = str(obj["toolName"]) if obj.get("toolName") is not None else None
    ts_utc, ts_source = _producer_timestamp(obj.get("createdAt"))
    return role, origin, event_type, tool_name, tool_call_id, ts_utc, ts_source


def _producer_timestamp(value: Any) -> tuple[str, str]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            dt = datetime.fromtimestamp(float(value) / 1000, UTC)
            return dt.isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ), "producer"
        except (OverflowError, OSError, ValueError):
            pass
    return now_iso(), "ingest"


def looks_like_protobuf(raw: bytes) -> bool:
    """Validate generic protobuf wire framing without interpreting its schema."""
    if not raw:
        return False
    index = 0
    try:
        while index < len(raw):
            tag = 0
            shift = 0
            while True:
                byte = raw[index]
                index += 1
                tag |= (byte & 0x7F) << shift
                if byte < 0x80:
                    break
                shift += 7
                if shift > 63:
                    return False
            field, wire = tag >> 3, tag & 7
            if field == 0 or wire in (3, 4, 6, 7):
                return False
            if wire == 0:
                while True:
                    byte = raw[index]
                    index += 1
                    if byte < 0x80:
                        break
            elif wire == 1:
                index += 8
            elif wire == 2:
                length = 0
                shift = 0
                while True:
                    byte = raw[index]
                    index += 1
                    length |= (byte & 0x7F) << shift
                    if byte < 0x80:
                        break
                    shift += 7
                    if shift > 63:
                        return False
                index += length
            elif wire == 5:
                index += 4
            if index > len(raw):
                return False
        return index == len(raw)
    except (IndexError, OverflowError):
        return False


def _parse_checkpoint(locator: str | None) -> int:
    if not locator or not locator.startswith("rowid="):
        return 0
    try:
        return int(locator.split("=", 1)[1])
    except ValueError:
        return 0


def _blob_event(
    store: EvidenceStore,
    session: Session,
    rowid: int,
    blob_id: str,
    raw: bytes,
    *,
    batch: str,
    dry_run: bool,
) -> tuple[bool, str]:
    digest = hashlib.sha256(raw).hexdigest()
    locator = (
        f"blob:{blob_id}" if digest == blob_id else f"blob:{blob_id}:rowid:{rowid}"
    )
    media_type = "application/octet-stream"
    role, origin, event_type = "unknown", "derived", "unknown"
    tool_name = tool_call_id = None
    ts_utc, ts_source = now_iso(), "ingest"
    try:
        obj = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        if looks_like_protobuf(raw):
            media_type = "application/x-protobuf"
            classification = "graph_raw"
        else:
            classification = "unparsed"
    else:
        if not isinstance(obj, dict):
            classification = "unparsed"
        else:
            classification = "json_parsed"
            media_type = "application/json"
            if obj.get("role") in ("user", "assistant", "tool", "system"):
                role, origin, event_type, tool_name, tool_call_id, ts_utc, ts_source = (
                    _event_projection(obj, session.session_id, rowid)
                )
            else:
                event_type = "unknown"
    if not dry_run:
        try:
            event_id, created = store.put_event(
                producer=PRODUCER,
                source_uri=source_uri(session.session_id),
                source_locator=locator,
                raw=raw,
                ts_utc=ts_utc,
                ts_source=ts_source,
                role=role,
                origin=origin,
                event_type=event_type,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                producer_session_id=session.session_id,
                source_seq=rowid,
                scope=PRODUCER,
                ingest_batch=batch,
                content_encoding="utf-8"
                if media_type == "application/json"
                else "binary",
                media_type=media_type,
                sensitivity="sensitive",
            )
            store.assign_conversation(
                event_id,
                f"{PRODUCER}:{session.session_id}",
                assigned_by=ADAPTER_VERSION,
                confidence=1.0,
            )
        except SourceMutated:
            return False, "mutated"
        return created, classification
    return False, classification


def scan_session(
    store: EvidenceStore,
    session: Session,
    *,
    batch: str,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int | bool]:
    result: dict[str, int | bool] = {
        "sessions": int(session.store.is_file()),
        "blobs_read": 0,
        "created": 0,
        "skipped": 0,
        "json_parsed": 0,
        "graph_raw": 0,
        "unparsed": 0,
        "gaps": 0,
        "failed": False,
    }
    uri = source_uri(session.session_id)
    meta_created, meta_skipped, meta_gaps = _metadata_events(
        store, session, batch=batch, dry_run=dry_run
    )
    result["created"] = meta_created
    result["skipped"] = meta_skipped
    result["gaps"] = meta_gaps
    if not session.store.exists():
        checkpoint = None if dry_run else store.checkpoint(PRODUCER, uri)
        if checkpoint:
            result["gaps"] = int(result["gaps"]) + _record_gap(
                store,
                uri,
                "session store.db missing; prior evidence may be incomplete",
                dry_run=dry_run,
            )
            result["failed"] = True
        return result

    try:
        with open_store_readonly(session) as con:
            tables = {
                str(row[0])
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "blobs" not in tables or "meta" not in tables:
                raise sqlite3.DatabaseError("required Cursor tables absent")
            columns = {str(row[1]) for row in con.execute('PRAGMA table_info("blobs")')}
            if not {"id", "data"}.issubset(columns):
                raise sqlite3.DatabaseError("unsupported Cursor blob schema")
            high = con.execute("SELECT COALESCE(MAX(rowid),0) FROM blobs").fetchone()[0]
            high = int(high or 0)
            last = (
                con.execute("SELECT id FROM blobs WHERE rowid=?", (high,)).fetchone()
                if high
                else None
            )
            high_id = str(last["id"]) if last else ""
            db_size = session.store.stat().st_size
            checkpoint = None if dry_run else store.checkpoint(PRODUCER, uri)
            committed = _parse_checkpoint(
                checkpoint["committed_locator"] if checkpoint else None
            )
            prior = checkpoint["source_fingerprint"].split(";", 3) if checkpoint else []
            expected_id = prior[2] if len(prior) == 4 else ""
            try:
                prior_size = int(prior[0].removeprefix("size=")) if prior else 0
            except ValueError:
                prior_size = 0
            checkpoint_row = (
                con.execute(
                    "SELECT id FROM blobs WHERE rowid=?", (committed,)
                ).fetchone()
                if committed
                else None
            )
            anomaly = bool(
                checkpoint
                and (
                    committed > high
                    or db_size < prior_size
                    or checkpoint_row is None
                    or str(checkpoint_row["id"]) != expected_id
                )
            )
            start = 0 if anomaly else committed
            if anomaly:
                result["gaps"] = int(result["gaps"]) + _record_gap(
                    store,
                    uri,
                    "store.db shrank or checkpoint blob id changed; rescanning",
                    from_locator=f"rowid={committed}",
                    to_locator=f"rowid={high}",
                    dry_run=dry_run,
                )
            query = "SELECT rowid,id,data FROM blobs WHERE rowid>? ORDER BY rowid"
            params: tuple[Any, ...] = (start,)
            if limit is not None:
                query += " LIMIT ?"
                params = (start, max(0, limit))
            max_rowid = start
            for row in con.execute(query, params):
                rowid = int(row["rowid"])
                blob_id = str(row["id"])
                raw = row["data"]
                if not isinstance(raw, bytes):
                    raw = bytes(raw)
                result["blobs_read"] = int(result["blobs_read"]) + 1
                created, classification = _blob_event(
                    store, session, rowid, blob_id, raw, batch=batch, dry_run=dry_run
                )
                result["created"] = int(result["created"]) + int(created)
                result["skipped"] = int(result["skipped"]) + int(
                    not created and not dry_run
                )
                if classification in ("json_parsed", "graph_raw", "unparsed"):
                    result[classification] = int(result[classification]) + 1
                if hashlib.sha256(raw).hexdigest() != blob_id:
                    result["gaps"] = int(result["gaps"]) + _record_gap(
                        store,
                        uri,
                        "blob id does not match SHA-256(data)",
                        from_locator=f"rowid={rowid}",
                        to_locator=f"blob:{blob_id}",
                        dry_run=dry_run,
                    )
                if classification == "mutated":
                    result["gaps"] = int(result["gaps"]) + _record_gap(
                        store,
                        uri,
                        "blob identity changed at a committed coordinate",
                        from_locator=f"rowid={rowid}",
                        dry_run=dry_run,
                    )
                    result["failed"] = True
                    break
                max_rowid = rowid
            if not dry_run and not result["failed"]:
                store.set_checkpoint(
                    PRODUCER,
                    uri,
                    source_fingerprint=f"size={db_size};max_rowid={high};{high_id};sha256={high_id}",
                    committed_locator=f"rowid={max(max_rowid, high if limit is None else max_rowid)}",
                    adapter_version=ADAPTER_VERSION,
                )
    except (sqlite3.Error, OSError, PermissionError):
        result["gaps"] = int(result["gaps"]) + _record_gap(
            store,
            uri,
            "store.db unavailable or corrupt; retry next scan",
            dry_run=dry_run,
        )
        result["failed"] = True
    return result


def scan(
    store: EvidenceStore,
    *,
    chats: Path = CHAT_ROOT,
    acp_sessions: Path = ACP_ROOT,
    config_chats: Path = CONFIG_CHAT_ROOT,
    batch: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int | bool]:
    totals: dict[str, int | bool] = {
        "sessions": 0,
        "blobs_read": 0,
        "created": 0,
        "skipped": 0,
        "json_parsed": 0,
        "graph_raw": 0,
        "unparsed": 0,
        "gaps": 0,
        "failed": False,
    }
    batch = batch or f"cursor-cli:{now_iso()}"
    sessions = discover_sessions(chats, acp_sessions, config_chats)
    if limit is not None:
        sessions = sessions[: max(0, limit)]
    present = {session.session_id for session in sessions}
    for session in sessions:
        current = scan_session(store, session, batch=batch, dry_run=dry_run)
        for key in (
            "sessions",
            "blobs_read",
            "created",
            "skipped",
            "json_parsed",
            "graph_raw",
            "unparsed",
            "gaps",
        ):
            totals[key] = int(totals[key]) + int(current[key])
        totals["failed"] = bool(totals["failed"]) or bool(current["failed"])
    if not dry_run:
        rows = store.db.execute(
            "SELECT source_uri FROM ingest_checkpoint WHERE producer=?", (PRODUCER,)
        ).fetchall()
        for row in rows:
            uri = str(row["source_uri"])
            session_id = uri.removeprefix("cursor-cli:")
            if session_id not in present:
                totals["gaps"] = int(totals["gaps"]) + _record_gap(
                    store,
                    uri,
                    "previously checkpointed session is no longer present",
                    dry_run=dry_run,
                )
                totals["failed"] = True
    return totals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest Cursor agent CLI sessions into S1"
    )
    parser.add_argument("--db", default=None, help="S1 database")
    parser.add_argument("--cas", default=None, help="S1 content-addressed store")
    parser.add_argument("--chats", default=str(CHAT_ROOT), help="Cursor CLI chats root")
    parser.add_argument(
        "--acp-sessions", default=str(ACP_ROOT), help="acp-run Cursor sessions root"
    )
    parser.add_argument(
        "--config-chats",
        default=str(CONFIG_CHAT_ROOT),
        help="new Cursor chats root, if present",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser(
        "scan", help="ingest allow-listed Cursor CLI session evidence"
    )
    command.add_argument("--dry-run", action="store_true")
    command.add_argument(
        "--limit", type=int, default=None, help="limit session directories"
    )
    args = parser.parse_args(argv)
    kwargs: dict[str, Any] = {}
    if args.db:
        kwargs["db_path"] = args.db
    if args.cas:
        kwargs["cas_root"] = args.cas
    store = EvidenceStore(**kwargs)
    try:
        result = scan(
            store,
            chats=Path(args.chats).expanduser(),
            acp_sessions=Path(args.acp_sessions).expanduser(),
            config_chats=Path(args.config_chats).expanduser(),
            dry_run=args.dry_run,
            limit=args.limit,
        )
        closing = {
            key: int(result[key])
            for key in (
                "sessions",
                "blobs_read",
                "created",
                "skipped",
                "json_parsed",
                "graph_raw",
                "unparsed",
                "gaps",
            )
        }
        print(json.dumps(closing, sort_keys=True))
        return 1 if result["failed"] else 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
