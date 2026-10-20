#!/usr/bin/env python3
"""Keep graft's Claude Code hook timeouts in seconds.

graft (@nanonets/graft, upstream trailhq/Graft#283, still open at 0.20.0)
writes its hook entries into ~/.claude/settings.json with timeout
8000/10000/15000. Claude Code reads `timeout` as SECONDS, so those are 2-4 hour
hook budgets. Every `graft init` rewrites graft's entries wholesale from that
template (dist/hosts/claude-global.js -> mergeGraftHooks), so a hand fix lasts
only until the next init or upgrade. That happened on 2026-09-21 and again on
2026-09-26.

Run by launchd (com.djbclark.graft-hook-timeout-fix, WatchPaths on the settings
file): on every change, any graft hook timeout above MAX_SANE seconds is reset to
the value chosen on 2026-09-21. Nothing else in the file is touched, and the file
is rewritten only when something needed fixing. The Hermes cron "Hindsight Hook
Invariants" still alerts if a bad value ever survives.

It also keeps GRAFT_NO_REFRESH=1 on the UserPromptSubmit `prompt` hook (2026-10-18).
Since graft 0.2x a query rebuilds a drifted graph inline before answering. In a big tree
that takes minutes (25+ min and 11 GB for ~/src/hermes-worktrees, whose five children are
full hermes-agent trees). The rebuild is synchronous, so the SIGTERM from the hook's
`graft ask` child timeout is not handled until it finishes. The hook then hits Claude
Code's 60 s limit and is SIGKILLed, which leaves a stale graft/.cache/.sync.lock. Raising
the timeout (20 -> 40 -> 60) never helped. With refresh off, the prompt hook answers from
the current graph; the Stop hook's background sync and the MCP tools still refresh it.

It also routes every graft hook through graft-hook-guard.sh (2026-10-18), which skips
the hook for denied project dirs (~/src/hermes-worktrees): graft's Stop hook otherwise
runs a detached `graft build .` there that splits into five full hermes-agent trees.

`strip-project DIR...` (2026-10-18) removes graft's hooks from DIR/.claude/settings.json.
`graft init` in a repo also writes project-scope copies there, as
`node "${CLAUDE_PROJECT_DIR:-.}/.claude/helpers/graft-hooks.cjs" <event>`. Claude Code runs
project hooks on top of user hooks, so every graft hook ran twice, and the project's
UserPromptSubmit `prompt` hook bypassed the guard and put the per-prompt pack back
(djbclark-ade aef5f51, 2026-10-16). graft-hook-guard.sh calls this on `session-start`, so a
re-init is undone at the next session. Only graft-hooks.cjs entries go; other hooks and keys
stay. It does nothing unless the user settings already run graft through the guard (so the
project copies are duplicates), and never in KEEP_PROJECTS. The file is usually tracked, so
the edit shows up in `git status` and gets a log line; commit it like any other change.

Remove the timeout part once graft writes seconds (check its settings-merge.js), and the
refresh part once graft's prompt hook stops rebuilding inline.
"""
import json, os, sys, tempfile, time

