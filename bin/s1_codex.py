#!/usr/bin/env python3
"""Codex rollout adapter for S1 (Phase B).

Codex writes one JSONL rollout per session under
`~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl` (full tool calls and
outputs). `~/.codex/sessions` is itself a symlink into site-private's
`.codex-runtime/sessions` tree, and the survey (s1-survey-report.md §2.1)
showed the month directories were re-laid around 2026-09-09 — the path of a
rollout is *not* stable evidence. So this adapter keys every event on the
`session_meta` id inside the file plus the byte offset within it
(`codex://sessions/<id>`), never on the path; a file that moves between month
directories is rediscovered by content and resumes through the fingerprint
check exactly like an append-only file that stayed put.

Two rules carry the weight:

- **Path allow-list.** Only `rollout-*.jsonl` files that resolve inside the
  resolved sessions tree are ever opened. `auth.json`, the sqlite indexes and
  everything else under `~/.codex` are never read, and a symlinked file that
  resolves outside the tree is refused even under `--path`.
- **Append-only tailing.** Identical to `s1_claude.py`: resume from the last
  committed byte offset, never ingest a line that has no terminating newline
  yet, and verify the consumed prefix's fingerprint before resuming.

Usage:
    s1_codex.py scan            # all rollouts, resuming each session
    s1_codex.py scan --dry-run  # report what would be ingested
    s1_codex.py scan --path <rollout.jsonl>
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

PRODUCER = "codex"
ADAPTER_VERSION = "codex-tail-1"
SESSIONS_ROOT = Path.home() / ".codex" / "sessions"

# response_item message role -> (role, origin). Unlisted payload types are
# retained as system events: a lossless store keeps records it does not
# recognise rather than dropping them.
MESSAGE_ROLE_MAP: dict[str, tuple[str, str]] = {
    "user": ("user", "human"),
    "assistant": ("assistant", "model"),
    "developer": ("system", "system"),
    "system": ("system", "system"),
}
PAYLOAD_ROLE_MAP: dict[str, tuple[str, str]] = {
    "reasoning": ("assistant", "model"),
    "custom_tool_call": ("tool", "tool"),
    "custom_tool_call_output": ("tool", "tool"),
    "function_call": ("tool", "tool"),
    "function_call_output": ("tool", "tool"),
}


def resolved_root(root: Path) -> Path:
    return root.expanduser().resolve()


def is_allowed(path: Path, root: Path) -> bool:
    """Only rollout JSONL files that resolve inside the sessions tree.

    Resolving the root once is the single permitted symlink hop
    (`~/.codex/sessions` -> site-private's runtime tree). Anything that
    resolves outside that tree — a planted symlink, `auth.json`, the sqlite
    indexes — is never opened by this adapter.
    """
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if not (resolved.name.startswith("rollout-") and resolved.suffix == ".jsonl"):
        return False
    return resolved_root(root) in resolved.parents


def session_meta(path: Path) -> dict[str, Any] | None:
    """The session_meta payload from the first complete line, or None.

    None means either the first record is still being written (transient —
    the next pass picks it up) or the file does not start with a usable
    session id (permanent — the caller records a gap, because an event
    identity we cannot derive from content is one we must not invent from
    the path).
    """
    try:
        with path.open("rb") as handle:
            line = handle.readline()
    except OSError:
        return None
    if not line.endswith(b"\n"):
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict) or record.get("type") != "session_meta":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    if not (payload.get("id") or payload.get("session_id")):
        return None
    return payload


def role_origin(payload_type: str, payload: dict[str, Any]) -> tuple[str, str]:
    if payload_type == "message":
        return MESSAGE_ROLE_MAP.get(str(payload.get("role")), ("unknown", "system"))
    return PAYLOAD_ROLE_MAP.get(payload_type, ("unknown", "system"))


def tool_fields(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    ptype = payload.get("type")
    if ptype in ("custom_tool_call", "function_call"):
        return payload.get("name"), payload.get("call_id")
    if ptype in ("custom_tool_call_output", "function_call_output"):
        return None, payload.get("call_id")
    return None, None


def ingest_file(
    store: EvidenceStore,
    path: Path,
    *,
    batch: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    meta = session_meta(path)
    if meta is None:
        # No content-derived identity: skip rather than keying on the path.
        # A first line still being written is transient and silent; a complete
        # first record without a session id is a real hole in our coverage.
        try:
            with path.open("rb") as handle:
                first = handle.readline()
        except OSError:
            first = b""
        if first.endswith(b"\n") and not dry_run:
            uri = path.resolve().as_uri()
            store.record_gap(
                PRODUCER, uri,
                "rollout has no session_meta id on its first line; cannot derive "
                "a path-independent event identity",
            )
        return {"file": path.name, "read": 0, "created": 0, "skipped": 0}

    session_id = str(meta.get("id") or meta.get("session_id"))
    uri = f"{PRODUCER}://sessions/{session_id}"
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
                    "consumed prefix changed (truncated, rewritten or a second "
                    "rollout claims the session id); prior content may be "
                    "unrecoverable",
                    from_locator=checkpoint["committed_locator"],
                )

    created = seen = skipped = 0
    last_locator = checkpoint["committed_locator"] if checkpoint else None
    scope = repo_scope(str(meta.get("cwd") or "") or None)
    producer_version = str(meta.get("cli_version") or "") or None

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
        payload = record.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        payload_type = str(payload.get("type") or "")
        if record_type == "session_meta":
            role, origin = "system", "system"
        elif record_type == "response_item":
            role, origin = role_origin(payload_type, payload)
        else:
            # event_msg, turn_context, world_state, token_usage_record, ...
            role, origin = "system", "system"
        event_type = payload_type or record_type
        timestamp = record.get("timestamp")
        if isinstance(timestamp, str) and timestamp:
            ts_utc, ts_source = timestamp, "producer"
        else:
            ts_utc = datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            ts_source = "filesystem"
        tool_name, tool_call_id = tool_fields(payload)

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
                event_type=event_type,
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
            # Same coordinates, different bytes: a second rollout file claims
            # this session id with different content, or the file was rewritten
            # under us. Record it and stop; a later pass re-fingerprints.
            store.record_gap(PRODUCER, uri, "record changed at a committed offset",
                             from_locator=locator)
            skipped += 1
            break

        created += was_created
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


def rollout_paths(root: Path) -> list[Path]:
    """Every allow-listed rollout file under the sessions tree."""
    resolved = resolved_root(root)
    if not resolved.is_dir():
        return []
    return sorted(p for p in resolved.glob("*/*/*/rollout-*.jsonl") if is_allowed(p, root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest Codex rollout transcripts into S1")
    parser.add_argument("--db", default=None)
    parser.add_argument("--cas", default=None)
    parser.add_argument("--sessions", default=str(SESSIONS_ROOT),
                        help="sessions tree (the symlink is resolved once)")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="ingest new records from every rollout")
    scan.add_argument("--path", default=None, help="one rollout instead of all")
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
            parser.error(f"{candidate} is not an allow-listed rollout under {root}")
        paths = [candidate]
    else:
        paths = rollout_paths(root)
    if args.limit:
        paths = paths[: args.limit]

    batch = f"codex-tail:{now_iso()}"
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
