#!/usr/bin/env python3
"""fleet — every running agent session on this machine, any TUI, no model.

    fleet.py [--all] [--json]        running sessions (--all: sleeper and plain shell panes too)
    fleet.py ended [--days N] [--json]
                                     ended sessions that still hold open items: a handoff whose
                                     next steps nobody picked up, or a last reply that asked a question
    fleet.py show <id> [--json]      one session with its transcript tail
    fleet.py conflicts --cwd DIR [--sid ID]
                                     who else works in that repo: working sessions (exit 1: do not start
                                     a second one, message it instead), live bigteam claims, dirty files,
                                     and whether SID is already live somewhere (never resume it twice)

Sources, merged by pane and session id: herdr `agent list` (any agent kind), the Claude Code
registry (~/.claude/sessions), a process scan for TUIs running outside herdr, Hermes gateway
sessions active in the last day (~/.hermes/state.db, read-only), and the sessions launch.py
started over ACP (~/.local/state/session-finder/launches.jsonl). Each record says how to reach
the session (`reach`) and whether it already finished with /handoff or /quit (`finished`), so a
caller never continues a session that handed off.

Shared by session-find.py, helm.py and launch.py. Exit 0 = something listed, 1 = nothing, 2 = usage.
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import where as _where  # noqa: E402
except ImportError:
    _where = None

HOME = str(Path.home())
CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
HERDR = os.environ.get("HERDR_BIN_PATH") or shutil.which("herdr") or str(Path.home() / ".local/bin/herdr")
STATE_DIR = Path(os.environ.get("SESSION_FINDER_STATE", Path.home() / ".local/state/session-finder"))
LAUNCHES = STATE_DIR / "launches.jsonl"
HANDOFFS = Path.home() / ".local/state/handoffs"
HERMES_DB = Path.home() / ".hermes" / "state.db"
TAIL = 600_000          # bytes read from the end of a Claude transcript
HERMES_ACTIVE = 24 * 3600
REG_STATUS = {"busy": "working", "shell": "working", "waiting": "blocked", "idle": "idle"}
# binary name -> agent label, for TUIs running outside herdr (herdr panes are taken from herdr itself)
PROC_AGENTS = {"claude": "claude", "codex": "codex", "cursor-agent": "cursor", "opencode": "opencode",
               "zcode": "zcode", "crush": "crush", "copilot": "copilot", "qwen": "qwen", "agy": "agy",
               "muse": "muse", "cline": "cline", "hermes": "hermes", "grok": "grok", "devin": "devin"}
PROC_SKIP = re.compile(r"(acp|mcp|--acp|gateway|dashboard|language-server|lsp|sleeper|serve\b|Helper|node_modules|"
                       r"claude-agent-acp|codex-acp| -p |--print|exec |run |\bresume-globally\b)")
STRIP = re.compile(r"<(system-reminder|local-command-[a-z]+|command-[a-z]+|pasted_content)\b.*?</\1>", re.S)
CMD = re.compile(r"<command-name>\s*(/\S+)")
FINISHERS = ("/handoff", "/quit", "/exit")


# ---- small helpers --------------------------------------------------------------------------

def run(*cmd, timeout=10):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def herdr_json(*args):
    try:
        return json.loads(run(HERDR, *args)[1]).get("result") or {}
    except (ValueError, AttributeError):
        return {}


_LABELS = {}


def herdr_label(kind, ident):
    if (kind, ident) not in _LABELS:
        o = herdr_json(kind, "get", ident).get(kind) or {}
        _LABELS[kind, ident] = f"{o.get('label') or '?'}#{o.get('number') or '?'}" if o else ident
    return _LABELS[kind, ident]


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def ancestors():
    pids, pid = set(), os.getpid()
    for _ in range(15):
        try:
            pid = int(run("ps", "-o", "ppid=", "-p", str(pid))[1].strip())
        except ValueError:
            break
        if pid <= 1:
            break
        pids.add(pid)
    return pids


def short(path):
    return "~" + path[len(HOME):] if path and path.startswith(HOME) else path or ""


def clip(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else "…" + text[-(n - 1):]


def toplevel(path):
    rc, out = run("git", "-C", path or ".", "rev-parse", "--show-toplevel")
    return out.strip() if rc == 0 and out.strip() else (path or "")


# ---- Claude transcripts ---------------------------------------------------------------------

_TX = {}


def transcript(sid):
    hits = sorted((CLAUDE / "projects").glob(f"*/{sid}.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _ts(rec):
    t = rec.get("timestamp")
    if not t:
        return None
    try:
        return time.mktime(time.strptime(t[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone + (0 if t.endswith("Z") else 0)
    except ValueError:
        return None


def parse(path):
    """Tail of a Claude transcript: pending tool calls, last reply, the operator's prompts with
    times, whether the session finished (/handoff, /quit), and its typical unattended work stretch."""
    st = path.stat()
    key = (st.st_size, st.st_mtime_ns)
    hit = _TX.get(path)
    if hit and hit[0] == key:
        return hit[1]
    with open(path, "rb") as fh:
        fh.seek(max(0, st.st_size - TAIL))
        lines = fh.read().decode("utf-8", "replace").splitlines()
    if st.st_size > TAIL:
        lines = lines[1:]
    uses, done, answers = {}, set(), {}
    prompts, stops = [], []     # (epoch, text) per operator prompt; epoch per assistant stop (question or end of turn)
    last_text = last_prompt = ""
    last_ts = None
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict) or r.get("isSidechain"):
            continue
        m = r.get("message") or {}
        content, role = m.get("content"), m.get("role")
        ts = _ts(r)
        if ts:
            last_ts = ts
        if isinstance(content, str):
            if role == "user" and not r.get("isMeta"):
                last_prompt = content
                prompts.append((ts, content))
            continue
        for b in content if isinstance(content, list) else []:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "tool_use":
                uses[b.get("id")] = (b.get("name"), b.get("input") or {})
                if b.get("name") == "AskUserQuestion" and ts:
                    stops.append(ts)
            elif t == "tool_result":
                done.add(b.get("tool_use_id"))
                tur = r.get("toolUseResult")
                if isinstance(tur, dict) and "answers" in tur:
                    answers[b.get("tool_use_id")] = tur["answers"]
            elif t == "text" and (b.get("text") or "").strip():
                if role == "assistant":
                    last_text = b["text"]
                    if ts:
                        stops.append(ts)
                elif role == "user" and not r.get("isMeta"):
                    last_prompt = b["text"]
                    prompts.append((ts, b["text"]))
    info = {"size": st.st_size, "mtime": st.st_mtime, "last_text": last_text, "last_prompt": last_prompt,
            "pending": [(k, n, i) for k, (n, i) in uses.items() if k not in done], "answers": answers,
            "finished": finished_by(prompts, last_text), "stretch_min": work_stretch(prompts, stops),
            "asks": last_text.rstrip().endswith("?") or any(n == "AskUserQuestion" for k, (n, _) in uses.items()
                                                           if k not in done),
            "last_ts": last_ts}
    _TX[path] = (key, info)
    return info


def _cmd_of(text):
    m = CMD.search(text)
    if m:
        return m.group(1).lower()
    t = STRIP.sub(" ", text).strip()
    return t.split()[0].lower() if t.startswith("/") else ""


def finished_by(prompts, last_text=""):
    """'/handoff' when the last real prompt (ignoring command output echoes) was a handoff or
    quit, else ''. A substantive prompt after the handoff means work resumed."""
    for _, text in reversed(prompts[-6:]):
        if "<local-command-stdout>" in text and "<command-name>" not in text:
            continue
        cmd = _cmd_of(text)
        if cmd in FINISHERS:
            return "/handoff" if cmd == "/handoff" or "handoff" in last_text.lower() else cmd
        if len(STRIP.sub(" ", text).strip()) > 40:
            return ""
    return ""


def work_stretch(prompts, stops):
    """Median minutes the session worked after an operator prompt before it next needed one
    (next question or end of turn). None when there is too little history."""
    stops = sorted(s for s in stops if s)
    spans = []
    for ts, _ in prompts:
        if not ts:
            continue
        nxt = next((s for s in stops if s > ts), None)
        if nxt:
            spans.append((nxt - ts) / 60)
    spans = spans[-8:]
    if len(spans) < 2:
        return None
    spans.sort()
    return round(spans[len(spans) // 2], 1)


# ---- sources --------------------------------------------------------------------------------

def _rec(**kw) -> dict:
    base: dict = {"id": "", "agent": "?", "host": "", "sid": None, "name": "", "title": "", "cwd": "", "status": "unknown",
            "where": "", "focus": "", "chan": None, "reach": "", "self": False, "focused": False, "finished": "",
            "pid": None, "transcript": None, "launch": None}
    base.update(kw)
    return base


def _from_herdr(s, a):
    s.update(host="herdr", chan=("herdr", a["pane_id"]), focused=bool(a.get("focused")),
             title=a.get("terminal_title_stripped") or s.get("title") or "",
             focus=f"herdr tab focus {a['tab_id']}", cwd=s.get("cwd") or a.get("cwd") or "",
             where=f"herdr · ws {herdr_label('workspace', a['workspace_id'])} · tab {herdr_label('tab', a['tab_id'])}")
    if a["pane_id"] == os.environ.get("HERDR_PANE_ID"):
        s["self"] = True
    if a.get("agent_status") in ("idle", "working", "blocked", "done"):
        s["status"] = "idle" if a["agent_status"] == "done" else a["agent_status"]


def _acp_pane_of(pid):
    """Walk up from PID to an acp-run process and return the HERDR_PANE_ID it inherited, if any."""
    for _ in range(5):
        rc, out = run("ps", "-o", "ppid=,command=", "-p", str(pid))
        parts = out.split(None, 1)
        if len(parts) < 2:
            return None
        ppid, cmd = parts[0], parts[1]
        if "acp-run" in cmd:
            return (_where.env_of(pid) if _where else {}).get("HERDR_PANE_ID")
        try:
            pid = int(ppid)
        except ValueError:
            return None
        if pid <= 1:
            return None
    return None


def _claude_sessions(agents_by_sid, used, anc, launch_panes=None):
    me = os.environ.get("CLAUDE_CODE_SESSION_ID")
    launch_panes = launch_panes or {}
    out = []
    for f in sorted((CLAUDE / "sessions").glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        pid, sid = d.get("pid"), d.get("sessionId")
        if not sid or not alive(pid):
            continue
        s = _rec(id=sid[:8], agent="claude", sid=sid, name=d.get("name") or "", cwd=d.get("cwd") or "",
                 status=REG_STATUS.get(d.get("status"), "unknown"), self=(pid in anc or sid == me), pid=pid,
                 reach=f"SendMessage to {d.get('name') or sid[:8]}")
        a = agents_by_sid.get(sid)
        env = _where.env_of(pid) if (_where and not a) else {}
        pane = a["pane_id"] if a else env.get("HERDR_PANE_ID")   # the sdk-ts entrypoint has no herdr hook: use its env
        if not pane and not a and launch_panes:
            pane = _acp_pane_of(pid)   # claude-agent-acp scrubs the env; the acp-run ancestor still has the pane id
        if pane in launch_panes:
            # the Claude Code that claude-agent-acp runs inside one of our ACP launches: one session, not two
            launch = launch_panes[pane]
            launch["sid"], launch["transcript"], launch["pid"] = sid, str(transcript(sid) or ""), pid
            launch["underlying"] = {"name": d.get("name") or "", "status": REG_STATUS.get(d.get("status"), "unknown")}
            if launch["status"] == "working" and REG_STATUS.get(d.get("status")) == "blocked":
                launch["status"] = "blocked"    # e.g. an AskUserQuestion inside the ACP session
            continue
        if a:
            used.add(a["pane_id"])
            _from_herdr(s, a)
        elif _where:
            w = _where.lookup(pid, d.get("procStart", "")) or {}
            s.update(where=w.get("where", ""), focus=w.get("focus", ""), title=w.get("title", ""), host="terminal")
            if env.get("ORCA_TERMINAL_HANDLE"):
                s.update(chan=("orca", env["ORCA_TERMINAL_HANDLE"]), host="orca")
            elif env.get("TMUX_PANE"):
                s.update(chan=("tmux", env["TMUX_PANE"]), host="tmux")
        path = transcript(sid)
        if path:
            s["transcript"] = str(path)
            tx = parse(path)
            s["finished"] = tx["finished"]
            if not s["title"] and tx["last_prompt"]:
                s["title"] = clip(STRIP.sub(" ", tx["last_prompt"]), 70)
        out.append(s)
    return out


def _other_herdr(agents, used):
    out = []
    for a in agents:
        if a["pane_id"] in used or a.get("agent") in (None, "", "sleeper"):
            continue
        sess = (a.get("agent_session") or {}).get("value")
        s = _rec(id=a["pane_id"], agent=a.get("agent") or "?", sid=sess, cwd=a.get("cwd") or "",
                 reach=f"helm.py send {a['pane_id']} (keys into the pane)")
        _from_herdr(s, a)
        if s["agent"] == "hermes":
            s["reach"] = "ask_hermes (MCP) or helm.py send into the pane"
        out.append(s)
        used.add(a["pane_id"])
    return out


def _shell_panes(agents, used):
    out = []
    for a in agents:
        if a["pane_id"] in used:
            continue
        s = _rec(id=a["pane_id"], agent=a.get("agent") or "shell", cwd=a.get("cwd") or "", status="unknown",
                 reach="free pane: launch.py --pane " + a["pane_id"])
        _from_herdr(s, a)
        s["status"] = "shell"
        out.append(s)
    return out


def _proc_scan(known_pids, known_panes, anc):
    """TUIs running outside herdr (Ghostty, Orca, tmux, ssh). Only the user's own processes."""
    out = []
    rc, text = run("ps", "-axo", "pid=,ppid=,lstart=,command=", timeout=5)
    for line in text.splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        pid, cmd = int(parts[0]), parts[7]
        if pid in known_pids or pid == os.getpid() or PROC_SKIP.search(cmd):
            continue
        exe = os.path.basename(cmd.split()[0])
        agent = PROC_AGENTS.get(exe)
        if not agent and len(cmd.split()) > 1:
            agent = PROC_AGENTS.get(os.path.basename(cmd.split()[1]))  # `python … hermes`, `node … cursor-agent`
        if not agent:
            continue
        env = _where.env_of(pid) if _where else {}
        if env.get("HERDR_PANE_ID") in known_panes:
            continue
        if env.get("HERDR_PANE_ID"):
            continue  # a herdr pane herdr did not classify: its agent list is the authority there
        w = (_where.lookup(pid, " ".join(parts[2:7])) or {}) if _where else {}
        sid = None
        m = re.search(r"--(?:resume|session)[= ]([0-9a-f-]{8,})", cmd)
        if m:
            sid = m.group(1)
        s = _rec(id=f"pid{pid}", agent=agent, sid=sid, pid=pid, cwd=w.get("cwd", ""), where=w.get("where", ""),
                 focus=w.get("focus", ""), title=w.get("title", ""), self=pid in anc, host="terminal",
                 reach="no channel: use its focus command", status="unknown")
        if env.get("ORCA_TERMINAL_HANDLE"):
            s.update(chan=("orca", env["ORCA_TERMINAL_HANDLE"]), host="orca", reach=f"helm.py send pid{pid} (Orca terminal)")
        elif env.get("TMUX_PANE"):
            s.update(chan=("tmux", env["TMUX_PANE"]), host="tmux", reach=f"helm.py send pid{pid} (tmux)")
        out.append(s)
    return out


