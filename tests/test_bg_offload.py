"""bin/bg offloads a held targeted test run in a `ci` repo to CI (bin/bg-offload, 2026-10-23).

On 2026-10-23 a 2 s pytest file sat over an hour in bg's load gate in a `ci`-mode repo at load 25-93. Now,
once the gate has held a targeted run for BG_OFFLOAD_AFTER seconds, bg hands it to bin/bg-offload, which
runs the repo's CI route on a commit of the working tree and exits with CI's verdict.

Nothing here reaches GitHub. Each run gets a throwaway HOME and a throwaway git repo, with stubs for:
  load-watch  ($HOME/src/djbclark-ade/bin/load-watch): `ci check` answers the repo's mode, `admit` exits 75
              (too hot) or whatever the codes file says, one per call, the last repeating;
  the route   (scripts/github-ci-run in the repo, called as `--no-wait REF`): records the ref and the
              test file's content in that ref, then prints the two lines the real script prints;
  gh          (BG_GH): `run list` answers from runs.json through the real jq expression bg-offload passes,
              `run view` prints failed.log.
BG_MAX_LOAD_PER_CORE=1000 keeps bg's own load check passing, so the stub `admit` alone holds the gate. A
BASH_ENV shim turns every `sleep` into 0.2 s, so the 15 s gate poll and bg-offload's poll cost nothing
while the real clock still drives BG_OFFLOAD_AFTER and BG_MAX_WAIT.
"""

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parent.parent / "bin"
BG = BIN / "bg"
OFFLOAD = BIN / "bg-offload"
COMMIT = "a" * 40

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="the gh stub applies bg-offload's --jq with jq")

LW_STUB = """#!/bin/bash
d={state}
case "$1" in
  ci) printf '%s\\t%s\\t%s\\n' {mode} 'scripts/github-ci-run REF' "$2"; exit 0 ;;
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

RUNNER_STUB = """#!/bin/bash
d={state}
printf '%s\\n' "$*" >> "$d/runner.calls"
git show "$2:tests/test_a.py" > "$d/ref.testfile"
git rev-parse HEAD > "$d/head"
printf '%s\\n' "$2" > "$d/ref"
if [ -f "$d/runner.fail" ]; then echo "runner exploded" >&2; exit 1; fi
echo "overlay {commit} for $2 -> origin ci/run/x-abc"
echo "pushed https://github.com/djbclark/stubrepo/tree/ci/run/x-abc"
"""

GH_STUB = """#!/bin/bash
d={state}
printf '%s\\n' "$*" >> "$d/gh.calls"
case "$1 $2" in
  "run list")
    expr=
    while [ $# -gt 0 ]; do [ "$1" = --jq ] && expr=$2; shift; done
    if [ -f "$d/gh.fail" ]; then echo "gh: HTTP 502" >&2; exit 1; fi
    jq -r "$expr" < "$d/runs.json"
    ;;
  "run view") cat "$d/failed.log" ;;
