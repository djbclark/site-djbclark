#!/usr/bin/env python3
"""Read-only SQLite transcript adapter for OpenCode and opencode-shaped stores.

Only the explicitly listed session/message tables are queried. Credential,
account, settings, and operational tables are outside the allow-list. Row
payloads are canonical JSON over content columns; mutable timestamps and session
counters are excluded. The raw bytes may contain secrets, so every event and CAS
object is marked sensitive and is not redacted at capture time.

Resume uses SQLite rowid independently for each table. Event coordinates use the
table, primary key, and content hash, so an in-place content revision becomes a
new immutable observation; a changed/deleted high-water row records a gap and
causes the table's surviving rows to be re-read idempotently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s1_evidence import EvidenceStore, SourceMutated, now_iso  # noqa: E402

PRODUCER = "opencode"
ADAPTER_VERSION = "opencode-sqlite-1"
SOURCE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
SOURCE_URI = "sqlite://opencode"

# Each entry is both the table allow-list and its immutable/content fields.
# Unknown future columns are not silently captured (and credentials/settings
# tables are never considered). time_updated and mutable aggregate/status fields
# are deliberately excluded.
CONTENT_COLUMNS: dict[str, tuple[str, ...]] = {
    "session": (
        "id",
        "project_id",
        "workspace_id",
        "parent_id",
        "slug",
        "directory",
        "path",
        "title",
        "version",
        "metadata",
        "revert",
        "permission",
        "agent",
        "model",
        "time_created",
    ),
    "session_v2": (
        "id",
        "project_id",
        "workspace_id",
        "parent_id",
        "fork_session_id",
        "fork_boundary",
        "slug",
        "directory",
        "path",
        "title",
        "version",
        "metadata",
        "revert",
        "permission",
        "agent",
        "model",
        "time_created",
    ),
    "message": ("id", "session_id", "time_created", "data"),
    "part": ("id", "message_id", "session_id", "time_created", "data"),
    "session_message": ("id", "session_id", "type", "seq", "time_created", "data"),
}
REQUIRED_TABLES = ("session", "message", "part")
ROLE_MAP = {
    "user": ("user", "human"),
    "assistant": ("assistant", "model"),
    "tool": ("tool", "tool"),
    "system": ("system", "system"),
}


def canonical_row(row: sqlite3.Row, table: str) -> bytes:
    """Serialize only allow-listed content columns, never mutable status data."""
    payload = {name: row[name] for name in CONTENT_COLUMNS[table] if name in row.keys()}
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def checkpoint_uri(producer: str, table: str) -> str:
    return f"sqlite://{producer}#table={table}"


def parse_checkpoint(locator: str | None) -> int:
    try:
        return int(locator or "0")
    except (TypeError, ValueError):
        return 0


def row_fingerprint(row: sqlite3.Row, table: str) -> str:
    return hashlib.sha256(canonical_row(row, table)).hexdigest()


def parse_data(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def event_fields(
    table: str, row: sqlite3.Row
) -> tuple[str, str, str, str | None, str | None]:
    """Return event type, role, origin, tool name, and tool-call id."""
    data = parse_data(row["data"]) if "data" in row.keys() else {}
    tool_name = tool_call_id = None
    if table == "part":
        kind = str(data.get("type") or "unknown")
        if kind == "tool":
            tool_name = data.get("tool") if isinstance(data.get("tool"), str) else None
            tool_call_id = (
                data.get("callID") if isinstance(data.get("callID"), str) else None
            )
        return f"part.{kind}", "assistant", "model", tool_name, tool_call_id
    if table in ("message", "session_message"):
        role_name = str(data.get("role") or "unknown")
        role, origin = ROLE_MAP.get(role_name, ("unknown", "system"))
        if table == "message":
            event_type = f"message.{role_name}"
        else:
            message_type = str(row["type"]) if "type" in row.keys() else "unknown"
            event_type = f"session_message.{message_type}.{role_name}"
        return event_type, role, origin, None, None
    return f"{table}.snapshot", "system", "derived", None, None


def to_utc(value: Any) -> tuple[str, str]:
    """OpenCode timestamps are epoch milliseconds; accept epoch seconds too."""
    try:
        number = float(value)
        seconds = number / 1000 if abs(number) >= 100_000_000_000 else number
        return (
            datetime.fromtimestamp(seconds, timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "producer",
        )
    except (OverflowError, OSError, TypeError, ValueError):
        return now_iso(), "ingest"


def open_source(path: Path) -> sqlite3.Connection:
    """Open exactly the configured history DB, read-only; immutable is fallback."""
    uri = path.expanduser().resolve().as_uri()
    for suffix in ("?mode=ro", "?mode=ro&immutable=1"):
        con: sqlite3.Connection | None = None
        try:
            con = sqlite3.connect(uri + suffix, uri=True, timeout=1)
            con.row_factory = sqlite3.Row
            # SQLite opens lazily; force a read here so a WAL/lock failure can
            # take the immutable fallback before any table is partially read.
            con.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
            return con
        except sqlite3.OperationalError:
            if con is not None:
                con.close()
            if suffix.endswith("immutable=1"):
                raise
    raise sqlite3.OperationalError("source unavailable")


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")')}


def _record_gap(
    store: EvidenceStore,
    producer: str,
    uri: str,
    reason: str,
    *,
    from_locator: str | None = None,
    dry_run: bool = False,
) -> int:
    if dry_run:
        return 0
    store.record_gap(producer, uri, reason, from_locator=from_locator)
    return 1


def sink(
    store: EvidenceStore,
    source_db: str | Path = SOURCE_DB,
    *,
    producer: str = PRODUCER,
    batch: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    """Ingest the allow-listed SQLite history tables, resuming each by rowid."""
    source = Path(source_db).expanduser()
    uri = f"sqlite://{producer}"
    result = {
        "files": 0,
        "tables": 0,
        "read": 0,
        "created": 0,
        "skipped": 0,
        "gaps": 0,
        "failed": 0,
    }
    batch = batch or f"{producer}-sqlite:{now_iso()}"
    if not source.is_file():
        result["gaps"] += _record_gap(
            store,
            producer,
            uri,
            "source database missing; prior evidence may be incomplete",
            dry_run=dry_run,
        )
        result["failed"] = 1
        return result

    try:
        con = open_source(source)
    except sqlite3.Error as exc:
        result["gaps"] += _record_gap(
            store,
            producer,
            uri,
            f"source database unavailable ({type(exc).__name__}); retry next run",
            dry_run=dry_run,
        )
        result["failed"] = 1
        return result

    result["files"] = 1
    remaining = limit
    try:
        present = {
            str(r[0])
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = [table for table in REQUIRED_TABLES if table not in present]
        if missing:
            result["gaps"] += _record_gap(
                store,
                producer,
                uri,
                "required history tables absent; source schema unsupported",
                dry_run=dry_run,
            )
            result["failed"] = 1
            return result

        for table, content_fields in CONTENT_COLUMNS.items():
            if table not in present:
                continue  # v2 tables are optional in older/opencode-shaped stores
            available = _columns(con, table)
            selected = [column for column in content_fields if column in available]
            if "id" not in selected or "time_created" not in selected:
                result["gaps"] += _record_gap(
                    store,
                    producer,
                    uri,
                    f"allow-listed table {table} lacks required identity/time columns",
                    dry_run=dry_run,
                )
                result["failed"] = 1
                break

            cp_uri = checkpoint_uri(producer, table)
            checkpoint = store.checkpoint(producer, cp_uri)
            committed = parse_checkpoint(
                checkpoint["committed_locator"] if checkpoint else None
            )
            reset_checkpoint = False
            try:
                high_rowid = int(
                    con.execute(
                        f'SELECT COALESCE(MAX(rowid),0) FROM "{table}"'
                    ).fetchone()[0]
                )
                start = committed
                if committed:
                    expected = (
                        checkpoint["source_fingerprint"].split(";", 2)
                        if checkpoint
                        else []
                    )
                    last = con.execute(
                        f"SELECT rowid AS _s1_rowid,{','.join(chr(34) + c + chr(34) for c in selected)} "
                        f'FROM "{table}" WHERE rowid=?',
                        (committed,),
                    ).fetchone()
                    actual_hash = (
                        row_fingerprint(last, table) if last is not None else "missing"
                    )
                    actual_pk = str(last["id"]) if last is not None else "missing"
                    if (
                        committed > high_rowid
                        or last is None
                        or len(expected) != 3
                        or expected[0] != str(committed)
                        or expected[1] != actual_pk
                        or expected[2] != actual_hash
                    ):
                        result["gaps"] += _record_gap(
                            store,
                            producer,
                            uri,
                            f"{table} high-water row changed or was pruned; surviving rows resnapshotted",
                            from_locator=f"{table}:{committed}",
                            dry_run=dry_run,
                        )
                        start = 0
                        reset_checkpoint = True
                query = (
                    f"SELECT rowid AS _s1_rowid,{','.join(chr(34) + c + chr(34) for c in selected)} "
                    f'FROM "{table}" WHERE rowid>? ORDER BY rowid'
                )
                cursor = con.execute(query, (start,))
                last_rowid = start
                last_hash = ""
                last_pk = ""
                table_read = 0
                result["tables"] += 1
                for row in cursor:
                    if remaining is not None and remaining <= 0:
                        break
                    table_read += 1
                    result["read"] += 1
                    if remaining is not None:
                        remaining -= 1
                    rowid = int(row["_s1_rowid"])
                    raw = canonical_row(row, table)
                    digest = hashlib.sha256(raw).hexdigest()
                    pk = str(row["id"])
                    event_type, role, origin, tool_name, tool_call_id = event_fields(
                        table, row
                    )
                    session_id = (
                        str(row["session_id"]) if "session_id" in row.keys() else pk
                    )
                    ts_utc, ts_source = to_utc(row["time_created"])
                    if dry_run:
                        last_rowid, last_hash, last_pk = rowid, digest, pk
                        continue
                    locator = f"{table}:{pk}#{digest}"
                    try:
                        event_id, was_created = store.put_event(
                            producer=producer,
                            source_uri=uri,
                            source_locator=locator,
                            raw=raw,
                            ts_utc=ts_utc,
                            ts_source=ts_source,
                            role=role,
                            origin=origin,
                            event_type=event_type,
                            tool_name=tool_name,
                            tool_call_id=tool_call_id,
                            producer_session_id=session_id,
                            source_seq=(
                                int(row["seq"])
                                if "seq" in row.keys() and row["seq"] is not None
                                else rowid
                            ),
                            scope=producer,
                            ingest_batch=batch,
                            content_encoding="utf-8",
                            media_type="application/json",
                            sensitivity="sensitive",
                        )
                    except SourceMutated:
                        result["gaps"] += _record_gap(
                            store,
                            producer,
                            uri,
                            f"{table} identity collision at row {rowid}",
                            from_locator=f"{table}:{rowid}",
                        )
                        result["skipped"] += 1
                        result["failed"] = 1
                        break
                    result["created"] += int(was_created)
                    last_rowid, last_hash, last_pk = rowid, digest, pk
                    if session_id:
                        store.assign_conversation(
                            event_id,
                            f"{producer}:{session_id}",
                            assigned_by=ADAPTER_VERSION,
                            confidence=1.0,
                        )

                if not dry_run and (last_rowid > committed or reset_checkpoint):
                    store.set_checkpoint(
                        producer,
                        cp_uri,
                        source_fingerprint=f"{last_rowid};{last_pk};{last_hash}",
                        committed_locator=str(last_rowid),
                        adapter_version=ADAPTER_VERSION,
                    )
                if result["failed"]:
                    break
                if remaining is not None and remaining <= 0:
                    break
            except sqlite3.Error as exc:
                result["gaps"] += _record_gap(
                    store,
                    producer,
                    uri,
                    f"{table} read interrupted ({type(exc).__name__}); checkpoint retained for retry",
                    from_locator=f"{table}:{committed}",
                    dry_run=dry_run,
                )
                result["failed"] = 1
                break
    except sqlite3.Error as exc:
        result["gaps"] += _record_gap(
            store,
            producer,
            uri,
            f"source schema/read failed ({type(exc).__name__}); retry next run",
            dry_run=dry_run,
        )
        result["failed"] = 1
    finally:
        con.close()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest OpenCode SQLite history into S1"
    )
    parser.add_argument("--db", default=None, help="S1 database")
    parser.add_argument("--cas", default=None, help="S1 content-addressed store")
    parser.add_argument(
        "--source-db", default=str(SOURCE_DB), help="OpenCode history database"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("sink", help="ingest allow-listed history rows, resuming")
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    kwargs: dict[str, Any] = {}
    if args.db:
        kwargs["db_path"] = args.db
    if args.cas:
        kwargs["cas_root"] = args.cas
    store = EvidenceStore(**kwargs)
    try:
        result = sink(
            store, Path(args.source_db), dry_run=args.dry_run, limit=args.limit
        )
        print(json.dumps({"dry_run": args.dry_run, **result}, indent=2))
        return 1 if result["failed"] else 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