def _hermes_gateway():
    """Hermes conversations active in the last day (Telegram, desktop, Discord…): not a terminal,
    reached through the hermes MCP server. CLI sessions in herdr panes come from herdr instead."""
    out = []
    if not HERMES_DB.exists():
        return out
    try:
        db = sqlite3.connect(f"file:{HERMES_DB}?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT id, source, chat_id, thread_id, title, cwd, COALESCE(last_activity_at, started_at) last, "
            "last_activity_description FROM sessions WHERE ended_at IS NULL AND source NOT IN ('cli','oneshot') "
            "AND COALESCE(last_activity_at, started_at) > ? ORDER BY last DESC", (time.time() - HERMES_ACTIVE,)
        ).fetchall()
        db.close()
    except sqlite3.Error:
        return out
    for r in rows:
        target = f"telegram:{r['chat_id']}" + (f":{r['thread_id']}" if r["thread_id"] else "") if r["source"] == "telegram" else r["source"]
        out.append(_rec(id=f"hermes:{r['id'][-8:]}", agent="hermes", host="hermes-gw", sid=r["id"], cwd=r["cwd"] or "",
                        title=(r["title"] or "").strip(), status="idle", where=f"Hermes {r['source']} · {target}",
                        reach=f"ask_hermes, or messages_send target={target} (MCP hermes)",
                        focus=f"hermes --resume {r['id']}"))
    return out


