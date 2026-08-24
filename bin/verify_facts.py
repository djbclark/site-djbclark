#!/usr/bin/env python3
"""Check model-mined facts against the evidence they came from, and against
the machine they describe.

`mine_sessions.py distil` asks a model to read session excerpts and emit
durable facts. Two things about its output cannot be taken at face value:

1. **Provenance is batch-level, not fact-level.** Every fact in a batch is
   stamped with all six of the batch's passage ids, so no fact can be checked
   against the passage it actually came from. Grounding every claim to its own
   source text is the standard fix; without it there is nothing to check a
   claim against, which is why fabricated claims survive.
2. **The model's self-reported `confidence` carries almost no signal.** In the
   first run 72 of 78 facts said "high". A field that is nearly constant
   cannot rank anything.

So this does not ask a model how sure it is. It asks two questions that have
checkable answers:

  **Grounding** — do the concrete literals in the fact (paths, flags,
  commands, env vars, quoted code) actually appear in one of its candidate
  source passages? This pins each fact to the single passage that supports it
  and exposes facts whose subject matter appears in none of them.

  **Machine truth** — this corpus is unusual in a way that helps: the facts
  are about *this machine*, not the world. A fact naming `~/.hermes/config.yaml`
  or `just ops-memory-sync` can simply be re-probed. That turns "unverified"
  into "checked on <date>, and here is what was found".

Both stages are deterministic, cost nothing, and need no model or API key.
Stage three (`--entail`) sends only the facts that stage one pinned to a
cheap model to ask whether the passage really establishes the claim; it is
opt-in because it is the only part that spends anything.

A note on the vocabulary, which is deliberate. A passive "unverified" tag is
known to be an unreliable signal — models honour it anywhere between never and
most of the time, so it silently fails open. Every verdict here therefore says
what was *checked*, not how confident someone felt: `ungrounded` means the
sources do not contain the claim's subject, while `no-literals` means the fact
is too abstract for this check. Those are different, and collapsing them into
one word is how a knowledge base launders a guess into a fact.

Usage:
    verify_facts.py check facts.json                 # grounding + machine probe
    verify_facts.py check facts.json --json -o out.json
    verify_facts.py check facts.json --entail        # + model entailment
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hindsight_s1 import EvidenceStore
from hindsight_s1_search import SearchIndex, project

ENTAIL_MODEL = "gemini-3.1-pro-high"

# Must match the window mine_sessions.py used to build the passages.
NEIGHBOUR_WINDOW = 3

# Repos whose `just` recipes a fact might name. Order is irrelevant; a recipe
# found in any of them counts as real.
SEARCH_REPOS = (
    Path.home() / "ops/site-djbclark",
    Path.home() / "ops/stayturgid",
    Path.home() / "ops/site-private",
    Path.home() / "src/aiuse",
    Path.home() / "orca/projects/djbclark-ade",
    Path.home() / "src/orca",
)

JUST_REPOS = (
    Path.home() / "ops/site-djbclark",
    Path.home() / "ops/stayturgid",
    Path.home() / "ops/site-private",
    Path.home() / "src/aiuse",
)

# Literal kinds worth extracting. Each pattern captures something a fact can be
# wrong about in a way that a string search can detect.
PATTERNS: tuple[tuple[str, str], ...] = (
    # Anchored at a real boundary. Without the lookbehind these match from a
    # slash in the *middle* of a repo-relative path, so `src/main/foo.ts` was
    # extracted as `/main/foo.ts` — an absolute path that of course does not
    # exist, and the probe below then called a true fact contradicted.
    ("path", r"(?<![\w/~.-])(?:~|\.{1,2})?/(?:[\w.@-]+/)*[\w.@-]+\.[\w]{1,6}\b"),
    ("path", r"(?<![\w/~.-])~/[\w.@/-]+"),
    ("relpath", r"(?<![\w/~.-])(?:[\w.@-]+/){1,}[\w.@-]+\.[\w]{1,6}\b"),
    ("flag", r"(?<![\w-])--[a-z][a-z0-9-]{2,}"),
    ("envvar", r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+){1,}\b"),
    ("just", r"\bjust\s+([a-z][a-z0-9-]{2,})"),
    ("command", r"`([a-z][\w.-]*)\s"),
)

# Words that match the envvar shape but name concepts, not variables.
NOT_ENVVARS = {"README_MD", "JSON_RPC", "HTTP_GET", "AI_CLI", "MCP_SERVER"}


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# -- stage 1: grounding ----------------------------------------------------

def literals(text: str) -> dict[str, set[str]]:
    """Concrete, checkable strings in a fact, grouped by kind.

    Backticked spans are harvested first and whole: a fact's code spans are
    exactly the part an author had to get right, so they are the highest-value
    thing to check, and the generic patterns below would shred them.
    """
    out: dict[str, set[str]] = {k: set() for k, _ in PATTERNS}
    out["code"] = set()
    for span in re.findall(r"`([^`]{2,80})`", text):
        out["code"].add(span.strip())
    for kind, pattern in PATTERNS:
        for m in re.finditer(pattern, text):
            # rstrip, not strip: trailing sentence punctuation should go, but
            # stripping both ends turns `../site-private/x.toml` into
            # `/site-private/x.toml` — a path that looks absolute, does not
            # exist, and made the probe below call a true fact contradicted.
            value = (m.group(1) if m.groups() else m.group(0)).rstrip(".,;:)")
            if len(value) < 3:
                continue
            if kind == "envvar" and (value in NOT_ENVVARS or value.isdigit()):
                continue
            out[kind].add(value)
    return {k: v for k, v in out.items() if v}


def passage_for(store: EvidenceStore, index: SearchIndex, prefix: str,
                *, window: int = NEIGHBOUR_WINDOW) -> tuple[str, str] | None:
    """Resolve a truncated event id to (full_id, the text the model was shown).

    mine_sessions stores only the first 14 characters of each event id, so the
    lookup has to be a prefix match. 14 hex characters is far too wide a space
    to collide across a corpus of this size, but the query is bounded at two
    rows so an ambiguous prefix is reported rather than silently taking one.

    The reconstruction must include the anchor's neighbours, not just the
    anchor. mine_sessions built each passage from `neighbours(eid, window=3)`
    precisely because a lone turn rarely carries the *why*, so the sentence a
    fact was drawn from is usually in an adjacent turn. Reading only the anchor
    scored almost every fact ungrounded on the first run here — a bug in this
    checker that looked exactly like mass fabrication in the corpus.
    """
    rows = store.db.execute(
        "SELECT event_id FROM event WHERE event_id LIKE ? LIMIT 2", (prefix + "%",)
    ).fetchall()
    if len(rows) != 1:
        return None
    eid = rows[0]["event_id"]
    try:
        turns = index.neighbours(eid, window=window)
    except Exception:          # a missing or unindexed anchor is not fatal
        turns = []
    parts = []
    for row in turns or [{"event_id": eid}]:
        try:
            parts.append(project(store.raw_for(row["event_id"])))
        except Exception:
            continue
    if not parts:
        return None
    return eid, "\n".join(parts)


def ground(fact: dict[str, Any], store: EvidenceStore, index: SearchIndex,
           cache: dict[str, tuple[str, str] | None]) -> dict[str, Any]:
    """Pin a fact to whichever of its candidate passages actually supports it."""
    lits = literals(fact.get("fact", ""))
    flat = {v for values in lits.values() for v in values}
    if not flat:
        return {"grounding": "no-literals", "literals": {}, "best_source": None,
                "matched": [], "match_rate": None}

    best: tuple[float, str, list[str]] | None = None
    for prefix in fact.get("sources", []):
        if prefix not in cache:
            cache[prefix] = passage_for(store, index, prefix)
        resolved = cache[prefix]
        if not resolved:
            continue
        eid, text = resolved
        low = text.lower()
        hit = sorted(v for v in flat if v.lower() in low)
        rate = len(hit) / len(flat)
        if best is None or rate > best[0]:
            best = (rate, eid, hit)

    if best is None:
        return {"grounding": "sources-unreadable", "literals": _plain(lits),
                "best_source": None, "matched": [], "match_rate": None}

    rate, eid, hit = best
    # One literal in common is what any two passages about the same tool will
    # share; it does not show the passage carries this claim. Requiring a third
    # of them, or two absolute, is the line between "mentions the subject" and
    # "is about the subject".
    grounding = "grounded" if (rate >= 0.34 or len(hit) >= 2) else "ungrounded"
    return {"grounding": grounding, "literals": _plain(lits), "best_source": eid,
            "matched": hit, "match_rate": round(rate, 2)}


def _plain(lits: dict[str, set[str]]) -> dict[str, list[str]]:
    return {k: sorted(v) for k, v in lits.items()}


# -- stage 2: machine probe ------------------------------------------------

def just_recipes() -> set[str]:
    """Every recipe name across the repos a fact might refer to."""
    found: set[str] = set()
    if not shutil.which("just"):
        return found
    for repo in JUST_REPOS:
        if not (repo / "justfile").exists() and not (repo / "Justfile").exists():
            continue
        try:
            out = subprocess.run(["just", "--list"], cwd=repo, capture_output=True,
                                 text=True, timeout=60, check=False).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for line in out.splitlines()[1:]:
            name = line.strip().split(" ")[0]
            if name and not name.startswith("#"):
                found.add(name)
    return found


def probe(fact: dict[str, Any], verdict: dict[str, Any],
          recipes: set[str]) -> dict[str, Any]:
    """Re-check a fact's literals against the machine as it is today.

    Only existence is ever reported. Several of these paths are credential
    surfaces (`~/.hermes/.env` among them); whether a file is there is a fact
    worth keeping, and its contents are not this script's business.
    """
    lits = verdict.get("literals") or {}
    checks: list[dict[str, Any]] = []

    for raw in lits.get("path", []):
        if not raw.startswith(("~", "/")):
            continue
        checks.append({"kind": "path", "value": raw,
                       "present": Path(os.path.expanduser(raw)).exists()})

    # A repo-relative path has no meaning without knowing the repo, so try each
    # one a fact could plausibly mean and accept a hit anywhere.
    for raw in lits.get("relpath", []):
        checks.append({"kind": "repo-path", "value": raw,
                       "present": any((r / raw).exists() for r in SEARCH_REPOS)})
    for raw in lits.get("path", []):
        if raw.startswith("."):       # `../sibling/x` — resolve per candidate repo
            checks.append({"kind": "repo-path", "value": raw,
                           "present": any((r / raw).exists() for r in SEARCH_REPOS)})

    for name in lits.get("just", []):
        checks.append({"kind": "just-recipe", "value": name,
                       "present": name in recipes})

    for name in lits.get("command", []):
        checks.append({"kind": "command", "value": name,
                       "present": shutil.which(name) is not None})

    # The verdict rests only on checks that mean one thing. A command miss is
    # ambiguous (subcommand vs binary); so is a repo-relative miss, because
    # SEARCH_REPOS is a guess at which repo a fact meant and cannot be
    # complete. Both are recorded and shown, neither condemns a fact alone.
    decisive = [c for c in checks if c["kind"] not in ("command", "repo-path")]
    if not decisive:
        return {"machine": "not-probeable", "checks": checks}
    missing = [c for c in decisive if not c["present"]]
    if not missing:
        return {"machine": "confirmed", "checks": checks}
    if len(missing) == len(decisive):
        return {"machine": "contradicted", "checks": checks}
    return {"machine": "partial", "checks": checks}


# -- stage 3: entailment (opt-in, costs tokens) ----------------------------

ENTAIL_PROMPT = """Does the PASSAGE below actually establish the CLAIM?

