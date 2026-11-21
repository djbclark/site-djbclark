"""bin/bgrun for Apple `container` commands (ADE queue 85 (a)-(c), 2026-11-21).

A fake `container` first on PATH stands in for the real CLI, so no apiserver, VM or XPC service is touched. The fixture HOME holds
a stub load-watch (bg takes it from $HOME/src/djbclark-ade/bin) that reports `local` and admits at once.

- (b) a run whose stderr carries the XPC "Connection invalid" error exits non-zero even when the CLI exited 0; any other status is
  passed through; stderr is still relayed, stdin reaches the command, a TERM reaches the command.
- (a) a down apiserver is started once before the run; a failed start refuses the run (72); BG_CONTAINER_AUTOSTART=0 skips it.
- (c) BGRUN_RUN_ID / BGRUN_RUN_START reach every command, and differ per run.
"""

import os
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

BG = Path(__file__).resolve().parent.parent / "bin" / "bgrun"

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="bgrun's gates are asserted on the Mac's tool set")

LOAD_WATCH = """#!/bin/bash
case "$1" in
  ci) printf 'local\\t\\t\\n' ;;
esac
exit 0
"""

# FAKE_STATE: a directory. `up` exists = apiserver running. FAKE_START=ok|fail decides whether `system start` creates `up`.
# `run` behaviour comes from FAKE_RUN: xpc0 (error text, exit 0), xpc3 (error text, exit 3), exit5, cat, sleep, else a clean run.
FAKE_CONTAINER = r"""#!/bin/bash
S="$FAKE_STATE"
echo "$*" >> "$S/calls"
[ "$1" = "--version" ] && { echo "container CLI version 1.7.1 (build: release, commit: unspecified)"; exit 0; }
case "$1 $2" in
  "system status")
    [ "${FAKE_STATUS:-}" = slow ] && exec /bin/sleep 30
    if [ -e "$S/up" ]; then echo '{"server":{"status":"running"}}'; else echo 'apiserver is not running and not registered with launchd' >&2; exit 1; fi
    exit 0 ;;
  "system start")
    [ "${FAKE_START:-ok}" = ok ] && : > "$S/up"
    exit 0 ;;
esac
case "$FAKE_RUN" in
  xpc0) echo 'Error: interrupted: "XPC connection error: Connection invalid"' >&2; exit 0 ;;
  xpc3) echo 'Error: interrupted: "XPC connection error: Connection invalid"' >&2; exit 3 ;;
  exit5) echo "boom" >&2; exit 5 ;;
  cat) cat; exit 0 ;;
  sleep) echo $$ > "$S/childpid"; exec sleep 30 ;;
  flood) echo $$ > "$S/childpid"; exec /usr/bin/yes 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx' >&2 ;;
  *) echo "ran: $*"; echo "diag line" >&2; exit 0 ;;
esac
"""


@pytest.fixture
def box(tmp_path):
    home, work, bindir, state = (tmp_path / n for n in ("home", "work", "fakebin", "state"))
    lw = home / "src" / "djbclark-ade" / "bin" / "load-watch"
    for d in (lw.parent, work, bindir, state):
        d.mkdir(parents=True)
    lw.write_text(LOAD_WATCH)
    lw.chmod(0o755)
    fake = bindir / "container"
    fake.write_text(FAKE_CONTAINER)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    shim = tmp_path / "sleep-shim.sh"
    shim.write_text("sleep() { command sleep 0.2; }\n")
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "BASH_ENV": str(shim),
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
        "BG_MAX_LOAD_PER_CORE": "1000",
        "BG_PING_CMD": "/usr/bin/true",
        "BG_NO_DEADLINE": "1",
        "FAKE_STATE": str(state),
    }
    for k in ("BG_LOAD_WAIT", "DEADLINE_NAME", "PASEO_AGENT_ID", "BG_CONTAINER_AUTOSTART", "BG_CONTAINER_STATUS_TIMEOUT", "FAKE_RUN", "FAKE_START", "FAKE_STATUS",
              "BGRUN_RUN_ID", "BGRUN_RUN_START"):
        env.pop(k, None)
    return work, env, state


def fake_path(box):
    # bgrun puts /opt/homebrew/bin first on PATH, so the real `container` would win a bare name: use the fake by path.
    return str(Path(box[1]["PATH"].split(":")[0]) / "container")


def bg(box, *argv, extra=None, stdin=None, timeout=60):
    work, env, _ = box
    argv = [fake_path(box) if a == "container" else a for a in argv]
    return subprocess.run([str(BG), *argv], cwd=work, env={**env, **(extra or {})}, input=stdin, capture_output=True, text=True,
                          timeout=timeout)


def up(box):
    (box[2] / "up").write_text("")


def calls(box):
    f = box[2] / "calls"
    return f.read_text().splitlines() if f.exists() else []


def test_exit_zero_with_an_xpc_connection_invalid_error_fails(box):
    up(box)
    r = bg(box, "container", "run", "--rm", "img", extra={"FAKE_RUN": "xpc0"})
    assert r.returncode == 70, r.stderr
    assert "Connection invalid" in r.stderr and "did not run" in r.stderr


def test_a_real_nonzero_status_is_passed_through_even_with_the_xpc_error(box):
    up(box)
    assert bg(box, "container", "run", "img", extra={"FAKE_RUN": "xpc3"}).returncode == 3
    r = bg(box, "container", "run", "img", extra={"FAKE_RUN": "exit5"})
    assert r.returncode == 5 and "boom" in r.stderr


def test_a_clean_run_exits_zero_and_relays_both_streams(box):
    up(box)
    r = bg(box, "container", "run", "--rm", "img")
    assert r.returncode == 0
    assert "ran: run --rm img" in r.stdout and "diag line" in r.stderr


