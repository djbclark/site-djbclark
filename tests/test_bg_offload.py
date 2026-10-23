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
              but only for `--branch ci/run/x-abc` and no more rows than `--limit` (as the real one), `run view`
              prints failed.log. Like real gh, an unfinished run has `"conclusion": ""`.
  gitleaks    the real one (installed; those tests skip without it), BG_GITLEAKS points at a missing one.
BG_MAX_LOAD_PER_CORE=1000 keeps bg's own load check passing, so the stub `admit` alone holds the gate. A
BASH_ENV shim turns every `sleep` into 0.2 s, so the 15 s gate poll and bg-offload's poll cost nothing
while the real clock still drives BG_OFFLOAD_AFTER and BG_MAX_WAIT.
"""

import json
import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parent.parent / "bin"
BG = BIN / "bg"
OFFLOAD = BIN / "bg-offload"
COMMIT = "a" * 40

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="the gh stub applies bg-offload's --jq with jq")
needs_gitleaks = pytest.mark.skipif(shutil.which("gitleaks") is None, reason="needs the real gitleaks")
# Shaped like a GitHub personal access token; gitleaks' github-pat rule matches it (made up, not a credential).
FAKE_TOKEN = "ghp_" + "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dE3fG5"

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
git rev-list --parents -n 1 "$2" > "$d/ref.parents"
git grep -q "SECRETXY[Z]" "$2" -- . && echo yes > "$d/ref.hassecret" || echo no > "$d/ref.hassecret"
git log -1 --format=%B "$2" > "$d/ref.msg"
if [ -f "$d/runner.slow" ]; then
  echo $$ > "$d/runner.pid"
  # a child that outlives its parent if only the parent is killed (like the git push inside github-ci-run)
  sh -c 'echo $$ > "$0/slow.pid"; sleep 4; touch "$0/slow.marker"' "$d"
fi
if [ -f "$d/runner.garbage" ]; then cat "$d/runner.garbage"; exit 0; fi
if [ -f "$d/runner.fail" ]; then echo "runner exploded" >&2; exit 1; fi
echo "overlay {commit} for $2 -> origin ci/run/x-abc"
echo "pushed https://github.com/djbclark/stubrepo/tree/ci/run/x-abc"
"""

