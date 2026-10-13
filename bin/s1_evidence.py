#!/usr/bin/env python3
"""S1 — the lossless evidence store for the memory architecture (Phase B).

S1 is the only irreplaceable machine-readable store: it keeps producer bytes
exactly as they arrived, before any normalization, and uses SQLite for identity
and transactional state. Everything else in the architecture (projections,
indexes, exported notes) is rebuildable from here, so this module's contract is
narrow and strict:

- raw bytes land in the SQLite CAS pack first (while legacy loose SHA-256 files
  remain readable), and the event row that describes them commits only after
  the packed object is durable;
- CAS packing is resumable and verifies loose names against their bytes; loose
  deletion is a distinct, maintenance-lock-gated operation;
- an event's identity is derived from where it came from, never invented, so
  re-ingesting the same source twice is a no-op rather than a duplicate;
- gaps are recorded rather than papered over — a missing interval is evidence
  about our coverage, and claiming losslessness we don't have is worse than
  admitting the hole.

The database file also carries the tables of the retired Phase A candidate
ledger; this module only adds its own (CREATE TABLE IF NOT EXISTS) and is
self-sufficient on an empty file.

Spec: site-djbclark/docs/plans/memory-architecture-v2.md §4.1.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import hashlib
import json
import random
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_DB = Path.home() / ".local" / "share" / "s1-evidence" / "candidates.sqlite3"
DEFAULT_CAS = Path.home() / ".local" / "share" / "s1-evidence" / "cas"
DEFAULT_PACK = DEFAULT_CAS.parent / "cas-pack" / "pack.sqlite3"
SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 30_000
PACK_BATCH_SIZE = 1000
DICT_SAMPLE_SIZE = 20_000
DICT_MAX_SIZE = 112_640
RAW_MIN_SIZE = 96

# event_id inputs are joined with ASCII unit separator: it cannot occur in a
# path or a hex digest, so no combination of fields can collide by concatenation.
_SEP = "\x1f"

TS_SOURCES = ("producer", "filesystem", "ingest", "inferred")
ROLES = ("user", "assistant", "system", "tool", "unknown")
ORIGINS = ("human", "model", "tool", "web", "system", "derived")


def now_iso() -> str:
    """RFC 3339 UTC with a literal Z, per the spec's timestamp rule."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def format_age(seconds: int) -> str:
    """Compact age: 49d3h, 6h12m, 45m, 30s. fleet-watch prints the same form."""
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
    """Deterministic identity: producer | source_uri | source_locator | raw_sha256.

    Native session IDs and sequence numbers are evidence, not identity — they are
    not inputs here. Because the raw hash participates, the same coordinates
    holding different bytes produce a different id, which is how source mutation
    becomes visible instead of silently overwriting.
    """
    joined = _SEP.join((producer, source_uri, source_locator, raw_sha256))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class SourceMutated(RuntimeError):
    """Same source coordinates, different bytes — the source was not immutable."""


