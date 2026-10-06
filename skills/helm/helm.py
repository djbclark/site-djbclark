#!/usr/bin/env python3
"""helm — one queue of every agent session that needs the operator. Runs no model.

    helm.py scan [--all] [--json]       open items (--all: every session, working ones too)
    helm.py wait [--auto-audit] [--settle S] [--timeout S] [--json]
                                        block until an item appears or changes; print only those
    helm.py show <id>                   one session in full: question, last reply, screen
    helm.py answer <id> <n>...          pick option n (1-based), one number per question
    helm.py answer <id> --text "..."    answer a single question in free text
    helm.py send <id> "<prompt>"        submit a prompt to an idle session
    helm.py audit <id>                  send /loose and remember that this session was audited
    helm.py skip <id>                   hide this item until the session changes
    helm.py keys <id> <key>...          raw keys, for a prompt helm cannot parse (read `show` first)
    helm.py brief                       one token for fleet-watch: N:project@id/mark,... (blocked sessions)

Sessions come from herdr (`herdr agent list`: state, pane, title), the Claude Code session
registry (~/.claude/sessions) and each Claude transcript's tail, where a pending
AskUserQuestion is read verbatim. Answers go back as key presses (herdr, Orca or tmux) and
are confirmed against the transcript, never assumed. State: ~/.local/state/helm (0700).
Exit: 0 ok, 1 refused or unverified, 2 usage, 3 wait timed out with nothing new.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "session-finder"))
try:
    import where as _where  # noqa: E402
except ImportError:
    _where = None

CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
STATE_DIR = Path(os.environ.get("HELM_STATE_DIR", Path.home() / ".local/state/helm"))
STATE = STATE_DIR / "state.json"
HERDR = os.environ.get("HERDR_BIN_PATH") or shutil.which("herdr") or str(Path.home() / ".local/bin/herdr")
HOME = str(Path.home())
TAIL = 600_000   # bytes of transcript read from the end
COLD = 55 * 60   # idle longer than this: the prompt cache (1 h) is gone, an audit re-reads it all
POLL = 5
REG_STATUS = {"busy": "working", "shell": "working", "waiting": "blocked", "idle": "idle"}
ATTENTION = ("question", "plan", "permission", "blocked", "idle")


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
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
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


# ---- transcripts -----------------------------------------------------------------------

_TX = {}


def transcript(sid):
    hits = list((CLAUDE / "projects").glob(f"*/{sid}.jsonl"))
    return hits[0] if hits else None


def parse(path):
    """Tail of a Claude transcript: tool calls still waiting for a result, the last reply."""
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
    last_text = last_prompt = ""
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict) or r.get("isSidechain"):
            continue
        m = r.get("message") or {}
        content, role = m.get("content"), m.get("role")
        if isinstance(content, str):
            if role == "user" and not r.get("isMeta"):
                last_prompt = content
            continue
        for b in content if isinstance(content, list) else []:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "tool_use":
                uses[b.get("id")] = (b.get("name"), b.get("input") or {})
            elif t == "tool_result":
                done.add(b.get("tool_use_id"))
                tur = r.get("toolUseResult")
                if isinstance(tur, dict) and "answers" in tur:
                    answers[b.get("tool_use_id")] = tur["answers"]
            elif t == "text" and (b.get("text") or "").strip():
                if role == "assistant":
                    last_text = b["text"]
                elif role == "user" and not r.get("isMeta"):
                    last_prompt = b["text"]
    info = {"size": st.st_size, "mtime": st.st_mtime, "last_text": last_text, "last_prompt": last_prompt,
            "pending": [(k, n, i) for k, (n, i) in uses.items() if k not in done], "answers": answers}
    _TX[path] = (key, info)
    return info


# ---- channels: how to reach a session's terminal ------------------------------------------


def screen(s, lines=30):
    kind, target = s.get("chan") or (None, None)
    if kind == "herdr":
        out = run(HERDR, "agent", "read", target, "--source", "visible", "--lines", str(lines))[1]
    elif kind == "orca":
        out = run("orca", "terminal", "read", "--terminal", target)[1]
    elif kind == "tmux":
        out = run("tmux", "capture-pane", "-p", "-t", target)[1]
    else:
        return ""
    rows = [ln.rstrip()[:160] for ln in out.splitlines() if ln.strip()]
    return "\n".join(rows[-lines:])


def send_keys(s, *keys):
    kind, target = s["chan"]
    if kind == "herdr":
        return run(HERDR, "agent", "send-keys", target, *keys)[0] == 0
    ok = True
    for k in keys:
        if kind == "orca":
            args = ["--enter"] if k == "enter" else ["--text", k]
            ok &= run("orca", "terminal", "send", "--terminal", target, *args)[0] == 0
        else:
            ok &= run("tmux", "send-keys", "-t", target, "Enter" if k == "enter" else k)[0] == 0
    return ok


def send_text(s, text):
    kind, target = s["chan"]
    if kind == "herdr":
        return run(HERDR, "pane", "send-text", target, text)[0] == 0
    if kind == "orca":
        return run("orca", "terminal", "send", "--terminal", target, "--text", text)[0] == 0
    return run("tmux", "send-keys", "-t", target, "-l", text)[0] == 0


def submit(s, text):
    kind, target = s["chan"]
    if kind == "herdr":
        return run(HERDR, "agent", "prompt", target, text, timeout=20)[0] == 0
    if kind == "orca":
        return run("orca", "terminal", "send", "--terminal", target, "--text", text, "--enter", timeout=20)[0] == 0
    return send_text(s, text) and send_keys(s, "enter")


def draft(s):
    """Text the operator has typed but not sent in a Claude Code input box, if any."""
    for ln in reversed(screen(s, 14).splitlines()):
        if ln.startswith("❯"):
            return ln[1:].strip()
    return ""


# ---- sessions --------------------------------------------------------------------------


def sessions():
    anc, mypane = ancestors(), os.environ.get("HERDR_PANE_ID")
    agents = herdr_json("agent", "list").get("agents") or []
    by_sid = {(a.get("agent_session") or {}).get("value"): a for a in agents}
    out, used = [], set()

    def from_herdr(s, a):
        s.update(chan=("herdr", a["pane_id"]), focused=bool(a.get("focused")),
                 title=a.get("terminal_title_stripped") or "", focus=f"herdr tab focus {a['tab_id']}",
                 where=f"herdr · ws {herdr_label('workspace', a['workspace_id'])} · tab {herdr_label('tab', a['tab_id'])}")
        if a["pane_id"] == mypane:
            s["self"] = True
        if a.get("agent_status") in ("idle", "working", "blocked", "done"):
            s["status"] = "idle" if a["agent_status"] == "done" else a["agent_status"]

    for f in sorted((CLAUDE / "sessions").glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        pid, sid = d.get("pid"), d.get("sessionId")
        if not sid or not alive(pid):
            continue
        s = {"id": sid[:8], "agent": "claude", "sid": sid, "name": d.get("name") or "", "cwd": d.get("cwd") or "",
             "status": REG_STATUS.get(d.get("status"), "unknown"), "self": pid in anc, "chan": None,
             "title": "", "where": "", "focus": "", "focused": False}
        a = by_sid.get(sid)
        if a:
            used.add(a["pane_id"])
            from_herdr(s, a)
        elif _where:
            w = _where.lookup(pid, d.get("procStart", "")) or {}
            env = _where.env_of(pid)
            s.update(where=w.get("where", ""), focus=w.get("focus", ""), title=w.get("title", ""))
            if env.get("ORCA_TERMINAL_HANDLE"):
                s["chan"] = ("orca", env["ORCA_TERMINAL_HANDLE"])
            elif env.get("TMUX_PANE"):
                s["chan"] = ("tmux", env["TMUX_PANE"])
        out.append(s)
    for a in agents:  # agents herdr sees that are not registered Claude sessions
        if a["pane_id"] in used:
            continue
        s = {"id": a["pane_id"], "agent": a.get("agent") or "?", "sid": None, "name": "", "cwd": a.get("cwd") or "",
             "status": "unknown", "self": False}
        from_herdr(s, a)
        out.append(s)
    return out


def classify(s, st):
    """Turn a session into a queue item. `st` is this session's saved state (mutated)."""
    it = {k: s[k] for k in ("id", "agent", "name", "title", "where", "focus", "status")}
    it.update(project=os.path.basename(s["cwd"].rstrip("/")) or "?", cwd=short(s["cwd"]), reachable=bool(s.get("chan")))
    path = transcript(s["sid"]) if s.get("sid") else None
    tx = parse(path) if path else None
    if tx:
        it["context"] = clip(tx["last_text"], 500)
    if s["status"] == "blocked":
        pend = tx["pending"] if tx else []
        asked = [p for p in pend if p[1] == "AskUserQuestion"]
        if asked:
            tid, _, inp = asked[-1]
            it.update(kind="question", fp=tid, tool_use_id=tid, questions=inp.get("questions") or [])
        elif pend:
            tid, name, inp = pend[-1]
            it.update(kind="plan" if name == "ExitPlanMode" else "permission", fp=tid, tool=name,
                      detail=clip(json.dumps(inp, ensure_ascii=False), 400), screen=screen(s, 22))
        else:
            scr = screen(s, 22)
            it.update(kind="blocked", fp=hashlib.sha1(scr.encode()).hexdigest()[:12], screen=scr)
    elif s["status"] == "idle":
        if tx:
            size = tx["size"]
            # Audited = the last thing anyone prompted here was /loose (ours or his own). A
            # /loose we just sent counts for two minutes, until the transcript shows it.
            ran = "/loose" in tx["last_prompt"][:400]
            if ran or time.time() - st.get("audit_sent", 0) > 120:
                st.pop("audit_sent", None)
            idle_for = int(time.time() - tx["mtime"])
            it.update(kind="idle", fp=f"idle:{size}", size=size, idle_for=idle_for, cold=idle_for > COLD,
                      audited=ran or "audit_sent" in st, mb=round(size / 1e6, 1))
        else:
            scr = screen(s, 12)
            it.update(kind="idle", fp="idle:" + hashlib.sha1(scr.encode()).hexdigest()[:12], idle_for=None,
                      cold=None, audited=st.get("audited_fp") == hashlib.sha1(scr.encode()).hexdigest()[:12], screen=scr)
    else:
        it.update(kind=s["status"] if s["status"] == "working" else "unknown", fp="")
    it["open"] = (it["kind"] in ATTENTION and not s["self"] and st.get("skipped") != it["fp"]
                  and not (it["kind"] == "idle" and it["audited"]))
    return it


