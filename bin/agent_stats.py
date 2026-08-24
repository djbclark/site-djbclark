#!/usr/bin/env python3
"""Collect operating stats for the agent fleet into SQLite, and flag drift.

Everything here is measured, not asked for: quota comes from the snapshot
`aiuse` already writes, token usage is computed from Claude Code's own session
transcripts (which carry per-message `usage` including cache reads vs cache
writes), and config values are read from the files that actually govern
behaviour. No slash command is required, so this runs unattended.

Two jobs in one place because they share a schema:

1. **Track** — quota headroom, per-session token usage and cache hit rate,
   sizes of the instruction files that load into every session, and the
   config values we have agreed on.
2. **Notice drift** — `EXPECTED` below records what those config values are
   *supposed* to be. Anything that changes underneath us is reported rather
   than silently accepted. This exists because on 2026-08-23 a watchdog
   silently rewrote a bank mission and nobody noticed for hours.

Cache hit rate is the metric worth watching. Per Anthropic's cost docs the
whole conversation is re-sent every request; whether that history is billed as
a cache read or a cache write is the difference that dominates everything
else.

Usage:
    agent_stats.py collect            # one sample, for the scheduler
    agent_stats.py report --hours 24  # what the morning summary prints
    agent_stats.py drift              # config drift only; exit 10 if drifted
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

DB = Path(os.environ.get("AGENT_STATS_DB") or
          (Path.home() / ".local/state/agent-stats/stats.sqlite3"))
AIUSE_SNAPSHOT = Path.home() / ".cache/aiuse/snapshots/latest.json"
PROJECTS = Path.home() / ".claude/projects"

# Instruction files load into context on every session, so their length is a
# recurring tax. Anthropic's cost docs advise keeping each under 200 lines and
# moving specialised material into skills, which load on demand.
WATCHED_FILES: list[tuple[str, int]] = [
    (str(Path.home() / "orca/projects/djbclark-ade/AGENTS.md"), 200),
    (str(Path.home() / "ops/site-private/home-agents.md"), 200),
    (str(Path.home() / "ops/site-djbclark/AGENTS.md"), 200),
    (str(Path.home() / "ops/stayturgid/AGENTS.md"), 200),
    (str(Path.home() / "ops/site-private/AGENTS.md"), 200),
    (str(Path.home() / ".hermes/memories/MEMORY.md"), 400),
    (str(Path.home() / ".hermes/memories/USER.md"), 200),
]

# What we have agreed these should be. A mismatch is reported, never fixed
# automatically — silent auto-correction is the failure mode this guards.
EXPECTED: dict[str, str] = {
    "claude.env.ENABLE_PROMPT_CACHING_1H": "1",
    "hermes.hindsight.auto_recall": "True",
    "hermes.hindsight.auto_retain": "True",
    "hermes.hindsight.bank_id": "hermes-shared",
    "hindsight.coding_agent.dynamicBankId": "True",
    "hindsight.coding_agent.bankIdTemplate": "coding-agent::{gitProject}",
}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=30000")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS sample (
      id INTEGER PRIMARY KEY, collected_at TEXT NOT NULL, host TEXT);
    CREATE TABLE IF NOT EXISTS quota (
      sample_id INTEGER REFERENCES sample(id) ON DELETE CASCADE,
      provider TEXT NOT NULL, window_label TEXT NOT NULL,
      remaining_pct REAL, billing_kind TEXT);
    CREATE TABLE IF NOT EXISTS session_usage (
      session_id TEXT NOT NULL, day TEXT NOT NULL, cwd TEXT,
      messages INTEGER, input_tokens INTEGER, cache_write INTEGER,
      cache_read INTEGER, output_tokens INTEGER, thinking_tokens INTEGER,
      last_seen TEXT, PRIMARY KEY (session_id));
    CREATE TABLE IF NOT EXISTS file_size (
      sample_id INTEGER REFERENCES sample(id) ON DELETE CASCADE,
      path TEXT NOT NULL, lines INTEGER, bytes INTEGER,
      limit_lines INTEGER, over INTEGER);
    CREATE TABLE IF NOT EXISTS config_value (
      sample_id INTEGER REFERENCES sample(id) ON DELETE CASCADE,
      key TEXT NOT NULL, value TEXT, expected TEXT, drifted INTEGER);
    -- Scheduled agent jobs cost tokens on a timer, so a job quietly pointed at
    -- an expensive or protected pool is a recurring leak. Inventoried each
    -- sample so a change of mode/model shows up as history, not a surprise.
    CREATE TABLE IF NOT EXISTS cron_job (
      sample_id INTEGER REFERENCES sample(id) ON DELETE CASCADE,
      name TEXT NOT NULL, mode TEXT, model TEXT, schedule TEXT, costs_tokens INTEGER);
    -- Deliberate changes we are measuring. Best guess first, then refine from
    -- what actually happened — an experiment nobody records is just a change.
    CREATE TABLE IF NOT EXISTS experiment (
      id INTEGER PRIMARY KEY, name TEXT NOT NULL, hypothesis TEXT,
      variable TEXT, from_value TEXT, to_value TEXT,
      started_at TEXT NOT NULL, ended_at TEXT, outcome TEXT, verdict TEXT);
    -- /insights writes a friction report; tracking its existence over time
    -- measures whether we are getting better, not merely cheaper.
    CREATE TABLE IF NOT EXISTS insights_report (
      path TEXT PRIMARY KEY, generated_at TEXT, bytes INTEGER, seen_at TEXT);
    CREATE INDEX IF NOT EXISTS sample_time ON sample(collected_at);
    CREATE INDEX IF NOT EXISTS usage_day ON session_usage(day);
    """)
    db.commit()
    return db


