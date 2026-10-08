#!/usr/bin/env python3
"""launch — start an agent session over ACP, hosted where the operator can see it. No model.

    launch.py --agent A --cwd DIR (-p TEXT | -f FILE) [--model M] [--name NAME] [--baton [--chain ID|PATH]]
              [--pane PANE] [--host auto|herdr|orca|none] [--timeout S] [--perm P] [--set K=V]... [--dry-run] [--json]
    launch.py reply <id> "<text>"     next prompt: into the live session's inbox when it is interactive (acp-run
                                      --interactive keeps the ACP session open), else a new acp-run turn with the
                                      brief and the last reply as context
    launch.py audit <id>              send /loose (or the loose-skill text) as the session's next turn
    launch.py list [--json]           every launch and its state
    launch.py close <id> [--keep-pane] /exit a live session, mark it closed, close its herdr tab or pane

Route (djbclark 2026-10-08: "use ACP if possible … other methods have proven to be fragile"):
  1. The agent is driven over ACP by acp-run (typed permissions, exit codes, JSONL log). The call runs
     inside a visible terminal so it is a session the operator can look at: an Orca terminal when this
     runs from Orca, else a herdr tab in the workspace that already holds that repo (a new workspace
     when none fits), else detached with no terminal. The pane is reported to herdr as an agent
     (`pane report-agent`, source session-finder) so helm and fleet list it like any other.
  2. Agents with no ACP route (zcode, crush, muse) get `herdr agent start --kind` + `agent prompt`.
  --pane: host in that herdr pane. If a finished Claude session still sits there idle, it is sent /exit
  first (what herdr-sleeper does); a pane with a draft in its input box is refused.
  --baton: the brief tells the session to follow the baton skill from the named Tier 1 chain
  (resolved from --chain, else the chain whose workspace is DIR), then do the instruction.
State: ~/.local/state/session-finder/launches.jsonl and launch-<id>/ (brief, log, out, runner).
Exit: 0 started, 1 refused or failed, 2 usage.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fleet  # noqa: E402

ACP_RUN = os.environ.get("ACP_RUN") or shutil.which("acp-run") or str(Path.home() / "ops/site-private/bin/acp-run")
ACP_AGENTS = {"claude", "codex", "copilot", "opencode", "cursor", "qwen", "cline", "hermes", "agy", "devin"}
HERDR_KINDS = {"claude", "codex", "cursor", "opencode", "copilot", "qwen", "cline", "hermes", "agy", "muse", "grok", "devin"}
EXCLUDED = {"grok"}   # operator exclusion 2026-10-06 (bigteam: Current exclusions)
SKILLS = Path.home() / "ops/site-private/skills"
STATE = fleet.STATE_DIR
HERDR = fleet.HERDR


def die(msg, rc=1):
    print(f"launch: {msg}", file=sys.stderr)
    sys.exit(rc)


_ACP_I = {}


def acp_interactive():
    """Does the installed acp-run have --interactive (added 2026-10-08)?"""
    if "v" not in _ACP_I:
        try:
            _ACP_I["v"] = "--interactive" in Path(ACP_RUN).read_text(errors="replace")[:6000]
        except OSError:
            _ACP_I["v"] = False
    return _ACP_I["v"]


def inbox_send(d, text):
    """Hand TEXT to a live interactive session as its next prompt (no keys, no new process)."""
    inbox = Path(d.get("inbox") or "")
    if not inbox.is_dir():
        return False
    tmp = inbox / f".{int(time.time() * 1000)}.tmp"
    tmp.write_text(text if text.endswith("\n") else text + "\n")
    tmp.rename(inbox / f"{int(time.time() * 1000)}.txt")
    return True


AUDIT = {"claude": "/loose", "hermes": "/loose"}
AUDIT_OTHER = "Use the loose skill: audit this session for loose ends, then step me through them."


def new_id(agent):
    return time.strftime("%Y%m%d-%H%M%S") + f"-{agent}-{os.getpid() % 10000:04d}"


def record(d):
    STATE.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE, 0o700)
    with fleet.LAUNCHES.open("a") as fh:
        fh.write(json.dumps(d, ensure_ascii=False) + "\n")


# ---- chains (for --baton) -------------------------------------------------------------------

def find_chain(cwd, want=None):
    top = fleet.toplevel(cwd)
    if want:
        p = Path(want)
        if p.is_file():
            return p
        p = fleet.HANDOFFS / "chains" / want / "SESSION_LOG.md"
        if p.is_file():
            return p
        die(f"no chain {want!r} under {fleet.HANDOFFS / 'chains'}")
    hits = [c for c in fleet._chain_logs(days=120) if top in {fleet.toplevel(d) for d in c["dirs"]}]
    if not hits:
        hits = [c for c in fleet._chain_logs(days=120) if any(d.startswith(top + "/") or top.startswith(d.rstrip("/") + "/")
                                                                for d in c["dirs"])]
    if not hits:
        die(f"no handoff chain lists {top}; pass --chain <id|path> (fleet.py ended lists candidates)")
    hits.sort(key=lambda c: -c["updated"])
    if len(hits) > 1 and hits[0]["updated"] - hits[1]["updated"] < 3600:
        print("launch: several chains for this directory, taking the newest: " +
              ", ".join(f"{c['chain']} ({fleet.ago(c['updated'])} ago)" for c in hits[:4]), file=sys.stderr)
    return Path(hits[0]["path"])


def baton_brief(cwd, chain_path, instruction, model=None):
    chain = chain_path.parent.name
    return f"""You are a fresh session that session-finder's launcher started in {cwd}, to continue work a previous session handed off. Work unattended: do not wait for confirmation on anything you can decide yourself.