def load():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE)


def snapshot(state):
    ss = sessions()
    items = [classify(s, state.setdefault(s["id"], {})) for s in ss]
    for gone in set(state) - {s["id"] for s in ss}:
        del state[gone]
    return ss, items


def find(ident, state):
    ss, items = snapshot(state)
    # Exact id or session name only: a prefix once matched the wrong session.
    hits = [(s, it) for s, it in zip(ss, items) if ident in (s["id"], s["name"])]
    if len(hits) != 1:
        sys.exit(f"helm: no session with id or name {ident!r}; ids: {', '.join(s['id'] for s in ss)}")
    return hits[0]


# ---- output ----------------------------------------------------------------------------


def ago(sec):
    if sec is None:
        return "?"
    return f"{sec // 3600}h{sec % 3600 // 60:02d}m" if sec >= 3600 else f"{sec // 60}m"


def heading(it):
    bits = [it["where"] or "no terminal found"]
    if it["title"]:
        bits.append(f'"{it["title"]}"')
    who = it["agent"] + (f" {it['name']}" if it["name"] else "")
    return f"[{it['id']}] {it['project']} — {' · '.join(bits)}  ({who})"


def render(it, full=False):
    out = [heading(it)]
    k = it["kind"]
    if k == "question":
        for qi, q in enumerate(it["questions"], 1):
            tag = f"QUESTION {qi}/{len(it['questions'])}" if len(it["questions"]) > 1 else "QUESTION"
            multi = " [multi-select]" if q.get("multiSelect") else ""
            out.append(f"  {tag} ({q.get('header', '')}){multi}: {q.get('question', '')}")
            for n, o in enumerate(q.get("options") or [], 1):
                desc = f" — {o['description']}" if o.get("description") else ""
                out.append(f"    {n}. {o.get('label', '')}{desc}")
        if it.get("context"):
            out.append(f"  said before asking: {it['context']}")
        how = f"helm.py answer {it['id']} <n> | --text \"...\"" if it["reachable"] else "no channel: answer in the pane"
        out.append(f"  answer: {how}")
    elif k in ("plan", "permission", "blocked"):
        label = {"plan": "PLAN APPROVAL", "permission": f"PERMISSION ({it.get('tool')})", "blocked": "BLOCKED"}[k]
        out.append(f"  {label}: {it.get('detail', 'waiting on a prompt helm cannot parse')}")
        out += ["  screen:"] + ["    | " + ln for ln in it.get("screen", "").splitlines()[-(22 if full else 12):]]
        out.append(f"  answer: helm.py keys {it['id']} <key>...   (read the screen for the choices)")
    elif k == "idle":
        state = "audited" if it["audited"] else "NOT audited"
        cold = f" · COLD cache ({it.get('mb')} MB transcript; an audit re-reads it at full price)" if it["cold"] else ""
        out.append(f"  IDLE {ago(it['idle_for'])} · {state}{cold}")
        if it.get("context"):
            out.append(f"  last reply: {it['context']}")
        if it.get("screen") and (full or not it.get("context")):
            out += ["  screen:"] + ["    | " + ln for ln in it["screen"].splitlines()[-8:]]
        if not it["audited"]:
            out.append(f"  next: helm.py audit {it['id']}  |  helm.py skip {it['id']}")
    else:
        out.append(f"  {k.upper()}")
    if it["focus"]:
        out.append(f"  focus: {it['focus']}")
    return "\n".join(out)


