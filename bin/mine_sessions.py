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
- **distil** — sends those passages to a model and asks for durable facts,
  each attributed to the one excerpt it came from. That attribution is the
  model's claim, so `attribute()` checks it against the passage's text rather
  than recording it as given; an uncheckable citation is worth little more
  than none. Before 2026-08-24 every fact was stamped with all six of its
  batch's passage ids, which is not provenance and left the output
  unverifiable — `bin/verify_facts.py` and `docs/fact-verification.md` cover
  the check and what the first run of it found.

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

from hindsight_s1 import EvidenceStore
from hindsight_s1_search import SearchIndex
from verify_facts import literals

MODEL = "gemini-3.1-pro-high"

# Share of a fact's literals that must appear in a passage for it to count as
# that fact's source. Matches the grounding threshold in verify_facts.py: one
# literal in common is what any two passages about the same tool will share.
LITERAL_SUPPORT = 0.34

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
  {"fact": "...", "why_durable": "...", "confidence": "high"|"medium", \
"source": <excerpt number>}

"source" is the number of the single EXCERPT the fact came from. Every fact \
must come from exactly one excerpt; if you find yourself combining two, they \
are two facts or neither. Getting this number right matters as much as the \
fact itself — a fact whose source cannot be checked cannot be trusted later.

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


def attribute(fact: dict[str, Any], batch: list[dict[str, Any]]) -> dict[str, Any]:
    """Pin a fact to the one passage it came from, and check that claim.

    The model states a source excerpt number, which is the only way to get
    fact-level provenance without one model call per passage. But a stated
    citation is itself a claim, and an uncorroborated one is how a batch id
    ends up masquerading as evidence. So the number is checked, not trusted:
    the fact's concrete literals (paths, flags, recipes, code spans) have to
    actually appear in the passage it names.

    When the model's pick has no literal support but another passage in the
    batch does, the best-corroborated passage wins and the disagreement is
    recorded. When nothing corroborates, `source` is left null rather than
    guessed — an honest gap beats a plausible wrong answer, because everything
    downstream treats a populated `source` as checkable.

    A fact with no literals at all cannot be corroborated either way. Its
    stated source is kept, but labelled `model-stated-unverifiable` rather than
    `model-stated`, because the two were arrived at differently and a reader
    who cannot tell them apart is being told a check happened that did not.
    """
    lits = literals(fact.get("fact", ""))
    flat = {v for values in lits.values() for v in values}

    def supports(item: dict[str, Any]) -> float:
        if not flat:
            return 0.0
        low = item["passage"].lower()
        return sum(1 for v in flat if v.lower() in low) / len(flat)

    stated = fact.get("source")
    picked = None
    if isinstance(stated, int) and 1 <= stated <= len(batch):
        picked = batch[stated - 1]

    if picked is not None and not flat:
        method = "model-stated-unverifiable"
    elif picked is not None and supports(picked) >= LITERAL_SUPPORT:
        method = "model-stated"
    else:
        scored = sorted(batch, key=supports, reverse=True)
        best = scored[0] if scored else None
        if best is not None and supports(best) >= LITERAL_SUPPORT:
            method = "literal-corrected" if picked is not None else "literal-matched"
            picked = best
        else:
            method = "unattributed"
            picked = None

    return {
        "fact": fact.get("fact", ""),
        "why_durable": fact.get("why_durable", ""),
        "confidence": fact.get("confidence"),
        "source": picked["event_id"] if picked else None,
        "source_method": method,
        "source_stated": stated if isinstance(stated, int) else None,
        # Kept for audit only. This is NOT provenance: it is every passage the
        # model saw in one call, which is exactly the batch-level "sources"
        # list that made the first run's facts uncheckable.
        "batch": [c["event_id"] for c in batch],
    }


def distil(batch: list[dict[str, Any]], *, model: str, timeout: int) -> list[dict[str, Any]]:
    numbered = "\n\n---\n\n".join(
        f"[EXCERPT {i}]\n{c['passage']}" for i, c in enumerate(batch, 1)
    )
    try:
        out = subprocess.run(["agy", "-p", PROMPT + numbered, "--model", model],
                             capture_output=True, text=True, timeout=timeout,
                             check=False)
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
    return [attribute(f, batch) for f in facts
            if isinstance(f, dict) and f.get("fact")]


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
        facts.extend(got)
        unattributed = sum(1 for f in got if f["source_method"] == "unattributed")
        note = f", {unattributed} unattributed" if unattributed else ""
        print(f"  batch {i}/{len(batches)}: +{len(got)} facts{note} "
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
