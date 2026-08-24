#!/usr/bin/env python3
"""Hermes event sink for S1 (Phase B).

Hermes keeps every message and tool event in `~/.hermes/state.db`. That
database stays authoritative and source-compatible — this adapter only reads
it, copying each row into S1 as evidence so the record survives independently
of Hermes's own retention, compaction, and pruning.

The one design decision worth stating plainly: **a database row is not a file
byte range**, so "the producer bytes" have to be defined. We serialise a fixed
set of *content* columns as canonical JSON (sorted keys, no whitespace
variance) and treat that as the raw payload. Mutable status columns —
`observed`, `active`, `compacted`, and the display/routing metadata Hermes
rewrites as conversations age — are deliberately excluded. Including them
would mean a row's bytes change every time Hermes marks it compacted, and S1
would correctly report that the source had mutated. Excluding them keeps
re-ingestion idempotent while still preserving everything that carries
meaning.

Usage:
    hindsight_s1_hermes.py sink              # ingest new rows, resuming
    hindsight_s1_hermes.py sink --dry-run
    hindsight_s1_hermes.py sink --limit 5000
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hindsight_s1 import EvidenceStore, SourceMutated, now_iso  # noqa: E402

PRODUCER = "hermes"
ADAPTER_VERSION = "hermes-sink-1"
STATE_DB = Path.home() / ".hermes" / "state.db"

# Content columns only. Anything Hermes rewrites in place is excluded — see the
# module docstring for why that is a correctness requirement, not tidiness.
CONTENT_COLUMNS = (
    "id", "session_id", "role", "content", "tool_call_id", "tool_calls",
    "tool_name", "timestamp", "token_count", "finish_reason", "reasoning",
    "reasoning_content", "reasoning_details", "codex_reasoning_items",
    "codex_message_items", "platform_message_id", "api_content",
)
MUTABLE_COLUMNS = ("observed", "active", "compacted", "effect_disposition",
                   "display_kind", "display_metadata")

ROLE_MAP = {
    "user": ("user", "human"),
    "assistant": ("assistant", "model"),
    "tool": ("tool", "tool"),
    "system": ("system", "system"),
    "session_meta": ("system", "system"),
}


def row_bytes(row: sqlite3.Row) -> bytes:
    """Canonical JSON for the content columns — the row's 'producer bytes'."""
    payload = {k: row[k] for k in CONTENT_COLUMNS if k in row.keys()}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def to_utc(ts: Any) -> tuple[str, str]:
    """Hermes stores epoch seconds as REAL; fall back honestly if absent."""
    try:
        dt = datetime.fromtimestamp(float(ts), timezone.utc)
        return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"), "producer"
    except (TypeError, ValueError):
        return now_iso(), "ingest"


def sink(
    store: EvidenceStore,
    state_db: Path = STATE_DB,
    *,
    batch: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    uri = state_db.resolve().as_uri()
    batch = batch or f"hermes-sink:{now_iso()}"
    checkpoint = store.checkpoint(PRODUCER, uri)
    last_id = 0
    if checkpoint is not None and checkpoint["committed_locator"]:
        try:
            last_id = int(str(checkpoint["committed_locator"]).split(":", 1)[1])
        except (IndexError, ValueError):
            last_id = 0

    # Read-only: never hold a write lock on Hermes's live database.
    con = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    query = "SELECT * FROM messages WHERE id > ? ORDER BY id"
    if limit:
        query += f" LIMIT {int(limit)}"

    created = seen = skipped = 0
    max_id = last_id
    try:
        for row in con.execute(query, (last_id,)):
            seen += 1
            raw = row_bytes(row)
            role, origin = ROLE_MAP.get(str(row["role"]), ("unknown", "system"))
            ts_utc, ts_source = to_utc(row["timestamp"])
            if dry_run:
                max_id = max(max_id, int(row["id"]))
                continue
            try:
                event_id, was_created = store.put_event(
                    producer=PRODUCER,
                    source_uri=uri,
                    source_locator=f"messages:{row['id']}",
                    raw=raw,
                    ts_utc=ts_utc,
                    ts_source=ts_source,
                    role=role,
                    origin=origin,
                    event_type=f"message.{row['role']}",
                    tool_name=row["tool_name"],
                    tool_call_id=row["tool_call_id"],
                    producer_session_id=row["session_id"],
                    source_seq=int(row["id"]),
                    scope="hermes",
                    ingest_batch=batch,
                    media_type="application/json",
                )
            except SourceMutated:
                # A committed row's content columns changed. Record it rather
                # than overwrite — the whole point of S1 is that evidence is
                # not silently rewritten.
                store.record_gap(PRODUCER, uri, "content columns changed for a committed row",
                                 from_locator=f"messages:{row['id']}")
                skipped += 1
                continue
            created += was_created
            if row["session_id"]:
                store.assign_conversation(event_id, f"{PRODUCER}:{row['session_id']}",
                                          assigned_by=ADAPTER_VERSION, confidence=1.0)
            max_id = max(max_id, int(row["id"]))
    finally:
        con.close()

    if not dry_run and seen:
        store.set_checkpoint(
            PRODUCER, uri,
            source_fingerprint=f"messages:max={max_id}",
            committed_locator=f"messages:{max_id}",
            adapter_version=ADAPTER_VERSION,
        )
    return {"read": seen, "created": created, "skipped": skipped,
            "from_id": last_id, "to_id": max_id}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest Hermes events into S1")
    parser.add_argument("--db", default=None, help="S1 database")
    parser.add_argument("--cas", default=None)
    parser.add_argument("--state-db", default=str(STATE_DB))
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sink", help="ingest new Hermes messages, resuming")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--limit", type=int, default=None)

    args = parser.parse_args(argv)
    kwargs: dict[str, Any] = {}
    if args.db:
        kwargs["db_path"] = args.db
    if args.cas:
        kwargs["cas_root"] = args.cas
    store = EvidenceStore(**kwargs)
    result = sink(store, Path(args.state_db).expanduser(),
                  dry_run=args.dry_run, limit=args.limit)
    print(json.dumps({"dry_run": args.dry_run, **result}, indent=2))
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
