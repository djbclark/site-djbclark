#!/usr/bin/env python3
"""Full-text search over every agent session on this machine, live or ended.

    session-history.py ccc slowness         # best-matching sessions across all agents
    session-history.py --agent hermes ccc   # one agent only (repeatable)
    session-history.py --limit 20 ccc       # more sessions
    session-history.py --json ccc           # machine-readable
    session-history.py --update-only        # just bring the index up to date
    session-history.py --rebuild            # drop and rebuild (slow)
    session-history.py --agents             # which adapters loaded, session counts

One adapter per agent in adapters/*.py (contract in adapters/README.md). SQLite FTS5
index at ~/.local/state/session-index/history.v2.sqlite: a session is re-read only
when its fingerprint changed. User and assistant text only (no tool output).
The index holds prompt text: private, never copy it into a repo. No model tokens.
Exit 0 = hits, 1 = none, 2 = cannot run.
"""
import argparse
import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
INDEX_DIR = Path.home() / ".local/state/session-index"
DB = INDEX_DIR / "history.v2.sqlite"
CAP = {"user": 4000, "assistant": 2000}
SCHEMA = """
CREATE TABLE IF NOT EXISTS files(key TEXT PRIMARY KEY, agent TEXT, sid TEXT, fp TEXT, cwd TEXT, title TEXT, mtime REAL);
CREATE VIRTUAL TABLE IF NOT EXISTS msgs USING fts5(key UNINDEXED, role UNINDEXED, text, tokenize='porter unicode61');
"""


def load_adapters(only):
    mods = []
    for p in sorted((HERE / "adapters").glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"sf_adapter_{p.stem}", p)
        try:
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
        except Exception as e:  # a broken adapter must not take the others down
            print(f"adapter {p.name} failed to load: {e}", file=sys.stderr)
            continue
        if not only or m.AGENT in only:
            mods.append(m)
    return mods


def update(db, mods):
    stats = {}
    for m in mods:
        added = seen = 0
        try:
            sess = list(m.sessions())
        except Exception as e:
            print(f"adapter {m.AGENT}: sessions() failed: {e}", file=sys.stderr)
            continue
        for s in sess:
            seen += 1
            row = db.execute("SELECT fp FROM files WHERE key=?", (s["key"],)).fetchone()
            if row and row[0] == s["fp"]:
                continue
            try:
                cwd, title, msgs = s["load"]()
            except Exception as e:
                print(f"adapter {m.AGENT}: skip {s['sid']}: {e}", file=sys.stderr)
                continue
            db.execute("DELETE FROM msgs WHERE key=?", (s["key"],))
            db.executemany(
                "INSERT INTO msgs(key, role, text) VALUES (?,?,?)",
                [(s["key"], r, t[: CAP.get(r, 2000)]) for r, t in msgs if t and len(t) > 3],
            )
            db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)",
                       (s["key"], m.AGENT, s["sid"], s["fp"], cwd or "", title or "", s["mtime"]))
            db.commit()
            added += 1
        stats[m.AGENT] = (seen, added)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("keywords", nargs="*")
    ap.add_argument("--agent", action="append", default=[])
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--update-only", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--agents", action="store_true")
    a = ap.parse_args()
    if not (a.keywords or a.update_only or a.rebuild or a.agents):
        ap.print_usage(sys.stderr)
        return 2

    INDEX_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    if a.rebuild and DB.exists():
        DB.unlink()
    db = sqlite3.connect(DB, timeout=120)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    mods = load_adapters(set(a.agent))
    t0 = time.time()
    stats = update(db, mods)
    if a.agents or a.update_only or a.rebuild:
        for name, (seen, added) in stats.items():
            print(f"{name:10} sessions={seen:5} reindexed={added}", file=sys.stderr)
        print(f"{time.time() - t0:.1f}s", file=sys.stderr)
        if not a.keywords:
            return 0

    match = " ".join('"' + k.replace('"', "") + '"*' for k in a.keywords)
    agent_sql = ""
    params = [match]
    if a.agent:
        agent_sql = f"AND f.agent IN ({','.join('?' * len(a.agent))})"
        params += a.agent
    rows = db.execute(
        f"SELECT m.key, m.role, bm25(msgs), snippet(msgs, 2, '[', ']', '...', 24) "
        f"FROM msgs m JOIN files f ON f.key = m.key WHERE msgs MATCH ? {agent_sql} ORDER BY 3 LIMIT 600",
        params,
    ).fetchall()
    best = {}
    for key, role, rank, snip in rows:
        prev = best.get(key)
        count = prev[3] + 1 if prev else 1
        if not prev or rank < prev[0]:
            best[key] = (rank, role, snip, count)
        else:
            best[key] = (prev[0], prev[1], prev[2], count)
    live = {m.AGENT: (m.live() if hasattr(m, "live") else set()) for m in mods}
    info = {m.AGENT: (m.live_info() if hasattr(m, "live_info") else {}) for m in mods}
    resume = {m.AGENT: getattr(m, "RESUME", "") for m in mods}
    out = []
    for key, (rank, role, snip, count) in sorted(best.items(), key=lambda kv: kv[1][0])[: a.limit]:
        agent, sid, cwd, title, mtime = db.execute(
            "SELECT agent, sid, cwd, title, mtime FROM files WHERE key=?", (key,)).fetchone()
        out.append({"agent": agent, "sessionId": sid, "live": sid in live.get(agent, set()), "cwd": cwd,
                    "title": title, "lastActive": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
                    "hits": count, "role": role, "snippet": " ".join(snip.split()),
                    "resume": resume.get(agent, "").format(sid=sid, cwd=cwd) if resume.get(agent) else ""})
    if info:
        sys.path.insert(0, str(HERE))  # python -I drops the script dir
        import where as _where
        for r in out:
            i = info.get(r["agent"], {}).get(r["sessionId"])
            if i:
                r["name"] = i["name"]
                r["where"] = _where.lookup(i["pid"], i["procStart"])
    if a.json:
        print(json.dumps(out, indent=1))
    else:
        for r in out:
            print(f"{r['agent']}  {r['sessionId']}  {'LIVE' if r['live'] else 'ended'}  {r['lastActive']}  hits={r['hits']}  cwd={r['cwd']}")
            print(f"    title: {r['title'] or '(untitled)'}")
            if r.get("name"):
                print(f"    send to: {r['name']}")
            if r.get("where"):
                print(f"    where: {r['where']['where']} · {r['where']['cwd']}")
                if r["where"]["focus"]:
                    print(f"    focus: {r['where']['focus']}")
            print(f"    {r['role']}: {r['snippet']}")
            if not r["live"] and r["resume"]:
                print(f"    resume: {r['resume']}")
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
