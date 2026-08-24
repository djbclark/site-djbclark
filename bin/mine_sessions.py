#!/usr/bin/env python3
"""Mine durable knowledge out of the S1 session corpus.

S1 holds 448k events losslessly and indexes them, so the corpus is
*searchable* — but searching is not mining. Nothing reads those sessions and
produces knowledge, so everything learned mid-task and never written down is
still effectively lost.

Two modes, deliberately separate because they fail differently:

- **candidates** — cheap, local, no model. Finds passages where somebody was
  *corrected*: "actually", "turns out", "the real cause", "does not work".
  High precision, definitely incomplete. Judgeable in an afternoon.
- **distil** — sends those passages to a model and asks for durable facts.

The prompt below is sharp on purpose. Hindsight's extraction over the same
material produced a corpus that was **83% episodic** — session narration
("the agent retired the wrapper…") rather than knowledge you could act on
later. That is the failure mode to design against, so the prompt demands
present-tense facts that stay true after the session ends, and explicitly
rejects narration.

Runs against an idle pool by default (see `bin/route_agent.py`): antigravity
sits near 0% used while claude carries the load, and this is exactly the bulk
work it should absorb.

Usage:
    mine_sessions.py candidates --limit 200 > cands.json
    mine_sessions.py distil --input cands.json --out facts.json
    mine_sessions.py distil --input cands.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hindsight_s1 import EvidenceStore  # noqa: E402
from hindsight_s1_search import SearchIndex  # noqa: E402

MODEL = "gemini-3.1-pro-high"

# Phrases that reliably precede a correction — someone discovering the world
# is not as they assumed. Deliberately narrow: precision beats recall here,
# because the output has to be worth reading.
SIGNALS = (
    "actually it", "turns out", "the real cause", "root cause",
    "does not work", "doesn't work", "that was wrong", "i was wrong",
    "the mistake", "gotcha", "surprisingly", "contrary to",
    "the fix was", "the issue was", "no longer", "deprecated",
)

PROMPT = """You are extracting DURABLE OPERATIONAL KNOWLEDGE from excerpts of \
an engineer's AI-assistant sessions on their own machine.

Return ONLY a JSON array. Each element:
  {"fact": "...", "why_durable": "...", "confidence": "high"|"medium"}

What qualifies — a fact that is still true next month and would change what \
someone does:
  - how a specific tool/service on this machine actually behaves, especially \
where it differs from its documentation
  - a non-obvious constraint, flag, path, or failure mode and its cause
  - a decision and the reason behind it

What does NOT qualify — reject these even though the text is full of them:
  - narration of what happened ("the agent ran X", "then we fixed Y")
  - anything true only during that session (task status, progress, plans)
  - restatements of common knowledge or generic best practice
  - speculation, or anything the excerpt does not actually establish

Write each fact in the present tense, self-contained, naming the concrete \
tool/path/flag. Someone reading it a month from now with no memory of the \
session must be able to act on it. If an excerpt yields nothing durable, \
return [] — that is a correct and expected answer, and far better than \
padding.

EXCERPTS:
"""


def gather(store: EvidenceStore, index: SearchIndex, *, limit: int,
           per_signal: int, window: int, producer: str | None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for signal in SIGNALS:
        if len(out) >= limit:
            break
        try:
            hits = index.search(signal, mode="trigram", limit=per_signal)
        except Exception:
            continue
        for hit in hits:
            if len(out) >= limit:
                break
            eid = hit["event_id"]
            if eid in seen:
                continue
            if producer and hit["producer"] != producer:
                continue
            seen.add(eid)
            try:
                rows = index.neighbours(eid, window=window)
            except KeyError:
                continue
            passage = []
            for row in rows:
                try:
                    raw = store.raw_for(row["event_id"])
                except (FileNotFoundError, KeyError, Exception):
                    continue
                text = _readable(raw)
                if text:
                    passage.append(f"[{row['role']}] {text[:1200]}")
            if len(passage) < 2:          # a lone turn rarely carries the why
                continue
            out.append({
                "event_id": eid, "signal": signal,
                "producer": hit["producer"], "scope": hit["scope"],
                "ts": hit["ts_utc"], "passage": "\n".join(passage)[:6000],
            })
    return out


def _readable(raw: bytes) -> str:
    """Flatten a payload to its text, dropping JSON scaffolding."""
    try:
        obj = json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str) and len(node) > 24:
            parts.append(node)
    walk(obj)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def distil(batch: list[dict[str, Any]], *, model: str, timeout: int) -> list[dict[str, Any]]:
    prompt = PROMPT + "\n\n---\n\n".join(c["passage"] for c in batch)
    try:
        out = subprocess.run(["agy", "-p", prompt, "--model", model],
                             capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return []
    text = out.stdout.strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        facts = json.loads(text[start:end + 1])
    except ValueError:
        return []
    return [f for f in facts if isinstance(f, dict) and f.get("fact")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mine durable knowledge from S1 sessions")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("candidates", help="find correction passages (no model)")
    c.add_argument("--limit", type=int, default=200)
    c.add_argument("--per-signal", type=int, default=25)
    c.add_argument("--window", type=int, default=3)
    c.add_argument("--producer", default=None)
    d = sub.add_parser("distil", help="turn passages into durable facts")
    d.add_argument("--input", required=True)
    d.add_argument("--out", default=None)
    d.add_argument("--model", default=MODEL)
    d.add_argument("--batch", type=int, default=6)
    d.add_argument("--max-batches", type=int, default=None)
    d.add_argument("--timeout", type=int, default=600)
    d.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    store = EvidenceStore()
    if args.command == "candidates":
        index = SearchIndex(store)
        found = gather(store, index, limit=args.limit, per_signal=args.per_signal,
                       window=args.window, producer=args.producer)
        print(json.dumps(found, indent=1))
        print(f"{len(found)} candidate passages", file=sys.stderr)
        return 0

    cands = json.loads(Path(args.input).read_text())
    batches = [cands[i:i + args.batch] for i in range(0, len(cands), args.batch)]
    if args.max_batches:
        batches = batches[: args.max_batches]
    if args.dry_run:
        print(json.dumps({"passages": len(cands), "batches": len(batches),
                          "model": args.model}, indent=2))
        return 0

    facts: list[dict[str, Any]] = []
    for i, batch in enumerate(batches, 1):
        got = distil(batch, model=args.model, timeout=args.timeout)
        for f in got:
            f["sources"] = [c["event_id"][:14] for c in batch]
        facts.extend(got)
        print(f"  batch {i}/{len(batches)}: +{len(got)} facts "
              f"({len(facts)} total)", file=sys.stderr, flush=True)
    payload = json.dumps(facts, indent=1)
    if args.out:
        Path(args.out).write_text(payload)
        print(f"{len(facts)} facts -> {args.out}", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