def emit(items, as_json, full=False):
    if as_json:
        print(json.dumps(items, ensure_ascii=False))
    else:
        print("\n\n".join(render(it, full) for it in items))


# ---- commands --------------------------------------------------------------------------


def can_audit(s, it, settle):
    """Safe to send /loose unattended: Claude, idle and settled, warm cache, not being typed into."""
    return (it["kind"] == "idle" and s["agent"] == "claude" and it["reachable"] and not it["audited"]
            and not s["self"] and not s["focused"] and it["idle_for"] is not None
            and settle <= it["idle_for"] <= COLD)


AUDIT_OTHER = "Use the loose skill: audit this session for loose ends, then step me through them."


def audit_text(s):
    return "/loose" if s["agent"] in ("claude", "hermes") else AUDIT_OTHER


def cmd_scan(a, state):
    _, items = snapshot(state)
    shown = items if a.all else [it for it in items if it["open"]]
    order = {k: i for i, k in enumerate(ATTENTION)}
    shown.sort(key=lambda it: (not it["open"], order.get(it["kind"], 9)))
    emit(shown, a.json)
    if not a.json:
        n = lambda k: sum(1 for it in items if it["kind"] == k)  # noqa: E731
        print(f"\n{sum(it['open'] for it in items)} open · {n('working')} working · "
              f"{sum(1 for it in items if it['kind'] == 'idle' and it['audited'])} idle+audited · {len(items)} sessions")


