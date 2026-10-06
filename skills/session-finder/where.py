#!/usr/bin/env python3
"""Say where a running agent process lives: herdr ws/tab/pane, Orca worktree, tmux, Ghostty...

    where.py <pid>            # one line + focus command
    where.py --json <pid>

Same set of facts as ~/.local/bin/hermes-ping, but for ANOTHER process: reads that
pid's environment with `ps eww` (same user only) instead of our own. Every lookup
has a short timeout. Exit 0 = found something, 1 = pid gone/unreadable.
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

KEYS = ("HERDR_ENV", "HERDR_PANE_ID", "HERDR_TAB_ID", "HERDR_WORKSPACE_ID", "HERDR_BIN_PATH", "HERDR_SESSION",
        "ORCA_PANE_KEY", "ORCA_TAB_ID", "ORCA_WORKSPACE_ROOT", "ORCA_TERMINAL_HANDLE", "TERM_PROGRAM", "TMUX",
        "TMUX_PANE", "ITERM_SESSION_ID", "SSH_CONNECTION")


def run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def env_of(pid):
    out = run("ps", "eww", "-o", "command=", "-p", str(pid))
    env = {}
    for tok in out.split(" "):
        k, sep, v = tok.partition("=")
        if sep and k in KEYS:
            env[k] = v.strip()
    return env


def jget(text, *path):
    try:
        d = json.loads(text)
    except ValueError:
        return None
    for p in path:
        d = d.get(p) if isinstance(d, dict) else None
    return d


def lab(text, kind):
    o = jget(text, "result", kind)
    return f"{o.get('label') or '?'}#{o.get('number') or '?'}" if isinstance(o, dict) else None


def cwd_of(pid):
    for line in run("lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn").splitlines():
        if line.startswith("n"):
            home = str(os.path.expanduser("~"))
            p = line[1:]
            return "~" + p[len(home):] if p.startswith(home) else p
    return ""


def where(pid):
    env = env_of(pid)
    if not env and not run("ps", "-p", str(pid), "-o", "pid="):
        return None
    focus = ""
    title = ""
    if env.get("HERDR_ENV") and env.get("HERDR_PANE_ID"):
        hb = env.get("HERDR_BIN_PATH") or "herdr"
        ws = lab(run(hb, "workspace", "get", env.get("HERDR_WORKSPACE_ID", "")), "workspace")
        tab = lab(run(hb, "tab", "get", env.get("HERDR_TAB_ID", "")), "tab")
        pj = run(hb, "pane", "get", env["HERDR_PANE_ID"])
        pane = jget(pj, "result", "pane") or {}
        title = pane.get("terminal_title_stripped") or ""
        sess = env.get("HERDR_SESSION", "")
        text = (f"herdr{' session ' + sess if sess else ''} · ws {ws or env.get('HERDR_WORKSPACE_ID')} · "
                f"tab {tab or env.get('HERDR_TAB_ID')} · pane {pane.get('label') or pane.get('agent') or env['HERDR_PANE_ID']}")
        focus = f"herdr tab focus {env.get('HERDR_TAB_ID')}"
    elif env.get("ORCA_PANE_KEY") or env.get("TERM_PROGRAM") == "Orca":
        wt = os.path.basename(env.get("ORCA_WORKSPACE_ROOT", "")) or "?"
        text = f"Orca · worktree {wt}" + (f" · tab {env['ORCA_TAB_ID']}" if env.get("ORCA_TAB_ID") else "")
        if env.get("ORCA_TERMINAL_HANDLE"):
            focus = f"orca terminal switch --terminal {env['ORCA_TERMINAL_HANDLE']}"
    elif env.get("TMUX"):
        tp = run("tmux", "display", "-p", "-t", env.get("TMUX_PANE", ""), "#S:#I.#P #W").strip()
        text = f"tmux {tp or '?'}"
        if env.get("TMUX_PANE"):
            focus = f"tmux switch-client -t {env['TMUX_PANE']}"
    else:
        tp = env.get("TERM_PROGRAM", "")
        text = {"ghostty": "Ghostty", "iTerm.app": "iTerm2", "Apple_Terminal": "Terminal.app",
                "vscode": "VS Code/Cursor"}.get(tp, tp or "unknown terminal")
    if env.get("SSH_CONNECTION"):
        text += " · ssh"
    return {"pid": pid, "where": text, "title": title, "cwd": cwd_of(pid), "focus": focus}


DB = Path.home() / ".local/state/session-index/history.v2.sqlite"
TTL = 3600


def lookup(pid, proc_start=""):
    """where(pid), cached in the history DB per (pid, procStart) for an hour, so repeat
    queries cost nothing. Returns None when the pid is gone."""
    try:
        db = sqlite3.connect(DB, timeout=60)
        db.execute("CREATE TABLE IF NOT EXISTS locations(pid INTEGER PRIMARY KEY, proc_start TEXT, ts REAL, data TEXT)")
        row = db.execute("SELECT proc_start, ts, data FROM locations WHERE pid=?", (pid,)).fetchone()
        if row and row[0] == proc_start and time.time() - row[1] < TTL:
            return json.loads(row[2])
    except sqlite3.Error:
        db = None
    w = where(pid)
    if w and db:
        try:
            db.execute("INSERT OR REPLACE INTO locations VALUES (?,?,?,?)", (pid, proc_start, time.time(), json.dumps(w)))
            db.commit()
        except sqlite3.Error:
            pass
    return w


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    if len(args) != 1 or not args[0].isdigit():
        print(__doc__, file=sys.stderr)
        return 2
    w = where(int(args[0]))
    if not w:
        return 1
    if "--json" in sys.argv:
        print(json.dumps(w))
    else:
        print(f"{w['where']}{' · \"' + w['title'] + '\"' if w['title'] else ''} · {w['cwd']}")
        if w["focus"]:
            print(f"focus: {w['focus']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