def launches():
    if not LAUNCHES.exists():
        return []
    out = {}
    for line in LAUNCHES.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("id"):
            out[d["id"]] = {**out.get(d["id"], {}), **d}   # later lines update earlier ones
    return list(out.values())


def launch_state(d):
    """State of an ACP session launch.py started, from its acp-run log. Non-interactive: working
    until the result record, then idle (exited) with the final text. Interactive (acp-run
    --interactive): a `turn` record ends each turn; after one the process waits for input, so
    the session is idle-and-alive until the runner appends its exit line. Text ending in a
    question -> blocked (needs an answer). Returns (status, last turn's text, result or None)."""
    log = Path(d.get("log") or "")
    cur, turns, result = [], [], None
    if log.exists():
        for line in log.read_text(errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            k, data = r.get("kind"), r.get("data") or {}
            if k == "update" and data.get("sessionUpdate") == "agent_message_chunk":
                cur.append((data.get("content") or {}).get("text") or "")
            elif k == "new_session" and data.get("sessionId"):
                d["acp_session"] = data["sessionId"]
            elif k == "load_session":
                d["acp_session"] = data.get("sessionId") or d.get("resumed") or d.get("acp_session")
                d["load_session"] = True   # it loaded once, so it can load again
            elif k == "initialize":
                d["load_session"] = bool((data.get("agentCapabilities") or {}).get("loadSession"))
            elif k == "turn":
                turns.append({**data, "text": "".join(cur)})
                cur = []
            elif k == "result":
                result = data
    final = turns[-1]["text"] if turns and not "".join(cur).strip() else "".join(cur)
    exited = result is not None or d.get("exit") is not None
    if exited:
        status = "blocked" if final.rstrip().endswith("?") else "idle"
        result = result or {"exit": d.get("exit")}
    elif turns and not "".join(cur).strip():
        status = "blocked" if final.rstrip().endswith("?") else "idle"   # between turns, waiting for input
    else:
        status = "working"
    d["turns"] = len(turns)
    return status, final, result


def _launched(used_panes):
    out = []
    for d in launches():
        if d.get("closed"):
            continue
        status, final, result = launch_state(d)
        host = d.get("host") or {}
        alive_interactive = d.get("interactive") and result is None
        s = _rec(id=d["id"], agent=d.get("agent", "?"), host="acp", sid=d.get("acp_session") or d["id"], name=d.get("name", ""),
                 title=d.get("name") or clip(d.get("prompt_head", ""), 60), cwd=d.get("cwd", ""), status=status,
                 launch={**d, "final": clip(final, 600), "result": result, "alive": result is None}, pid=d.get("pid"),
                 reach=(f"launch.py reply {d['id']} \"<text>\" (next turn in the live ACP session, via its inbox)"
                        if alive_interactive else f"launch.py reply {d['id']} \"<text>\" (new ACP turn, same cwd and brief)"))
        if host.get("kind") == "herdr" and host.get("pane"):
            s.update(chan=("herdr", host["pane"]), focus=f"herdr tab focus {host.get('tab', '')}".strip(),
                     where=f"herdr · ws {herdr_label('workspace', host.get('workspace', ''))} · tab {herdr_label('tab', host.get('tab', ''))} (acp)")
            used_panes.add(host["pane"])
        elif host.get("kind") == "orca":
            s.update(chan=("orca", host.get("terminal")), where=f"Orca · terminal {host.get('terminal')} (acp)",
                     focus=f"orca terminal switch --terminal {host.get('terminal')}")
        else:
            s["where"] = "acp (no terminal)"
        if result is not None and status == "idle":
            s["finished"] = "done"
        if d.get("audited_turn") is not None and d.get("turns", 0) > d["audited_turn"]:
            s["audited"] = True         # the /loose turn has completed
        out.append(s)
    return out


def sessions(include_shell=False):
    anc = ancestors()
    agents = herdr_json("agent", "list").get("agents") or []
    by_sid = {(a.get("agent_session") or {}).get("value"): a for a in agents if a.get("agent_session")}
    used = set()
    launched = _launched(used)
    launch_panes = {s["chan"][1]: s for s in launched if s.get("chan") and s["chan"][0] == "herdr"}
    out = _claude_sessions(by_sid, used, anc, launch_panes)
    out += _other_herdr(agents, used)
    out += launched
    known_pids = {s["pid"] for s in out if s.get("pid")}
    out += _proc_scan(known_pids, used | {a["pane_id"] for a in agents}, anc)
    out += _hermes_gateway()
    if include_shell:
        out += _shell_panes(agents, used)
    return out


# ---- ended sessions with open items ---------------------------------------------------------

def _chain_logs(days):
    out = []
    for log in (HANDOFFS / "chains").glob("*/SESSION_LOG.md"):
        try:
            text = log.read_text(errors="replace")
        except OSError:
            continue
        if time.time() - log.stat().st_mtime > days * 86400:
            continue
        fm = text.split("---", 2)[1] if text.startswith("---") else ""
        dirs = re.findall(r"^\s+dir:\s*(\S+)", fm, re.M)
        active = re.search(r"Active work:\s*(.+)", text)
        nxt = re.search(r"Next steps:\s*(.*?)(?:\n##|\Z)", text, re.S)
        steps = [ln.strip(" -*") for ln in (nxt.group(1) if nxt else "").splitlines() if ln.strip(" -*")]
        if not steps or all(s.lower() in ("none", "none.") for s in steps):
            continue
        out.append({"chain": log.parent.name, "path": str(log), "dirs": dirs, "updated": log.stat().st_mtime,
                    "active": (active.group(1).strip() if active else ""), "steps": steps[:6]})
    return out


def ended_open(days=14, live=None):
    """Ended sessions that still need someone: handoff chains with next steps and no live session
    in their directory (-> start a /baton session there), and Claude transcripts whose last reply
    was a question nobody answered (-> resume, or answer in a fresh session)."""
    live = sessions() if live is None else live
    live_dirs = {toplevel(s["cwd"]) for s in live if s.get("cwd")}
    live_sids = {s["sid"] for s in live if s.get("sid")}
    items = []
    for c in _chain_logs(days):
        tops = {toplevel(d) for d in c["dirs"]}
        if tops & live_dirs:
            continue
        items.append({"kind": "handoff", "id": f"chain:{c['chain']}", "agent": "any", "cwd": c["dirs"][0] if c["dirs"] else "",
                      "title": c["active"], "updated": c["updated"], "steps": c["steps"], "path": c["path"],
                      "action": f"launch.py --baton --cwd {c['dirs'][0] if c['dirs'] else '<dir>'}"})
    cutoff = time.time() - days * 86400
    for path in (CLAUDE / "projects").glob("*/*.jsonl"):
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_mtime < cutoff or path.stem in live_sids or st.st_size < 2000:
            continue
        tx = parse(path)
        if tx["finished"] or not tx["asks"]:
            continue
        if not tx["last_text"].rstrip().endswith("?"):
            continue
        cwd = path.parent.name.replace("-", "/")
        items.append({"kind": "ended-question", "id": path.stem[:8], "agent": "claude", "sid": path.stem,
                      "cwd": cwd if cwd.startswith("/") else "/" + cwd, "title": clip(STRIP.sub(" ", tx["last_prompt"]), 60),
                      "updated": st.st_mtime, "question": clip(tx["last_text"], 300), "mb": round(st.st_size / 1e6, 1),
                      "action": f"claude --resume {path.stem} (transcript {round(st.st_size / 1e6, 1)} MB) "
                                f"or launch.py --agent claude --cwd <dir> with the answer"})
    items.sort(key=lambda it: -it["updated"])
    return items


# ---- conflicts: who else works where I am about to work --------------------------------------

BIGTEAM = Path.home() / ".local/state/bigteam"
CLAIM_LIVE = 6 * 3600


def claims():
    """bigteam Step 0 claims: ~/.local/state/bigteam/<task>/CLAIM, live unless it ends with DONE
    or is older than six hours. Free text; a `files:`/`owned:` line lists paths, `repo:` the repo."""
    out = []
    if not BIGTEAM.is_dir():
        return out
    for c in BIGTEAM.glob("*/CLAIM"):
        try:
            st, text = c.stat(), c.read_text(errors="replace")
        except OSError:
            continue
        if time.time() - st.st_mtime > CLAIM_LIVE or re.search(r"^\s*DONE\b", text, re.M | re.I):
            continue
        files = []
        for m in re.finditer(r"^\s*(?:files|owned|owns|paths)\s*:\s*(.+)$", text, re.M | re.I):
            files += [f.strip() for f in re.split(r"[,\s]+", m.group(1)) if f.strip()]
        repo = re.search(r"^\s*repo\s*:\s*(\S+)", text, re.M | re.I)
        sess = re.search(r"^\s*session\s*:\s*(.+)$", text, re.M | re.I)
        out.append({"task": c.parent.name, "path": str(c), "repo": repo.group(1) if repo else "", "files": files,
                    "session": sess.group(1).strip() if sess else "", "age": time.time() - st.st_mtime})
    return out


def write_claim(task, session, repo, files, note=""):
    d = BIGTEAM / task
    d.mkdir(parents=True, exist_ok=True)
    (d / "CLAIM").write_text(f"session: {session}\nrepo: {repo}\nfiles: {' '.join(files) or '(whole repo, unspecified)'}\n"
                             f"start: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n{note}\n")
    return str(d / "CLAIM")


def release_claim(task):
    c = BIGTEAM / task / "CLAIM"
    if c.exists():
        with c.open("a") as fh:
            fh.write(f"DONE {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")


def conflicts(cwd, live=None, sid=None):
    """What would collide with new work in CWD's repo: live sessions there (working ones block,
    finished ones do not), live claims naming that repo or files under it, the worktree's dirty
    files (another session's uncommitted work), and whether SID is already live somewhere."""
    top = toplevel(cwd)
    live = sessions() if live is None else live
    here = [s for s in live if s.get("cwd") and toplevel(s["cwd"]) == top and not s.get("self")]
    blocking = [s for s in here if not s.get("finished") and s.get("status") in ("working", "blocked")]
    idle = [s for s in here if not s.get("finished") and s.get("status") not in ("working", "blocked")]
    repo = os.path.basename(top)
    mine = [c for c in claims() if c["repo"] in (repo, top) or any(f.startswith(top) for f in c["files"])]
    rc, out = run("git", "-C", top, "status", "--porcelain", timeout=15)
    dirty = [ln[3:] for ln in out.splitlines() if ln.strip()] if rc == 0 else []
    sid_live = [s for s in live if sid and s.get("sid") == sid]
    return {"repo": top, "blocking": blocking, "idle": idle, "finished": [s for s in here if s.get("finished")],
            "claims": mine, "dirty": dirty[:40], "sid_live": sid_live}


def render_conflicts(c):
    lines = [f"repo {short(c['repo'])}:"]
    for s in c["blocking"]:
        lines.append(f"  BLOCKING: [{s['id']}] {s['agent']} {s.get('name') or ''} is {s['status']} here — {s['where'] or s['reach']}")
    for s in c["idle"]:
        lines.append(f"  idle here: [{s['id']}] {s['agent']} {s.get('name') or ''} — reach: {s['reach']}")
    for s in c["finished"]:
        lines.append(f"  finished ({s['finished']}): [{s['id']}] {s['agent']} — its pane is free to reuse")
    for cl in c["claims"]:
        lines.append(f"  claim {cl['task']} ({int(cl['age'] // 60)} min old, session {cl['session'] or '?'}): files {', '.join(cl['files']) or '(unspecified)'}")
    if c["dirty"]:
        lines.append(f"  dirty in worktree ({len(c['dirty'])}): {', '.join(c['dirty'][:12])}{' …' if len(c['dirty']) > 12 else ''}")
    for s in c["sid_live"]:
        lines.append(f"  SESSION ALREADY LIVE: [{s['id']}] in {s['where']} — never resume it a second time")
    if len(lines) == 1:
        lines.append("  nothing else works here")
    return "\n".join(lines)


# ---- output ---------------------------------------------------------------------------------

def ago(ts):
    if not ts:
        return "?"
    sec = int(time.time() - ts)
    return f"{sec // 86400}d" if sec >= 86400 else (f"{sec // 3600}h{sec % 3600 // 60:02d}m" if sec >= 3600 else f"{sec // 60}m")


def render(s):
    who = s["agent"] + (f" {s['name']}" if s["name"] else "")
    head = f"[{s['id']}] {who}  {s['status']}  {short(s['cwd'])}"
    if s["self"]:
        head += "  (this session)"
    if s["finished"]:
        head += f"  FINISHED ({s['finished']})"
    lines = [head]
    if s["title"]:
        lines.append(f"    title: {s['title']}")
    if s["where"]:
        lines.append(f"    where: {s['where']}" + (f"   focus: {s['focus']}" if s["focus"] else ""))
    lines.append(f"    reach: {s['reach']}")
    if s.get("launch") and s["launch"].get("final"):
        lines.append(f"    last: {clip(s['launch']['final'], 200)}")
    return "\n".join(lines)


def render_ended(it):
    lines = [f"[{it['id']}] {it['kind']}  {short(it['cwd'])}  updated {ago(it['updated'])} ago"]
    if it.get("title"):
        lines.append(f"    {it['title']}")
    for s in it.get("steps", []):
        lines.append(f"    - {s}")
    if it.get("question"):
        lines.append(f"    asked: {it['question']}")
    lines.append(f"    next: {it['action']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="list", choices=["list", "ended", "show", "conflicts"])
    ap.add_argument("ident", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--cwd", help="conflicts: the directory new work would run in")
    ap.add_argument("--sid", help="conflicts: a session id you intend to resume")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.cmd == "conflicts":
        c = conflicts(a.cwd or os.getcwd(), sid=a.sid)
        print(json.dumps(c, ensure_ascii=False, default=str) if a.json else render_conflicts(c))
        return 1 if (c["blocking"] or c["sid_live"]) else 0
    if a.cmd == "ended":
        items = ended_open(a.days)
        print(json.dumps(items, ensure_ascii=False) if a.json else "\n\n".join(render_ended(it) for it in items))
        return 0 if items else 1
    ss = sessions(include_shell=a.all or a.cmd == "show")
    if a.cmd == "show":
        ss = [s for s in ss if a.ident in (s["id"], s["name"], s["sid"])]
        for s in ss:
            if s.get("transcript"):
                s["tail"] = {k: v for k, v in parse(Path(s["transcript"])).items() if k != "answers"}
                s["tail"]["pending"] = [(n, clip(json.dumps(i), 200)) for _, n, i in s["tail"]["pending"]]
    if a.json:
        print(json.dumps(ss, ensure_ascii=False, default=str))
    else:
        print("\n".join(render(s) for s in ss))
        if a.cmd == "show":
            for s in ss:
                t = s.get("tail") or {}
                la = s.get("launch") or {}
                if la:
                    print(f"    acp: {la.get('turns', 0)} turn(s) · {'alive' if la.get('alive') else 'exited'} · brief: {la.get('brief')}")
                    print(f"    last reply (acp log): {clip(la.get('final', ''), 500)}")
                if t or not la:
                    print(f"    last prompt: {clip(STRIP.sub(' ', t.get('last_prompt', '')), 300)}")
                    print(f"    last reply: {clip(t.get('last_text', ''), 400)}")
                    print(f"    work stretch: {t.get('stretch_min')} min · pending: {t.get('pending')}")
    return 0 if ss else 1


if __name__ == "__main__":
    sys.exit(main())