class _Zstd:
    """Small stdlib-only binding to the already-installed libzstd ABI."""

    def __init__(self) -> None:
        candidates = [
            ctypes.util.find_library("zstd"),
            "/opt/homebrew/opt/zstd/lib/libzstd.1.dylib",
            "/usr/local/opt/zstd/lib/libzstd.1.dylib",
            "libzstd.so.1",
            "libzstd.dylib",
        ]
        error: OSError | None = None
        for candidate in candidates:
            if not candidate:
                continue
            try:
                self.lib = ctypes.CDLL(candidate)
                break
            except OSError as exc:
                error = exc
        else:
            raise RuntimeError("libzstd is required for S1 CAS packing") from error
        lib = self.lib
        lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
        lib.ZSTD_compressBound.restype = ctypes.c_size_t
        lib.ZSTD_createCCtx.restype = ctypes.c_void_p
        lib.ZSTD_freeCCtx.argtypes = [ctypes.c_void_p]
        lib.ZSTD_CCtx_setParameter.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
        ]
        lib.ZSTD_CCtx_loadDictionary.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        lib.ZSTD_compress2.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        lib.ZSTD_createDCtx.restype = ctypes.c_void_p
        lib.ZSTD_freeDCtx.argtypes = [ctypes.c_void_p]
        lib.ZSTD_DCtx_loadDictionary.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        lib.ZSTD_decompressDCtx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
        lib.ZSTD_isError.restype = ctypes.c_uint
        lib.ZSTD_getErrorName.argtypes = [ctypes.c_size_t]
        lib.ZSTD_getErrorName.restype = ctypes.c_char_p
        lib.ZDICT_trainFromBuffer.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_uint,
        ]
        lib.ZDICT_trainFromBuffer.restype = ctypes.c_size_t
        lib.ZDICT_isError.argtypes = [ctypes.c_size_t]
        lib.ZDICT_isError.restype = ctypes.c_uint
        lib.ZDICT_getErrorName.argtypes = [ctypes.c_size_t]
        lib.ZDICT_getErrorName.restype = ctypes.c_char_p
        self._compressors: dict[int, ctypes.c_void_p] = {}
        self._decompressors: dict[int, ctypes.c_void_p] = {}
        self._dictionaries: dict[int, bytes] = {}
        self._lock = threading.RLock()

    def _check(self, result: int) -> int:
        if self.lib.ZSTD_isError(result):
            message = self.lib.ZSTD_getErrorName(result).decode("ascii", "replace")
            raise ValueError(f"zstd error: {message}")
        return result

    def _context(self, dictionary_id: int, dictionary: bytes | None, *, compress: bool):
        cache = self._compressors if compress else self._decompressors
        if dictionary_id in cache:
            return cache[dictionary_id]
        if compress:
            ctx = self.lib.ZSTD_createCCtx()
            if not ctx:
                raise MemoryError("could not allocate zstd compressor")
            self._check(
                self.lib.ZSTD_CCtx_setParameter(ctx, 100, 3)
            )  # ZSTD_c_compressionLevel
            if dictionary:
                buf = ctypes.create_string_buffer(dictionary)
                self._check(
                    self.lib.ZSTD_CCtx_loadDictionary(ctx, buf, len(dictionary))
                )
        else:
            ctx = self.lib.ZSTD_createDCtx()
            if not ctx:
                raise MemoryError("could not allocate zstd decompressor")
            if dictionary:
                buf = ctypes.create_string_buffer(dictionary)
                self._check(
                    self.lib.ZSTD_DCtx_loadDictionary(ctx, buf, len(dictionary))
                )
        cache[dictionary_id] = ctx
        if dictionary:
            self._dictionaries[dictionary_id] = dictionary
        return ctx

    def compress(
        self, payload: bytes, dictionary_id: int, dictionary: bytes | None
    ) -> bytes:
        with self._lock:
            ctx = self._context(dictionary_id, dictionary, compress=True)
            capacity = self.lib.ZSTD_compressBound(len(payload))
            output = ctypes.create_string_buffer(max(capacity, 1))
            source = ctypes.create_string_buffer(payload)
            size = self._check(
                self.lib.ZSTD_compress2(ctx, output, capacity, source, len(payload))
            )
            return output.raw[:size]

    def decompress(
        self,
        payload: bytes,
        raw_size: int,
        dictionary_id: int,
        dictionary: bytes | None,
    ) -> bytes:
        with self._lock:
            ctx = self._context(dictionary_id, dictionary, compress=False)
            output = ctypes.create_string_buffer(max(raw_size, 1))
            source = ctypes.create_string_buffer(payload)
            size = self._check(
                self.lib.ZSTD_decompressDCtx(
                    ctx, output, raw_size, source, len(payload)
                )
            )
            if size != raw_size:
                raise ValueError(f"zstd size mismatch: expected {raw_size}, got {size}")
            return output.raw[:size]

    def train(self, samples: list[bytes], max_size: int = DICT_MAX_SIZE) -> bytes:
        if len(samples) < 100:
            raise ValueError(
                f"need at least 100 samples to train dictionary, got {len(samples)}"
            )
        joined = b"".join(samples)
        sizes = (ctypes.c_size_t * len(samples))(*(len(sample) for sample in samples))
        source = ctypes.create_string_buffer(joined)
        output = ctypes.create_string_buffer(max_size)
        result = self.lib.ZDICT_trainFromBuffer(
            output, max_size, source, sizes, len(samples)
        )
        if self.lib.ZDICT_isError(result):
            message = self.lib.ZDICT_getErrorName(result).decode("ascii", "replace")
            raise ValueError(f"zstd dictionary training failed: {message}")
        return output.raw[:result]

    def close(self) -> None:
        for ctx in self._compressors.values():
            self.lib.ZSTD_freeCCtx(ctx)
        for ctx in self._decompressors.values():
            self.lib.ZSTD_freeDCtx(ctx)
        self._compressors.clear()
        self._decompressors.clear()