1. Follow the `baton` skill ({SKILLS}/baton/SKILL.md -> `resume` -> the `session-handoff` skill's Reader protocol). If the Skill tool is not available to you, read those three SKILL.md files directly. Your Tier 1 canonical log is {chain_path} (chain {chain}): read it first, then the Tier 2 handoff it names in `latest_handoff` (under ~/ops/site-private/memory/handoffs/), then run the staleness check against the real HEAD of each workspace it lists. State the resume plan in one short paragraph and continue; do not ask the operator for anything the log already answers.
2. Then do this: {instruction}
3. Rules: read the repo's AGENTS.md first and follow it. This is a shared checkout: stage by path, never `git add -A`; commit small and push when the repo's rules say so. Do not start other agents or sessions. Work through blockers yourself (search the web before trial and error); only stop for a decision that is genuinely the operator's.
4. End your reply with one of `DONE: <what changed, commit shas>` or `BLOCKED: <what you need>`, and update the Tier 1 log through the session-handoff Writer protocol before you finish.
"""


# ---- hosts ----------------------------------------------------------------------------------

def herdr_up():
    return bool(fleet.herdr_json("workspace", "list"))


def pane_shell_ready(pane, tries=12):
    """True once the pane shows a shell prompt on its last line."""
    for _ in range(tries):
        out = fleet.run(HERDR, "pane", "read", pane, "--source", "visible", "--lines", "6")[1]
        last = next((ln.rstrip() for ln in reversed(out.splitlines()) if ln.strip()), "")
        if re.search(r"(\$|%|❯|>)\s*$", last) and "Resume this session" not in last:
            return True
        time.sleep(1)
    return False


def pane_draft(pane):
    out = fleet.run(HERDR, "pane", "read", pane, "--source", "visible", "--lines", "14")[1]
    for ln in reversed(out.splitlines()):
        if ln.startswith("❯"):
            return ln[1:].strip()
    return ""


def pane_exists(pane):
    return bool(fleet.herdr_json("pane", "get", pane).get("pane"))


def free_pane(pane):
    """Make sure PANE is at a shell prompt: a finished agent there is asked to /exit first."""
    a = fleet.herdr_json("agent", "get", pane).get("agent") or {}
    if a.get("agent"):
        if a.get("agent_status") not in ("idle", "done", None):
            die(f"pane {pane} runs a {a['agent']} agent that is {a.get('agent_status')}; not touching it")
        if pane_draft(pane):
            die(f"pane {pane} has an unsent draft in its input box; not touching it")
        if fleet.run(HERDR, "agent", "prompt", pane, "/exit", timeout=20)[0] != 0:
            die(f"could not send /exit to the agent in {pane}")
        time.sleep(2)
    if not pane_shell_ready(pane):
        die(f"pane {pane} did not reach a shell prompt")


def pick_workspace(cwd):
    top = fleet.toplevel(cwd)
    panes = fleet.herdr_json("pane", "list").get("panes") or []
    score = {}
    for p in panes:
        if p.get("cwd") and fleet.toplevel(p["cwd"]) == top:
            score[p["workspace_id"]] = score.get(p["workspace_id"], 0) + 1
    if score:
        return max(score, key=score.get), False
    for w in fleet.herdr_json("workspace", "list").get("workspaces") or []:
        if (w.get("label") or "").lower() == os.path.basename(top).lower() and w.get("workspace_id"):
            return w["workspace_id"], False
    if os.environ.get("HERDR_WORKSPACE_ID"):
        return os.environ["HERDR_WORKSPACE_ID"], False
    r = fleet.herdr_json("workspace", "create", "--cwd", cwd, "--label", os.path.basename(top), "--no-focus")
    wid = (r.get("workspace") or {}).get("workspace_id") or r.get("workspace_id")
    if not wid:
        die("could not create a herdr workspace")
    return wid, True


def new_herdr_pane(cwd, name, wid):
    r = fleet.herdr_json("tab", "create", "--workspace", wid, "--cwd", cwd, "--label", name[:24], "--no-focus")
    tab = (r.get("tab") or {}).get("tab_id") or r.get("tab_id")
    pane = (r.get("pane") or {}).get("pane_id") or r.get("pane_id")
    if tab and not pane:
        for _ in range(10):
            for p in fleet.herdr_json("pane", "list", "--workspace", wid).get("panes") or []:
                if p.get("tab_id") == tab:
                    pane = p["pane_id"]
            if pane:
                break
            time.sleep(0.5)
    if not pane:
        die(f"herdr tab create returned no pane: {json.dumps(r)[:300]}")
    if not pane_shell_ready(pane):
        die(f"new pane {pane} never showed a shell prompt")
    return pane, tab


def pane_tab(pane):
    p = fleet.herdr_json("pane", "get", pane).get("pane") or {}
    return p.get("tab_id", ""), p.get("workspace_id", "")


def report(pane, agent, state, lid, name="", message=""):
    args = [HERDR, "pane", "report-agent", pane, "--source", "session-finder", "--agent", agent, "--state", state,
            "--agent-session-id", lid]
    if message:
        args += ["--message", message]
    fleet.run(*args)
    if name:
        fleet.run(HERDR, "pane", "report-metadata", pane, "--source", "session-finder", "--title", name[:60],
                  "--display-agent", f"{agent} (acp)")


# ---- the run ---------------------------------------------------------------------------------

def runner_script(d, acp_cmd, pane=None):
    """A bash script the host runs: acp-run in the foreground, exit status kept, state reported."""
    q = lambda s: "'" + str(s).replace("'", "'\\''") + "'"  # noqa: E731
    lines = ["#!/usr/bin/env bash", "set -o pipefail", f"echo 'launch {d['id']}: {d['agent']} in {d['cwd']} (acp)'"]
    if pane:
        lines.append(f"{q(HERDR)} pane report-agent {q(pane)} --source session-finder --agent {q(d['agent'])} "
                     f"--state working --agent-session-id {q(d['id'])} >/dev/null 2>&1")
    # PYTHONUNBUFFERED: stdout is a pipe (tee), and the pane must show the agent as it streams
    lines.append("PYTHONUNBUFFERED=1 " + " ".join(q(c) for c in acp_cmd) + f" 2> >(tee {q(d['err'])} >&2) | tee {q(d['out'])}")
    lines.append("rc=${PIPESTATUS[0]}")
    lines.append(f"printf '%s\\n' \"{{\\\"id\\\": \\\"{d['id']}\\\", \\\"exit\\\": $rc, \\\"ended\\\": $(date +%s)}}\" >> {q(fleet.LAUNCHES)}")
    if d.get("claim"):
        lines.append(f"printf 'DONE %s\\n' \"$(date +%Y-%m-%dT%H:%M:%S)\" >> {q(d['claim'])}")
    if pane:
        lines.append(f"{q(HERDR)} pane report-agent {q(pane)} --source session-finder --agent {q(d['agent'])} "
                     f"--state idle --agent-session-id {q(d['id'])} --message \"exit $rc\" >/dev/null 2>&1")
    lines.append(f"echo \"launch {d['id']} exit=$rc  log: {d['log']}\"")
    return "\n".join(lines) + "\n"


def start(a, brief_text, parent=None):
    agent = a.agent
    if agent in EXCLUDED:
        die(f"{agent} is excluded by operator rule (bigteam: Current exclusions)")
    cwd = str(Path(a.cwd).expanduser().resolve())
    if not Path(cwd).is_dir():
        die(f"no such directory {cwd}")
    lid = new_id(agent)
    # conflicts (operator 2026-10-08: never collide with another session's work)
    c = fleet.conflicts(cwd)
    if c["blocking"] and not a.force:
        die("another session is working in this repo; message it instead (session-finder) or pass --force:\n"
            + fleet.render_conflicts(c))
    own = []
    if parent:
        # a reply turn: files the parent launch (this chain) modified since it started are its own work
        pd = next((x for x in fleet.launches() if x["id"] == parent), None)
        if pd:
            root = c["repo"]
            for f in list(c["dirty"]):
                try:
                    if os.path.getmtime(os.path.join(root, f)) >= pd.get("ts", 0):
                        own.append(f)
                        c["dirty"].remove(f)
                except OSError:
                    pass
    guard = ""
    if own:
        guard += f"\n\nFiles your previous turn(s) left modified or staged — yours to finish: {', '.join(own)}."
    if c["dirty"] or c["claims"] or c["idle"]:
        guard += "\n\nOther sessions share this checkout. " + (
            f"Files already modified in the worktree belong to someone else — read them, never edit, stage or revert them: "
            f"{', '.join(c['dirty'])}. " if c["dirty"] else "") + (
            "Files owned by live bigteam claims are off limits: " + "; ".join(
                f"{cl['task']}: {', '.join(cl['files']) or 'unspecified'}" for cl in c["claims"]) + ". " if c["claims"] else "") + (
            "Idle sessions here: " + ", ".join(f"{s['agent']} {s.get('name') or s['id']}" for s in c["idle"]) +
            " — if your task overlaps theirs, stop and say so rather than duplicating it. " if c["idle"] else "") + \
            "Stage by path and commit only what you changed."
        brief_text += guard
    d = {"id": lid, "ts": time.time(), "agent": agent, "cwd": cwd, "name": a.name or os.path.basename(cwd),
         "model": a.model, "parent": parent, "chain": getattr(a, "_chain", None),
         "claim": None if a.dry_run else fleet.write_claim(f"sf-{lid}", f"launch {lid}", c["repo"], a.files or [],
                                                           f"brief: {a.name or ''}")}
    ldir = STATE / f"launch-{lid}"
    ldir.mkdir(parents=True, exist_ok=True)
    d.update(brief=str(ldir / "brief.md"), log=str(ldir / "acp.jsonl"), out=str(ldir / "out.txt"),
             err=str(ldir / "err.txt"), runner=str(ldir / "run.sh"), prompt_head=" ".join(brief_text.split())[:200])
    Path(d["brief"]).write_text(brief_text)

    host = a.host
    if host == "auto":
        host = "orca" if os.environ.get("ORCA_TERMINAL_HANDLE") or os.environ.get("TERM_PROGRAM") == "Orca" else (
            "herdr" if herdr_up() else "none")
    if agent not in ACP_AGENTS:
        return start_tui(a, d, brief_text, host)

    acp_cmd = [ACP_RUN, agent, "-C", cwd, "-f", d["brief"], "--timeout", str(a.timeout), "--log", d["log"]]
    if getattr(a, "resume", None):
        acp_cmd += ["--resume", a.resume]   # session/load: the agent replays its own history
        d["resumed"] = a.resume
    if getattr(a, "interactive", True) and acp_interactive():
        # the pane shows the agent live and takes the next prompt from the keyboard or the inbox
        d["interactive"], d["inbox"] = True, str(ldir / "inbox")
        Path(d["inbox"]).mkdir(exist_ok=True)
        acp_cmd += ["--interactive", "--inbox", d["inbox"]]
    if a.model:
        acp_cmd += ["--model", a.model]
    if a.perm:
        acp_cmd += ["--perm", a.perm]
    for kv in a.set or []:
        acp_cmd += ["--set", kv]
    if not a.model:
        print("launch: no --model; acp-run will use the agent's default (for claude that is the expensive settings model)",
              file=sys.stderr)

    pane = tab = None
    if host == "herdr":
        if a.pane and not pane_exists(a.pane):
            print(f"launch: pane {a.pane} is gone; opening a new tab instead", file=sys.stderr)
            a.pane = None
        if a.pane:
            free_pane(a.pane)
            pane = a.pane
            tab, wid = pane_tab(pane)
        elif a.dry_run:
            wid, created = pick_workspace(cwd) if not a.dry_run else (os.environ.get("HERDR_WORKSPACE_ID", "?"), False)
            pane, tab = "(new pane)", "(new tab)"
        else:
            wid, created = pick_workspace(cwd)
            pane, tab = new_herdr_pane(cwd, d["name"], wid)
        d["host"] = {"kind": "herdr", "pane": pane, "tab": tab, "workspace": wid}
    elif host == "orca":
        d["host"] = {"kind": "orca"}
    else:
        d["host"] = {"kind": "none"}
    Path(d["runner"]).write_text(runner_script(d, acp_cmd, None if a.dry_run else pane))
    os.chmod(d["runner"], 0o700)
    if a.dry_run:
        print(json.dumps({**d, "acp_cmd": acp_cmd, "dry_run": "no tab, claim or record was created"}, indent=1))
        return d
    record(d)

    if host == "herdr":
        report(pane, agent, "working", lid, d["name"])
        rc, out = fleet.run(HERDR, "pane", "run", pane, "bash", d["runner"], timeout=20)
        if rc != 0 or '"error"' in out:
            die(f"herdr pane run failed: {out[:300]}")
    elif host == "orca":
        rc, out = fleet.run("orca", "terminal", "create", "--worktree", f"path:{cwd}", "--title", d["name"][:40],
                            "--command", f"bash {d['runner']}", "--json", timeout=30)
        try:
            handle = json.loads(out).get("terminal", {}).get("handle") or json.loads(out).get("handle")
        except ValueError:
            handle = None
        if rc != 0 or not handle:
            die(f"orca terminal create failed: {out[:300]}")
        d["host"]["terminal"] = handle
        record({"id": lid, "host": d["host"]})
    else:
        p = subprocess.Popen(["bash", d["runner"]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        record({"id": lid, "pid": p.pid})
    return d


def start_tui(a, d, brief_text, host):
    """No ACP route: an interactive TUI in a herdr pane, prompted by key presses (the fragile way)."""
    if host != "herdr" or a.agent not in HERDR_KINDS:
        die(f"{a.agent} has no ACP route and no herdr kind; run it by hand: see model-routing's headless table")
    if a.pane:
        free_pane(a.pane)
        pane, (tab, wid) = a.pane, pane_tab(a.pane)
    else:
        wid, _ = pick_workspace(d["cwd"])
        pane, tab = new_herdr_pane(d["cwd"], d["name"], wid)
    d["host"] = {"kind": "herdr-tui", "pane": pane, "tab": tab, "workspace": wid}
    if a.dry_run:
        print(json.dumps(d, indent=1))
        return d
    record(d)
    args = [HERDR, "agent", "start", f"sf-{d['id'][-8:]}", "--kind", a.agent, "--pane", pane, "--timeout", "60000"]
    rc, out = fleet.run(*args, timeout=70)
    if rc != 0 or '"error"' in out:
        die(f"herdr agent start failed: {out[:300]}")
    rc, out = fleet.run(HERDR, "agent", "prompt", pane, brief_text, timeout=30)
    if rc != 0 or '"error"' in out:
        die(f"herdr agent prompt failed: {out[:300]}")
    print(f"started {a.agent} TUI in {pane} (herdr tab focus {tab}); prompt submitted by keys, verify in the pane")
    return d


# ---- commands --------------------------------------------------------------------------------

def cmd_start(a):
    if a.prompt is None and a.prompt_file is None:
        die("give -p TEXT or -f FILE", 2)
    text = a.prompt if a.prompt is not None else Path(a.prompt_file).read_text()
    if a.baton:
        chain = find_chain(a.cwd, a.chain)
        a._chain = str(chain)
        text = baton_brief(str(Path(a.cwd).expanduser().resolve()), chain, text.strip(), a.model)
    d = start(a, text)
    if a.dry_run:
        return 0
    h = d["host"]
    where = {"herdr": f"herdr tab focus {h.get('tab')}", "herdr-tui": f"herdr tab focus {h.get('tab')}",
             "orca": f"orca terminal switch --terminal {h.get('terminal')}", "none": "no terminal"}[h["kind"]]
    msg = {"id": d["id"], "agent": d["agent"], "cwd": d["cwd"], "name": d["name"], "model": d["model"], "host": h,
           "focus": where, "log": d["log"], "brief": d["brief"], "chain": d.get("chain")}
    print(json.dumps(msg) if a.json else
          f"started {d['id']}: {d['agent']} in {fleet.short(d['cwd'])} as \"{d['name']}\"\n  focus: {where}\n  log: {d['log']}\n"
          f"  watch: fleet.py show {d['id']}   (helm lists it when it stops or asks)")
    return 0


def cmd_reply(a):
    old = next((d for d in fleet.launches() if d["id"] == a.id), None)
    if not old:
        die(f"no launch {a.id}")
    status, final, result = fleet.launch_state(old)
    if old.get("interactive") and result is None:
        # the session is alive: queue the prompt in its inbox (acp-run picks it up when idle)
        if not inbox_send(old, a.text):
            die(f"{a.id} is interactive but its inbox {old.get('inbox')} is gone")
        print(f"queued for [{a.id}] ({'now' if status != 'working' else 'after its current turn'}): {fleet.clip(a.text, 80)}")
        return 0
    if status == "working":
        die(f"{a.id} is still working; wait for its result first")
    resume = old.get("acp_session") if old.get("load_session") and acp_interactive() else None
    if resume:
        text = a.text        # session/load brings the whole conversation back; just the new prompt
    else:
        brief = Path(old["brief"]).read_text() if Path(old.get("brief", "")).exists() else old.get("prompt_head", "")
        text = (f"This continues an earlier turn in {old['cwd']}. The brief for that turn was:\n\n{brief}\n\n"
                f"Your reply to it ended:\n\n{final[-3000:]}\n\nThe operator now says: {a.text}\n\n"
                "Continue from there; re-read the files you changed before editing them again.")
    ns = argparse.Namespace(agent=old["agent"], cwd=old["cwd"], model=a.model or old.get("model"), name=old.get("name"),
                            resume=resume,
                            host=a.host, pane=(old.get("host") or {}).get("pane") if a.host == "herdr" or a.host == "auto" else None,
                            timeout=a.timeout, perm=a.perm, set=a.set, dry_run=a.dry_run, json=a.json, prompt=None,
                            prompt_file=None, baton=False, chain=None, files=old.get("files") or [], force=True)
    if ns.pane:
        ag = fleet.herdr_json("agent", "get", ns.pane).get("agent") or {}
        if (ag.get("agent_status") or "idle") not in ("idle", "done"):
            ns.pane = None   # busy pane: open a new tab instead
    d = start(ns, text, parent=a.id)
    if not a.dry_run:
        record({"id": a.id, "closed": True, "superseded_by": d["id"]})
        if resume:
            record({"id": d["id"], "audited_turn": old.get("audited_turn")} if old.get("audited_turn") is not None else {"id": d["id"]})
        print(f"started {d['id']} as the next turn of {a.id} ({'session/load of ' + resume[:8] if resume else 'new ACP session'}; "
              f"focus: herdr tab focus {(d['host'] or {}).get('tab', '?')})")
    return 0


def cmd_list(a):
    rows = []
    for d in fleet.launches():
        status, final, result = fleet.launch_state(d)
        rows.append({"id": d["id"], "agent": d.get("agent"), "cwd": fleet.short(d.get("cwd", "")), "name": d.get("name"),
                     "status": "closed" if d.get("closed") else status, "exit": (result or {}).get("exit", d.get("exit")),
                     "host": d.get("host"), "last": fleet.clip(final, 160), "ts": d.get("ts")})
    if a.json:
        print(json.dumps(rows, ensure_ascii=False))
    else:
        for r in rows:
            print(f"[{r['id']}] {r['agent']} {r['status']}  {r['cwd']}  \"{r['name']}\"  exit={r['exit']}")
            if r["last"]:
                print(f"    last: {r['last']}")
    return 0 if rows else 1


def cmd_audit(a):
    """Send the loose-ends audit as the session's next turn (operator 2026-10-08: /loose on the
    ACP window when done, then close it)."""
    d = next((x for x in fleet.launches() if x["id"] == a.id), None)
    if not d:
        die(f"no launch {a.id}")
    status, final, result = fleet.launch_state(d)
    if d.get("closed"):
        die(f"{a.id} is closed")
    text = AUDIT.get(d.get("agent"), AUDIT_OTHER)
    if d.get("interactive") and result is None:
        if not inbox_send(d, text):
            die("inbox gone")
        record({"id": a.id, "audited_turn": d.get("turns", 0), "audit_sent": time.time()})
        print(f"audit queued for [{a.id}] as turn {d.get('turns', 0) + 1}")
        return 0
    if status == "working":
        die(f"{a.id} is still working")
    record({"id": a.id, "audited_turn": d.get("turns", 0), "audit_sent": time.time()})
    ns = argparse.Namespace(id=a.id, text=text, model=None, host="auto", timeout=1800, perm=None, set=None,
                            dry_run=False, json=False)
    return cmd_reply(ns)


def cmd_close(a):
    """Mark closed and, by default, close the herdr tab that hosted it so tabs do not pile up.
    A live interactive session is asked to /exit first; a working one is refused unless --force."""
    d = next((x for x in fleet.launches() if x["id"] == a.id), None)
    if not d:
        die(f"no launch {a.id}")
    status, final, result = fleet.launch_state(d)
    host = d.get("host") or {}
    if status == "working" and result is None and not a.force:
        die(f"{a.id} is still working; wait, or --force")
    if d.get("interactive") and result is None and d.get("exit") is None:
        inbox_send(d, "/exit")
        for _ in range(30):
            time.sleep(1)
            if any(x.get("exit") is not None for x in fleet.launches() if x["id"] == a.id):
                break
    record({"id": a.id, "closed": True, "closed_at": time.time()})
    if host.get("kind") in ("herdr", "herdr-tui") and host.get("pane") and not a.keep_pane:
        if pane_exists(host["pane"]):
            ag = fleet.herdr_json("agent", "get", host["pane"]).get("agent") or {}
            if ag.get("agent") and ag.get("agent_status") == "working" and not a.force:
                die(f"closed {a.id} but pane {host['pane']} still runs a working {ag['agent']}; not closing it")
            tab = host.get("tab")
            panes = [p for p in (fleet.herdr_json("pane", "list").get("panes") or []) if p.get("tab_id") == tab]
            if tab and len(panes) == 1:
                fleet.run(HERDR, "tab", "close", tab)
            else:
                fleet.run(HERDR, "pane", "close", host["pane"])
            print(f"closed {a.id} and its herdr {'tab ' + tab if tab and len(panes) == 1 else 'pane ' + host['pane']}")
            return 0
    print(f"closed {a.id}")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="launch.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--model")
        p.add_argument("--host", choices=["auto", "herdr", "orca", "none"], default="auto")
        p.add_argument("--timeout", type=int, default=14400,
                       help="seconds per turn (default 4 h: a 1 h limit cut a real deploy short on 2026-10-08)")
        p.add_argument("--perm")
        p.add_argument("--set", action="append")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("start")
    p.add_argument("--agent", required=True)
    p.add_argument("--cwd", required=True)
    p.add_argument("-p", "--prompt")
    p.add_argument("-f", "--prompt-file")
    p.add_argument("--name")
    p.add_argument("--baton", action="store_true")
    p.add_argument("--chain")
    p.add_argument("--pane")
    p.add_argument("--files", nargs="*", help="paths this session will own (written to its bigteam claim)")
    p.add_argument("--force", action="store_true", help="start even though another session works in that repo")
    p.add_argument("--no-interactive", dest="interactive", action="store_false",
                   help="one turn and exit (default: keep the ACP session open; the pane shows it and takes input)")
    common(p)
    p.set_defaults(fn=cmd_start)
    p = sub.add_parser("reply")
    p.add_argument("id")
    p.add_argument("text")
    common(p)
    p.set_defaults(fn=cmd_reply)
    p = sub.add_parser("list")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("audit")
    p.add_argument("id")
    p.set_defaults(fn=cmd_audit)
    p = sub.add_parser("close")
    p.add_argument("id")
    p.add_argument("--keep-pane", action="store_true", help="mark closed but leave the herdr tab/pane")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_close)
    argv = sys.argv[1:]
    if argv and argv[0].startswith("-"):
        argv = ["start"] + argv     # `launch.py --agent …` is the common form
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_usage(sys.stderr)
        return 2
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