GH_STUB = """#!/bin/bash
d={state}
printf '%s\\n' "$*" >> "$d/gh.calls"
case "$1 $2" in
  "run list")
    echo $PPID > "$d/gh.ppid"
    if [ -f "$d/gh.fail" ]; then
      n=$(cat "$d/gh.fail")
      if [ -z "$n" ]; then echo "gh: HTTP 502" >&2; exit 1; fi
      if [ "$n" -gt 0 ]; then echo $((n - 1)) > "$d/gh.fail"; echo "gh: HTTP 502" >&2; exit 1; fi
    fi
    # args after "run list": -R REPO --branch BR --limit N --json F --jq EXPR
    shift 2; branch=; limit=30; expr=
    while [ $# -gt 0 ]; do
      case "$1" in --branch) branch=$2 ;; --limit) limit=$2 ;; --jq) expr=$2 ;; esac
      shift
    done
    [ "$branch" = ci/run/x-abc ] || exit 0
    jq -c ".[0:$limit]" < "$d/runs.json" | jq -r "$expr"
    ;;
  "run view") cat "$d/failed.log" ;;
esac
"""


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def run(rid, status="completed", conclusion="success", sha=COMMIT, name="linux-ci"):
    if conclusion is None:
        conclusion = ""  # real gh: "" for an unfinished run (adversary review, 2026-10-23)
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
        git(self.work, "update-ref", "refs/remotes/origin/main", "HEAD")  # HEAD is on the remote: nothing unpushed
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
             "BG_OFFLOAD_TESTING": "1", "BG_GH": str(self.home / "fakebin" / "gh"), "BG_MAX_LOAD_PER_CORE": "1000", "BG_MAX_WAIT": "5",
             "BG_OFFLOAD_AFTER": "1", "BG_PING_CMD": "/usr/bin/true", "BG_WATCH_POLL": "1", **env}
        e = {k: v for k, v in e.items() if v is not None}
        e.pop("BG_LOAD_WAIT", None)  # 0 would skip the gate under test
        cmd = argv or (str(self.home / "fakebin" / "pytest"), "tests/test_a.py")
        return subprocess.run([str(BG), *cmd], cwd=self.work, env=e, capture_output=True, text=True, timeout=120)

    def gl_wrapper(self):
        """A BG_GITLEAKS that records argv, the GITLEAKS_* environment and the full output, then runs the real one."""
        w = self.root / "gitleaks-wrap"
        w.write_text(f'#!/bin/bash\nd={shlex.quote(str(self.state))}\nprintf "%s\\n" "$@" > "$d/gl.args"\n'
                     f'env | grep ^GITLEAKS_ > "$d/gl.env"\npwd > "$d/gl.cwd"\n'
                     f'{shutil.which("gitleaks")} "$@" > "$d/gl.full" 2>&1; rc=$?\ncat "$d/gl.full"\nexit $rc\n')
        w.chmod(0o755)
        return str(w)

    def commit_all(self, msg, on_remote=True):
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", msg)
        if on_remote:
            git(self.work, "update-ref", "refs/remotes/origin/main", "HEAD")

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
    assert "CI workflow PASSED" in r.stdout and "actions/runs/11" in r.stdout
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
    assert (s.home / ".local" / "state" / "bg" / "offload" / "12.log").stat().st_mode & 0o777 == 0o600
    calls = s.read("gh.calls").splitlines()
    assert any(c.startswith("run view 12") for c in calls)
    assert all("-R djbclark/stubrepo" in c for c in calls)  # incl. `run view`


