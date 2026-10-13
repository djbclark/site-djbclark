#!/usr/bin/env python3
"""acp-run capture adapter for S1 (Phase B).

`acp-run` (`site-private/bin/acp-run`) logs every headless ACP run it launches
as one JSONL file under `~/.local/state/acp-run/<ts>-<agent>-<pid>.jsonl`, a
uniform `{t, kind, data}` stream (`initialize`, `new_session`, `update`,
`set_config`, `prompt_response`, `turn`, `result`) for whichever agent it
drove — one adapter covers a dozen agents' dispatched runs.

Two rules carry the weight:

- **Agent/model come from the records, never the file name.** The name
  embeds an agent guess; the authoritative identity is
  `initialize.data.agentInfo` (and `result.data.agent`), and the model is the
  `id: "model"` config option's `currentValue` from `new_session`/`set_config`.
- **Path allow-list.** Only `*.jsonl` directly under the log directory is
  opened — the `.stderr` siblings and anything else that lands there stay out.

Tailing is the shared append-only discipline (`s1_jsonl`): resume from the
committed byte offset, never ingest a line without its terminating newline,
verify the consumed prefix's fingerprint before resuming.

Usage:
    s1_acprun.py scan            # all run logs, resuming each file
    s1_acprun.py scan --dry-run
    s1_acprun.py scan --path <run.jsonl>
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

PRODUCER = "acp-run"
ADAPTER_VERSION = "acp-run-tail-1"
LOG_DIR = Path.home() / ".local" / "state" / "acp-run"

# sessionUpdate subtype -> (role, origin). Unlisted kinds and subtypes are
# retained as system events: a lossless store keeps records it does not
# recognise rather than dropping them.
UPDATE_MAP: dict[str, tuple[str, str]] = {
    "user_message_chunk": ("user", "human"),
    "agent_message_chunk": ("assistant", "model"),
    "agent_thought_chunk": ("assistant", "model"),
    "tool_call": ("tool", "tool"),
    "tool_call_update": ("tool", "tool"),
}
KIND_MAP: dict[str, tuple[str, str]] = {
    "prompt_response": ("assistant", "model"),
}


def resolved_root(root: Path) -> Path:
    return root.expanduser().resolve()


def is_allowed(path: Path, root: Path) -> bool:
    """Only `*.jsonl` files directly inside the acp-run log directory."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if resolved.suffix != ".jsonl":
        return False
    return resolved.parent == resolved_root(root)


def to_utc(ts: Any, fallback_path: Path) -> tuple[str, str]:
    """Records carry epoch seconds in `t`; fall back honestly if absent."""
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


def model_of(config_options: Any) -> str | None:
    """The current model from a configOptions list, if it has a model selector."""
    if not isinstance(config_options, list):
        return None
    for option in config_options:
        if not isinstance(option, dict):
            continue
        if option.get("id") == "model" or option.get("category") == "model":
            value = option.get("currentValue")
            return str(value) if value else None
    return None


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
    agent: str | None = None
    agent_version: str | None = None
    model: str | None = None
    session_id: str | None = None

    for begin, end, raw in iter_records(path, start):
        seen += 1
        locator = f"{begin}:{end}#{seen}"
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            record = {}
        if not isinstance(record, dict):
            record = {}

        kind = str(record.get("kind") or "unknown")
        data = record.get("data")
        if not isinstance(data, dict):
            data = {}

        # Identity from record contents, refreshed as the run announces it.
        if kind == "initialize":
            info = data.get("agentInfo")
            if isinstance(info, dict):
                if info.get("name"):
                    agent = str(info["name"])
                if info.get("version"):
                    agent_version = str(info["version"])
        elif kind == "new_session":
            if data.get("sessionId"):
                session_id = str(data["sessionId"])
            model = model_of(data.get("configOptions")) or model
        elif kind == "set_config":
            model = model_of(data.get("configOptions")) or model
        elif kind == "result" and data.get("agent") and not agent:
            agent = str(data["agent"])

        if kind == "update":
            subtype = str(data.get("sessionUpdate") or "")
            role, origin = UPDATE_MAP.get(subtype, ("system", "system"))
            event_type = f"update.{subtype or 'unknown'}"
        else:
            role, origin = KIND_MAP.get(kind, ("system", "system"))
            event_type = kind
        tool_name = str(data["title"]) if data.get("title") else None
        tool_call_id = str(data["toolCallId"]) if data.get("toolCallId") else None
        ts_utc, ts_source = to_utc(record.get("t"), path)

        scope = (agent or PRODUCER).lower()
        if model:
            scope = f"{scope}/{model}"

        if dry_run:
            last_locator = locator
            continue

        try:
            event_id, was_created = store.put_event(
                producer=PRODUCER,
                producer_version=agent_version,
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


def log_paths(root: Path) -> list[Path]:
    """Every allow-listed run log in the directory."""
    resolved = resolved_root(root)
    if not resolved.is_dir():
        return []
    return sorted(p for p in resolved.glob("*.jsonl") if is_allowed(p, root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest acp-run headless-run logs into S1")
    parser.add_argument("--db", default=None)
    parser.add_argument("--cas", default=None)
    parser.add_argument("--log-dir", default=str(LOG_DIR))
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="ingest new records from every run log")
    scan.add_argument("--path", default=None, help="one log instead of all")
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

    root = Path(args.log_dir).expanduser()
    if args.path:
        candidate = Path(args.path).expanduser()
        if not is_allowed(candidate, root):
            parser.error(f"{candidate} is not an allow-listed run log under {root}")
        paths = [candidate]
    else:
        paths = log_paths(root)
    if args.limit:
        paths = paths[: args.limit]

    batch = f"acp-run-tail:{now_iso()}"
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
