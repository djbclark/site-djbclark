#!/usr/bin/env python3
"""Copilot CLI adapter for S1 (Phase B).

Copilot CLI writes one append-only `events.jsonl` per session under
`~/.copilot/session-state/<uuid>/`, with `{id, parentId, timestamp, type,
data}` records (`session.start`, `user.message`, `assistant.message`,
`tool.execution_start`/`complete`, hooks, usage checkpoints). Its
`session-store.db` is only a derived summary and is rewritten on upgrades, so
this adapter reads the JSONL transcripts and never touches the db.

Two rules carry the weight:

- **Path allow-list.** Only `events.jsonl` exactly one level under the
  session-state root is opened; `workspace.yaml`, `checkpoints/` and every
  other sibling stay out.
- **Append-only tailing.** The shared `s1_jsonl` discipline: resume from the
  committed byte offset, never ingest a line without its terminating newline,
  verify the consumed prefix's fingerprint before resuming.

Usage:
    s1_copilot.py scan            # all sessions, resuming each file
    s1_copilot.py scan --dry-run
    s1_copilot.py scan --path <events.jsonl>
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s1_claude import repo_scope  # noqa: E402
from s1_evidence import EvidenceStore, SourceMutated, now_iso  # noqa: E402
from s1_jsonl import fingerprint_prefix, iter_records, parse_locator  # noqa: E402

PRODUCER = "copilot"
ADAPTER_VERSION = "copilot-tail-1"
SESSION_STATE = Path.home() / ".copilot" / "session-state"

# Record type -> (role, origin). Unlisted types are retained as system events:
# a lossless store keeps records it does not recognise rather than dropping
# them.
TYPE_MAP: dict[str, tuple[str, str]] = {
    "user.message": ("user", "human"),
    "assistant.message": ("assistant", "model"),
    "tool.execution_start": ("tool", "tool"),
    "tool.execution_complete": ("tool", "tool"),
    "system.message": ("system", "system"),
}


def resolved_root(root: Path) -> Path:
    return root.expanduser().resolve()


def is_allowed(path: Path, root: Path) -> bool:
    """Only `<session-state>/<uuid>/events.jsonl`, nothing else."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if resolved.name != "events.jsonl":
        return False
    return resolved.parent.parent == resolved_root(root)


