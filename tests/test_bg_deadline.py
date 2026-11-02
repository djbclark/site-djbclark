"""bin/bg's deadline records (2026-11-02): the run record exists only for a run that started, and both carry a --holder.

A gate-refused bg must leave no `bg-run-*` record (the sweep would otherwise announce "expired, recover" for work that never ran);
a started run registers `bg-run-PID-T` from its detached watcher with `--holder` = the watcher's pid, never bg's own. The real
`deadline` is replaced by a stand-in that appends its argv to a log; DEADLINE_STATE_DIR points at a temp dir so nothing can reach
the live ~/.local/state/deadlines. A throwaway HOME holds a stub load-watch (bg takes it from $HOME/src/djbclark-ade/bin) and a
BASH_ENV file makes `sleep` cost 0.2 s at most.
"""

import os
import shlex
import subprocess
import time
from pathlib import Path

BG = Path(__file__).resolve().parent.parent / "bin" / "bg"

LOAD_WATCH = """#!/bin/bash
case "$1" in
  ci) printf 'local\\t\\t\\n' ;;
  admit) exit {admit_rc} ;;
esac
exit 0
"""

STAND_IN = """#!/bin/bash
printf '%s\\n' "$*" >> {log}
exit 0
"""


def setup(tmp_path, admit_rc):
    home, work, state = tmp_path / "home", tmp_path / "work", tmp_path / "dlstate"
    lw = home / "src" / "djbclark-ade" / "bin" / "load-watch"
    for d in (lw.parent, work, state):
        d.mkdir(parents=True)
    lw.write_text(LOAD_WATCH.format(admit_rc=admit_rc))
    lw.chmod(0o755)
    log = tmp_path / "deadline.calls"
    standin = tmp_path / "deadline-standin"
    standin.write_text(STAND_IN.format(log=shlex.quote(str(log))))
    standin.chmod(0o755)
    shim = tmp_path / "sleep-shim.sh"
    shim.write_text('sleep() { command sleep 0.2; }\n')
    env = {
        **os.environ,
        "HOME": str(home),
        "BASH_ENV": str(shim),
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
        "BG_MAX_LOAD_PER_CORE": "1000",
        "BG_PING_CMD": "/usr/bin/true",
        "BG_WATCH_POLL": "1",
        "BG_DEADLINE_CMD": str(standin),
        "DEADLINE_STATE_DIR": str(state),
    }
    for k in ("BG_LOAD_WAIT", "BG_NO_DEADLINE", "DEADLINE_NAME", "PASEO_AGENT_ID"):
        env.pop(k, None)
    return work, env, log


def calls(log):
    return log.read_text().splitlines() if log.exists() else []


def wait_for(pred, secs=20.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.1)
    return pred()


def test_a_gate_refused_bg_registers_no_run_record_only_its_wait_record_with_a_holder(tmp_path):
    work, env, log = setup(tmp_path, admit_rc=75)
    env["BG_MAX_WAIT"] = "3"
    p = subprocess.Popen([str(BG), "/usr/bin/true"], cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate(timeout=60)
    assert p.returncode == 75, err
    time.sleep(1.0)   # a watcher forked anywhere on this path would have registered by now
    got = calls(log)
    assert not [c for c in got if "bg-run-" in c], got
    starts = [c for c in got if c.startswith("start bg-wait-")]
    assert len(starts) == 1 and f"--holder {p.pid}" in starts[0] and "--on-expire notify" in starts[0] and "--pid" not in starts[0]
    assert [c for c in got if c.startswith("done bg-wait-")], "the EXIT trap closes the wait record"
    assert not list((tmp_path / "home" / ".local" / "state" / "bg").glob("run-started.*"))


def test_a_started_run_registers_its_record_with_the_watcher_as_holder_and_closes_it(tmp_path):
    work, env, log = setup(tmp_path, admit_rc=0)
    p = subprocess.Popen([str(BG), "/bin/sleep", "2"], cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate(timeout=60)
    assert p.returncode == 0, err
    assert wait_for(lambda: any(c.startswith("done bg-run-") for c in calls(log))), calls(log)
    got = calls(log)
    starts = [c for c in got if c.startswith("start bg-run-")]
    assert len(starts) == 1 and not [c for c in got if "bg-wait-" in c], got   # no wait happened: no wait record
    words = starts[0].split()
    assert words[1].startswith(f"bg-run-{p.pid}-") and "--on-expire" in words and "--pid" not in words
    holder = int(words[words.index("--holder") + 1])
    assert holder != p.pid and holder > 1, "the watcher's own pid, not bg's (which is the command's pid after the exec)"
    assert starts[0] == got[0] and got[-1].startswith("done bg-run-"), got   # start first, done last
    assert not list((tmp_path / "home" / ".local" / "state" / "bg").glob("run-started.*")), "the marker is consumed"