esac
"""


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def run(rid, status="completed", conclusion="success", sha=COMMIT, name="linux-ci"):
    return {"databaseId": rid, "headSha": sha, "status": status, "conclusion": conclusion,
            "url": f"https://github.com/djbclark/stubrepo/actions/runs/{rid}", "name": name}


class Setup:
    def __init__(self, tmp_path):
        self.root = tmp_path
        self.home = tmp_path / "home"
        self.state = tmp_path / "state"
        self.work = tmp_path / "work"
        self.marker = tmp_path / "ran"
        for d in (self.home / "src" / "djbclark-ade" / "bin", self.home / "fakebin", self.state, self.work / "tests",
                  self.work / "scripts"):
            d.mkdir(parents=True, exist_ok=True)
        (self.state / "runs.json").write_text(json.dumps([run(11)]))
        (self.state / "failed.log").write_text("".join(f"line {i}\n" for i in range(1, 101)) + "FAILED test_x\n")
        fake = self.home / "fakebin" / "pytest"
        fake.write_text(f'#!/bin/bash\ntouch {shlex.quote(str(self.marker))}\necho "FAKE-PYTEST $*"\n')
        fake.chmod(0o755)
        (self.work / "tests" / "test_a.py").write_text("def test_x(): pass\n")
        self.route(True)
        git(self.work, "init", "-q")
        git(self.work, "config", "user.name", "t")
        git(self.work, "config", "user.email", "t@example.invalid")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "init")
        self.load_watch("ci")
        self.codes([75])
        gh = self.home / "fakebin" / "gh"
        gh.write_text(GH_STUB.format(state=shlex.quote(str(self.state))))
        gh.chmod(0o755)
        shim = self.state / "sleep-shim.sh"
        shim.write_text('sleep() { command sleep 0.2; }\n')

    def route(self, present):
        r = self.work / "scripts" / "github-ci-run"
        if present:
            r.write_text(RUNNER_STUB.format(state=shlex.quote(str(self.state)), commit=COMMIT))
            r.chmod(0o755)
        elif r.exists():
            r.unlink()

    def load_watch(self, mode):
        lw = self.home / "src" / "djbclark-ade" / "bin" / "load-watch"
        if mode is None:
            lw.unlink(missing_ok=True)
            return
        lw.write_text(LW_STUB.format(state=shlex.quote(str(self.state)), mode=shlex.quote(mode)))
        lw.chmod(0o755)

    def codes(self, codes):
        (self.state / "codes").write_text("".join(f"{c}\n" for c in codes))

    def bg(self, *argv, **env):
        e = {**os.environ, "HOME": str(self.home), "BASH_ENV": str(self.state / "sleep-shim.sh"),
             "BG_GH": str(self.home / "fakebin" / "gh"), "BG_MAX_LOAD_PER_CORE": "1000", "BG_MAX_WAIT": "5",
             "BG_OFFLOAD_AFTER": "1", "BG_PING_CMD": "/usr/bin/true", "BG_WATCH_POLL": "1", **env}
        e = {k: v for k, v in e.items() if v is not None}
        e.pop("BG_LOAD_WAIT", None)  # 0 would skip the gate under test
        cmd = argv or (str(self.home / "fakebin" / "pytest"), "tests/test_a.py")
        return subprocess.run([str(BG), *cmd], cwd=self.work, env=e, capture_output=True, text=True, timeout=120)

    def read(self, name):
        p = self.state / name
        return p.read_text() if p.exists() else ""


@pytest.fixture
def s(tmp_path):
    return Setup(tmp_path)


def test_a_held_targeted_run_is_offloaded_and_passes(s):
    r = s.bg()
    assert r.returncode == 0, r.stderr
    assert not s.marker.exists()  # the command never ran here
    assert "CI PASSED" in r.stdout and "actions/runs/11" in r.stdout
    assert "running it on CI instead of waiting longer" in r.stderr
    assert "unless the load gate holds it past 1 s" in r.stderr
    # clean tree: CI builds HEAD
    assert s.read("ref").strip() == s.read("head").strip()
    assert s.read("runner.calls").strip() == f"--no-wait {s.read('head').strip()}"
    # gh was always told which repo (it can resolve to an upstream remote otherwise)
    assert all("-R djbclark/stubrepo" in c for c in s.read("gh.calls").splitlines())


def test_a_ci_failure_is_exit_1_with_the_failed_log_tail(s):
    (s.state / "runs.json").write_text(json.dumps([run(12, conclusion="failure")]))
    r = s.bg()
    assert r.returncode == 1, r.stderr
    assert not s.marker.exists()
    assert "CI FAILED" in r.stdout and "actions/runs/12" in r.stdout
    assert "FAILED test_x" in r.stdout and "line 100" in r.stdout and "line 20\n" not in r.stdout  # last 60 lines
    assert (s.home / ".local" / "state" / "bg" / "offload" / "12.log").read_text().startswith("line 1\n")
    assert "whole CI workflow" in r.stderr


def test_a_dirty_tree_goes_as_a_stash_commit_and_untracked_files_are_listed(s):
    (s.work / "tests" / "test_a.py").write_text("def test_x(): assert 1 == 1  # edited\n")
    (s.work / "notes.txt").write_text("not tracked\n")
    r = s.bg()
    assert r.returncode == 0, r.stderr
    assert s.read("ref").strip() != s.read("head").strip()  # a stash commit, not HEAD
    assert "# edited" in s.read("ref.testfile")  # carrying the tracked edit
    assert "untracked files are NOT in the CI run" in r.stderr
    assert "?? notes.txt" in r.stderr
    # the working tree itself was not touched
    assert "# edited" in (s.work / "tests" / "test_a.py").read_text()
    assert (s.work / "notes.txt").exists()


def test_only_untracked_files_means_clean_head_with_a_note(s):
    (s.work / "notes.txt").write_text("not tracked\n")
    r = s.bg()
    assert r.returncode == 0, r.stderr
    assert s.read("ref").strip() == s.read("head").strip()
    assert "?? notes.txt" in r.stderr
    assert "only untracked files" in r.stderr


def test_a_test_file_that_is_untracked_cannot_go_to_ci(s):
    (s.work / "tests" / "test_new.py").write_text("def test_n(): pass\n")
    r = s.bg(str(s.home / "fakebin" / "pytest"), "tests/test_new.py::test_n", BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr  # fell back to waiting, then the budget ran out
    assert "tests/test_new.py is untracked" in r.stderr
    assert "could not offload to CI" in r.stderr
    assert s.read("runner.calls") == ""


def test_a_run_not_held_past_the_threshold_stays_here(s):
    s.codes([75, 0])  # hot once, then ok
    r = s.bg(BG_OFFLOAD_AFTER="60")
    assert r.returncode == 0, r.stderr
    assert s.marker.exists()
    assert "FAKE-PYTEST tests/test_a.py" in r.stdout
    assert s.read("runner.calls") == ""
    assert "running it on CI" not in r.stderr


def test_a_not_targeted_run_is_refused_not_offloaded(s):
    r = s.bg(str(s.home / "fakebin" / "pytest"))  # a bare suite
    assert r.returncode == 3
    assert s.read("runner.calls") == ""
    assert "offload" not in r.stderr


def test_a_local_repo_waits_and_never_offloads(s):
    s.load_watch("local")
    r = s.bg(BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert "giving up without running it" in r.stderr
    assert s.read("runner.calls") == ""
    assert not s.marker.exists()


def test_no_runnable_route_keeps_waiting(s):
    s.route(False)
    r = s.bg(BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert s.read("runner.calls") == ""
    assert "runs on CI instead" not in r.stderr and "unless the load gate" not in r.stderr


def test_opt_out_keeps_the_old_waiting_behaviour(s):
    r = s.bg(BG_OFFLOAD="0", BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert s.read("runner.calls") == ""
    assert "this targeted test run stays here." in r.stderr


def test_fails_open_without_load_watch(s):
    s.load_watch(None)
    # no load-watch means no CI decision and no memory gate; an absurdly low per-core limit holds the gate
    r = s.bg(BG_MAX_LOAD_PER_CORE="0.0001", BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert s.read("runner.calls") == ""


def test_fails_open_without_gh(s):
    r = s.bg(BG_GH=str(s.root / "no-such-gh"), BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert s.read("runner.calls") == ""
    assert "unless the load gate" not in r.stderr


def test_a_failing_runner_falls_back_to_waiting(s):
    (s.state / "runner.fail").write_text("")
    r = s.bg(BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert "the CI runner exited 1" in r.stderr and "runner exploded" in r.stderr
    assert "could not offload to CI" in r.stderr
    assert len(s.read("runner.calls").splitlines()) == 1  # tried once, not on every poll


def test_a_worktree_has_no_route(s):
    git(s.work, "worktree", "add", "-q", str(s.root / "wt"), "-b", "other")
    r = subprocess.run([str(OFFLOAD), "--probe", str(s.root / "wt")], env={**os.environ, "BG_GH": str(s.home / "fakebin" / "gh")})
    assert r.returncode != 0
    r = subprocess.run([str(OFFLOAD), "--probe", str(s.work)], env={**os.environ, "BG_GH": str(s.home / "fakebin" / "gh")})
    assert r.returncode == 0


def test_ci_still_running_at_the_limit_is_76(s):
    (s.state / "runs.json").write_text(json.dumps([run(13, status="in_progress", conclusion=None)]))
    r = s.bg(BG_OFFLOAD_WAIT="1")
    assert r.returncode == 76, r.stderr
    assert "still going" in r.stderr and "actions/runs/13" in r.stderr


def test_a_run_that_never_appears_is_77(s):
    (s.state / "runs.json").write_text("[]")
    r = s.bg(BG_OFFLOAD_APPEAR="1")
    assert r.returncode == 77, r.stderr
    assert "no verdict" in r.stderr


def test_a_stale_run_for_another_commit_is_not_the_verdict(s):
    (s.state / "runs.json").write_text(json.dumps([run(14, sha="b" * 40)]))
    r = s.bg(BG_OFFLOAD_APPEAR="1")
    assert r.returncode == 77, r.stderr
    assert "CI PASSED" not in r.stdout


def test_a_cancelled_run_is_77(s):
    (s.state / "runs.json").write_text(json.dumps([run(15, conclusion="cancelled")]))
    r = s.bg()
    assert r.returncode == 77, r.stderr
    assert "ended 'cancelled'" in r.stderr


def test_gh_failing_repeatedly_is_77(s):
    (s.state / "gh.fail").write_text("")
    r = s.bg()
    assert r.returncode == 77, r.stderr
    assert "failed 5 times in a row" in r.stderr


def test_every_run_on_the_commit_must_pass(s):
    (s.state / "runs.json").write_text(json.dumps([run(16), run(17, conclusion="failure", name="agent-ci")]))
    r = s.bg()
    assert r.returncode == 1, r.stderr
    assert "actions/runs/17" in r.stdout
