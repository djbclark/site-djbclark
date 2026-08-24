#!/usr/bin/env python3
"""Claude Code transcript adapter for S1 (Phase B).

Claude Code writes one JSONL record per event under
`~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`, and garbage-collects
those files over time. That GC is not hypothetical: it already cost us the
repo attribution for 15 Hindsight documents dated 2026-08-15..19, which is
recorded as this store's first `ingest_gap`. Copying the bytes into S1 before
they vanish is the whole point of this adapter.

Two properties matter more than throughput:

- **Append-only tailing.** Each file is treated as an immutable prefix that
  grows. We resume from the last committed byte offset, and we never ingest a
  line that has no terminating newline yet — a partially-flushed record would
  hash differently once completed, and S1 would then see it as a mutated
  source.
- **Attribution captured at ingest.** Each record carries `cwd`, so the repo
  it belongs to is knowable *now*, while the transcript still exists. That is
  stored in `event.scope`, so attribution survives the transcript itself.

Usage:
    hindsight_s1_claude.py scan            # all projects, resuming each file
    hindsight_s1_claude.py scan --dry-run  # report what would be ingested
    hindsight_s1_claude.py scan --path <file.jsonl>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hindsight_s1 import EvidenceStore, SourceMutated, now_iso  # noqa: E402

PRODUCER = "claude-code"
ADAPTER_VERSION = "claude-tail-1"
FINGERPRINT_BYTES = 4096

# Claude record type -> (role, origin). Anything unlisted is retained too, as
# system/derived: losing a record because we did not recognise its type would
# defeat the purpose of a lossless store.
TYPE_MAP: dict[str, tuple[str, str]] = {
    "user": ("user", "human"),
    "assistant": ("assistant", "model"),
    "system": ("system", "system"),
    "attachment": ("user", "human"),
    "last-prompt": ("user", "human"),
    "file-history-snapshot": ("system", "derived"),
    "file-history-delta": ("system", "derived"),
    "mode": ("system", "system"),
    "permission-mode": ("system", "system"),
    "ai-title": ("system", "model"),
    "queue-operation": ("system", "system"),
    "pr-link": ("system", "system"),
}


def fingerprint_prefix(path: Path, upto: int) -> str:
    """Hash of the prefix we have already consumed, capped for cost.

    The invariant this protects is precise: *the bytes we already ingested must
    not have changed*. Hashing a fixed-size window instead would be wrong on a
    short file, where a normal append rewrites the window and every append
    would look like a truncation.

    `upto` is the committed byte offset, so verification recomputes over
    exactly the same span that produced the stored value. Once the file is
    longer than the cap the value stops moving and stays a cheap constant.
    """
    window = min(upto, FINGERPRINT_BYTES)
    if window <= 0:
        return ""
    with path.open("rb") as handle:
        return hashlib.sha256(handle.read(window)).hexdigest()


def repo_scope(cwd: str | None) -> str:
    """The project a record belongs to, resolved the way git would see it.

    Mirrors how bank ids are derived elsewhere on this machine: the git
    toplevel's basename when cwd is inside a repo, otherwise the directory's
    own name. Recorded now because the transcript that proves it is transient.
    """
    if not cwd:
        return "unknown"
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).name
    except (OSError, subprocess.SubprocessError):
        pass
    return Path(cwd).name or "unknown"


def parse_locator(locator: str | None) -> int:
    """Byte offset just past the last committed record, or 0."""
    if not locator:
        return 0
    try:
        span = locator.split("#", 1)[0]
        return int(span.split(":", 1)[1])
    except (IndexError, ValueError):
        return 0


def tool_fields(record: dict[str, Any]) -> tuple[str | None, str | None]:
    """Pull a tool name / call id out of a message body when present."""
    message = record.get("message")
    if not isinstance(message, dict):
        return None, None
    content = message.get("content")
    if not isinstance(content, list):
        return None, None
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            return block.get("name"), block.get("id")
        if block.get("type") == "tool_result":
            return None, block.get("tool_use_id")
    return None, None


def iter_records(path: Path, start: int) -> Iterator[tuple[int, int, bytes]]:
    """Yield (start_offset, end_offset, raw_line) for complete records only.

    A line without a trailing newline is still being written; we stop there and
    pick it up on the next pass rather than ingesting a half record.
    """
    with path.open("rb") as handle:
        handle.seek(start)
        offset = start
        while True:
            line = handle.readline()
            if not line:
                return
            if not line.endswith(b"\n"):
                return  # incomplete tail; do not commit
            end = offset + len(line)
            stripped = line.strip()
            if stripped:
                yield offset, end, line
            offset = end


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
        role, origin = TYPE_MAP.get(record_type, ("unknown", "system"))
        timestamp = record.get("timestamp")
        if isinstance(timestamp, str) and timestamp:
            ts_utc, ts_source = timestamp, "producer"
        else:
            ts_utc = datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            ts_source = "filesystem"
        tool_name, tool_call_id = tool_fields(record)
        session_id = record.get("sessionId") or record.get("session_id")

        if dry_run:
            last_locator = locator
            continue

        try:
            event_id, was_created = store.put_event(
                producer=PRODUCER,
                producer_version=str(record.get("version") or "") or None,
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
                producer_session_id=str(session_id) if session_id else None,
                source_seq=seen,
                scope=repo_scope(record.get("cwd")),
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


def transcript_paths(root: Path) -> list[Path]:
    return sorted(root.glob("*/*.jsonl"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest Claude Code transcripts into S1")
    parser.add_argument("--db", default=None)
    parser.add_argument("--cas", default=None)
    parser.add_argument("--projects", default=str(Path.home() / ".claude" / "projects"))
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="ingest new records from every transcript")
    scan.add_argument("--path", default=None, help="one transcript instead of all")
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

    paths = [Path(args.path)] if args.path else transcript_paths(Path(args.projects).expanduser())
    if args.limit:
        paths = paths[: args.limit]

    batch = f"claude-tail:{now_iso()}"
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
