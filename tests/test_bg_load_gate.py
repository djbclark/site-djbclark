"""bin/bg's load gate asks `load-watch admit` for the memory side and waits while it exits 75 (2026-10-23).

Since 2026-11-14 bg looks once with `admit --wait 0`; once held it calls `admit --wait CHUNK` (load-watch polls, staggers and applies
its starvation valve) instead of polling `--wait 0` every 15 s itself, so the valve can reach bg.

The real load average is no help (the machine often sits at load 30-60), so every test sets
BG_MAX_LOAD_PER_CORE=1000: bg's own load check always passes and the stub load-watch alone decides
whether the memory side is hot. bg takes load-watch from $HOME/src/djbclark-ade/bin/load-watch, so each
run gets a throwaway HOME holding a stub that answers `admit` from a file of exit codes (one per call,
the last one repeating) and `ci check` with "local". A BASH_ENV file replaces `sleep` with a function that
records its argument and sleeps 0.2 s, so bg's own 15 s poll (used only when load-watch is missing or errors, or answers a
`--wait` call at once) costs nothing while BG_MAX_WAIT still runs out in real time.
"""

import os
import re
import shlex
import subprocess
import time
from pathlib import Path

import pytest

BG = Path(__file__).resolve().parent.parent / "bin" / "bg"

STUB = """#!/bin/bash
d={state}
case "$1" in
  ci) printf 'local\\t\\t\\n'; exit 0 ;;
  admit)
    printf '%s\\n' "$*" >> "$d/admit.calls"
    rc=$(head -n 1 "$d/codes")
    if [ "$(( $(wc -l < "$d/codes") ))" -gt 1 ]; then
      tail -n +2 "$d/codes" > "$d/codes.tmp" && mv "$d/codes.tmp" "$d/codes"
    fi
    if [ -n "$LW_STUB_DISARM" ] && [ "$3" != 0 ]; then command sleep 3; chmod -x "$0"; fi   # a real wait, then load-watch vanishes
    [ "$rc" = 0 ] && [ -n "$LW_STUB_FORCED" ] && echo "admit ok forced=starved waited_s=300 overrode=load"
    [ "$rc" = 0 ] && [ -n "$LW_STUB_WAITED" ] && echo "admit ok load1=1 per_core=0.10 cores=10 waited_s=120"
    exit "$rc"
    ;;
esac
exit 0
"""


def run_bg(tmp_path, admit_codes, max_wait, max_per_core="1000", extra_env=None):
    """Run `bg touch MARKER` with a stub `load-watch admit` that exits with ADMIT_CODES in turn.

    Returns (CompletedProcess, marker Path, admit calls, sleep arguments, seconds taken).
    """
    home = tmp_path / "home"
    state = tmp_path / "state"
    work = tmp_path / "work"
    lw = home / "src" / "djbclark-ade" / "bin" / "load-watch"
    for d in (lw.parent, state, work):
        d.mkdir(parents=True)
    lw.write_text(STUB.format(state=shlex.quote(str(state))))
    lw.chmod(0o755)
    (state / "codes").write_text("".join(f"{c}\n" for c in admit_codes))
    sleeps = state / "sleeps"
    shim = state / "sleep-shim.sh"
    shim.write_text(f'sleep() {{ printf "%s\\n" "$1" >> {shlex.quote(str(sleeps))}; command sleep 0.2; }}\n')
    marker = tmp_path / "ran"
    env = {
        **os.environ,
        "HOME": str(home),
        "BASH_ENV": str(shim),
        # work is not in a git repo, so bg skips `load-watch ci check`; the stub answers it anyway.
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
        "BG_MAX_LOAD_PER_CORE": max_per_core,
        "BG_MAX_WAIT": str(max_wait),
        "BG_PING_CMD": "/usr/bin/true",
        "BG_NO_DEADLINE": "1",
        "BG_WATCH_POLL": "1",
    }
    env.pop("BG_LOAD_WAIT", None)  # 0 would skip the gate under test
    env.update(extra_env or {})
    t0 = time.monotonic()
    r = subprocess.run(
        [str(BG), "/usr/bin/touch", str(marker)], cwd=work, env=env, capture_output=True, text=True, timeout=120
    )
    took = time.monotonic() - t0
    calls = (state / "admit.calls").read_text().splitlines() if (state / "admit.calls").exists() else []
    slept = sleeps.read_text().split() if sleeps.exists() else []
    return r, marker, calls, slept, took


def test_bg_waits_and_gives_up_while_admit_says_hot(tmp_path):
    r, marker, calls, slept, took = run_bg(tmp_path, [75], max_wait=5)
    assert r.returncode == 75, r.stderr
    assert not marker.exists()
    assert took >= 3  # bg counts its budget in whole seconds from an earlier start; 4.46 s was seen for 5
    assert len(calls) > 1  # it kept asking, not once and out
    assert "memory churn" in r.stderr
    assert "giving up without running it" in r.stderr
    # the first look is a pure check; once held bg hands the waiting to load-watch (`--wait N`, N > 0), whose valve then applies
    assert calls[0] == "admit --wait 0 --max-per-core 1000"
    assert all(re.fullmatch(r"admit --wait [1-9][0-9]* --max-per-core 1000", c) for c in calls[1:]), calls
    assert "15" in slept  # a --wait call that returns at once must not spin: bg keeps its 15 s poll then


def test_bg_starts_the_command_when_admit_says_ok(tmp_path):
    r, marker, calls, slept, took = run_bg(tmp_path, [0], max_wait=60)
    assert r.returncode == 0, r.stderr
    assert marker.exists()
    assert calls == ["admit --wait 0 --max-per-core 1000"]
    assert "15" not in slept  # no poll wait
    assert took < 20