def test_a_dirty_tree_is_not_pushed_without_the_opt_in(s):
    (s.work / "tests" / "test_a.py").write_text("def test_x(): assert 1 == 1  # edited\n")
    r = s.bg(BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr  # fell back to waiting; the command never ran, nothing was pushed
    assert s.read("runner.calls") == ""
    assert "tests/test_a.py" in r.stderr  # names the dirty file
    assert "BG_OFFLOAD_DIRTY=1" in r.stderr  # and how to opt in
    assert "could not offload to CI" in r.stderr


def test_a_staged_only_change_also_counts_as_dirty(s):
    (s.work / "tests" / "test_a.py").write_text("def test_x(): assert 1 == 1  # staged\n")
    git(s.work, "add", "tests/test_a.py")
    r = s.bg(BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert s.read("runner.calls") == ""


@needs_gitleaks
def test_an_opted_in_dirty_tree_goes_as_a_commit_on_head_with_its_files_listed(s):
    (s.work / "tests" / "test_a.py").write_text("def test_x(): assert 1 == 1  # edited\n")
    (s.work / "notes.txt").write_text("SECRETXYZ in an untracked file\n")
    r = s.bg(BG_OFFLOAD_DIRTY="1")
    assert r.returncode == 0, r.stderr
    assert s.read("ref.hassecret").strip() == "no"  # untracked content never travels (git add -u, not -A)
    assert "A\tnotes.txt" not in r.stderr and "notes.txt" not in s.read("ref.parents")
    assert "git diff --name-status" in r.stderr and "M\ttests/test_a.py" in r.stderr  # what goes, before the push
    assert s.read("ref").strip() != s.read("head").strip()  # a new commit, not HEAD
    assert "# edited" in s.read("ref.testfile")  # carrying the tracked edit
    assert s.read("ref.parents").split() == [s.read("ref").strip(), s.read("head").strip()]  # parent: HEAD only
    assert "tracked files with uncommitted changes" in r.stderr and "tests/test_a.py" in r.stderr  # listed first
    assert "scanned by gitleaks" in r.stderr
    assert "?? notes.txt" in r.stderr
    # the working tree and the index were not touched
    assert "# edited" in (s.work / "tests" / "test_a.py").read_text()
    assert (s.work / "notes.txt").exists()
    assert subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=s.work).returncode == 0


@needs_gitleaks
def test_a_secret_staged_and_then_removed_does_not_travel(s):
    (s.work / "tests" / "test_a.py").write_text("SECRETXYZ = 1\n")
    git(s.work, "add", "tests/test_a.py")
    (s.work / "tests" / "test_a.py").write_text("def test_x(): pass  # cleaned\n")
    r = s.bg(BG_OFFLOAD_DIRTY="1")
    assert r.returncode == 0, r.stderr
    assert s.read("ref.hassecret").strip() == "no"
    assert len(s.read("ref.parents").split()) == 2  # itself and HEAD: no index commit in the history
    # the secret is not reachable from the pushed ref at all
    out = subprocess.run(["git", "log", "-p", s.read("ref").strip()], cwd=s.work, capture_output=True, text=True).stdout
    assert "SECRETXYZ" not in out


@needs_gitleaks
def test_a_secret_in_the_dirty_diff_stops_the_offload(s):
    (s.work / "tests" / "test_a.py").write_text(f'TOKEN = "{FAKE_TOKEN}"\ndef test_x(): pass\n')
    r = s.bg(BG_OFFLOAD_DIRTY="1", BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert "gitleaks found a possible secret" in r.stderr
    assert FAKE_TOKEN not in r.stderr and FAKE_TOKEN not in r.stdout  # redacted
    assert s.read("runner.calls") == ""


def test_a_dirty_tree_without_gitleaks_is_not_pushed(s):
    (s.work / "tests" / "test_a.py").write_text("def test_x(): assert 1 == 1  # edited\n")
    r = s.bg(BG_OFFLOAD_DIRTY="1", BG_GITLEAKS=str(s.root / "no-gitleaks"), BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert "gitleaks not found" in r.stderr
    assert s.read("runner.calls") == ""


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
    r = subprocess.run([str(OFFLOAD), "--probe", str(s.root / "wt")], env={**os.environ, "BG_OFFLOAD_TESTING": "1", "BG_GH": str(s.home / "fakebin" / "gh")})
    assert r.returncode != 0
    r = subprocess.run([str(OFFLOAD), "--probe", str(s.work)], env={**os.environ, "BG_OFFLOAD_TESTING": "1", "BG_GH": str(s.home / "fakebin" / "gh")})
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
    assert "CI workflow PASSED" not in r.stdout


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


def test_a_named_test_outside_the_repo_is_not_offloaded(s):
    other = s.root / "elsewhere"
    other.mkdir()
    (other / "test_b.py").write_text("def test_b(): assert False\n")
    r = s.bg(str(s.home / "fakebin" / "pytest"), str(other / "test_b.py"), BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert "is outside the repo" in r.stderr
    assert s.read("runner.calls") == ""


def test_every_run_skipped_is_no_verdict(s):
    (s.state / "runs.json").write_text(json.dumps([run(18, conclusion="skipped"), run(19, conclusion="neutral")]))
    r = s.bg()
    assert r.returncode == 77, r.stderr
    assert "nothing was tested" in r.stderr
    assert "PASSED" not in r.stdout


def test_a_skipped_run_next_to_a_success_still_passes(s):
    (s.state / "runs.json").write_text(json.dumps([run(20, conclusion="skipped"), run(21)]))
    r = s.bg()
    assert r.returncode == 0, r.stderr
    assert "1 of 2 run(s) succeeded" in r.stdout


@pytest.mark.parametrize("status", ["queued", "waiting", "in_progress", "pending", "requested"])
def test_an_unfinished_status_keeps_polling(s, status):
    (s.state / "runs.json").write_text(json.dumps([run(22, status=status, conclusion=None)]))
    r = s.bg(BG_OFFLOAD_WAIT="1")
    assert r.returncode == 76, r.stderr
    assert "actions/runs/22" in r.stderr  # the run URL, not its name (the "" conclusion must not shift fields)


@pytest.mark.parametrize("garbage", [
    "overlay nothex for x -> o b\npushed https://github.com/djbclark/stubrepo/tree/ci/run/x-abc\n",
    f"overlay {COMMIT} for x -> o b\npushed https://github.com/a/b/c/tree/ci/run/x-abc\n",
    f"overlay {COMMIT} for x -> o b\npushed https://github.com/djbclark/stubrepo/tree/x;touch$IFS/tmp/pwn\n",
    f"overlay {COMMIT[:39]} for x -> o b\npushed https://github.com/djbclark/stubrepo/tree/ci/run/x-abc\n",
    "nothing useful\n",
])
def test_malformed_runner_output_is_no_verdict_and_gh_is_never_called(s, garbage):
    (s.state / "runner.garbage").write_text(garbage)
    r = s.bg()
    assert r.returncode == 77, r.stderr
    assert s.read("gh.calls") == ""


def test_transient_gh_errors_do_not_add_up(s):
    # four failures, a good poll that sees the run still going, four more failures, then it finishes: the
    # error count must reset on the good poll, or the 5th failure overall would end it with 77.
    (s.state / "gh.fail").write_text("4\n")
    (s.state / "runs.json").write_text(json.dumps([run(23, status="in_progress", conclusion=None)]))
    import threading

    def finish():
        time.sleep(3)
        (s.state / "gh.fail").write_text("4\n")
        (s.state / "runs.json").write_text(json.dumps([run(23)]))

    t = threading.Thread(target=finish)
    t.start()
    r = s.bg(BG_OFFLOAD_WAIT="60")
    t.join()
    assert r.returncode == 0, r.stderr


def test_killing_bg_stops_the_offload_poller(s):
    (s.state / "runs.json").write_text(json.dumps([run(24, status="in_progress", conclusion=None)]))
    e = {**os.environ, "HOME": str(s.home), "BASH_ENV": str(s.state / "sleep-shim.sh"),
         "BG_OFFLOAD_TESTING": "1", "BG_GH": str(s.home / "fakebin" / "gh"), "BG_MAX_LOAD_PER_CORE": "1000", "BG_MAX_WAIT": "60",
         "BG_OFFLOAD_AFTER": "1", "BG_PING_CMD": "/usr/bin/true", "BG_OFFLOAD_WAIT": "120"}
    e.pop("BG_LOAD_WAIT", None)
    tdir = s.root / "tmpdir"
    tdir.mkdir()
    e["TMPDIR"] = str(tdir)
    p = subprocess.Popen([str(BG), str(s.home / "fakebin" / "pytest"), "tests/test_a.py"], cwd=s.work, env=e,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ppid = None
    for _ in range(100):
        if (s.state / "gh.ppid").exists() and (s.state / "gh.ppid").read_text().strip():
            ppid = int(s.read("gh.ppid"))
            break
        time.sleep(0.2)
    assert ppid, "the poller never started"
    os.kill(ppid, 0)  # alive: the helper is polling
    p.send_signal(signal.SIGTERM)
    p.wait(timeout=20)
    for _ in range(50):
        try:
            os.kill(ppid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.2)
    else:
        os.kill(ppid, signal.SIGKILL)
        pytest.fail("bg-offload kept polling after bg was killed")
    # and its TERM trap ran its cleanup: a default TERM death would leave the temp dir behind
    assert [x.name for x in tdir.iterdir() if x.name.startswith("bg-offload.")] == []


def test_a_failed_greadlink_never_runs_a_helper_from_the_cwd(s):
    # A repo-planted ./bg-offload must not run: with greadlink gone bg has no helper and just waits.
    planted = s.work / "bg-offload"
    planted.write_text(f"#!/bin/bash\ntouch {shlex.quote(str(s.root / 'planted-ran'))}\nexit 0\n")
    planted.chmod(0o755)
    # bg puts /opt/homebrew/bin first, so greadlink is shadowed by an exported shell function: the wrapper
    # defines it and a function wins over any file lookup.
    wrapper = s.root / "wrap.sh"
    wrapper.write_text(f'greadlink() {{ return 1; }}\nexport -f greadlink\nexec {shlex.quote(str(BG))} "$@"\n')
    e = {**os.environ, "HOME": str(s.home), "BASH_ENV": str(s.state / "sleep-shim.sh"),
         "BG_OFFLOAD_TESTING": "1", "BG_GH": str(s.home / "fakebin" / "gh"), "BG_MAX_LOAD_PER_CORE": "1000", "BG_MAX_WAIT": "4",
         "BG_OFFLOAD_AFTER": "1", "BG_PING_CMD": "/usr/bin/true"}
    e.pop("BG_LOAD_WAIT", None)
    r = subprocess.run(["bash", str(wrapper), str(s.home / "fakebin" / "pytest"), "tests/test_a.py"], cwd=s.work,
                       env=e, capture_output=True, text=True, timeout=60)
    assert r.returncode == 75, r.stderr
    assert not (s.root / "planted-ran").exists()
    assert s.read("runner.calls") == ""


def test_a_non_numeric_run_id_is_never_used_for_the_log(s):
    bad = run("12;touch", conclusion="failure")
    (s.state / "runs.json").write_text(json.dumps([bad]))
    r = s.bg()
    assert r.returncode == 77, r.stderr
    assert "odd run id" in r.stderr
    assert not any(c.startswith("run view") for c in s.read("gh.calls").splitlines())


def _new_file_commit(s, name, data):
    (s.work / name).write_bytes(data)
    s.commit_all(f"add {name}")


@needs_gitleaks
def test_a_binary_changed_file_is_not_published(s):
    _new_file_commit(s, "data.bin", b"\x00old\n")
    (s.work / "data.bin").write_bytes(b"\x00" + FAKE_TOKEN.encode() + b"\n")  # gitleaks cannot see into this
    r = s.bg(BG_OFFLOAD_DIRTY="1", BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert "binary to git" in r.stderr and "data.bin" in r.stderr
    assert s.read("runner.calls") == ""


@needs_gitleaks
def test_a_file_marked_minus_diff_is_not_published(s):
    (s.work / ".gitattributes").write_text("*.cfg -diff\n")
    _new_file_commit(s, "app.cfg", b"a = 1\n")
    (s.work / "app.cfg").write_text(f'token = "{FAKE_TOKEN}"\n')
    r = s.bg(BG_OFFLOAD_DIRTY="1", BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert "binary to git" in r.stderr and "app.cfg" in r.stderr
    assert s.read("runner.calls") == ""


def _token_in_test_file(s, suffix=""):
    (s.work / "tests" / "test_a.py").write_text(f'TOKEN = "{FAKE_TOKEN}"{suffix}\ndef test_x(): pass\n')


@needs_gitleaks
@pytest.mark.parametrize("how", ["planted_config", "inline_allow", "env_config", "gitleaksignore"])
def test_the_scan_cannot_be_loosened_from_the_checkout_or_the_environment(s, how):
    env = {}
    permissive = '[extend]\nuseDefault = true\n[allowlist]\npaths = [\'\'\'.*\'\'\']\n'
    if how == "planted_config":
        (s.work / ".gitleaks.toml").write_text(permissive)  # untracked, in the repo top
    if how == "env_config":
        (s.root / "permissive.toml").write_text(permissive)
        env["GITLEAKS_CONFIG"] = str(s.root / "permissive.toml")
    if how == "gitleaksignore":
        (s.work / ".gitleaksignore").write_text("0000:tests/test_a.py:github-pat:1\n")
    _token_in_test_file(s, "  # gitleaks:allow" if how == "inline_allow" else "")
    r = s.bg(BG_OFFLOAD_DIRTY="1", BG_MAX_WAIT="4", **env)
    assert r.returncode == 75, r.stderr
    assert s.read("runner.calls") == ""
    assert ("gitleaksignore" in r.stderr) if how == "gitleaksignore" else ("possible secret" in r.stderr)


@needs_gitleaks
def test_gitleaks_runs_hardened_and_never_shows_the_secret(s):
    _token_in_test_file(s)
    (s.root / "permissive.toml").write_text("[allowlist]\npaths = ['''.*''']\n")
    r = s.bg(BG_OFFLOAD_DIRTY="1", BG_MAX_WAIT="4", BG_GITLEAKS=s.gl_wrapper(), GITLEAKS_CONFIG=str(s.root / "permissive.toml"))
    assert r.returncode == 75, r.stderr
    args = s.read("gl.args").split("\n")
    assert "--redact" in args and "--ignore-gitleaks-allow" in args
    cfg = args[args.index("-c") + 1]
    assert Path(cfg).name == "gl.toml"
    ign = args[args.index("-i") + 1]
    assert Path(ign).name == "glignore"
    assert s.read("gl.env").strip() == ""  # GITLEAKS_* removed from its environment
    assert Path(s.read("gl.cwd").strip()).name == "glcwd"  # run from an empty directory
    # gitleaks' own full output (what --redact controls), not just what bg prints
    full = s.read("gl.full")
    assert "leaks found" in full and FAKE_TOKEN not in full and "REDACTED" in full
    assert FAKE_TOKEN not in r.stderr and FAKE_TOKEN not in r.stdout


def test_test_hooks_are_ignored_without_the_testing_variable(s):
    # An inherited BG_GITLEAKS=/usr/bin/true must not switch the scan off.
    _token_in_test_file(s)
    r = s.bg(BG_OFFLOAD_DIRTY="1", BG_MAX_WAIT="4", BG_GITLEAKS="/usr/bin/true", BG_OFFLOAD_TESTING=None)
    assert r.returncode == 75, r.stderr
    assert s.read("runner.calls") == ""
    assert s.read("gh.calls") == ""


def test_local_only_commits_are_not_published_without_the_opt_in(s):
    (s.work / "feature.txt").write_text("work in progress\n")
    s.commit_all("local feature", on_remote=False)
    r = s.bg(BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert s.read("runner.calls") == ""
    assert "not on remote origin" in r.stderr and "local feature" in r.stderr
    assert "BG_OFFLOAD_DIRTY=1" in r.stderr


@needs_gitleaks
def test_a_token_in_a_local_only_commit_is_found_with_the_opt_in(s):
    (s.work / "conf.txt").write_text(f'token = "{FAKE_TOKEN}"\n')
    s.commit_all("add conf", on_remote=False)
    r = s.bg(BG_OFFLOAD_DIRTY="1", BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert "possible secret" in r.stderr and "conf.txt" in r.stderr
    assert s.read("runner.calls") == ""


@needs_gitleaks
def test_a_clean_local_only_commit_goes_with_the_opt_in(s):
    (s.work / "feature.txt").write_text("harmless\n")
    s.commit_all("local feature", on_remote=False)
    r = s.bg(BG_OFFLOAD_DIRTY="1")
    assert r.returncode == 0, r.stderr
    assert s.read("ref").strip() == s.read("head").strip()  # HEAD itself
    assert "local-only commit(s), scanned by gitleaks" in r.stderr


@needs_gitleaks
def test_a_binary_file_in_a_local_only_commit_is_not_published(s):
    _new_file_commit(s, "blob.bin", b"\x00\x01")
    git(s.work, "update-ref", "-d", "refs/remotes/origin/main")
    git(s.work, "update-ref", "refs/remotes/origin/main", "HEAD~1")
    r = s.bg(BG_OFFLOAD_DIRTY="1", BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert "blob.bin" in r.stderr and "binary to git" in r.stderr


def test_killing_bg_stops_an_in_flight_push(s):
    (s.state / "runner.slow").write_text("")
    e = {**os.environ, "HOME": str(s.home), "BASH_ENV": str(s.state / "sleep-shim.sh"), "BG_OFFLOAD_TESTING": "1",
         "BG_GH": str(s.home / "fakebin" / "gh"), "BG_MAX_LOAD_PER_CORE": "1000", "BG_MAX_WAIT": "60",
         "BG_OFFLOAD_AFTER": "1", "BG_PING_CMD": "/usr/bin/true"}
    e.pop("BG_LOAD_WAIT", None)
    p = subprocess.Popen([str(BG), str(s.home / "fakebin" / "pytest"), "tests/test_a.py"], cwd=s.work, env=e,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if (s.state / "slow.pid").exists() and (s.state / "slow.pid").read_text().strip():
            break
        time.sleep(0.2)
    else:
        p.kill()
        pytest.fail("the slow runner never started")
    child = int(s.read("slow.pid"))
    os.kill(child, 0)  # the "push" is in flight
    p.send_signal(signal.SIGTERM)
    p.wait(timeout=20)
    time.sleep(6)  # longer than the child's 4 s sleep
    assert not (s.state / "slow.marker").exists(), "the push child finished after bg was killed"
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


def _named(s, *args, **env):
    return s.bg(str(s.home / "fakebin" / "pytest"), *args, BG_MAX_WAIT="4", **env)


def test_a_named_test_that_does_not_exist_is_not_offloaded(s):
    r = _named(s, "tests/test_typo.py::test_x")
    assert r.returncode == 75, r.stderr
    assert "does not exist here" in r.stderr
    assert s.read("runner.calls") == ""


def test_a_tracked_test_deleted_in_the_working_tree_is_not_offloaded(s):
    (s.work / "tests" / "test_gone.py").write_text("def test_g(): pass\n")
    s.commit_all("add gone")
    (s.work / "tests" / "test_gone.py").unlink()
    r = _named(s, "tests/test_gone.py::test_g")
    assert r.returncode == 75, r.stderr
    assert "does not exist here" in r.stderr
    assert s.read("runner.calls") == ""


def test_a_directory_outside_the_repo_with_dash_k_is_not_offloaded(s):
    other = s.root / "elsewhere"
    other.mkdir()
    (other / "test_b.py").write_text("def test_b(): assert False\n")
    r = _named(s, str(other), "-k", "test_b")
    assert r.returncode == 75, r.stderr
    assert "is outside the repo" in r.stderr
    assert s.read("runner.calls") == ""


def test_a_sibling_directory_sharing_the_repo_prefix_is_outside(s):
    sib = Path(str(s.work) + "2")
    sib.mkdir()
    (sib / "test_s.py").write_text("def test_s(): assert False\n")
    r = _named(s, str(sib / "test_s.py"))
    assert r.returncode == 75, r.stderr
    assert "is outside the repo" in r.stderr


def test_an_untracked_only_directory_with_dash_k_is_not_offloaded(s):
    (s.work / "newtests").mkdir()
    (s.work / "newtests" / "test_n.py").write_text("def test_n(): pass\n")
    r = _named(s, "newtests", "-k", "test_n")
    assert r.returncode == 75, r.stderr
    assert "has no tracked file" in r.stderr
    assert s.read("runner.calls") == ""


def test_a_tracked_directory_with_dash_k_is_offloaded(s):
    r = s.bg(str(s.home / "fakebin" / "pytest"), "tests", "-k", "test_x")
    assert r.returncode == 0, r.stderr
    assert "CI workflow PASSED" in r.stdout


def test_the_output_shape_of_shizukutendcf_github_ci_run_is_accepted(s):
    (s.state / "runner.garbage").write_text(
        f"overlay {COMMIT} for x -> origin ci/run/x-abc\n"
        "branch: https://github.com/djbclark/stubrepo/tree/ci/run/x-abc\n"
        "run: https://github.com/djbclark/stubrepo/actions/runs/11\n")
    r = s.bg()
    assert r.returncode == 0, r.stderr
    assert "CI workflow PASSED" in r.stdout