def cmd_wait(a, state):
    deadline = time.time() + a.timeout if a.timeout else None
    while True:
        state.clear()
        state.update(load())  # other helm commands (answer, skip, audit) write it meanwhile
        ss, items = snapshot(state)
        fresh, started = [], []
        for s, it in zip(ss, items):
            st = state[s["id"]]
            if a.auto_audit and can_audit(s, it, a.settle):
                if not draft(s) and submit(s, audit_text(s)):
                    st["audit_sent"] = time.time()
                    started.append(it["id"])
                    continue
            if a.auto_audit and it["kind"] == "idle" and not it["audited"] and (it["idle_for"] or 0) < a.settle:
                continue  # not settled yet; the next pass decides
            if it["open"] and st.get("seen") != it["fp"]:
                st["seen"] = it["fp"]
                fresh.append(it)
        save(state)
        if started and not a.json:
            print(f"helm: sent /loose to {', '.join(started)}", file=sys.stderr)
        if fresh:
            emit(fresh, a.json)
            return 0
        if deadline and time.time() > deadline:
            return 3
        time.sleep(POLL)


def cmd_brief(a, state):
    """Sessions blocked on the operator, as one space-free token. The mark changes with each
    new prompt, so a watcher can tell a new question from one it has already reported."""
    _, items = snapshot(state)
    safe = lambda t: "".join(c if c.isalnum() or c in "._-" else "_" for c in t)  # noqa: E731
    waiting = [f"{safe(it['project'])}@{safe(it['id'])}/{it['fp'][-6:]}"
               for it in items if it["open"] and it["kind"] != "idle"]
    print(f"{len(waiting)}:{','.join(sorted(waiting))}")


