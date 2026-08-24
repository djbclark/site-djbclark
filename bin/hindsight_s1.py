#!/usr/bin/env python3
"""S1 — the lossless evidence store for the memory architecture (Phase B).

S1 is the only irreplaceable machine-readable store: it keeps producer bytes
exactly as they arrived, before any normalization, and uses SQLite for identity
and transactional state. Everything else in the architecture (Hindsight banks,
projections, indexes) is rebuildable from here, so this module's contract is
narrow and strict:

- raw bytes land in a content-addressed store first, and the row that describes
  them is written in the same transaction;
- an event's identity is derived from where it came from, never invented, so
  re-ingesting the same source twice is a no-op rather than a duplicate;
- gaps are recorded rather than papered over — a missing interval is evidence
  about our coverage, and claiming losslessness we don't have is worse than
  admitting the hole.

Phase A's candidate ledger lives in the same database file
(`hindsight_memory_candidates.py`); this module only adds tables.

Spec: site-djbclark/docs/plans/memory-architecture-v2.md §4.1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_DB = Path.home() / ".hindsight" / "candidates.sqlite3"
DEFAULT_CAS = Path.home() / ".hindsight" / "cas"
SCHEMA_VERSION = 1

# event_id inputs are joined with ASCII unit separator: it cannot occur in a
# path or a hex digest, so no combination of fields can collide by concatenation.
_SEP = "\x1f"

TS_SOURCES = ("producer", "filesystem", "ingest", "inferred")
ROLES = ("user", "assistant", "system", "tool", "unknown")
ORIGINS = ("human", "model", "tool", "web", "system", "derived")


def now_iso() -> str:
    """RFC 3339 UTC with a literal Z, per the spec's timestamp rule."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def derive_event_id(producer: str, source_uri: str, source_locator: str, raw_sha256: str) -> str:
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


class EvidenceStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB, cas_root: str | Path = DEFAULT_CAS):
        self.path = Path(db_path).expanduser()
        self.cas_root = Path(cas_root).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cas_root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self._migrate()

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

        -- CAS inventory. The bytes live on disk under cas_root; this row is the
        -- record that they are ours, how big, and how sensitive.
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

    def put_bytes(self, payload: bytes, *, media_type: str | None = None,
                  sensitivity: str = "normal") -> str:
        """Write bytes to the CAS and inventory them. Returns the digest.

        Content-addressed, so writing the same bytes twice is idempotent and
        costs one hash. The write goes to a temp file and is renamed, so a
        crash mid-write cannot leave a half-object at a name that claims to
        hash correctly.
        """
        digest = sha256_bytes(payload)
        target = self.cas_path(digest)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(payload)
            tmp.replace(target)
        self.db.execute(
            "INSERT OR IGNORE INTO raw_object (sha256, size, media_type, stored_at, sensitivity)"
            " VALUES (?,?,?,?,?)",
            (digest, len(payload), media_type, now_iso(), sensitivity),
        )
        return digest

    def get_bytes(self, digest: str) -> bytes:
        return self.cas_path(digest).read_bytes()

    # -- ingestion --------------------------------------------------------

    def _next_lsn(self) -> int:
        row = self.db.execute("SELECT COALESCE(MAX(ingest_lsn), 0) + 1 FROM event").fetchone()
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

        with self.db:  # one transaction: bytes are inventoried with their row
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
                    event_id, producer, producer_version, account_id, source_uri,
                    source_locator, producer_session_id, source_seq, self._next_lsn(),
                    ts_utc, ts_source, role, event_type, tool_name, tool_call_id,
                    f"cas:{digest}", digest, len(raw), content_encoding, origin,
                    scope, sensitivity, ingest_batch,
                ),
            )
        return event_id, True

    def assign_conversation(self, event_id: str, conversation_id: str, *,
                            assigned_by: str = "adapter", confidence: float | None = None) -> None:
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

    def record_gap(self, producer: str, source_uri: str, reason: str, *,
                   from_locator: str | None = None, to_locator: str | None = None) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO ingest_gap (producer, source_uri, from_locator, to_locator,"
                " reason, detected_at) VALUES (?,?,?,?,?,?)",
                (producer, source_uri, from_locator, to_locator, reason, now_iso()),
            )

    def set_checkpoint(self, producer: str, source_uri: str, *, source_fingerprint: str,
                       committed_locator: str | None, adapter_version: str) -> None:
        row = self.db.execute("SELECT COALESCE(MAX(ingest_lsn), 0) FROM event").fetchone()
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
                (producer, source_uri, source_fingerprint, committed_locator,
                 int(row[0]), adapter_version, now_iso()),
            )

    def checkpoint(self, producer: str, source_uri: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM ingest_checkpoint WHERE producer=? AND source_uri=?",
            (producer, source_uri),
        ).fetchone()

    # -- retrieval --------------------------------------------------------

    def get_event(self, event_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM event WHERE event_id=?", (event_id,)).fetchone()

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
            raise SourceMutated(f"CAS object for {event_id} does not match its recorded hash")
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
        report["integrity_check"] = self.db.execute("PRAGMA integrity_check").fetchone()[0]
        report["foreign_key_check"] = [dict(r) for r in self.db.execute("PRAGMA foreign_key_check")]
        query = "SELECT event_id, raw_sha256, raw_size FROM event ORDER BY ingest_lsn"
        if sample:
            query += f" LIMIT {int(sample)}"
        missing, mismatched, ok = [], [], 0
        for row in self.db.execute(query):
            path = self.cas_path(row["raw_sha256"])
            if not path.exists():
                missing.append(row["event_id"])
                continue
            payload = path.read_bytes()
            if sha256_bytes(payload) != row["raw_sha256"] or len(payload) != row["raw_size"]:
                mismatched.append(row["event_id"])
            else:
                ok += 1
        report.update(hash_ok=ok, hash_missing=missing, hash_mismatched=mismatched)
        report["events"] = self.db.execute("SELECT COUNT(*) FROM event").fetchone()[0]
        report["gaps"] = self.db.execute("SELECT COUNT(*) FROM ingest_gap").fetchone()[0]
        report["healthy"] = (
            report["integrity_check"] == "ok"
            and not report["foreign_key_check"]
            and not missing
            and not mismatched
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
            "events": cur["n"],
            "raw_bytes": cur["bytes"],
            "producers": cur["producers"],
            "sessions": cur["sessions"],
            "objects": self.db.execute("SELECT COUNT(*) FROM raw_object").fetchone()[0],
            "conversations": self.db.execute(
                "SELECT COUNT(DISTINCT conversation_id) FROM conversation_member"
            ).fetchone()[0],
            "gaps": self.db.execute("SELECT COUNT(*) FROM ingest_gap").fetchone()[0],
            "schema_version": self.db.execute(
                "SELECT value FROM s1_meta WHERE key='schema_version'"
            ).fetchone()[0],
        }

    def snapshot(self, destination: str | Path) -> Path:
        """Consistent backup via VACUUM INTO, per the retention policy.

        A live WAL copy is not a valid backup; this produces a file that is.
        """
        target = Path(destination).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        self.db.execute("VACUUM INTO ?", (str(target),))
        return target

    def close(self) -> None:
        self.db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1 evidence store (Phase B)")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--cas", default=str(DEFAULT_CAS))
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

    args = parser.parse_args(argv)
    store = EvidenceStore(args.db, args.cas)
    if args.command == "init":
        print(json.dumps(store.stats(), indent=2))
    elif args.command == "stats":
        print(json.dumps(store.stats(), indent=2))
    elif args.command == "verify":
        report = store.verify(sample=args.sample)
        print(json.dumps(report, indent=2))
        return 0 if report["healthy"] else 1
    elif args.command == "snapshot":
        print(store.snapshot(args.destination))
    elif args.command == "search":
        for row in store.search(args.needle, limit=args.limit):
            print(f"{row['event_id'][:16]}  {row['ts_utc']}  {row['producer']}  {row['event_type']}")
    elif args.command == "show":
        sys.stdout.buffer.write(store.raw_for(args.event_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