class EvidenceStore:
    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB,
        cas_root: str | Path = DEFAULT_CAS,
        pack_path: str | Path | None = None,
        maintenance_lock_path: str | Path | None = None,
    ):
        self.path = Path(db_path).expanduser()
        self.cas_root = Path(cas_root).expanduser()
        self.pack_path = (
            Path(pack_path).expanduser()
            if pack_path is not None
            else self.cas_root.parent / "cas-pack" / "pack.sqlite3"
        )
        if self.pack_path.resolve() == self.path.resolve():
            raise ValueError(
                "CAS pack database must be separate from the evidence database"
            )
        self.maintenance_lock = (
            Path(maintenance_lock_path).expanduser()
            if maintenance_lock_path is not None
            else self.path.parent / "maintenance.lock"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cas_root.mkdir(parents=True, exist_ok=True)
        self.pack_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        # Long-running ingest holds the write lock in batches, and opening a
        # second connection runs DDL, which needs that lock. Without a busy
        # timeout the second process fails instantly with "database is locked"
        # — even for something as harmless as reading stats mid-index. Wait
        # instead of erroring.
        self.db.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        self._migrate()
        self.pack_db = sqlite3.connect(self.pack_path)
        self.pack_db.row_factory = sqlite3.Row
        self.pack_db.execute("PRAGMA page_size=4096")
        self.pack_db.execute("PRAGMA journal_mode=WAL")
        self.pack_db.execute("PRAGMA synchronous=FULL")
        self.pack_db.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        self.pack_db.executescript(
            """
            CREATE TABLE IF NOT EXISTS obj (
              id INTEGER PRIMARY KEY,
              sha BLOB NOT NULL UNIQUE CHECK(length(sha)=32),
              raw_size INTEGER NOT NULL CHECK(raw_size >= 0),
              data BLOB NOT NULL,
              codec INTEGER NOT NULL CHECK(codec IN (0,1)),
              dict_id INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS dictionary (
              id INTEGER PRIMARY KEY,
              data BLOB NOT NULL,
              sha256 TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pack_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            """
        )
        self.pack_db.commit()
        self._zstd: _Zstd | None = None
        self._load_active_dictionary()

    def _codec(self) -> _Zstd:
        if self._zstd is None:
            self._zstd = _Zstd()
        return self._zstd

    def _load_active_dictionary(self) -> None:
        row = self.pack_db.execute(
            "SELECT value FROM pack_meta WHERE key='active_dictionary_id'"
        ).fetchone()
        self.active_dictionary_id = int(row[0]) if row else 0
        dictionary = (
            self.pack_db.execute(
                "SELECT data FROM dictionary WHERE id=?", (self.active_dictionary_id,)
            ).fetchone()
            if self.active_dictionary_id
            else None
        )
        self.active_dictionary = bytes(dictionary[0]) if dictionary else None
        self.active_dictionary_error = (
            f"active zstd dictionary {self.active_dictionary_id} is missing"
            if self.active_dictionary_id and self.active_dictionary is None
            else None
        )

    # -- schema -----------------------------------------------------------

    def _migrate(self) -> None:
        self.db.executescript(
            """
        CREATE TABLE IF NOT EXISTS event (
          event_id            TEXT PRIMARY KEY,
          producer            TEXT NOT NULL CHECK (producer <> ''),
          producer_version    TEXT,
          account_id          TEXT NOT NULL,
          source_uri          TEXT NOT NULL,
          source_locator      TEXT NOT NULL,
          producer_session_id TEXT,
          source_seq          INTEGER,
          ingest_lsn          INTEGER NOT NULL UNIQUE,
          ts_utc              TEXT NOT NULL,
          ts_source           TEXT NOT NULL CHECK (ts_source IN ('producer','filesystem','ingest','inferred')),
          role                TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool','unknown')),
          event_type          TEXT NOT NULL,
          tool_name           TEXT,
          tool_call_id        TEXT,
          raw_ref             TEXT NOT NULL,
          raw_sha256          TEXT NOT NULL,
          raw_size            INTEGER NOT NULL CHECK (raw_size >= 0),
          content_encoding    TEXT NOT NULL,
          origin              TEXT NOT NULL CHECK (origin IN ('human','model','tool','web','system','derived')),
          scope               TEXT NOT NULL,
          sensitivity         TEXT NOT NULL,
          redaction_state     TEXT NOT NULL DEFAULT 'none',
          ingest_batch        TEXT NOT NULL,
          UNIQUE(producer, source_uri, source_locator)
        );

        CREATE TABLE IF NOT EXISTS conversation_member (
          event_id        TEXT NOT NULL REFERENCES event(event_id) ON DELETE CASCADE,
          conversation_id TEXT NOT NULL,
          assigned_by     TEXT NOT NULL,
          confidence      REAL,
          assigned_at     TEXT NOT NULL,
          PRIMARY KEY (event_id, conversation_id)
        );

        -- CAS inventory. Bytes may be packed or remain loose during migration;
        -- this row records ownership, size, and sensitivity.
        CREATE TABLE IF NOT EXISTS raw_object (
          sha256           TEXT PRIMARY KEY,
          size             INTEGER NOT NULL CHECK (size >= 0),
          media_type       TEXT,
          stored_at        TEXT NOT NULL,
          encryption       TEXT NOT NULL DEFAULT 'none',
          sensitivity      TEXT NOT NULL DEFAULT 'normal'
        );

        CREATE TABLE IF NOT EXISTS attachment (
          attachment_id    TEXT PRIMARY KEY,
          event_id         TEXT NOT NULL REFERENCES event(event_id) ON DELETE CASCADE,
          sha256           TEXT NOT NULL REFERENCES raw_object(sha256),
          media_type       TEXT,
          width            INTEGER,
          height           INTEGER,
          duration_s       REAL,
          description      TEXT,
          extraction_version TEXT
        );

        -- Where each source has been consumed up to, so an interrupted ingest
        -- resumes instead of restarting.
        CREATE TABLE IF NOT EXISTS ingest_checkpoint (
          producer          TEXT NOT NULL,
          source_uri        TEXT NOT NULL,
          source_fingerprint TEXT NOT NULL,
          committed_locator TEXT,
          committed_lsn     INTEGER,
          adapter_version   TEXT NOT NULL,
          updated_at        TEXT NOT NULL,
          PRIMARY KEY (producer, source_uri)
        );

        -- Explicit intervals whose evidence we know we do not have.
        CREATE TABLE IF NOT EXISTS ingest_gap (
          gap_id        INTEGER PRIMARY KEY,
          producer      TEXT NOT NULL,
          source_uri    TEXT NOT NULL,
          from_locator  TEXT,
          to_locator    TEXT,
          reason        TEXT NOT NULL,
          detected_at   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS s1_meta (
          key   TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS event_ts_idx        ON event(ts_utc);
        CREATE INDEX IF NOT EXISTS event_session_idx   ON event(producer, producer_session_id, source_seq);
        CREATE INDEX IF NOT EXISTS event_sha_idx       ON event(raw_sha256);
        CREATE INDEX IF NOT EXISTS conv_member_cid_idx ON conversation_member(conversation_id);
        """
        )
        self.db.execute(
            "INSERT OR IGNORE INTO s1_meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.db.commit()

    # -- content-addressed store -----------------------------------------

    def cas_path(self, digest: str) -> Path:
        return self.cas_root / digest[:2] / digest

    def _encode(self, payload: bytes) -> tuple[bytes, int, int]:
        if len(payload) < RAW_MIN_SIZE:
            return payload, 0, 0
        if self.active_dictionary_error:
            raise RuntimeError(self.active_dictionary_error)
        dictionary_id = self.active_dictionary_id
        dictionary = self.active_dictionary
        compressed = self._codec().compress(payload, dictionary_id, dictionary)
        if len(compressed) >= len(payload):
            return payload, 0, 0
        return compressed, 1, dictionary_id

    def _unpack(self, row: sqlite3.Row | tuple) -> bytes:
        data, raw_size, codec, dictionary_id = row
        if codec == 0:
            payload = bytes(data)
            if len(payload) != raw_size:
                raise ValueError(
                    f"raw pack size mismatch: expected {raw_size}, got {len(payload)}"
                )
            return payload
        if codec != 1:
            raise ValueError(f"unknown CAS pack codec {codec}")
        dictionary = None
        if dictionary_id:
            found = self.pack_db.execute(
                "SELECT data FROM dictionary WHERE id=?", (dictionary_id,)
            ).fetchone()
            if found is None:
                raise ValueError(
                    f"CAS object refers to missing dictionary {dictionary_id}"
                )
            dictionary = bytes(found[0])
        return self._codec().decompress(
            bytes(data), int(raw_size), int(dictionary_id), dictionary
        )

    def put_bytes(
        self,
        payload: bytes,
        *,
        media_type: str | None = None,
        sensitivity: str = "normal",
    ) -> str:
        """Durably pack bytes before inventory/event rows can commit.

        The pack is a separate WAL database. Its object transaction commits
        first; the evidence DB transaction that refers to it commits later.
        This preserves the original CAS-before-event crash invariant.
        """
        digest = sha256_bytes(payload)
        packed, codec, dictionary_id = self._encode(payload)
        with self.pack_db:
            cursor = self.pack_db.execute(
                "INSERT OR IGNORE INTO obj (sha, raw_size, data, codec, dict_id) VALUES (?,?,?,?,?)",
                (bytes.fromhex(digest), len(payload), packed, codec, dictionary_id),
            )
            if not cursor.rowcount:
                row = self.pack_db.execute(
                    "SELECT data,raw_size,codec,dict_id FROM obj WHERE sha=?",
                    (bytes.fromhex(digest),),
                ).fetchone()
                try:
                    existing = self._unpack(row) if row is not None else None
                except (ValueError, RuntimeError):
                    existing = None
                if existing is not None and sha256_bytes(existing) == digest:
                    if existing != payload:
                        raise SourceMutated(
                            f"SHA-256 collision for CAS object {digest}"
                        )
                else:
                    self.pack_db.execute(
                        "UPDATE obj SET raw_size=?,data=?,codec=?,dict_id=? WHERE sha=?",
                        (
                            len(payload),
                            packed,
                            codec,
                            dictionary_id,
                            bytes.fromhex(digest),
                        ),
                    )
        self.db.execute(
            "INSERT OR IGNORE INTO raw_object (sha256, size, media_type, stored_at, sensitivity)"
            " VALUES (?,?,?,?,?)",
            (digest, len(payload), media_type, now_iso(), sensitivity),
        )
        return digest

    def get_bytes(self, digest: str) -> bytes:
        try:
            sha = bytes.fromhex(digest)
        except ValueError:
            raise ValueError(f"invalid CAS sha256: {digest!r}") from None
        row = self.pack_db.execute(
            "SELECT data, raw_size, codec, dict_id FROM obj WHERE sha=?", (sha,)
        ).fetchone()
        if row is not None:
            try:
                return self._unpack(row)
            except (ValueError, RuntimeError) as exc:
                raise SourceMutated(
                    f"packed CAS object {digest} is corrupt: {exc}"
                ) from exc
        return self.cas_path(digest).read_bytes()

    def _loose_files(self) -> Iterator[tuple[Path, str]]:
        """Yield valid digest-named files in deterministic directory order."""
        if not self.cas_root.is_dir():
            return
        for prefix in sorted(self.cas_root.iterdir()):
            if not prefix.is_dir() or len(prefix.name) != 2:
                continue
            for path in sorted(prefix.iterdir()):
                digest = path.name.lower()
                if (
                    path.is_file()
                    and len(digest) == 64
                    and all(c in "0123456789abcdef" for c in digest)
                    and digest.startswith(prefix.name.lower())
                ):
                    yield path, digest

    def _train_dictionary(self, *, sample_size: int = DICT_SAMPLE_SIZE) -> int:
        """Train one deterministic dictionary from a random loose-object sample."""
        rng = random.Random(20261012)
        sample: list[tuple[Path, str]] = []
        for seen, item in enumerate(self._loose_files(), start=1):
            if len(sample) < sample_size:
                sample.append(item)
            else:
                slot = rng.randrange(seen)
                if slot < sample_size:
                    sample[slot] = item
        raw_samples = []
        for path, digest in sample:
            payload = path.read_bytes()
            if sha256_bytes(payload) == digest:
                raw_samples.append(payload)
        if len(raw_samples) < 100:
            return 0
        dictionary = self._codec().train(raw_samples)
        sha = hashlib.sha256(dictionary).hexdigest()
        with self.pack_db:
            existing = self.pack_db.execute(
                "SELECT id FROM dictionary WHERE sha256=?", (sha,)
            ).fetchone()
            if existing:
                dictionary_id = int(existing[0])
            else:
                dictionary_id = int(
                    self.pack_db.execute(
                        "SELECT COALESCE(MAX(id),0)+1 FROM dictionary"
                    ).fetchone()[0]
                )
                self.pack_db.execute(
                    "INSERT INTO dictionary (id, data, sha256, created_at) VALUES (?,?,?,?)",
                    (dictionary_id, dictionary, sha, now_iso()),
                )
            self.pack_db.execute(
                "INSERT INTO pack_meta (key,value) VALUES ('active_dictionary_id',?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(dictionary_id),),
            )
        self._load_active_dictionary()
        return dictionary_id

    def _write_pack_batch(
        self, batch: list[tuple[str, int, bytes, int, int]]
    ) -> tuple[int, list[str]]:
        inserted = 0
        existing: list[str] = []
        with self.pack_db:
            for digest, raw_size, data, codec, dictionary_id in batch:
                cursor = self.pack_db.execute(
                    "INSERT OR IGNORE INTO obj (sha, raw_size, data, codec, dict_id)"
                    " VALUES (?,?,?,?,?)",
                    (bytes.fromhex(digest), raw_size, data, codec, dictionary_id),
                )
                if cursor.rowcount:
                    inserted += 1
                else:
                    existing.append(digest)
        return inserted, existing

    def cas_pack(
        self,
        *,
        batch_size: int = PACK_BATCH_SIZE,
        retrain_dictionary: bool = False,
        max_batches: int | None = None,
    ) -> dict[str, Any]:
        """Verify and migrate loose CAS objects into the resumable packed store."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if retrain_dictionary or not self.active_dictionary_id:
            self._train_dictionary()
        report: dict[str, Any] = {
            "files_seen": 0,
            "packed": 0,
            "already_packed": 0,
            "hash_mismatched": [],
            "read_errors": [],
            "pack_mismatched": [],
            "batches": 0,
            "dictionary_id": self.active_dictionary_id,
        }
        batch: list[tuple[str, int, bytes, int, int]] = []

        def commit_batch() -> None:
            if not batch:
                return
            inserted, existing = self._write_pack_batch(batch)
            report["packed"] += inserted
            report["already_packed"] += len(existing)
            report["batches"] += 1
            for digest in existing:
                try:
                    row = self.pack_db.execute(
                        "SELECT data,raw_size,codec,dict_id FROM obj WHERE sha=?",
                        (bytes.fromhex(digest),),
                    ).fetchone()
                    if row is None or sha256_bytes(self._unpack(row)) != digest:
                        report["pack_mismatched"].append(digest)
                except (OSError, ValueError, RuntimeError) as exc:
                    report["pack_mismatched"].append(f"{digest}: {exc}")
            batch.clear()

        for path, digest in self._loose_files():
            report["files_seen"] += 1
            try:
                payload = path.read_bytes()
            except OSError as exc:
                report["read_errors"].append(f"{digest}: {exc}")
                continue
            if sha256_bytes(payload) != digest:
                report["hash_mismatched"].append(digest)
                continue
            packed, codec, dictionary_id = self._encode(payload)
            batch.append((digest, len(payload), packed, codec, dictionary_id))
            if len(batch) >= batch_size:
                commit_batch()
                if max_batches is not None and report["batches"] >= max_batches:
                    report["interrupted_after_batches"] = report["batches"]
                    return report
        commit_batch()
        return report

    def cas_prune_loose(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Remove only loose objects whose packed copy verifies in this run."""
        if not self.maintenance_lock.is_file():
            raise RuntimeError(f"refusing to prune without {self.maintenance_lock}")
        report: dict[str, Any] = {
            "dry_run": dry_run,
            "checked": 0,
            "would_prune": 0,
            "pruned": 0,
            "loose_bytes_removed": 0,
            "unverified": [],
            "loose_mismatched": [],
            "read_errors": [],
        }
        for path, digest in self._loose_files():
            report["checked"] += 1
            try:
                loose = path.read_bytes()
            except OSError as exc:
                report["read_errors"].append(f"{digest}: {exc}")
                continue
            if sha256_bytes(loose) != digest:
                report["loose_mismatched"].append(digest)
                continue
            row = self.pack_db.execute(
                "SELECT data,raw_size,codec,dict_id FROM obj WHERE sha=?",
                (bytes.fromhex(digest),),
            ).fetchone()
            try:
                if row is None or sha256_bytes(self._unpack(row)) != digest:
                    report["unverified"].append(digest)
                    continue
            except (ValueError, RuntimeError) as exc:
                report["unverified"].append(f"{digest}: {exc}")
                continue
            report["would_prune"] += 1
            if not dry_run:
                path.unlink()
                report["pruned"] += 1
                report["loose_bytes_removed"] += len(loose)
        return report

    # -- ingestion --------------------------------------------------------

    def _next_lsn(self) -> int:
        row = self.db.execute(
            "SELECT COALESCE(MAX(ingest_lsn), 0) + 1 FROM event"
        ).fetchone()
        return int(row[0])

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

        Re-ingesting an identical source coordinate with identical bytes returns
        the existing id with created=False — that is what makes a re-run safe.
        Identical coordinates with *different* bytes raise SourceMutated: the
        source was supposed to be immutable, and silently keeping either version
        would destroy the evidence trail.
        """
        if ts_source not in TS_SOURCES:
            raise ValueError(f"ts_source must be one of {TS_SOURCES}")
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if origin not in ORIGINS:
            raise ValueError(f"origin must be one of {ORIGINS}")

        digest = sha256_bytes(raw)
        event_id = derive_event_id(producer, source_uri, source_locator, digest)

        existing = self.db.execute(
            "SELECT event_id, raw_sha256 FROM event"
            " WHERE producer=? AND source_uri=? AND source_locator=?",
            (producer, source_uri, source_locator),
        ).fetchone()
        if existing is not None:
            if existing["raw_sha256"] != digest:
                raise SourceMutated(
                    f"{producer}:{source_uri}:{source_locator} previously held "
                    f"{existing['raw_sha256'][:12]}…, now {digest[:12]}…"
                )
            return existing["event_id"], False

        with self.db:  # pack is durable before this inventory/event transaction
            self.put_bytes(raw, media_type=media_type, sensitivity=sensitivity)
            self.db.execute(
                """INSERT INTO event (
                     event_id, producer, producer_version, account_id, source_uri,
                     source_locator, producer_session_id, source_seq, ingest_lsn,
                     ts_utc, ts_source, role, event_type, tool_name, tool_call_id,
                     raw_ref, raw_sha256, raw_size, content_encoding, origin,
                     scope, sensitivity, ingest_batch)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_id,
                    producer,
                    producer_version,
                    account_id,
                    source_uri,
                    source_locator,
                    producer_session_id,
                    source_seq,
                    self._next_lsn(),
                    ts_utc,
                    ts_source,
                    role,
                    event_type,
                    tool_name,
                    tool_call_id,
                    f"cas:{digest}",
                    digest,
                    len(raw),
                    content_encoding,
                    origin,
                    scope,
                    sensitivity,
                    ingest_batch,
                ),
            )
        return event_id, True

    def assign_conversation(
        self,
        event_id: str,
        conversation_id: str,
        *,
        assigned_by: str = "adapter",
        confidence: float | None = None,
    ) -> None:
        """Group an event into a conversation. Revisable metadata, not identity.

        Prefer a false split over an unsupported merge: it is cheap to join two
        conversations later, and impossible to un-merge two that were never
        the same.
        """
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO conversation_member"
                " (event_id, conversation_id, assigned_by, confidence, assigned_at)"
                " VALUES (?,?,?,?,?)",
                (event_id, conversation_id, assigned_by, confidence, now_iso()),
            )

    def record_gap(
        self,
        producer: str,
        source_uri: str,
        reason: str,
        *,
        from_locator: str | None = None,
        to_locator: str | None = None,
    ) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO ingest_gap (producer, source_uri, from_locator, to_locator,"
                " reason, detected_at) VALUES (?,?,?,?,?,?)",
                (producer, source_uri, from_locator, to_locator, reason, now_iso()),
            )

    def set_checkpoint(
        self,
        producer: str,
        source_uri: str,
        *,
        source_fingerprint: str,
        committed_locator: str | None,
        adapter_version: str,
    ) -> None:
        row = self.db.execute(
            "SELECT COALESCE(MAX(ingest_lsn), 0) FROM event"
        ).fetchone()
        with self.db:
            self.db.execute(
                "INSERT INTO ingest_checkpoint (producer, source_uri, source_fingerprint,"
                " committed_locator, committed_lsn, adapter_version, updated_at)"
                " VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(producer, source_uri) DO UPDATE SET"
                "   source_fingerprint=excluded.source_fingerprint,"
                "   committed_locator=excluded.committed_locator,"
                "   committed_lsn=excluded.committed_lsn,"
                "   adapter_version=excluded.adapter_version,"
                "   updated_at=excluded.updated_at",
                (
                    producer,
                    source_uri,
                    source_fingerprint,
                    committed_locator,
                    int(row[0]),
                    adapter_version,
                    now_iso(),
                ),
            )

    def checkpoint(self, producer: str, source_uri: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM ingest_checkpoint WHERE producer=? AND source_uri=?",
            (producer, source_uri),
        ).fetchone()

    # -- retrieval --------------------------------------------------------

    def get_event(self, event_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM event WHERE event_id=?", (event_id,)
        ).fetchone()

    def raw_for(self, event_id: str) -> bytes:
        """Return the exact producer bytes for an event, verifying the hash.

        Verification is not optional here: a silent mismatch would mean the
        evidence store returned something other than what it recorded, which is
        the one failure this whole layer exists to prevent.
        """
        row = self.get_event(event_id)
        if row is None:
            raise KeyError(event_id)
        payload = self.get_bytes(row["raw_sha256"])
        actual = sha256_bytes(payload)
        if actual != row["raw_sha256"]:
            raise SourceMutated(
                f"CAS object for {event_id} does not match its recorded hash"
            )
        return payload

    def conversation(self, conversation_id: str) -> Iterator[sqlite3.Row]:
        """Events of a conversation in deterministic order.

        Within a producer session order by source_seq; across sources fall back
        to time, then coordinates, then ingest_lsn as a total-order tie-break so
        the sequence never depends on row insertion luck.
        """
        yield from self.db.execute(
            "SELECT e.* FROM event e JOIN conversation_member m ON m.event_id = e.event_id"
            " WHERE m.conversation_id = ?"
            " ORDER BY e.ts_utc, e.producer, e.source_uri, e.source_seq, e.ingest_lsn",
            (conversation_id,),
        )

    def search(self, needle: str, *, limit: int = 20) -> list[sqlite3.Row]:
        """Exact substring search over raw bytes (Phase B's exact-retrieval leg).

        Deliberately a scan over the CAS rather than an index: it is the
        ground-truth check that what we stored is findable, and it is what a
        restore drill uses to prove retrieval still works.
        """
        hits = []
        probe = needle.encode("utf-8")
        for row in self.db.execute("SELECT * FROM event ORDER BY ingest_lsn"):
            try:
                if probe in self.get_bytes(row["raw_sha256"]):
                    hits.append(row)
            except FileNotFoundError:
                continue
            if len(hits) >= limit:
                break
        return hits

    # -- integrity --------------------------------------------------------

    def verify(self, *, sample: int | None = None) -> dict[str, Any]:
        """Run the restore-drill checks: integrity, foreign keys, and hashes.

        `sample` limits how many CAS objects are re-hashed; None means all. The
        spec asks for sampled verification on restore, but a full pass is cheap
        until the store is large, so full is the default.
        """
        report: dict[str, Any] = {"checked_at": now_iso()}
        report["integrity_check"] = self.db.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]
        report["pack_integrity_check"] = self.pack_db.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]
        report["foreign_key_check"] = [
            dict(r) for r in self.db.execute("PRAGMA foreign_key_check")
        ]
        query = "SELECT event_id, raw_sha256, raw_size FROM event ORDER BY ingest_lsn"
        if sample:
            query += f" LIMIT {int(sample)}"
        missing, mismatched, ok = [], [], 0
        for row in self.db.execute(query):
            try:
                payload = self.get_bytes(row["raw_sha256"])
            except FileNotFoundError:
                missing.append(row["event_id"])
                continue
            except (SourceMutated, ValueError, RuntimeError):
                mismatched.append(row["event_id"])
                continue
            if (
                sha256_bytes(payload) != row["raw_sha256"]
                or len(payload) != row["raw_size"]
            ):
                mismatched.append(row["event_id"])
            else:
                ok += 1
        pack_query = "SELECT sha,data,raw_size,codec,dict_id FROM obj ORDER BY id"
        if sample:
            pack_query += f" LIMIT {int(sample)}"
        pack_ok, pack_mismatched = 0, []
        for row in self.pack_db.execute(pack_query):
            digest = bytes(row["sha"]).hex()
            try:
                payload = self._unpack(
                    (row["data"], row["raw_size"], row["codec"], row["dict_id"])
                )
            except (ValueError, RuntimeError):
                pack_mismatched.append(digest)
                continue
            if sha256_bytes(payload) != digest:
                pack_mismatched.append(digest)
            else:
                pack_ok += 1
        object_query = "SELECT sha256 FROM raw_object ORDER BY sha256"
        if sample:
            object_query += f" LIMIT {int(sample)}"
        pack_missing: list[str] = []
        for object_row in self.db.execute(object_query):
            digest = object_row["sha256"]
            present = self.pack_db.execute(
                "SELECT 1 FROM obj WHERE sha=?", (bytes.fromhex(digest),)
            ).fetchone()
            if present:
                continue
            loose_path = self.cas_path(digest)
            if not loose_path.is_file():
                pack_missing.append(digest)
                continue
            try:
                if sha256_bytes(loose_path.read_bytes()) != digest:
                    pack_mismatched.append(digest)
            except OSError:
                pack_missing.append(digest)
        report.update(
            hash_ok=ok,
            hash_missing=missing,
            hash_mismatched=mismatched,
            pack_hash_ok=pack_ok,
            pack_hash_missing=pack_missing,
            pack_hash_mismatched=pack_mismatched,
        )
        report["events"] = self.db.execute("SELECT COUNT(*) FROM event").fetchone()[0]
        report["gaps"] = self.db.execute("SELECT COUNT(*) FROM ingest_gap").fetchone()[
            0
        ]
        report["healthy"] = (
            report["integrity_check"] == "ok"
            and report["pack_integrity_check"] == "ok"
            and not report["foreign_key_check"]
            and not missing
            and not mismatched
            and not pack_missing
            and not pack_mismatched
        )
        return report

    def stats(self) -> dict[str, Any]:
        cur = self.db.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(raw_size),0) bytes,"
            " COUNT(DISTINCT producer) producers,"
            " COUNT(DISTINCT producer_session_id) sessions FROM event"
        ).fetchone()
        return {
            "db": str(self.path),
            "cas": str(self.cas_root),
            "cas_pack": str(self.pack_path),
            "events": cur["n"],
            "raw_bytes": cur["bytes"],
            "producers": cur["producers"],
            "sessions": cur["sessions"],
            "objects": self.db.execute("SELECT COUNT(*) FROM raw_object").fetchone()[0],
            "packed_objects": self.pack_db.execute(
                "SELECT COUNT(*) FROM obj"
            ).fetchone()[0],
            "conversations": self.db.execute(
                "SELECT COUNT(DISTINCT conversation_id) FROM conversation_member"
            ).fetchone()[0],
            "gaps": self.db.execute("SELECT COUNT(*) FROM ingest_gap").fetchone()[0],
            "schema_version": self.db.execute(
                "SELECT value FROM s1_meta WHERE key='schema_version'"
            ).fetchone()[0],
            "newest_by_producer": self.newest_by_producer(),
        }

    def newest_by_producer(self, now: int | None = None) -> dict[str, dict[str, Any]]:
        """Newest event per producer and its age: how stale the store is.

        Nothing scheduled ingest until 2026-10-12 and the store sat seven weeks
        stale unnoticed; fleet-watch now pages on the same numbers. Both
        queries ride indexes (a skip-scan for the producers, then a backward
        walk of event_ts_idx), so this stays fast on a ~450k-event store.
        """
        now = int(datetime.now(timezone.utc).timestamp()) if now is None else now
        producers = [
            r[0]
            for r in self.db.execute(
                "WITH RECURSIVE p(x) AS (SELECT MIN(producer) FROM event"
                " UNION ALL SELECT (SELECT MIN(producer) FROM event WHERE producer > x)"
                " FROM p WHERE x IS NOT NULL) SELECT x FROM p WHERE x IS NOT NULL"
            )
        ]
        newest: dict[str, dict[str, Any]] = {}
        for producer in producers:
            ts, epoch = self.db.execute(
                "SELECT ts_utc, CAST(strftime('%s', ts_utc) AS INTEGER) FROM event"
                " INDEXED BY event_ts_idx WHERE producer=? ORDER BY ts_utc DESC LIMIT 1",
                (producer,),
            ).fetchone()
            entry: dict[str, Any] = {
                "newest_ts_utc": ts,
                "age_seconds": None,
                "age": None,
            }
            if epoch is not None:
                entry["age_seconds"] = now - epoch
                entry["age"] = format_age(now - epoch)
            newest[producer] = entry
        return newest

    def snapshot(self, destination: str | Path) -> Path:
        """Consistent event DB + pack snapshots; a live WAL copy is not a backup."""
        target = Path(destination).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        pack_target = target.with_name(f"{target.stem}.cas-pack.sqlite3")
        if pack_target.exists():
            pack_target.unlink()
        self.db.execute("VACUUM INTO ?", (str(target),))
        destination_db = sqlite3.connect(pack_target)
        try:
            self.pack_db.backup(destination_db)
        finally:
            destination_db.close()
        return target

    def close(self) -> None:
        self.db.close()
        self.pack_db.close()
        if self._zstd is not None:
            self._zstd.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1 evidence store (Phase B)")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--cas", default=str(DEFAULT_CAS))
    parser.add_argument(
        "--pack",
        default=None,
        help="CAS pack SQLite file (default: sibling cas-pack/pack.sqlite3)",
    )
    parser.add_argument(
        "--maintenance-lock",
        default=None,
        help="maintenance.lock path required by cas-prune-loose",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create or migrate the schema")
    sub.add_parser("stats", help="counts and sizes")
    verify_cmd = sub.add_parser("verify", help="integrity, foreign-key and hash checks")
    verify_cmd.add_argument("--sample", type=int, default=None)
    snap = sub.add_parser("snapshot", help="consistent backup via VACUUM INTO")
    snap.add_argument("destination")
    find = sub.add_parser("search", help="exact substring search over raw bytes")
    find.add_argument("needle")
    find.add_argument("--limit", type=int, default=20)
    show = sub.add_parser("show", help="print the exact raw bytes of one event")
    show.add_argument("event_id")
    pack = sub.add_parser(
        "cas-pack", help="verify and migrate loose CAS objects in batches"
    )
    pack.add_argument("--batch-size", type=int, default=PACK_BATCH_SIZE)
    pack.add_argument(
        "--retrain-dictionary",
        action="store_true",
        help="train and activate an additional dictionary from loose objects",
    )
    prune = sub.add_parser("cas-prune-loose", help="delete verified loose copies")
    prune.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    store = EvidenceStore(args.db, args.cas, args.pack, args.maintenance_lock)
    if args.command in ("init", "stats"):
        print(json.dumps(store.stats(), indent=2))
    elif args.command == "verify":
        report = store.verify(sample=args.sample)
        print(json.dumps(report, indent=2))
        store.close()
        return 0 if report["healthy"] else 1
    elif args.command == "snapshot":
        print(store.snapshot(args.destination))
    elif args.command == "search":
        for row in store.search(args.needle, limit=args.limit):
            print(
                f"{row['event_id'][:16]}  {row['ts_utc']}  {row['producer']}  {row['event_type']}"
            )
    elif args.command == "show":
        sys.stdout.buffer.write(store.raw_for(args.event_id))
    elif args.command == "cas-pack":
        report = store.cas_pack(
            batch_size=args.batch_size, retrain_dictionary=args.retrain_dictionary
        )
        print(json.dumps(report, indent=2))
        store.close()
        return (
            1
            if report["hash_mismatched"]
            or report["read_errors"]
            or report["pack_mismatched"]
            else 0
        )
    elif args.command == "cas-prune-loose":
        try:
            report = store.cas_prune_loose(dry_run=args.dry_run)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            store.close()
            return 2
        print(json.dumps(report, indent=2))
        store.close()
        return (
            1
            if report["unverified"]
            or report["loose_mismatched"]
            or report["read_errors"]
            else 0
        )
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