@pytest.mark.parametrize("code", [1, 3, 127])
def test_bg_fails_open_when_admit_errors(tmp_path, code):
    r, marker, calls, slept, took = run_bg(tmp_path, [code], max_wait=60)
    assert r.returncode == 0, r.stderr
    assert marker.exists()
    assert len(calls) == 1
    assert took < 20


def test_bg_runs_the_command_once_admit_clears(tmp_path):
    r, marker, calls, slept, took = run_bg(tmp_path, [75, 0], max_wait=60)
    assert r.returncode == 0, r.stderr
    assert marker.exists()
    assert "memory churn" in r.stderr  # it announced the wait
    # hot -> announce, then `--wait N` (load-watch does the waiting); a call that answered at once staggered nothing, so bg keeps
    # its own random 5-30 s pause and re-read, then starts
    assert len(calls) == 3
    assert calls[0] == "admit --wait 0 --max-per-core 1000"
    m = re.fullmatch(r"admit --wait ([0-9]+) --max-per-core 1000", calls[1])
    assert m and 1 <= int(m.group(1)) <= 60, calls
    assert len(slept) == 1 and 5 <= int(slept[0]) <= 30


def test_bg_hands_the_waiting_to_admit_in_chunks(tmp_path):
    r, marker, calls, slept, took = run_bg(tmp_path, [75, 75, 0], max_wait=60, extra_env={"BG_ADMIT_CHUNK": "7"})
    assert r.returncode == 0, r.stderr
    assert marker.exists()
    assert calls[:2] == ["admit --wait 0 --max-per-core 1000", "admit --wait 7 --max-per-core 1000"]


@pytest.mark.parametrize("chunk", ["08", "09", "0480", "x", "-3", "12345678"])
def test_bg_ignores_a_bad_admit_chunk_and_keeps_the_gate(tmp_path, chunk):
    """A leading zero reads as octal in bash arithmetic; the error used to abort the whole gate and run the command hot."""
    r, marker, calls, slept, took = run_bg(tmp_path, [75], max_wait=20, extra_env={"BG_ADMIT_CHUNK": chunk})
    assert r.returncode == 75, r.stderr
    assert not marker.exists()
    assert "syntax error" not in r.stderr and "value too great" not in r.stderr
    if chunk in ("08", "09"):  # a chunk smaller than the budget is really used, as plain decimal
        assert calls[1] == f"admit --wait {int(chunk)} --max-per-core 1000", calls


def test_bg_clamps_the_admit_chunk_to_the_heartbeat(tmp_path):
    r, marker, calls, slept, took = run_bg(tmp_path, [75, 0], max_wait=3600, extra_env={"BG_ADMIT_CHUNK": "9999"})
    assert r.returncode == 0, r.stderr
    assert calls[1] == "admit --wait 480 --max-per-core 1000"


def test_bg_polls_itself_again_when_load_watch_vanishes_mid_wait(tmp_path):
    """A stale exit 75 from the last `--wait` call must not skip bg's 15 s poll once load-watch is gone (busy-spin)."""
    r, marker, calls, slept, took = run_bg(
        tmp_path, [75], max_wait=5, max_per_core="0.0001", extra_env={"LW_STUB_DISARM": "1"}
    )
    assert r.returncode == 75, r.stderr
    assert not marker.exists()
    assert len(calls) == 2  # the look and the one waiting call; then load-watch is not executable
    assert "15" in slept


def test_bg_default_chunk_is_cut_to_the_rest_of_the_budget(tmp_path):
    r, marker, calls, slept, took = run_bg(tmp_path, [75, 0], max_wait=100)
    assert r.returncode == 0, r.stderr
    n = int(calls[1].split()[2])
    assert 95 <= n <= 100, calls  # the whole budget fits in one chunk (default 420 s) and is what is left of BG_MAX_WAIT


def test_bg_reports_a_forced_admit_and_runs_the_command(tmp_path):
    r, marker, calls, slept, took = run_bg(tmp_path, [75, 0], max_wait=60, extra_env={"LW_STUB_FORCED": "1"})
    assert r.returncode == 0, r.stderr
    assert marker.exists()
    assert "starvation valve admitted" in r.stderr
    assert len(calls) == 2  # not re-read: the forced claim is spent


def test_bg_does_not_re_read_after_load_watch_waited_and_staggered(tmp_path):
    r, marker, calls, slept, took = run_bg(tmp_path, [75, 0], max_wait=60, extra_env={"LW_STUB_WAITED": "1"})
    assert r.returncode == 0, r.stderr
    assert marker.exists()
    assert len(calls) == 2 and slept == []  # `waited_s=` in its line: it staggered itself; no second pause


def test_bg_load_wait_zero_skips_the_gate(tmp_path):
    r, marker, calls, slept, took = run_bg(tmp_path, [75], max_wait=60, extra_env={"BG_LOAD_WAIT": "0"})
    assert r.returncode == 0, r.stderr
    assert marker.exists()
    assert calls == []  # load-watch admit never asked


def test_bg_lets_the_watcher_admit_above_its_own_load_limit(tmp_path):
    """2026-10-25: load-watch admit raises the limit while the compressor is calm, so exit 0 beats bg's awk check."""
    r, marker, calls, slept, took = run_bg(tmp_path, [0], max_wait=60, max_per_core="0.0001")
    assert r.returncode == 0, r.stderr
    assert marker.exists()
    assert calls == ["admit --wait 0 --max-per-core 0.0001"]


def test_bg_keeps_its_own_limit_when_admit_errors(tmp_path):
    r, marker, calls, slept, took = run_bg(tmp_path, [1], max_wait=5, max_per_core="0.0001")
    assert r.returncode == 75, r.stderr
    assert not marker.exists()