def cmd_show(a, state):
    s, it = find(a.id, state)
    it.setdefault("screen", screen(s, 22))
    emit([it], a.json, full=True)


def cmd_answer(a, state):
    s, it = find(a.id, state)
    if it["kind"] != "question":
        sys.exit(f"helm: {it['id']} has no pending question (it is {it['kind']}); nothing sent")
    if not s.get("chan"):
        sys.exit(f"helm: no channel to {it['id']}; answer in the pane ({it['focus'] or it['where']})")
    qs = it["questions"]
    if any(q.get("multiSelect") for q in qs):
        sys.exit(f"helm: multi-select prompt; answer in the pane ({it['focus']}) or drive it with `keys`")
    if a.text is not None:
        if len(qs) != 1:
            sys.exit("helm: --text answers a single question; this prompt has several")
        picks = [len(qs[0].get("options") or []) + 1]
    else:
        picks = a.choice
        if len(picks) != len(qs) or any(not 1 <= p <= len(q.get("options") or []) for p, q in zip(picks, qs)):
            sys.exit(f"helm: need one option number per question ({len(qs)}), each within range")
    probe = " ".join(qs[0].get("question", "").split())[:24]
    for _ in range(10):  # the prompt must be on screen, or the keys land in the input box
        scr = " ".join(screen(s, 40).split())
        if "to select" in scr and (probe in scr or len(qs) > 1):
            break
        time.sleep(0.5)
    else:
        sys.exit(f"helm: the question is not on {it['id']}'s screen; nothing sent")
    for i, p in enumerate(picks):
        send_keys(s, str(p))
        time.sleep(0.6)
        if a.text is not None:
            send_text(s, a.text)
            time.sleep(0.3)
            send_keys(s, "enter")
    if len(qs) > 1:  # the review tab: "Submit answers" is preselected
        if "Review your answers" not in screen(s, 40):
            sys.exit(f"helm: expected the review tab on {it['id']} and did not see it; check: {it['focus']}")
        send_keys(s, "enter")
    path = transcript(s["sid"])
    for _ in range(40):
        got = parse(path)["answers"].get(it["tool_use_id"])
        if got is not None:
            break
        time.sleep(0.5)
    else:
        sys.exit(f"helm: keys sent but no answer recorded for {it['id']} after 20 s; check: {it['focus']}")
    want = [a.text] if a.text is not None else [q["options"][p - 1]["label"] for p, q in zip(picks, qs)]
    have = [got.get(q.get("question")) for q in qs]
    for q, h in zip(qs, have):
        print(f'answered [{it["id"]}] "{clip(q.get("question"), 70)}" = "{h}"')
    if have != want:
        sys.exit(f"helm: MISMATCH, wanted {want}; the session recorded {have}")
    save(state)