def ingest_file(
    store: EvidenceStore,
    path: Path,
    *,
    batch: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    uri = path.resolve().as_uri()
    checkpoint = store.checkpoint(PRODUCER, uri)

    start = 0
    if checkpoint is not None:
        committed = parse_locator(checkpoint["committed_locator"])
        # Verify over exactly the span that produced the stored fingerprint.
        if checkpoint["source_fingerprint"] == fingerprint_prefix(path, committed):
            start = committed
        else:
            # The prefix we already consumed has changed, so this is no longer
            # the file we were tailing. Its earlier content may be
            # unrecoverable — say so rather than quietly re-reading.
            if not dry_run:
                store.record_gap(
                    PRODUCER, uri,
                    "consumed prefix changed (truncated or rewritten); prior "
                    "content may be unrecoverable",
                    from_locator=checkpoint["committed_locator"],
                )

    created = seen = skipped = 0
    last_locator = checkpoint["committed_locator"] if checkpoint else None
    # The directory name is the session uuid; records' session.start overrides.
    session_id: str | None = path.parent.name or None
    scope = "copilot"
    producer_version: str | None = None

    for begin, end, raw in iter_records(path, start):
        seen += 1
        locator = f"{begin}:{end}#{seen}"
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            record = {}
        if not isinstance(record, dict):
            record = {}

        record_type = str(record.get("type") or "unknown")
        data = record.get("data")
        if not isinstance(data, dict):
            data = {}
        if record_type == "session.start":
            if data.get("sessionId"):
                session_id = str(data["sessionId"])
            if data.get("copilotVersion"):
                producer_version = str(data["copilotVersion"])
            context = data.get("context")
            if isinstance(context, dict) and context.get("cwd"):
                scope = repo_scope(str(context["cwd"]))

        role, origin = TYPE_MAP.get(record_type, ("system", "system"))
        tool_name = str(data["toolName"]) if data.get("toolName") else None
        tool_call_id = str(data["toolCallId"]) if data.get("toolCallId") else None
        timestamp = record.get("timestamp")
        if isinstance(timestamp, str) and timestamp:
            ts_utc, ts_source = timestamp, "producer"
        else:
            ts_utc = datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            ts_source = "filesystem"

        if dry_run:
            last_locator = locator
            continue

        try:
            event_id, was_created = store.put_event(
                producer=PRODUCER,
                producer_version=producer_version,
                source_uri=uri,
                source_locator=locator,
                raw=raw,
                ts_utc=ts_utc,
                ts_source=ts_source,
                role=role,
                origin=origin,
                event_type=record_type,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                producer_session_id=session_id,
                source_seq=seen,
                scope=scope,
                ingest_batch=batch,
                content_encoding="utf-8",
                media_type="application/x-ndjson",
            )
        except SourceMutated:
            # Same coordinates, different bytes: the file was rewritten under
            # us. Record it and stop; a later pass re-fingerprints cleanly.
            store.record_gap(PRODUCER, uri, "record changed at a committed offset",
                             from_locator=locator)
            skipped += 1
            break

        created += was_created
        if session_id:
            store.assign_conversation(
                event_id, f"{PRODUCER}:{session_id}",
                assigned_by=ADAPTER_VERSION, confidence=1.0,
            )
        last_locator = locator

    if not dry_run and seen:
        store.set_checkpoint(
            PRODUCER, uri,
            source_fingerprint=fingerprint_prefix(path, parse_locator(last_locator)),
            committed_locator=last_locator,
            adapter_version=ADAPTER_VERSION,
        )
    return {"file": path.name, "read": seen, "created": created, "skipped": skipped}


def events_paths(root: Path) -> list[Path]:
    """Every allow-listed events.jsonl under the session-state root."""
    resolved = resolved_root(root)
    if not resolved.is_dir():
        return []
    return sorted(p for p in resolved.glob("*/events.jsonl") if is_allowed(p, root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest Copilot CLI transcripts into S1")
    parser.add_argument("--db", default=None)
    parser.add_argument("--cas", default=None)
    parser.add_argument("--session-state", default=str(SESSION_STATE))
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="ingest new records from every session")
    scan.add_argument("--path", default=None, help="one events.jsonl instead of all")
    scan.add_argument("--dry-run", action="store_true")
    scan.add_argument("--limit", type=int, default=None, help="stop after N files")
    scan.add_argument("--quiet", action="store_true")

    args = parser.parse_args(argv)
    kwargs: dict[str, Any] = {}
    if args.db:
        kwargs["db_path"] = args.db
    if args.cas:
        kwargs["cas_root"] = args.cas
    store = EvidenceStore(**kwargs)

    root = Path(args.session_state).expanduser()
    if args.path:
        candidate = Path(args.path).expanduser()
        if not is_allowed(candidate, root):
            parser.error(f"{candidate} is not an allow-listed events.jsonl under {root}")
        paths = [candidate]
    else:
        paths = events_paths(root)
    if args.limit:
        paths = paths[: args.limit]

    batch = f"copilot-tail:{now_iso()}"
    totals = {"files": 0, "read": 0, "created": 0, "skipped": 0}
    for path in paths:
        if not path.exists():
            continue
        try:
            result = ingest_file(store, path, batch=batch, dry_run=args.dry_run)
        except OSError as exc:
            print(f"  {path.name}: unreadable ({exc})", file=sys.stderr)
            continue
        totals["files"] += 1
        for key in ("read", "created", "skipped"):
            totals[key] += result[key]
        if not args.quiet and result["read"]:
            print(f"  {result['file'][:44]:44} read={result['read']:6} new={result['created']:6}")
    print(json.dumps({"dry_run": args.dry_run, **totals}, indent=2))
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
