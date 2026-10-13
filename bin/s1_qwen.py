#!/usr/bin/env python3
"""Rescue Qwen CLI chat JSONL and adjacent runtime snapshots into S1.

Only direct ``projects/*/chats/*.jsonl`` files and the matching
``<chat-stem>.runtime.json`` snapshots are read. Chats are tailed by byte
offset, complete lines only, with prefix verification and explicit gaps when a
source is rewritten or shrinks. Runtime snapshots are content-addressed. The
adapter never opens Qwen settings, credentials, environment files, or install
identifiers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s1_evidence import EvidenceStore, SourceMutated, now_iso
from s1_jsonl import fingerprint_prefix, iter_records, parse_locator

PRODUCER = "qwen"
ADAPTER_VERSION = "qwen-tail-1"
PROJECTS_ROOT = Path.home() / ".qwen" / "projects"
ROLE_MAP = {
    "user": ("user", "human"),
    "assistant": ("assistant", "model"),
    "system": ("system", "system"),
}


def _path_is_allowed(path: Path, root: Path, project: Path) -> bool:
    """Require the exact projects/<project>/chats/<file> layout, no symlinks."""
    if root.is_symlink() or project.is_symlink() or project.parent != root:
        return False
    chats = project / "chats"
    if chats.is_symlink() or path.parent != chats or path.is_symlink():
        return False
    if not path.is_file():
        return False
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def chat_paths(root: Path = PROJECTS_ROOT) -> list[Path]:
    """List only direct, allow-listed chat JSONL files."""
    root = root.expanduser()
    if root.is_symlink() or not root.is_dir():
        return []
    return sorted(
        path
        for path in root.glob("*/chats/*.jsonl")
        if _path_is_allowed(path, root, path.parent.parent)
    )


def source_uri(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return f"qwen://{quote(relative, safe='/')}"


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


def _timestamp(record: dict[str, Any], path: Path) -> tuple[str, str]:
    value = record.get("timestamp") or record.get("created_at")
    if isinstance(value, str) and value:
        return value, "producer"
    stamp = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    return stamp.replace(microsecond=0).isoformat().replace("+00:00", "Z"), "filesystem"


def _event_fields(record: dict[str, Any]) -> tuple[str, str, str]:
    kind = str(record.get("type") or record.get("role") or "unknown")
    role, origin = ROLE_MAP.get(kind.casefold(), ("unknown", "system"))
    subtype = record.get("subtype")
    event_type = f"{kind}.{subtype}" if isinstance(subtype, str) and subtype else kind
    return role, origin, event_type[:160]


def ingest_chat(
    store: EvidenceStore,
    path: Path,
    *,
    root: Path,
    batch: str,
    dry_run: bool = False,
) -> dict[str, int]:
    uri = source_uri(path, root)
    result = {"read": 0, "created": 0, "skipped": 0, "gaps": 0, "unparsed": 0}
    checkpoint = store.checkpoint(PRODUCER, uri)
    start = 0
    if checkpoint is not None:
        committed = parse_locator(checkpoint["committed_locator"])
        shrunk = False
        try:
            size = path.stat().st_size
            shrunk = size < committed
            intact = not shrunk and checkpoint[
                "source_fingerprint"
            ] == fingerprint_prefix(path, committed)
        except OSError:
            intact = False
        if intact:
            start = committed
        else:
            reason = (
                "chat JSONL shrank below its committed offset; retained evidence is not deleted"
                if shrunk
                else "consumed chat JSONL prefix changed; retained evidence is not deleted"
            )
            result["gaps"] += _record_gap(
                store,
                uri,
                reason,
                from_locator=checkpoint["committed_locator"],
                dry_run=dry_run,
            )
            # Hash-qualified locators make a full replay safe while preserving
            # both the earlier evidence and this rewritten generation.
            start = 0

    last_locator = checkpoint["committed_locator"] if checkpoint else None
    for begin, end, raw in iter_records(path, start):
        result["read"] += 1
        try:
            value = json.loads(raw)
            record = value if isinstance(value, dict) else {}
            parsed = isinstance(value, dict)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            record, parsed = {}, False
        result["unparsed"] += int(not parsed)
        role, origin, event_type = _event_fields(record)
        ts_utc, ts_source = _timestamp(record, path)
        digest = hashlib.sha256(raw).hexdigest()
        locator = f"{begin}:{end}#{result['read']}:sha256:{digest}"
        if dry_run:
            last_locator = locator
            continue
        session_id = record.get("session_id") or record.get("sessionId")
        try:
            event_id, created = store.put_event(
                producer=PRODUCER,
                source_uri=uri,
                source_locator=locator,
                raw=raw,
                ts_utc=ts_utc,
                ts_source=ts_source,
                role=role,
                origin=origin,
                event_type=event_type,
                producer_session_id=str(session_id) if session_id else path.stem,
                source_seq=begin,
                scope=PRODUCER,
                ingest_batch=batch,
                content_encoding="utf-8",
                media_type="application/x-ndjson",
                sensitivity="sensitive",
            )
        except SourceMutated:
            result["gaps"] += _record_gap(
                store,
                uri,
                "chat JSONL event identity collision",
                from_locator=locator,
            )
            continue
        result["created"] += int(created)
        result["skipped"] += int(not created)
        store.assign_conversation(
            event_id,
            f"qwen:{session_id or path.stem}",
            assigned_by=ADAPTER_VERSION,
            confidence=1.0,
        )
        last_locator = locator

    if not dry_run and result["read"] and last_locator:
        offset = parse_locator(last_locator)
        store.set_checkpoint(
            PRODUCER,
            uri,
            source_fingerprint=fingerprint_prefix(path, offset),
            committed_locator=last_locator,
            adapter_version=ADAPTER_VERSION,
        )
    return result


def ingest_runtime(
    store: EvidenceStore,
    path: Path,
    *,
    chat_path: Path,
    root: Path,
    batch: str,
    dry_run: bool = False,
) -> dict[str, int]:
    result = {"read": 0, "created": 0, "skipped": 0, "gaps": 0, "unparsed": 0}
    uri = source_uri(chat_path, root)
    if path != chat_path.with_name(
        chat_path.stem + ".runtime.json"
    ) or not _path_is_allowed(path, root, chat_path.parent.parent):
        result["gaps"] += _record_gap(
            store,
            uri,
            "runtime snapshot outside the exact chat allow-list",
            dry_run=dry_run,
        )
        return result
    try:
        raw = path.read_bytes()
    except OSError:
        result["gaps"] += _record_gap(
            store, uri, "allow-listed runtime snapshot unavailable", dry_run=dry_run
        )
        return result
    result["read"] = 1
    digest = hashlib.sha256(raw).hexdigest()
    try:
        json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        result["unparsed"] = 1
    if dry_run:
        return result
    try:
        _, created = store.put_event(
            producer=PRODUCER,
            source_uri=uri,
            source_locator=f"runtime:sha256:{digest}",
            raw=raw,
            ts_utc=now_iso(),
            ts_source="ingest",
            role="system",
            origin="derived",
            event_type="runtime_snapshot",
            producer_session_id=chat_path.stem,
            scope=PRODUCER,
            ingest_batch=batch,
            content_encoding="utf-8",
            media_type="application/json",
            sensitivity="sensitive",
        )
    except SourceMutated:
        result["gaps"] += _record_gap(store, uri, "runtime snapshot identity collision")
        return result
    result["created"] = int(created)
    result["skipped"] = int(not created)
    return result


def scan(
    store: EvidenceStore,
    *,
    root: Path = PROJECTS_ROOT,
    batch: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    root = root.expanduser()
    totals = {
        "files": 0,
        "read": 0,
        "created": 0,
        "skipped": 0,
        "gaps": 0,
        "failed": 0,
        "unparsed": 0,
    }
    paths = chat_paths(root)
    if limit is not None:
        paths = paths[: max(0, limit)]
    batch = batch or f"qwen-tail:{now_iso()}"
    present: set[str] = set()
    runtime_present: set[str] = set()
    for path in paths:
        uri = source_uri(path, root)
        present.add(uri)
        try:
            values = ingest_chat(store, path, root=root, batch=batch, dry_run=dry_run)
        except OSError:
            totals["gaps"] += _record_gap(
                store, uri, "allow-listed chat JSONL unavailable", dry_run=dry_run
            )
            continue
        for key, value in values.items():
            totals[key] += value
        totals["files"] += 1
        runtime = path.with_name(path.stem + ".runtime.json")
        if runtime.exists():
            if _path_is_allowed(runtime, root, path.parent.parent):
                runtime_present.add(uri)
            values = ingest_runtime(
                store, runtime, chat_path=path, root=root, batch=batch, dry_run=dry_run
            )
            for key, value in values.items():
                totals[key] += value
            totals["files"] += 1
    if limit is None and not dry_run:
        for row in store.db.execute(
            "SELECT DISTINCT source_uri FROM ingest_checkpoint WHERE producer=?",
            (PRODUCER,),
        ):
            uri = str(row["source_uri"])
            if uri.startswith("qwen://") and uri not in present:
                totals["gaps"] += _record_gap(
                    store,
                    uri,
                    "previously checkpointed chat source is no longer present",
                )
        for row in store.db.execute(
            "SELECT DISTINCT source_uri FROM event WHERE producer=? AND event_type='runtime_snapshot'",
            (PRODUCER,),
        ):
            uri = str(row["source_uri"])
            if uri.startswith("qwen://") and uri not in runtime_present:
                totals["gaps"] += _record_gap(
                    store,
                    uri,
                    "previously captured runtime snapshot is no longer present",
                )
    return totals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rescue Qwen CLI chats into S1")
    parser.add_argument("--db", default=None, help="S1 control database")
    parser.add_argument("--cas", default=None, help="S1 CAS root")
    parser.add_argument("--projects", default=str(PROJECTS_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser(
        "scan", help="tail allow-listed chats and runtime snapshots"
    )
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--limit", type=int, default=None, help="limit chat files")
    args = parser.parse_args(argv)
    kwargs: dict[str, Any] = {}
    if args.db:
        kwargs["db_path"] = args.db
    if args.cas:
        kwargs["cas_root"] = args.cas
    store = EvidenceStore(**kwargs)
    try:
        result = scan(
            store, root=Path(args.projects), dry_run=args.dry_run, limit=args.limit
        )
        print(json.dumps({"dry_run": int(args.dry_run), **result}, sort_keys=True))
        return 1 if result["failed"] else 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
