#!/usr/bin/env python3
"""Tail Cursor project agent transcripts into S1 without opening project state.

The only inputs are direct ``projects/*/agent-transcripts/<uuid>/<uuid>.jsonl``
files. Each complete source line is retained byte-for-byte and checkpointed by
byte offset; incomplete tails wait for the next scan, while rewritten or
shrunk prefixes record a gap and replay without deleting earlier evidence.
Project tools, canvases, terminals, MCP state, logs, and auth/approval files are
never read. SQLite/WAL session stores are handled separately by
``s1_cursor_cli.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s1_evidence import EvidenceStore, SourceMutated, now_iso
from s1_jsonl import fingerprint_prefix, iter_records, parse_locator

PRODUCER = "cursor-project-transcript"
ADAPTER_VERSION = "cursor-project-transcript-tail-1"
PROJECTS_ROOT = Path.home() / ".cursor" / "projects"
SESSION_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
ROLE_MAP = {
    "user": ("user", "human"),
    "assistant": ("assistant", "model"),
    "system": ("system", "system"),
    "tool": ("tool", "tool"),
}


def transcript_paths(root: Path = PROJECTS_ROOT) -> list[Path]:
    """Return only regular files in the exact project-transcript allow-list."""
    root = root.expanduser()
    if root.is_symlink() or not root.is_dir():
        return []
    paths: list[Path] = []
    for project in sorted(root.iterdir()):
        if project.is_symlink() or not project.is_dir():
            continue
        transcripts = project / "agent-transcripts"
        if transcripts.is_symlink() or not transcripts.is_dir():
            continue
        for session in sorted(transcripts.iterdir()):
            if (
                session.is_symlink()
                or not session.is_dir()
                or not SESSION_RE.fullmatch(session.name)
            ):
                continue
            path = session / f"{session.name}.jsonl"
            if _path_is_allowed(path, root, project, session):
                paths.append(path)
    return paths


def _path_is_allowed(path: Path, root: Path, project: Path, session: Path) -> bool:
    transcripts = project / "agent-transcripts"
    if (
        root.is_symlink()
        or project.is_symlink()
        or project.parent != root
        or transcripts.is_symlink()
        or session.is_symlink()
        or session.parent != transcripts
        or not SESSION_RE.fullmatch(session.name)
        or path != session / f"{session.name}.jsonl"
        or path.is_symlink()
        or not path.is_file()
    ):
        return False
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def source_uri(path: Path, root: Path) -> str:
    """Use project slug plus UUID: a shared UUID is not sufficient identity."""
    relative = path.relative_to(root).as_posix()
    return f"cursor-project-transcript://{quote(relative, safe='/')}"


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


def _timestamp(
    record: dict[str, Any], message: dict[str, Any], path: Path
) -> tuple[str, str]:
    value = (
        message.get("timestamp")
        or message.get("createdAt")
        or message.get("created_at")
        or record.get("timestamp")
        or record.get("createdAt")
        or record.get("created_at")
    )
    if isinstance(value, str) and value:
        return value, "producer"
    stamp = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    return stamp.replace(microsecond=0).isoformat().replace("+00:00", "Z"), "filesystem"


def _record_fields(record: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    role_text = str(record.get("role") or "").casefold()
    role, origin = ROLE_MAP.get(role_text, ("unknown", "system"))
    message = record.get("message")
    if not isinstance(message, dict):
        message = {}
    event_type = message.get("type")
    if not isinstance(event_type, str) or not event_type:
        event_type = "message" if role != "unknown" else "unknown"
    return role, origin, event_type[:160], message


def ingest_file(
    store: EvidenceStore,
    path: Path,
    *,
    root: Path,
    batch: str,
    dry_run: bool = False,
) -> dict[str, int]:
    """Tail one allow-listed transcript while preserving each exact source line."""
    uri = source_uri(path, root)
    result = {
        "read": 0,
        "created": 0,
        "skipped": 0,
        "gaps": 0,
        "unparsed": 0,
        "failed": 0,
    }
    project = path.parent.parent.parent
    session = path.parent
    if not _path_is_allowed(path, root, project, session):
        result["gaps"] += _record_gap(
            store, uri, "transcript file outside the exact allow-list", dry_run=dry_run
        )
        result["failed"] = 1
        return result

    checkpoint = None if dry_run else store.checkpoint(PRODUCER, uri)
    start = 0
    if checkpoint is not None:
        committed = parse_locator(checkpoint["committed_locator"])
        try:
            size = path.stat().st_size
            shrunk = size < committed
            intact = not shrunk and checkpoint[
                "source_fingerprint"
            ] == fingerprint_prefix(path, committed)
        except OSError:
            shrunk, intact = False, False
        if intact:
            start = committed
        else:
            reason = (
                "transcript JSONL shrank below its committed offset; retained evidence is not deleted"
                if shrunk
                else "consumed transcript JSONL prefix changed; retained evidence is not deleted"
            )
            result["gaps"] += _record_gap(
                store,
                uri,
                reason,
                from_locator=checkpoint["committed_locator"],
                dry_run=dry_run,
            )
            start = 0

    previous_locator = checkpoint["committed_locator"] if checkpoint else None
    try:
        for begin, end, raw in iter_records(path, start):
            result["read"] += 1
            try:
                value = json.loads(raw)
                parsed = isinstance(value, dict) and isinstance(
                    value.get("message"), dict
                )
                record = value if isinstance(value, dict) else {}
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
                record, parsed = {}, False
            result["unparsed"] += int(not parsed)
            role, origin, event_type, message = _record_fields(record)
            ts_utc, ts_source = _timestamp(record, message, path)
            digest = hashlib.sha256(raw).hexdigest()
            locator = f"{begin}:{end}#{result['read']}:sha256:{digest}"
            if dry_run:
                previous_locator = locator
                continue
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
                    producer_session_id=session.name,
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
                    "transcript event identity collision",
                    from_locator=locator,
                )
                result["failed"] = 1
                continue
            result["created"] += int(created)
            result["skipped"] += int(not created)
            store.assign_conversation(
                event_id,
                f"cursor-project-transcript:{path.parent.parent.name}:{session.name}",
                assigned_by=ADAPTER_VERSION,
                confidence=1.0,
            )
            previous_locator = locator
    except OSError:
        result["gaps"] += _record_gap(
            store, uri, "allow-listed transcript JSONL unavailable", dry_run=dry_run
        )
        result["failed"] = 1
        return result

    if not dry_run and not result["failed"] and result["read"] and previous_locator:
        committed = parse_locator(previous_locator)
        store.set_checkpoint(
            PRODUCER,
            uri,
            source_fingerprint=fingerprint_prefix(path, committed),
            committed_locator=previous_locator,
            adapter_version=ADAPTER_VERSION,
        )
    return result


def scan(
    store: EvidenceStore,
    *,
    root: Path = PROJECTS_ROOT,
    batch: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    """Scan allow-listed project transcripts; never inspect neighboring state."""
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
    paths = transcript_paths(root)
    if limit is not None:
        paths = paths[: max(0, limit)]
    batch = batch or f"{PRODUCER}:{now_iso()}"
    present: set[str] = set()
    for path in paths:
        uri = source_uri(path, root)
        present.add(uri)
        values = ingest_file(store, path, root=root, batch=batch, dry_run=dry_run)
        totals["files"] += 1
        for key in ("read", "created", "skipped", "gaps", "failed", "unparsed"):
            totals[key] += values[key]
    if limit is None and not dry_run:
        previous = {
            str(row[0])
            for row in store.db.execute(
                "SELECT DISTINCT source_uri FROM ingest_checkpoint WHERE producer=?",
                (PRODUCER,),
            )
        }
        previous.update(
            str(row[0])
            for row in store.db.execute(
                "SELECT DISTINCT source_uri FROM event WHERE producer=?", (PRODUCER,)
            )
        )
        for uri in sorted(previous - present):
            totals["gaps"] += _record_gap(
                store,
                uri,
                "previously captured project transcript is no longer present",
            )
    return totals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Tail Cursor project agent transcripts into S1"
    )
    parser.add_argument("--db", default=None, help="S1 control database")
    parser.add_argument("--cas", default=None, help="S1 CAS root")
    parser.add_argument(
        "--projects", default=str(PROJECTS_ROOT), help="Cursor projects root"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("scan", help="tail allow-listed agent-transcripts files")
    command.add_argument("--dry-run", action="store_true")
    command.add_argument(
        "--limit", type=int, default=None, help="limit transcript files"
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
            root=Path(args.projects).expanduser(),
            dry_run=args.dry_run,
            limit=args.limit,
        )
        print(json.dumps({"dry_run": int(args.dry_run), **result}, sort_keys=True))
        return 1 if result["failed"] else 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
