#!/usr/bin/env python3
"""Warn when a Hermes session's context is big enough to be expensive.

Why (2026-09-29 credit attribution): one never-ended Telegram session re-sent a
~100k+ token context on every turn for 975 API calls (105M cache-read tokens)
and was the single biggest spender of the xAI extra credits. Compaction fires
automatically (config: compression.threshold_tokens), but nobody was told a
session was getting heavy, or that /new is often better than /compress.

Reads ~/.hermes/state.db read-only (no tokens, no model). Context size is
estimated as chars/4 over the session's *active, non-compacted* messages plus a
fixed allowance for the system prompt and tool schemas, because
messages.token_count is not populated.

Silent unless a session crosses a level it has not already been warned about;
re-arms when the session shrinks (i.e. after a /compress). Output goes to
stdout for the Hermes no-agent cron to deliver.

Usage:
    hermes_context_watch.py check        # for the scheduler (silent when quiet)
    hermes_context_watch.py list         # every recent session with its estimate
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

DB = Path.home() / ".hermes/state.db"
STATE = Path.home() / ".local/state/hermes-context-watch/alerted.json"

OVERHEAD_TOKENS = 25_000      # system prompt + tool schemas + memory injection
WARN_TOKENS = 80_000          # level 1: suggest /compress
HEAVY_TOKENS = 150_000        # level 2: /compress now, or /new
STALE_TOKENS = 40_000         # level 3 floor: idle + this big = start fresh
ACTIVE_WINDOW_H = 6           # levels 1-2 only for sessions touched this recently
STALE_AFTER_H = 12            # level 3: idle this long
LOOKBACK_H = 72


def scan() -> list[dict[str, Any]]:
    if not DB.exists():
        return []
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    try:
        rows = con.execute(
            """
            select s.id, s.source, coalesce(s.title, ''), s.last_activity_at,
                   cast(sum(length(coalesce(m.content, ''))
                          + length(coalesce(m.tool_calls, ''))
                          + length(coalesce(m.reasoning, ''))) / 4 as int)
            from sessions s
            join messages m on m.session_id = s.id and m.active = 1
                           and coalesce(m.compacted, 0) = 0
            where s.last_activity_at > strftime('%s', 'now', ?)
              and s.source != 'cron'
            group by s.id
            """,
            (f"-{LOOKBACK_H} hours",),
        ).fetchall()
    finally:
        con.close()
    now = time.time()
    out: list[dict[str, Any]] = []
    for sid, source, title, last, est in rows:
        out.append({
            "id": sid, "source": source, "title": title or "(untitled)",
            "idle_h": (now - (last or now)) / 3600.0,
            "tokens": (est or 0) + OVERHEAD_TOKENS,
        })
    return sorted(out, key=lambda r: -r["tokens"])


def level(r: dict[str, Any]) -> int:
    if r["idle_h"] <= ACTIVE_WINDOW_H:
        if r["tokens"] >= HEAVY_TOKENS:
            return 2
        if r["tokens"] >= WARN_TOKENS:
            return 1
    if r["idle_h"] >= STALE_AFTER_H and r["tokens"] >= STALE_TOKENS:
        return 3
    return 0


def load_state() -> dict[str, int]:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, int]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state))


def message(r: dict[str, Any], lvl: int) -> str:
    k = f"{int(r['tokens']) // 1000}k"
    head = f"{r['title'][:60]} ({r['source']}, {r['id'][-6:]})"
    if lvl == 1:
        return (f"⚠ Context ~{k} tokens: {head}\n"
                f"  Every turn re-sends all of it. Send /compress to shrink it now.")
    if lvl == 2:
        return (f"⚠⚠ Context is heavy, ~{k} tokens: {head}\n"
                f"  /compress now — or /new if the topic has changed (Basic Memory keeps "
                f"long-term memory across sessions, so nothing important is lost).")
    return (f"💤 Idle {r['idle_h']:.0f}h at ~{k} tokens: {head}\n"
            f"  Resuming pays to re-read all of it. Prefer /new (memory carries over), "
            f"or /compress before your next message.")


def check() -> list[str]:
    state = load_state()
    msgs: list[str] = []
    seen = set()
    for r in scan():
        seen.add(r["id"])
        lvl = level(r)
        prior = state.get(r["id"], 0)
        if lvl == 0:
            state.pop(r["id"], None)        # shrank or went quiet: re-arm
        elif lvl > prior:
            msgs.append(message(r, lvl))
            state[r["id"]] = lvl
    for sid in [s for s in state if s not in seen]:
        state.pop(sid)                      # aged out of the lookback window
    save_state(state)
    return msgs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Warn about heavy Hermes session contexts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        for r in scan():
            print(f"{r['tokens']:>8} tok  level={level(r)}  idle={r['idle_h']:5.1f}h  "
                  f"{r['source']:<9} {r['id'][-6:]}  {r['title'][:50]}")
        return 0
    out = check()
    if out:
        print("\n\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
