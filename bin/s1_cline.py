#!/usr/bin/env python3
"""Read-only Cline session and hub-event adapter for S1.

The file allow-list is restricted to ``sessions/<id>/<id>.json`` and its
``<id>.messages.json`` companion, plus the single production hub-events SQLite
database. Rewritten files are retained as content-hash-addressed snapshots.
Hub rows are captured by monotonically increasing sequence from a read-only,
WAL-aware connection; each row is stored in a typed envelope that round-trips
all SQLite values and supplies a bounded ``_s1_search_text`` projection. No
settings, credentials, other databases, or logs are read.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s1_evidence import EvidenceStore, SourceMutated, now_iso

PRODUCER = "cline"
ADAPTER_VERSION = "cline-snapshot-1"
DATA_ROOT = Path.home() / ".cline" / "data"
HUB_DB = DATA_ROOT / "db" / "hub-events-hub-production.db"
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_SEARCH_CHARS = 12_000
MAX_WALK_NODES = 20_000
MAX_WALK_DEPTH = 24
REQUIRED_HUB_COLUMNS = {
    "sequence",
    "event",
    "session_id",
    "envelope_json",
    "created_at",
}


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _tag_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bytes):
        return {
            "type": "blob",
            "base64": base64.b64encode(value).decode("ascii"),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    if isinstance(value, bool):
        return {"type": "integer", "value": int(value)}
    if isinstance(value, int):
        return {"type": "integer", "value": value}
    if isinstance(value, float):
        return {"type": "real", "value": value.hex()}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    raise TypeError(f"unsupported SQLite value type: {type(value).__name__}")


def decode_row(raw: bytes) -> tuple[str, dict[str, Any]]:
    """Recover selected SQLite values from a Cline hub row envelope."""
    obj = json.loads(raw.decode("utf-8"))
    if obj.get("format") != "s1-cline-row-v1":
        raise ValueError("unsupported Cline row encoding")
    result: dict[str, Any] = {}
    for name, tagged in obj["row"]:
        kind = tagged["type"]
        if kind == "null":
            value = None
        elif kind == "integer":
            value = int(tagged["value"])
        elif kind == "real":
            value = float.fromhex(tagged["value"])
        elif kind == "text":
            value = str(tagged["value"])
        elif kind == "blob":
            value = base64.b64decode(tagged["base64"], validate=True)
            if hashlib.sha256(value).hexdigest() != tagged["sha256"]:
                raise ValueError(f"BLOB hash mismatch for {name}")
        else:
            raise ValueError(f"unknown SQLite value tag {kind!r}")
        result[name] = value
    return str(obj["table"]), result


def _walk_text(value: Any, *, limit: int = MAX_SEARCH_CHARS) -> str:
    """Extract bounded scalar text from generic JSON; failures return empty text."""
    out: list[str] = []
    chars = 0
    nodes = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal chars, nodes
        if chars >= limit or nodes >= MAX_WALK_NODES or depth > MAX_WALK_DEPTH:
            return
        nodes += 1
        if isinstance(node, dict):
            for child in node.values():
                walk(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                walk(child, depth + 1)
        elif isinstance(node, str):
            text = node[: max(0, limit - chars)]
            if text:
                out.append(text)
                chars += len(text)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            text = str(node)[: max(0, limit - chars)]
            if text:
                out.append(text)
                chars += len(text)

    try:
        walk(value, 0)
    except Exception:  # noqa: BLE001 - projection must never block raw capture
        return ""
    return " ".join(out)[:limit]


def encode_row(
    table: str, columns: list[str], row: sqlite3.Row, search_text: str
) -> bytes:
    return _json_bytes(
        {
            "_s1_search_text": search_text[:MAX_SEARCH_CHARS],
            "format": "s1-cline-row-v1",
            "table": table,
            "row": [[name, _tag_value(row[name])] for name in columns],
        }
    )


def encode_source_file(raw: bytes, search_text: str) -> bytes:
    """Envelope exact file bytes for index projection and byte-exact recovery."""
    return _json_bytes(
        {
            "_s1_search_text": search_text[:MAX_SEARCH_CHARS],
            "format": "s1-cline-file-v1",
            "source": {
                "base64": base64.b64encode(raw).decode("ascii"),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            },
        }
    )


def decode_source_file(raw: bytes) -> bytes:
    obj = json.loads(raw.decode("utf-8"))
    if obj.get("format") != "s1-cline-file-v1":
        raise ValueError("unsupported Cline file encoding")
    source = obj["source"]
    data = base64.b64decode(source["base64"], validate=True)
    if (
        len(data) != source["size"]
        or hashlib.sha256(data).hexdigest() != source["sha256"]
    ):
        raise ValueError("Cline source file hash mismatch")
    return data


def _allowed_session_file(path: Path, root: Path) -> tuple[str, str] | None:
    sessions = root / "sessions"
    if (
        sessions.is_symlink()
        or path.parent.parent != sessions
        or path.parent.is_symlink()
        or path.is_symlink()
    ):
        return None
    session_id = path.parent.name
    if not SESSION_ID_RE.fullmatch(session_id) or not path.is_file():
        return None
    if path.name == f"{session_id}.json":
        kind = "session"
    elif path.name == f"{session_id}.messages.json":
        kind = "messages"
    else:
        return None
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return None
    return session_id, kind


def session_paths(root: Path = DATA_ROOT) -> list[Path]:
    """Enumerate just the two exact session filenames in each direct session dir."""
    root = root.expanduser()
    sessions = root / "sessions"
    if root.is_symlink() or sessions.is_symlink() or not sessions.is_dir():
        return []
    found: list[Path] = []
    for directory in sorted(sessions.iterdir()):
        if (
            directory.is_symlink()
            or not directory.is_dir()
            or not SESSION_ID_RE.fullmatch(directory.name)
        ):
            continue
        for path in (
            directory / f"{directory.name}.json",
            directory / f"{directory.name}.messages.json",
        ):
            if _allowed_session_file(path, root):
                found.append(path)
    return found


def _file_source_uri(path: Path, root: Path) -> str:
    relative = path.relative_to(root / "sessions").as_posix()
    return f"cline://sessions/{quote(relative, safe='/')}"


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
    found = store.db.execute(
        "SELECT 1 FROM ingest_gap WHERE producer=? AND source_uri=? AND reason=? "
        "AND from_locator IS ? AND to_locator IS ? LIMIT 1",
        (PRODUCER, uri, reason, from_locator, to_locator),
    ).fetchone()
    if found:
        return 0
    store.record_gap(
        PRODUCER, uri, reason, from_locator=from_locator, to_locator=to_locator
    )
    return 1


def _timestamp(value: Any, path: Path) -> tuple[str, str]:
    if isinstance(value, str) and value:
        return value, "producer"
    stamp = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    return stamp.replace(microsecond=0).isoformat().replace("+00:00", "Z"), "filesystem"


def ingest_session_file(
    store: EvidenceStore,
    path: Path,
    *,
    root: Path,
    batch: str,
    dry_run: bool = False,
) -> dict[str, int]:
    result = {"read": 0, "created": 0, "skipped": 0, "gaps": 0, "unparsed": 0}
    identity = _allowed_session_file(path, root)
    if identity is None:
        result["gaps"] += _record_gap(
            store,
            "cline://sessions/unknown",
            "session file outside the exact allow-list",
            dry_run=dry_run,
        )
        return result
    session_id, kind = identity
    uri = _file_source_uri(path, root)
    try:
        source = path.read_bytes()
    except OSError:
        result["gaps"] += _record_gap(
            store, uri, "allow-listed session file unavailable", dry_run=dry_run
        )
        return result
    result["read"] = 1
    parsed: Any = None
    try:
        parsed = json.loads(source)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        result["unparsed"] = 1
    searchable = _walk_text(parsed) if parsed is not None else ""
    raw = encode_source_file(source, searchable)
    digest = hashlib.sha256(source).hexdigest()
    if dry_run:
        return result
    ts_utc, ts_source = _timestamp(
        parsed.get("createdAt") or parsed.get("created_at") or parsed.get("timestamp")
        if isinstance(parsed, dict)
        else None,
        path,
    )
    try:
        event_id, created = store.put_event(
            producer=PRODUCER,
            source_uri=uri,
            source_locator=f"sha256:{digest}",
            raw=raw,
            ts_utc=ts_utc,
            ts_source=ts_source,
            role="unknown",
            origin="derived",
            event_type=f"{kind}.snapshot",
            producer_session_id=session_id,
            scope=PRODUCER,
            ingest_batch=batch,
            content_encoding="utf-8",
            media_type="application/json",
            sensitivity="sensitive",
        )
    except SourceMutated:
        result["gaps"] += _record_gap(store, uri, "content-hash identity collision")
        return result
    result["created"] = int(created)
    result["skipped"] = int(not created)
    store.assign_conversation(
        event_id, f"cline:{session_id}", assigned_by=ADAPTER_VERSION, confidence=1.0
    )
    return result


def _readonly_connection(path: Path, data_root: Path) -> sqlite3.Connection:
    expected = data_root / "db" / "hub-events-hub-production.db"
    if (
        path != expected
        or data_root.is_symlink()
        or path.is_symlink()
        or not path.is_file()
    ):
        raise PermissionError("hub database path is outside the Cline allow-list")
    if (
        path.parent.is_symlink()
        or (path.parent / (path.name + "-wal")).is_symlink()
        or (path.parent / (path.name + "-shm")).is_symlink()
    ):
        raise PermissionError("hub database or SQLite sidecar is a symlink")
    try:
        path.resolve(strict=True).relative_to(data_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise PermissionError(
            "hub database resolves outside the Cline allow-list"
        ) from exc
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    con.row_factory = sqlite3.Row
    try:
        con.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
    except sqlite3.Error:
        con.close()
        raise
    return con


def _checkpoint_sequence(value: str | None) -> int:
    try:
        return int(str(value).split(":", 1)[1])
    except (IndexError, TypeError, ValueError):
        return 0


def ingest_hub_events(
    store: EvidenceStore,
    *,
    data_root: Path = DATA_ROOT,
    db_path: Path | None = None,
    batch: str,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    data_root = data_root.expanduser()
    source = db_path or data_root / "db" / "hub-events-hub-production.db"
    uri = "cline://hub-events/hub-production"
    result = {
        "rows_read": 0,
        "created": 0,
        "skipped": 0,
        "gaps": 0,
        "failed": 0,
        "unparsed": 0,
    }
    con: sqlite3.Connection | None = None
    try:
        con = _readonly_connection(source, data_root)
        table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='hub_events'"
        ).fetchone()
        if table is None:
            raise sqlite3.DatabaseError("hub_events table absent")
        columns = [
            str(row[1]) for row in con.execute('PRAGMA table_info("hub_events")')
        ]
        if not REQUIRED_HUB_COLUMNS.issubset(columns):
            raise sqlite3.DatabaseError("hub_events schema unsupported")
        quoted = ",".join('"' + name.replace('"', '""') + '"' for name in columns)
        checkpoint = store.checkpoint(PRODUCER, uri)
        last_sequence = (
            _checkpoint_sequence(checkpoint["committed_locator"]) if checkpoint else 0
        )
        bounds = con.execute(
            "SELECT MIN(sequence), MAX(sequence) FROM hub_events"
        ).fetchone()
        minimum = int(bounds[0]) if bounds and bounds[0] is not None else None
        if checkpoint and minimum is not None and minimum > last_sequence + 1:
            result["gaps"] += _record_gap(
                store,
                uri,
                "hub event rows rolled off before capture",
                from_locator=f"sequence:{last_sequence + 1}",
                to_locator=f"sequence:{minimum - 1}",
                dry_run=dry_run,
            )
        query = f"SELECT {quoted} FROM hub_events WHERE sequence>? ORDER BY sequence"
        params: tuple[Any, ...] = (last_sequence,)
        if limit is not None:
            query += " LIMIT ?"
            params += (max(0, limit),)
        previous = last_sequence if checkpoint else None
        rows = con.execute(query, params)
        for row in rows:
            sequence = int(row["sequence"])
            result["rows_read"] += 1
            if previous is not None and sequence > previous + 1:
                result["gaps"] += _record_gap(
                    store,
                    uri,
                    "hub event sequence gap",
                    from_locator=f"sequence:{previous + 1}",
                    to_locator=f"sequence:{sequence - 1}",
                    dry_run=dry_run,
                )
            event_name = str(row["event"] or "unknown")
            role, origin = {
                "reasoning.delta": ("assistant", "model"),
                "assistant.delta": ("assistant", "model"),
                "tool.updated": ("tool", "tool"),
                "capability.requested": ("system", "system"),
                "capability.resolved": ("system", "system"),
            }.get(event_name, ("unknown", "system"))
            search_parts: list[Any] = []
            extraction_failed = False
            for name in columns:
                value = row[name]
                search_parts.append(value)
                if name == "envelope_json" and isinstance(value, str):
                    try:
                        search_parts.append(json.loads(value))
                    except (json.JSONDecodeError, TypeError, RecursionError):
                        extraction_failed = True
            result["unparsed"] += int(extraction_failed)
            try:
                search_text = _walk_text(search_parts)
                raw = encode_row("hub_events", columns, row, search_text)
            except Exception:  # noqa: BLE001 - capture must proceed if projection fails
                result["unparsed"] += 1
                raw = encode_row("hub_events", columns, row, "")
            digest = hashlib.sha256(raw).hexdigest()
            locator = f"sequence:{sequence}:sha256:{digest}"
            if dry_run:
                previous = sequence
                continue
            try:
                event_id, created = store.put_event(
                    producer=PRODUCER,
                    source_uri=uri,
                    source_locator=locator,
                    raw=raw,
                    ts_utc=now_iso(),
                    ts_source="ingest",
                    role=role,
                    origin=origin,
                    event_type=event_name[:160],
                    producer_session_id=str(row["session_id"] or "") or None,
                    source_seq=sequence,
                    scope=PRODUCER,
                    ingest_batch=batch,
                    content_encoding="utf-8",
                    media_type="application/json",
                    sensitivity="sensitive",
                )
            except SourceMutated:
                result["gaps"] += _record_gap(
                    store,
                    uri,
                    "hub event identity collision",
                    from_locator=f"sequence:{sequence}",
                )
                previous = sequence
                continue
            result["created"] += int(created)
            result["skipped"] += int(not created)
            session_id = str(row["session_id"] or "")
            if session_id:
                store.assign_conversation(
                    event_id,
                    f"cline:{session_id}",
                    assigned_by=ADAPTER_VERSION,
                    confidence=1.0,
                )
            previous = sequence
        if not dry_run and previous is not None and previous > last_sequence:
            store.set_checkpoint(
                PRODUCER,
                uri,
                source_fingerprint=str(previous),
                committed_locator=f"sequence:{previous}",
                adapter_version=ADAPTER_VERSION,
            )
    except (sqlite3.Error, OSError, PermissionError):
        result["gaps"] += _record_gap(
            store,
            uri,
            "hub event database unavailable, corrupt, or schema-incompatible; retry next scan",
            dry_run=dry_run,
        )
        result["failed"] = 1
    finally:
        if con is not None:
            con.close()
    return result


def scan(
    store: EvidenceStore,
    *,
    data_root: Path = DATA_ROOT,
    db_path: Path | None = None,
    batch: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    data_root = data_root.expanduser()
    totals = {
        "files": 0,
        "rows_read": 0,
        "read": 0,
        "created": 0,
        "skipped": 0,
        "gaps": 0,
        "failed": 0,
        "unparsed": 0,
    }
    batch = batch or f"cline:{now_iso()}"
    paths = session_paths(data_root)
    if limit is not None:
        paths = paths[: max(0, limit)]
    present = {_file_source_uri(path, data_root) for path in paths}
    for path in paths:
        uri = _file_source_uri(path, data_root)
        try:
            result = ingest_session_file(
                store, path, root=data_root, batch=batch, dry_run=dry_run
            )
        except OSError:
            result = {
                "read": 0,
                "created": 0,
                "skipped": 0,
                "gaps": _record_gap(
                    store, uri, "allow-listed session file unavailable", dry_run=dry_run
                ),
                "unparsed": 0,
            }
        totals["files"] += 1
        for key, value in result.items():
            totals[key] += value
    hub = ingest_hub_events(
        store,
        data_root=data_root,
        db_path=db_path,
        batch=batch,
        dry_run=dry_run,
        limit=limit,
    )
    for key, value in hub.items():
        totals[key] += value
    if limit is None and not dry_run:
        known = store.db.execute(
            "SELECT DISTINCT source_uri FROM event WHERE producer=? AND source_uri LIKE 'cline://sessions/%'",
            (PRODUCER,),
        )
        for row in known:
            uri = str(row["source_uri"])
            if uri not in present:
                totals["gaps"] += _record_gap(
                    store, uri, "previously captured session file is no longer present"
                )
    return totals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest allow-listed Cline evidence into S1"
    )
    parser.add_argument("--db", default=None, help="S1 control database")
    parser.add_argument("--cas", default=None, help="S1 CAS root")
    parser.add_argument("--data", default=str(DATA_ROOT), help="Cline data root")
    parser.add_argument(
        "--source-db", default=None, help="override the allow-listed hub database path"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser(
        "scan", help="capture session snapshots and new hub sequences"
    )
    command.add_argument("--dry-run", action="store_true")
    command.add_argument(
        "--limit", type=int, default=None, help="limit files and hub rows"
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
            data_root=Path(args.data),
            db_path=Path(args.source_db) if args.source_db else None,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        print(json.dumps({"dry_run": int(args.dry_run), **result}, sort_keys=True))
        return 1 if result["failed"] else 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
