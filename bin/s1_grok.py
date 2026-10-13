#!/usr/bin/env python3
"""grok CLI adapter for S1 (Phase B).

grok keeps one session directory per conversation under
`~/.grok/sessions/<url-encoded cwd>/<uuid>/` and appends the full ACP message
stream to `updates.jsonl` (`{method, params, timestamp}` records whose
`params.update.sessionUpdate` carries user/assistant chunks and the tool-call
lifecycle). That one file is the evidence; this adapter touches nothing else.

Two rules carry the weight:

- **Path allow-list.** Only `updates.jsonl` exactly two levels under the
  sessions root is opened. The session-dir siblings (`chat_history.jsonl`,
  `system_prompt.txt`, `summary.json`, `*.lock`, ...) and the config/auth
  files under `~/.grok` are never read.
- **Append-only tailing.** The shared `s1_jsonl` discipline: resume from the
  committed byte offset, never ingest a line without its terminating newline,
  verify the consumed prefix's fingerprint before resuming.

Usage:
    s1_grok.py scan            # all sessions, resuming each file
    s1_grok.py scan --dry-run
    s1_grok.py scan --path <updates.jsonl>
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s1_evidence import EvidenceStore, SourceMutated, now_iso  # noqa: E402
from s1_jsonl import fingerprint_prefix, iter_records, parse_locator  # noqa: E402

PRODUCER = "grok"
ADAPTER_VERSION = "grok-tail-1"
SESSIONS_ROOT = Path.home() / ".grok" / "sessions"

# params.update.sessionUpdate -> (role, origin). Unlisted subtypes (hook
# executions, task lifecycle, usage) are retained as system events: a lossless
# store keeps records it does not recognise rather than dropping them.
UPDATE_MAP: dict[str, tuple[str, str]] = {
    "user_message_chunk": ("user", "human"),
    "agent_message_chunk": ("assistant", "model"),
    "agent_thought_chunk": ("assistant", "model"),
    "tool_call": ("tool", "tool"),
    "tool_call_update": ("tool", "tool"),
}


def resolved_root(root: Path) -> Path:
    return root.expanduser().resolve()


def is_allowed(path: Path, root: Path) -> bool:
    """Only `<sessions>/<cwd>/<uuid>/updates.jsonl`, nothing else."""
    try:
        resolved = path.resolve()
        rel = resolved.relative_to(resolved_root(root))
    except (OSError, ValueError):
        return False
    return resolved.name == "updates.jsonl" and len(rel.parts) == 3


def to_utc(ts: Any, fallback_path: Path) -> tuple[str, str]:
    """Records carry epoch seconds in `timestamp`; fall back honestly."""
    try:
        dt = datetime.fromtimestamp(float(ts), timezone.utc)
        return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"), "producer"
    except (TypeError, ValueError, OSError, OverflowError):
        pass
    try:
        dt = datetime.fromtimestamp(fallback_path.stat().st_mtime, timezone.utc)
        return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"), "filesystem"
    except OSError:
        return now_iso(), "ingest"


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
    # The directory name is the session uuid; records' sessionId overrides.
    session_id: str | None = path.parent.name or None

    for begin, end, raw in iter_records(path, start):
        seen += 1
        locator = f"{begin}:{end}#{seen}"
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            record = {}
        if not isinstance(record, dict):
            record = {}

        method = str(record.get("method") or "unknown")
        params = record.get("params")
        if not isinstance(params, dict):
            params = {}
        if params.get("sessionId"):
            session_id = str(params["sessionId"])
        update = params.get("update")
        if not isinstance(update, dict):
            update = {}
        subtype = str(update.get("sessionUpdate") or "")

        role, origin = UPDATE_MAP.get(subtype, ("system", "system"))
        event_type = f"{method}.{subtype}" if subtype else method
        tool_name = str(update["title"]) if update.get("title") else None
        tool_call_id = str(update["toolCallId"]) if update.get("toolCallId") else None
        ts_utc, ts_source = to_utc(record.get("timestamp"), path)

        if dry_run:
            last_locator = locator
            continue

        try:
            event_id, was_created = store.put_event(
                producer=PRODUCER,
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
                source_seq=seen,
                scope=PRODUCER,
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


def updates_paths(root: Path) -> list[Path]:
    """Every allow-listed updates.jsonl under the sessions root."""
    resolved = resolved_root(root)
    if not resolved.is_dir():
        return []
    return sorted(p for p in resolved.glob("*/*/updates.jsonl") if is_allowed(p, root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest grok updates.jsonl streams into S1")
    parser.add_argument("--db", default=None)
    parser.add_argument("--cas", default=None)
    parser.add_argument("--sessions", default=str(SESSIONS_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="ingest new records from every session")
    scan.add_argument("--path", default=None, help="one updates.jsonl instead of all")
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

    root = Path(args.sessions).expanduser()
    if args.path:
        candidate = Path(args.path).expanduser()
        if not is_allowed(candidate, root):
            parser.error(f"{candidate} is not an allow-listed updates.jsonl under {root}")
        paths = [candidate]
    else:
        paths = updates_paths(root)
    if args.limit:
        paths = paths[: args.limit]

    batch = f"grok-tail:{now_iso()}"
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
