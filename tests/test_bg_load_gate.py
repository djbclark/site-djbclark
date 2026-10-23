"""bin/bg's load gate asks `load-watch admit` for the memory side and waits while it exits 75 (2026-10-23).

The real load average is no help (the machine often sits at load 30-60), so every test sets
BG_MAX_LOAD_PER_CORE=1000: bg's own load check always passes and the stub load-watch alone decides
whether the memory side is hot. bg takes load-watch from $HOME/src/djbclark-ade/bin/load-watch, so each
run gets a throwaway HOME holding a stub that answers `admit` from a file of exit codes (one per call,
the last one repeating) and `ci check` with "local". A BASH_ENV file replaces `sleep` with a function that
records its argument and sleeps 0.2 s, so the 15 s poll and the 5-30 s pause after clearing cost nothing
while BG_MAX_WAIT still runs out in real time.
"""

import os
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
    exit "$rc"
    ;;
esac
exit 0
"""


def run_bg(tmp_path, admit_codes, max_wait):
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
        "BG_MAX_LOAD_PER_CORE": "1000",
        "BG_MAX_WAIT": str(max_wait),
        "BG_PING_CMD": "/usr/bin/true",
        "BG_WATCH_POLL": "1",
    }
    env.pop("BG_LOAD_WAIT", None)  # 0 would skip the gate under test
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
    assert slept[0] == "15"


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
    # hot -> 15 s poll; ok -> random 5-30 s pause; ok again -> start
    assert len(calls) == 3
    assert slept[0] == "15"
    assert 5 <= int(slept[1]) <= 30