Answer with ONLY a JSON object: {"entailed": true|false, "why": "<one short \
sentence>"}

Say true only if the passage contains evidence for the claim. Say false if the \
passage is merely about the same topic, if the claim generalises beyond what \
the passage shows, or if the claim is not discussed at all. Being unable to \
confirm is a false, not a true.

CLAIM:
%s

PASSAGE:
%s
"""


def entail(claim: str, passage: str, *, model: str, timeout: int) -> dict[str, Any]:
    prompt = ENTAIL_PROMPT % (claim, passage[:6000])
    try:
        out = subprocess.run(["agy", "-p", prompt, "--model", model],
                             capture_output=True, text=True, timeout=timeout,
                             check=False)
    except (OSError, subprocess.SubprocessError):
        return {"entailed": None, "why": "model call failed"}
    text = out.stdout
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {"entailed": None, "why": "unparseable model reply"}
    try:
        obj = json.loads(text[start:end + 1])
    except ValueError:
        return {"entailed": None, "why": "unparseable model reply"}
    return {"entailed": obj.get("entailed"), "why": str(obj.get("why", ""))[:200]}


# -- driver ----------------------------------------------------------------

def run(facts: list[dict[str, Any]], *, do_entail: bool, model: str,
        timeout: int) -> list[dict[str, Any]]:
    store = EvidenceStore()
    index = SearchIndex(store)
    cache: dict[str, tuple[str, str] | None] = {}
    recipes = just_recipes()
    results = []
    for i, fact in enumerate(facts, 1):
        v = ground(fact, store, index, cache)
        v.update(probe(fact, v, recipes))
        v["fact"] = fact.get("fact", "")
        v["claimed_confidence"] = fact.get("confidence")
        v["checked_utc"] = utc_today()
        if do_entail and v["grounding"] == "grounded" and v["best_source"]:
            passage = ""
            for prefix in fact.get("sources", []):
                got = cache.get(prefix)
                if got and got[0] == v["best_source"]:
                    passage = got[1]
                    break
            if passage:
                v["entailment"] = entail(v["fact"], passage, model=model,
                                         timeout=timeout)
            print(f"  entailed {i}/{len(facts)}", file=sys.stderr, flush=True)
        results.append(v)
    store.close()
    return results


def report(results: list[dict[str, Any]]) -> None:
    from collections import Counter
    g = Counter(r["grounding"] for r in results)
    m = Counter(r["machine"] for r in results)
    print(f"\n{len(results)} facts checked on {utc_today()}\n")
    print("  grounding — do the fact's literals appear in its own sources?")
    for k in ("grounded", "ungrounded", "no-literals", "sources-unreadable"):
        if g[k]:
            print(f"    {g[k]:4}  {k}")
    print("\n  machine — do the things it names still exist here?")
    for k in ("confirmed", "partial", "contradicted", "not-probeable"):
        if m[k]:
            print(f"    {m[k]:4}  {k}")

    # The cross-tab is the number that matters: neither axis alone says a fact
    # is worth trusting. Grounded-and-confirmed means the evidence supports it
    # *and* the machine still agrees.
    both = sum(1 for r in results
               if r["grounding"] == "grounded" and r["machine"] == "confirmed")
    unknowable = sum(1 for r in results
                     if r["grounding"] == "no-literals"
                     and r["machine"] == "not-probeable")
    print(f"\n  {both} fact(s) grounded in their evidence AND confirmed against "
          f"this machine.")
    print(f"  {unknowable} fact(s) too abstract for either check — not wrong, "
          f"just unfalsifiable\n  by this method; they need a human or a "
          f"different kind of review.")

    suspect = [r for r in results
               if r["grounding"] == "ungrounded" or r["machine"] == "contradicted"]
    if suspect:
        print(f"\n  {len(suspect)} fact(s) need a human look:\n")
        for r in suspect[:20]:
            why = []
            if r["grounding"] == "ungrounded":
                why.append(f"no source contains its literals "
                           f"(best match {r['match_rate']})")
            if r["machine"] == "contradicted":
                gone = ", ".join(c["value"] for c in r["checks"] if not c["present"])
                why.append(f"missing from this machine: {gone}")
            print(f"    - {r['fact'][:110]}")
            print(f"      {'; '.join(why)}")
    ent = [r for r in results if r.get("entailment", {}).get("entailed") is False]
    if ent:
        print(f"\n  {len(ent)} grounded fact(s) the model says its passage "
              f"does not establish:\n")
        for r in ent[:20]:
            print(f"    - {r['fact'][:110]}")
            print(f"      {r['entailment']['why']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check")
    c.add_argument("facts", help="JSON array from `mine_sessions.py distil`")
    c.add_argument("-o", "--out", default=None, help="write full results here")
    c.add_argument("--json", action="store_true", help="print JSON, not a report")
    c.add_argument("--entail", action="store_true",
                   help="also ask a model whether each passage establishes its "
                        "claim (spends tokens)")
    c.add_argument("--model", default=ENTAIL_MODEL)
    c.add_argument("--timeout", type=int, default=300)
    c.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    facts = json.loads(Path(args.facts).read_text())
    if args.limit:
        facts = facts[: args.limit]
    results = run(facts, do_entail=args.entail, model=args.model,
                  timeout=args.timeout)

    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1))
        print(f"{len(results)} results -> {args.out}", file=sys.stderr)
    if args.json:
        print(json.dumps(results, indent=1))
    else:
        report(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