def test_the_phrase_in_a_command_that_is_not_container_is_left_alone(box):
    p = box[0] / "noisy.sh"
    p.write_text('#!/bin/bash\necho "Error: XPC connection error: Connection invalid" >&2\n')
    p.chmod(0o755)
    assert bg(box, str(p)).returncode == 0  # no guard outside `container`: status passes through


def test_stdin_reaches_the_container_command(box):
    up(box)
    r = bg(box, "container", "run", "-i", "img", extra={"FAKE_RUN": "cat"}, stdin="hello from stdin\n")
    assert r.returncode == 0 and r.stdout == "hello from stdin\n"


def test_a_term_to_bg_reaches_the_command(box):
    up(box)
    work, env, state = box
    p = subprocess.Popen([str(BG), fake_path(box), "run", "img"], cwd=work, env={**env, "FAKE_RUN": "sleep"},
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 20
    while not (state / "childpid").exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    child = int((state / "childpid").read_text())
    p.send_signal(signal.SIGTERM)
    p.communicate(timeout=20)
    assert p.returncode == 128 + signal.SIGTERM
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


def test_a_down_apiserver_is_started_once_before_the_run(box):
    r = bg(box, "container", "run", "img")
    assert r.returncode == 0, r.stderr
    cs = calls(box)
    assert cs.count("system start --disable-kernel-install") == 1
    assert cs.index("system start --disable-kernel-install") < cs.index("run img")
    assert "starting it" in r.stderr


def test_a_running_apiserver_is_not_started(box):
    up(box)
    bg(box, "container", "run", "img")
    assert not any(c.startswith("system start") for c in calls(box))


def test_a_start_that_fails_refuses_the_run(box):
    r = bg(box, "container", "run", "img", extra={"FAKE_START": "fail"})
    assert r.returncode == 72
    assert "still not running" in r.stderr
    assert "run img" not in calls(box)


def test_autostart_can_be_turned_off(box):
    r = bg(box, "container", "run", "img", extra={"BG_CONTAINER_AUTOSTART": "0"})
    assert r.returncode == 0
    assert not any(c.startswith("system start") for c in calls(box))


def test_system_and_version_calls_need_no_preflight(box):
    bg(box, "container", "--version")
    bg(box, "container", "system", "status")
    assert not any(c.startswith("system start") for c in calls(box))


def test_the_guard_is_found_when_bg_is_reached_through_a_symlink(box, tmp_path):
    up(box)
    link = tmp_path / "linkdir" / "bgrun"
    link.parent.mkdir()
    link.symlink_to(BG)
    work, env, _ = box
    r = subprocess.run([str(link), fake_path(box), "run", "img"], cwd=work, env={**env, "FAKE_RUN": "xpc0"},
                       capture_output=True, text=True)
    assert r.returncode == 70


def test_each_run_gets_its_own_run_id_and_start_time(box):
    ids = []
    for _ in range(2):
        r = bg(box, "/usr/bin/env")
        assert r.returncode == 0
        env = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
        assert re.fullmatch(r"\d{8}T\d{6}Z-\d+", env["BGRUN_RUN_ID"]), env.get("BGRUN_RUN_ID")
        assert abs(int(env["BGRUN_RUN_START"]) - time.time()) < 120
        ids.append(env["BGRUN_RUN_ID"])
    assert ids[0] != ids[1]


def test_a_reader_that_goes_away_ends_the_run_instead_of_hanging_it(box):
    # `bgrun container ... 2>&1 | head`: the child must get SIGPIPE as before the guard, not block forever on a full pipe
    up(box)
    work, env, state = box
    p = subprocess.Popen([str(BG), fake_path(box), "build", "."], cwd=work, env={**env, "FAKE_RUN": "flood"},
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        p.stderr.read(100)
        p.stderr.close()
        p.wait(timeout=20)
    finally:
        if p.poll() is None:
            p.kill()
            pid = (state / "childpid")
            if pid.exists():
                os.kill(int(pid.read_text()), signal.SIGKILL)
    assert p.returncode is not None


def test_a_status_timeout_does_not_refuse_or_restart(box):
    r = bg(box, "container", "run", "img", extra={"FAKE_STATUS": "slow", "BG_CONTAINER_STATUS_TIMEOUT": "1"})
    assert r.returncode == 0, r.stderr
    assert "did not answer in time" in r.stderr
    assert not any(c.startswith("system start") for c in calls(box))
    assert "run img" in calls(box)


def test_only_apples_container_gets_the_guard(box):
    work = box[0]
    wrapper = work / "container"
    wrapper.write_text("#!/bin/bash\necho WRAPPER $*\necho 'Error: XPC connection error: Connection invalid' >&2\n")
    wrapper.chmod(0o755)
    r = bg(box, "./container", "run", "img")
    assert r.returncode == 0 and "WRAPPER run img" in r.stdout  # no preflight, no guard: status passes through
    assert calls(box) == []


def test_a_wrapper_prefix_does_not_hide_or_confuse_the_container_word(box):
    r = bg(box, "env", "FOO=/opt/homebrew/bin/container", "container", "run", "img", extra={"FAKE_RUN": "xpc0"})
    assert r.returncode == 70, r.stderr


def test_the_guard_ignores_the_callers_pythonpath(box, tmp_path):
    up(box)
    poison = tmp_path / "poison"
    poison.mkdir()
    (poison / "signal.py").write_text("raise SystemExit(99)\n")
    r = bg(box, "container", "run", "img", extra={"FAKE_RUN": "xpc0", "PYTHONPATH": str(poison)})
    assert r.returncode == 70, r.stderr