def cmd_send(a, state):
    s, it = find(a.id, state)
    if s["self"]:
        sys.exit("helm: that is this session")
    if not s.get("chan"):
        sys.exit(f"helm: no channel to {it['id']} ({it['where'] or 'unknown terminal'}); use SendMessage for a Claude session")
    if it["kind"] != "idle":
        sys.exit(f"helm: {it['id']} is {it['kind']}, not idle; nothing sent")
    d = draft(s) if s["agent"] == "claude" else ""
    if d:
        sys.exit(f"helm: {it['id']} has an unsent draft in its input box ({clip(d, 60)!r}); nothing sent")
    text = audit_text(s) if a.prompt is None else a.prompt
    if not submit(s, text):
        sys.exit(f"helm: could not submit to {it['id']}")
    if a.prompt is None:
        st = state[s["id"]]
        if "size" in it:
            st["audit_sent"] = time.time()
        else:
            st["audited_fp"] = it["fp"].split(":", 1)[1]
    save(state)
    print(f"sent to [{it['id']}] {it['project']}: {clip(text, 80)}")


def cmd_skip(a, state):
    _, it = find(a.id, state)
    state[it["id"]]["skipped"] = it["fp"]
    save(state)
    print(f"skipped [{it['id']}] until it changes")


def cmd_keys(a, state):
    s, it = find(a.id, state)
    if it["kind"] not in ("question", "plan", "permission", "blocked"):
        sys.exit(f"helm: {it['id']} is {it['kind']}, not waiting on a prompt; nothing sent")
    if not s.get("chan"):
        sys.exit(f"helm: no channel to {it['id']}")
    send_keys(s, *a.key)
    time.sleep(1.5)
    print(f"sent {' '.join(a.key)} to [{it['id']}]; screen now:")
    print("\n".join("  | " + ln for ln in screen(s, 14).splitlines()))


def main():
    ap = argparse.ArgumentParser(prog="helm.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan")
    p.add_argument("--all", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_scan)
    p = sub.add_parser("wait")
    p.add_argument("--auto-audit", action="store_true")
    p.add_argument("--settle", type=int, default=180)
    p.add_argument("--timeout", type=int, default=0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_wait)
    sub.add_parser("brief").set_defaults(fn=cmd_brief)
    p = sub.add_parser("show")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_show)
    p = sub.add_parser("answer")
    p.add_argument("id")
    p.add_argument("choice", nargs="*", type=int)
    p.add_argument("--text")
    p.set_defaults(fn=cmd_answer)
    p = sub.add_parser("send")
    p.add_argument("id")
    p.add_argument("prompt")
    p.set_defaults(fn=cmd_send)
    p = sub.add_parser("audit")
    p.add_argument("id")
    p.set_defaults(fn=cmd_send, prompt=None)
    p = sub.add_parser("skip")
    p.add_argument("id")
    p.set_defaults(fn=cmd_skip)
    p = sub.add_parser("keys")
    p.add_argument("id")
    p.add_argument("key", nargs="+")
    p.set_defaults(fn=cmd_keys)
    a = ap.parse_args()
    state = load()
    rc = a.fn(a, state)
    if a.cmd in ("scan", "show"):
        save(state)
    return rc or 0


if __name__ == "__main__":
    sys.exit(main())