SETTINGS = os.path.expanduser(os.environ.get("CLAUDE_SETTINGS", "~/.claude/settings.json"))
LOG = os.path.expanduser("~/.local/state/graft-hook-timeout-fix.log")
MAX_SANE = 600
# Seconds per graft hook subcommand (2026-09-21 choice; graft's ms values /1000
# plus headroom). Unknown future subcommands get ceil(ms / 1000).
NO_REFRESH = "GRAFT_NO_REFRESH=1 "
GUARD = os.path.join(os.path.dirname(os.path.realpath(__file__)), "graft-hook-guard.sh")
SECONDS = {"prompt": 60, "post-edit": 15, "tool-savings": 12, "session-start": 12, "stop": 12}
# Repos whose project graft hooks are meant to be there: graft's own source tree ships them
# (upstream trailhq/Graft), and a stripped copy there would ride into an upstream PR.
KEEP_PROJECTS = [os.path.expanduser("~/src/Graft")]


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def fix(d):
    changes = []
    for event, matchers in (d.get("hooks") or {}).items():
        for m in matchers if isinstance(matchers, list) else []:
            for h in m.get("hooks", []) if isinstance(m, dict) else []:
                cmd, t = h.get("command", ""), h.get("timeout")
                if "graft-hooks.cjs" not in cmd:
                    continue
                sub = cmd.rstrip().split()[-1]
                if sub == "prompt" and "GRAFT_NO_REFRESH=" not in cmd:
                    h["command"] = NO_REFRESH + cmd
                    changes.append(f"{event}/{sub}: added {NO_REFRESH.strip()}")
                at = h["command"].find('node "')
                if GUARD not in h["command"] and at >= 0:
                    h["command"] = h["command"][:at] + GUARD + " " + h["command"][at:]
                    changes.append(f"{event}/{sub}: added guard")
                if not isinstance(t, (int, float)) or t <= MAX_SANE:
                    continue
                new = SECONDS.get(sub, -(-int(t) // 1000))
                h["timeout"] = new
                changes.append(f"{event}/{sub}: {t} -> {new}")
    return changes


def graft_hooks(d):
    for event, matchers in (d.get("hooks") or {}).items():
        for m in matchers if isinstance(matchers, list) else []:
            for h in m.get("hooks", []) if isinstance(m, dict) else []:
                if "graft-hooks.cjs" in h.get("command", ""):
                    yield event, h


def strip(d):
    """Drop graft-hooks.cjs entries; drop matchers, events and `hooks` left empty."""
    changes = []
    hooks = d.get("hooks")
    if not isinstance(hooks, dict):
        return changes
    for event in list(hooks):
        matchers = hooks[event]
        if not isinstance(matchers, list):
            continue
        for m in matchers:
            if not isinstance(m, dict) or not isinstance(m.get("hooks"), list):
                continue
            keep = [h for h in m["hooks"] if "graft-hooks.cjs" not in h.get("command", "")]
            for h in m["hooks"]:
                if h not in keep:
                    changes.append(f"{event}/{h['command'].rstrip().split()[-1]}: removed")
            m["hooks"] = keep
        hooks[event] = [m for m in matchers if not (isinstance(m, dict) and m.get("hooks") == [])]
        if not hooks[event]:
            del hooks[event]
    if not hooks:
        del d["hooks"]
    return changes


def update(path, fn, label):
    """Apply fn to the JSON file at path and replace it atomically if fn changed anything."""
    for attempt in range(3):
        try:
            st = os.stat(path)
            with open(path) as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            log(f"skip: cannot read/parse {path}: {e}")  # mid-write or broken: next change retriggers
            return
        changes = fn(d)
        if not changes:
            return
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".settings.", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.chmod(tmp, st.st_mode & 0o7777)
        # Don't clobber a write that landed while we were working.
        if os.stat(path).st_mtime_ns != st.st_mtime_ns:
            os.unlink(tmp)
            time.sleep(0.5)
            continue
        os.replace(tmp, path)
        log(label + "; ".join(changes))
        return
    log(f"gave up: {path} kept changing underneath")


def strip_project(dirs):
    try:
        with open(SETTINGS) as f:
            user = json.load(f)
    except (OSError, ValueError) as e:
        log(f"strip-project skip: cannot read/parse {SETTINGS}: {e}")
        return
    if not any(GUARD in h["command"] for _, h in graft_hooks(user)):
        return  # the project copies may be the only graft hooks: leave them
    for d in dirs:
        root = os.path.realpath(d)
        if any(root == os.path.realpath(k) for k in KEEP_PROJECTS):
            continue
        path = os.path.join(root, ".claude", "settings.json")
        # A session whose project dir is $HOME (~ is a working directory here, not a repo)
        # makes this path the USER settings file. Stripping that removes graft's only
        # hooks, and the GUARD precondition above then fails forever, so they never come
        # back (2026-10-18/19: it fired twice; the global wiring was off for a day).
        if os.path.realpath(path) == os.path.realpath(SETTINGS):
            continue
        if os.path.isfile(path):
            update(path, strip, f"strip-project {path}: ")


def main():
    if sys.argv[1:2] == ["strip-project"]:
        strip_project(sys.argv[2:])
    else:
        update(SETTINGS, fix, "fixed ")


if __name__ == "__main__":
    main()
