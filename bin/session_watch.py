#!/usr/bin/env python3
"""Warn before an idle Claude Code session loses its prompt cache.

Anthropic's cost docs: the whole conversation is re-sent on every request, and
prompt caching means that history is billed as a cheap *read* — but only while
the cache lives. On a subscription the lifetime is **one hour of inactivity**,
and the first message after that reprocesses the entire context as a cache
*write*. For a large session that difference is the single biggest cost event
available, and it happens silently.

So this watches session transcripts (a stat call — no tokens, no model) and
says something while there is still time to act.

**It deliberately does not act.** A script cannot type into an interactive
session, and the mechanism that could — cross-session messaging — is itself
listed by the docs as a cause of usage climbing, because delivering a message
sends the full context as a new turn. That is precisely the expensive event we
are trying to avoid. Waking a session you have actually abandoned pays the
full cost for nothing, and a watcher cannot tell abandonment from a coffee
break. The operator can. So: notify, with the numbers needed to choose.

Suppression matters as much as detection. It alerts once per session per
window, and never while background work is running, because an alert that
fires every ten minutes trains you to ignore it.

Usage:
    session_watch.py check              # for the scheduler
    session_watch.py check --json
    session_watch.py list               # every recent session, no filtering
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECTS = Path.home() / ".claude/projects"
STATE = Path.home() / ".local/state/session-watch/alerted.json"
STATS_DB = Path.home() / ".local/state/agent-stats/stats.sqlite3"

CACHE_LIFETIME_MIN = 60      # subscription; 5 min on usage credits or API keys
WARN_AT_MIN = 50             # leaves ~10 minutes to decide
GIVE_UP_AFTER_MIN = 75       # past the lifetime, the cost is already paid
MIN_CONTEXT_TOKENS = 50_000  # below this the re-read is not worth interrupting for

# Commands whose presence means work is in flight; interrupting to suggest a
# handoff would be worse than the cache miss.
BUSY_PATTERNS = ("hindsight_s1", "mine_sessions", "agent_stats", "graft build",
                 "cow migrate", "yt-dlp")


def busy() -> list[str]:
    try:
        out = subprocess.run(["ps", "axo", "command"], capture_output=True,
                             text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted({p for p in BUSY_PATTERNS if p in out})


def last_usage_context(path: Path) -> int | None:
    """Current context size, from the transcript's final usage block.

    Must come from the *last* message, not a sum: the stats DB aggregates
    usage across a whole session, so summing there reports hundreds of
    millions of tokens for a long conversation and is meaningless as a
    context size. What the next request will carry is the last message's
    cache_read + cache_creation.
    """
    try:
        tail = path.read_bytes()[-400_000:].decode("utf-8", errors="replace")
    except OSError:
        return None
    best = None
    for line in tail.splitlines():
        if '"usage"' not in line:
            continue
        try:
            u = (json.loads(line).get("message") or {}).get("usage") or {}
        except ValueError:
            continue
        n = (u.get("cache_read_input_tokens") or 0) + \
            (u.get("cache_creation_input_tokens") or 0)
        if n:
            best = n
    return best


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1))


def scan() -> list[dict[str, Any]]:
    now = time.time()
    out = []
    for path in PROJECTS.glob("*/*.jsonl"):
        try:
            st = path.stat()
        except OSError:
            continue
        idle_min = (now - st.st_mtime) / 60.0
        if idle_min > 24 * 60:
            continue
        ctx = last_usage_context(path)
        out.append({
            "session_id": path.stem,
            "project": path.parent.name,
            "idle_min": round(idle_min, 1),
            "context_tokens": ctx,
            "size_mb": round(st.st_size / 1e6, 1),
            "expires_in_min": round(CACHE_LIFETIME_MIN - idle_min, 1),
        })
    return sorted(out, key=lambda s: s["idle_min"])


def check() -> tuple[list[dict[str, Any]], list[str]]:
    state = load_state()
    running = busy()
    at_risk = []
    for s in scan():
        if not (WARN_AT_MIN <= s["idle_min"] <= GIVE_UP_AFTER_MIN):
            continue
        if (s["context_tokens"] or 0) < MIN_CONTEXT_TOKENS:
            continue
        # One alert per session per idle window; a session that gets used
        # again resets, so a later idle period alerts afresh.
        prev = state.get(s["session_id"])
        if prev and prev.get("idle_min", 0) <= s["idle_min"] and \
                s["idle_min"] - prev.get("idle_min", 0) < GIVE_UP_AFTER_MIN:
            continue
        at_risk.append(s)
        state[s["session_id"]] = {"alerted_at": datetime.now(timezone.utc)
                                  .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                                  "idle_min": s["idle_min"]}
    if at_risk:
        save_state(state)
    return at_risk, running


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Warn before a session loses its cache")
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check")
    c.add_argument("--json", action="store_true")
    sub.add_parser("list")
    args = ap.parse_args(argv)

    if args.command == "list":
        for s in scan():
            ctx = f"{s['context_tokens']/1000:.0f}k" if s["context_tokens"] else "?"
            print(f"  {s['session_id'][:12]}  idle {s['idle_min']:6.1f}m  "
                  f"ctx {ctx:>7}  {s['project'][:44]}")
        return 0

    at_risk, running = check()
    if args.json:
        print(json.dumps({"at_risk": at_risk, "busy": running}, indent=2))
        return 10 if at_risk and not running else 0

    if running:
        # Say so rather than going silent: silence should mean "nothing at
        # risk", not "suppressed for a reason you cannot see".
        print(f"Session watch: {len(at_risk)} session(s) near cache expiry, but "
              f"background work is running ({', '.join(running)}) — not "
              f"interrupting.")
        return 0
    if not at_risk:
        return 0

    print("⏳ SESSIONS ABOUT TO LOSE THEIR PROMPT CACHE\n")
    for s in at_risk:
        ctx = f"{s['context_tokens']/1000:.0f}k tokens" if s["context_tokens"] else "size unknown"
        print(f"  {s['project'][:52]}")
        print(f"    idle {s['idle_min']:.0f}m — cache expires in "
              f"~{s['expires_in_min']:.0f}m, carrying {ctx}")
    print("\n  Coming back to it? Send any message before the hour to keep the")
    print("  cache warm — a read is far cheaper than the full re-write a miss")
    print("  costs. Done with it? /clear costs nothing and frees the context.")
    print("  Want to keep the thread but not the tokens? /handoff writes the")
    print("  state to disk so a fresh session can pick it up.")
    return 10


if __name__ == "__main__":
    raise SystemExit(main())