# -- collectors ----------------------------------------------------------

def read_quota() -> list[tuple[str, str, float | None, str | None]]:
    """Quota from the snapshot aiuse already maintains. Never probes."""
    try:
        data = json.loads(AIUSE_SNAPSHOT.read_text())
    except (OSError, ValueError):
        return []
    rows = []
    for acct in (data.get("snapshot", data).get("accounts") or []):
        name = acct.get("provider")
        if not name or acct.get("error"):
            continue
        for w in acct.get("windows") or []:
            rows.append((name, w.get("label") or "?", w.get("remaining_percent"),
                         acct.get("billing_kind")))
    return rows


def read_sessions(since_days: int = 7) -> list[dict[str, Any]]:
    """Token usage per session, straight from Claude Code's transcripts.

    Reads the `usage` block each assistant message carries, so this is the
    same data `/usage` reports — available without an interactive command.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    out = []
    for path in PROJECTS.glob("*/*.jsonl"):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff:
                continue
        except OSError:
            continue
        agg = {"messages": 0, "input_tokens": 0, "cache_write": 0, "cache_read": 0,
               "output_tokens": 0, "thinking_tokens": 0}
        cwd = None
        last = ""
        try:
            with path.open() as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    cwd = cwd or rec.get("cwd")
                    ts = rec.get("timestamp")
                    if isinstance(ts, str) and ts > last:
                        last = ts
                    u = (rec.get("message") or {}).get("usage") if isinstance(
                        rec.get("message"), dict) else None
                    if not u:
                        continue
                    agg["messages"] += 1
                    agg["input_tokens"] += u.get("input_tokens") or 0
                    agg["cache_write"] += u.get("cache_creation_input_tokens") or 0
                    agg["cache_read"] += u.get("cache_read_input_tokens") or 0
                    agg["output_tokens"] += u.get("output_tokens") or 0
                    agg["thinking_tokens"] += (
                        (u.get("output_tokens_details") or {}).get("thinking_tokens") or 0)
        except OSError:
            continue
        if not agg["messages"]:
            continue
        out.append({"session_id": path.stem, "day": (last or now())[:10],
                    "cwd": cwd, "last_seen": last or now(), **agg})
    return out


def read_files() -> list[tuple[str, int, int, int, int]]:
    rows = []
    for path, limit in WATCHED_FILES:
        p = Path(path)
        if not p.is_file():
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        lines = len(text.splitlines())
        rows.append((path, lines, len(text), limit, int(lines > limit)))
    return rows


def read_config() -> list[tuple[str, str | None]]:
    """The values that actually govern behaviour, from their real files."""
    vals: dict[str, Any] = {}

    def jget(path: Path, *keys: str, prefix: str) -> None:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return
        for k in keys:
            node: Any = data
            for part in k.split("."):
                node = node.get(part) if isinstance(node, dict) else None
            vals[f"{prefix}.{k.split('.')[-1]}"] = node

    jget(Path.home()/".claude/settings.json", "env.ENABLE_PROMPT_CACHING_1H",
         "env.MAX_THINKING_TOKENS", prefix="claude.env")
    vals["claude.effortLevel"] = _json_path(Path.home()/".claude/settings.json", "effortLevel")
    jget(Path.home()/".hermes/hindsight/config.json",
         "auto_recall", "auto_retain", "bank_id", prefix="hermes.hindsight")
    jget(Path.home()/".hindsight/coding-agent.json",
         "dynamicBankId", "bankIdTemplate", prefix="hindsight.coding_agent")
    return [(k, None if v is None else str(v)) for k, v in vals.items()]


def _json_path(path: Path, key: str) -> str | None:
    try:
        return str(json.loads(path.read_text()).get(key))
    except (OSError, ValueError):
        return None


def read_cron() -> list[tuple[str, str, str, str, int]]:
    """Inventory Hermes scheduled jobs and whether each spends tokens."""
    try:
        out = subprocess.run(["hermes", "cron", "list"], capture_output=True,
                             text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    import re
    rows = []
    for block in re.split(r"\n\s{2}[0-9a-f]{12} \[", out)[1:]:
        def field(label: str) -> str:
            m = re.search(rf"{label}:\s+(.+)", block)
            return m.group(1).strip() if m else ""
        name, mode = field("Name"), field("Mode")
        if not name:
            continue
        rows.append((name, mode, field("Model") or "default", field("Schedule"),
                     int("no-agent" not in mode)))
    return rows


def read_insights() -> list[tuple[str, str, int, str]]:
    """Notice /insights reports as they appear. Cheap: a directory stat."""
    d = Path.home() / ".claude/usage-data"
    if not d.is_dir():
        return []
    rows = []
    for f in d.glob("*.html"):
        try:
            st = f.stat()
        except OSError:
            continue
        rows.append((str(f), datetime.fromtimestamp(st.st_mtime, timezone.utc)
                     .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                     st.st_size, now()))
    return rows


def collect() -> dict[str, Any]:
    db = connect()
    cur = db.execute("INSERT INTO sample (collected_at, host) VALUES (?,?)",
                     (now(), os.uname().nodename))
    sid = cur.lastrowid
    q = read_quota()
    db.executemany("INSERT INTO quota (sample_id, provider, window_label, remaining_pct,"
                   " billing_kind) VALUES (?,?,?,?,?)", [(sid, *r) for r in q])
    f = read_files()
    db.executemany("INSERT INTO file_size (sample_id, path, lines, bytes, limit_lines, over)"
                   " VALUES (?,?,?,?,?,?)", [(sid, *r) for r in f])
    cfg = read_config()
    drifted = 0
    rows = []
    for key, value in cfg:
        exp = EXPECTED.get(key)
        d = int(exp is not None and value != exp)
        drifted += d
        rows.append((sid, key, value, exp, d))
    db.executemany("INSERT INTO config_value (sample_id, key, value, expected, drifted)"
                   " VALUES (?,?,?,?,?)", rows)
    s = read_sessions()
    db.executemany("""INSERT INTO session_usage
        (session_id, day, cwd, messages, input_tokens, cache_write, cache_read,
         output_tokens, thinking_tokens, last_seen)
        VALUES (:session_id,:day,:cwd,:messages,:input_tokens,:cache_write,
                :cache_read,:output_tokens,:thinking_tokens,:last_seen)
        ON CONFLICT(session_id) DO UPDATE SET
          messages=excluded.messages, input_tokens=excluded.input_tokens,
          cache_write=excluded.cache_write, cache_read=excluded.cache_read,
          output_tokens=excluded.output_tokens,
          thinking_tokens=excluded.thinking_tokens,
          last_seen=excluded.last_seen, day=excluded.day, cwd=excluded.cwd""", s)
    cj = read_cron()
    db.executemany("INSERT INTO cron_job (sample_id, name, mode, model, schedule,"
                   " costs_tokens) VALUES (?,?,?,?,?,?)", [(sid, *r) for r in cj])
    ins = read_insights()
    db.executemany("INSERT INTO insights_report (path, generated_at, bytes, seen_at)"
                   " VALUES (?,?,?,?) ON CONFLICT(path) DO UPDATE SET"
                   " bytes=excluded.bytes, generated_at=excluded.generated_at", ins)
    db.commit()
    db.close()
    return {"sample": sid, "quota_rows": len(q), "files": len(f),
            "config_keys": len(cfg), "drifted": drifted, "sessions": len(s),
            "cron_jobs": len(cj), "token_spending_jobs": sum(r[4] for r in cj),
            "insights_reports": len(ins)}


# -- reporting -----------------------------------------------------------

def drift_rows(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute("""SELECT key, value, expected FROM config_value
        WHERE sample_id = (SELECT MAX(id) FROM sample) AND drifted = 1""").fetchall()


def report(hours: int = 24) -> tuple[str, bool]:
    db = connect()
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)
             ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    lines: list[str] = []
    actionable = False

    d = drift_rows(db)
    if d:
        actionable = True
        lines.append("⚠️  CONFIG DRIFT")
        for r in d:
            lines.append(f"    {r['key']}: is {r['value']!r}, expected {r['expected']!r}")

    over = db.execute("""SELECT path, lines, limit_lines FROM file_size
        WHERE sample_id = (SELECT MAX(id) FROM sample) ORDER BY lines DESC""").fetchall()
    near = [r for r in over if r["lines"] > r["limit_lines"] * 0.85]
    if near:
        actionable = actionable or any(r["lines"] > r["limit_lines"] for r in near)
        lines.append("📏 INSTRUCTION FILES near/over limit (they load every session)")
        for r in near:
            flag = "OVER" if r["lines"] > r["limit_lines"] else "near"
            lines.append(f"    [{flag}] {r['lines']:>4}/{r['limit_lines']} lines  "
                         f"{r['path'].replace(str(Path.home()), '~')}")

    u = db.execute("""SELECT COUNT(*) n, SUM(messages) msgs, SUM(cache_read) cr,
        SUM(cache_write) cw, SUM(output_tokens) out, SUM(thinking_tokens) think
        FROM session_usage WHERE last_seen >= ?""", (since,)).fetchone()
    if u and u["n"]:
        cr, cw = u["cr"] or 0, u["cw"] or 0
        total = cr + cw
        hit = (100.0 * cr / total) if total else 0.0
        lines.append(f"🧮 USAGE last {hours}h — {u['n']} sessions, {u['msgs']} messages")
        lines.append(f"    cache hit rate {hit:.1f}%  "
                     f"(read {cr/1e6:.1f}M vs write {cw/1e6:.1f}M)")
        lines.append(f"    output {(u['out'] or 0)/1e6:.2f}M  "
                     f"thinking {(u['think'] or 0)/1e6:.2f}M")
        if total and hit < 70:
            actionable = True
            lines.append("    ⚠️  low cache hit rate — long gaps between messages, or "
                         "sessions left open past the 1h cache lifetime")

    # Retired pools are deliberately at zero; alarming on them trains you to
    # ignore the alarm, which costs more than the alarm is worth.
    tight = db.execute("""SELECT provider, window_label, remaining_pct FROM quota
        WHERE sample_id = (SELECT MAX(id) FROM sample) AND remaining_pct IS NOT NULL
          AND remaining_pct < 25 AND provider NOT IN ('deepseek','openrouter','opencode-zen')
        ORDER BY remaining_pct""").fetchall()
    if tight:
        actionable = True
        lines.append("⛽ QUOTA under 25%")
        for r in tight:
            lines.append(f"    {r['provider']} {r['window_label']}: "
                         f"{r['remaining_pct']:.0f}% left")

    jobs = db.execute("""SELECT name, model FROM cron_job
        WHERE sample_id = (SELECT MAX(id) FROM sample) AND costs_tokens = 1""").fetchall()
    if jobs:
        lines.append(f"⏰ SCHEDULED AGENT JOBS ({len(jobs)} spend tokens on a timer)")
        for r in jobs:
            lines.append(f"    {r['name'][:52]:52} model={r['model']}")
        lines.append("    (default = cline-pass/deepseek-v4-flash, the clinepass "
                     "lifeline — see experiment 'scheduled-jobs-off-clinepass')")

    running = db.execute("""SELECT id, name, started_at FROM experiment
        WHERE ended_at IS NULL ORDER BY started_at""").fetchall()
    if running:
        lines.append(f"🧪 EXPERIMENTS RUNNING ({len(running)})")
        for r in running:
            lines.append(f"    [{r['id']}] {r['name']}  since {r['started_at'][:10]}")

    idle = db.execute("""SELECT provider, MIN(remaining_pct) rem FROM quota
        WHERE sample_id = (SELECT MAX(id) FROM sample) AND remaining_pct >= 90
        GROUP BY provider ORDER BY rem DESC""").fetchall()
    if idle:
        lines.append("💤 IDLE capacity (route bulk here): " +
                     ", ".join(f"{r['provider']} {r['rem']:.0f}%" for r in idle))

    db.close()
    if not lines:
        lines.append("Nothing notable in the last "
                     f"{hours}h — no drift, no file over limit, quota healthy.")
    return "\n".join(lines), actionable


def experiment_start(name: str, hypothesis: str, variable: str,
                     from_value: str, to_value: str) -> int:
    db = connect()
    cur = db.execute("""INSERT INTO experiment
        (name, hypothesis, variable, from_value, to_value, started_at)
        VALUES (?,?,?,?,?,?)""",
        (name, hypothesis, variable, from_value, to_value, now()))
    db.commit(); eid = cur.lastrowid; db.close()
    return eid


def experiment_end(eid: int, outcome: str, verdict: str) -> None:
    db = connect()
    db.execute("UPDATE experiment SET ended_at=?, outcome=?, verdict=? WHERE id=?",
               (now(), outcome, verdict, eid))
    db.commit(); db.close()


def experiments() -> list[sqlite3.Row]:
    db = connect()
    rows = db.execute("SELECT * FROM experiment ORDER BY started_at DESC").fetchall()
    db.close()
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Agent fleet stats")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("collect")
    r = sub.add_parser("report")
    r.add_argument("--hours", type=int, default=24)
    sub.add_parser("drift")
    xs = sub.add_parser("experiment-start")
    xs.add_argument("--name", required=True)
    xs.add_argument("--hypothesis", required=True)
    xs.add_argument("--variable", required=True)
    xs.add_argument("--from-value", default="")
    xs.add_argument("--to-value", default="")
    xe = sub.add_parser("experiment-end")
    xe.add_argument("--id", type=int, required=True)
    xe.add_argument("--outcome", required=True)
    xe.add_argument("--verdict", required=True, choices=("keep", "revert", "inconclusive"))
    sub.add_parser("experiments")
    args = ap.parse_args(argv)

    if args.command == "experiment-start":
        eid = experiment_start(args.name, args.hypothesis, args.variable,
                               args.from_value, args.to_value)
        print(json.dumps({"experiment": eid, "name": args.name}, indent=2))
        return 0
    if args.command == "experiment-end":
        experiment_end(args.id, args.outcome, args.verdict)
        print(f"experiment {args.id}: {args.verdict}")
        return 0
    if args.command == "experiments":
        for e in experiments():
            state = e["verdict"] or ("running" if not e["ended_at"] else "?")
            print(f"[{e['id']}] {state:12} {e['name']}")
            print(f"      {e['variable']}: {e['from_value']!r} -> {e['to_value']!r}"
                  f"  started {e['started_at'][:10]}")
            print(f"      hypothesis: {e['hypothesis'][:100]}")
            if e["outcome"]:
                print(f"      outcome: {e['outcome'][:110]}")
        return 0

    if args.command == "collect":
        print(json.dumps(collect(), indent=2))
        return 0
    if args.command == "drift":
        db = connect()
        rows = drift_rows(db)
        db.close()
        for r in rows:
            print(f"{r['key']}: is {r['value']!r}, expected {r['expected']!r}")
        if not rows:
            print("no config drift")
        return 10 if rows else 0
    text, actionable = report(hours=args.hours)
    print(f"☀️  Agent fleet — {datetime.now().strftime('%A %d %B, %H:%M')}\n")
    print(text)
    return 10 if actionable else 0


if __name__ == "__main__":
    raise SystemExit(main())
