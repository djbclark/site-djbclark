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

Remove this agent once graft writes seconds (check its settings-merge.js).
"""
import json, os, tempfile, time

SETTINGS = os.path.expanduser(os.environ.get("CLAUDE_SETTINGS", "~/.claude/settings.json"))
LOG = os.path.expanduser("~/.local/state/graft-hook-timeout-fix.log")
MAX_SANE = 600
# Seconds per graft hook subcommand (2026-09-21 choice; graft's ms values /1000
# plus headroom). Unknown future subcommands get ceil(ms / 1000).
SECONDS = {"prompt": 60, "post-edit": 15, "tool-savings": 12, "session-start": 12, "stop": 12}


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
                if "graft-hooks.cjs" not in cmd or not isinstance(t, (int, float)) or t <= MAX_SANE:
                    continue
                sub = cmd.rstrip().split()[-1]
                new = SECONDS.get(sub, -(-int(t) // 1000))
                h["timeout"] = new
                changes.append(f"{event}/{sub}: {t} -> {new}")
    return changes


def main():
    for attempt in range(3):
        try:
            st = os.stat(SETTINGS)
            with open(SETTINGS) as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            log(f"skip: cannot read/parse {SETTINGS}: {e}")  # mid-write or broken: next change retriggers
            return
        changes = fix(d)
        if not changes:
            return
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(SETTINGS), prefix=".settings.", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.chmod(tmp, st.st_mode & 0o7777)
        # Don't clobber a write that landed while we were working.
        if os.stat(SETTINGS).st_mtime_ns != st.st_mtime_ns:
            os.unlink(tmp)
            time.sleep(0.5)
            continue
        os.replace(tmp, SETTINGS)
        log("fixed " + "; ".join(changes))
        return
    log("gave up: settings.json kept changing underneath")


if __name__ == "__main__":
    main()
