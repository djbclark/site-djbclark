"""bin/bg offloads a held targeted test run in a `ci` repo to CI (bin/bg-offload, 2026-10-23), and since 2026-11-01
a build or full suite at once, through routes (1)-(4) of bin/bg-offload's header, with the private-macOS guard and
artifact download (tests at the end of this file).

On 2026-10-23 a 2 s pytest file sat over an hour in bg's load gate in a `ci`-mode repo at load 25-93. Now,
once the gate has held a targeted run for BG_OFFLOAD_AFTER seconds, bg hands it to bin/bg-offload, which
runs the repo's CI route on HEAD, which must already be on the remote, and exits with CI's verdict.
bg-offload publishes nothing that is not already public: a tracked change, an unpushed commit or a local ci/base ahead
of the remote's is a refusal (djbclark's ruling 2026-10-23 after three review rounds on scanning what would be pushed).

Nothing here reaches GitHub. Each run gets a throwaway HOME and a throwaway git repo, with stubs for:
  load-watch  ($HOME/src/djbclark-ade/bin/load-watch): `ci check` answers the repo's mode, `admit` exits 75
              (too hot) or whatever the codes file says, one per call, the last repeating;
  the route   (scripts/github-ci-run in the repo, called as `--no-wait REF`): records the ref and the
              test file's content in that ref, then prints the two lines the real script prints;
  gh          (BG_GH): `run list` answers from runs.json through the real jq expression bg-offload passes,
              but only for `--branch ci/run/x-abc` and no more rows than `--limit` (as the real one), `run view`
              prints failed.log. Like real gh, an unfinished run has `"conclusion": ""`.
  a remote    a real bare repository (remote.git) that the work repo pushes to, so refs/remotes/origin/* are real.
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
printf '%s\\n' "${{GITHUB_CI_REMOTE:-}}" > "$d/runner.remote"
git rev-parse HEAD > "$d/head"
printf '%s\\n' "$2" > "$d/ref"
git grep -q "SECRETXY[Z]" "$2" -- . && echo yes > "$d/ref.hassecret" || echo no > "$d/ref.hassecret"
git config --get push.followTags > "$d/cfg.followTags" 2>/dev/null; git config --get push.recurseSubmodules > "$d/cfg.recurse" 2>/dev/null
git config --get core.testmarker > "$d/cfg.marker" 2>/dev/null
if [ -f "$d/runner.overlay" ]; then git show "$(cat "$d/runner.overlay")" > "$d/overlay.out" 2>/dev/null || echo MISSING > "$d/overlay.out"; fi
if [ -f "$d/runner.push" ]; then git push -q --force "${{GITHUB_CI_REMOTE:-origin}}" "$2:refs/heads/ci/run/x-abc" || exit 3; fi
if [ -f "$d/runner.slow" ]; then
  echo $$ > "$d/runner.pid"
  # a child that outlives its parent if only the parent is killed (like the git push inside github-ci-run)
  sh -c 'echo $$ > "$0/slow.pid"; sleep 4; touch "$0/slow.marker"' "$d"
fi
if [ -f "$d/runner.garbage" ]; then cat "$d/runner.garbage"; exit 0; fi
if [ -f "$d/runner.fail" ]; then echo "runner exploded" >&2; exit 1; fi
echo "overlay {commit} for $2 -> origin ci/run/x-abc"
echo "pushed https://github.com/$(cat "$d/runner.repo" 2>/dev/null || echo djbclark/stubrepo)/tree/ci/run/x-abc"
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
    # gh.rearm: after serving one good poll, fail the next N polls and then show runs.final (no timer involved)
    if [ -f "$d/gh.rearm" ]; then
      mv "$d/gh.rearm" "$d/gh.fail"; cp "$d/runs.final" "$d/runs.json"
    fi
    ;;
  "run view") cat "$d/failed.log" ;;
  "repo view")
    # repo.private holds what `--jq .isPrivate` prints, repo.perm what `--jq .viewerPermission` prints; without the
    # file gh cannot read the repo (fail closed)
    case "$*" in *viewerPermission*) f="$d/repo.perm" ;; *) f="$d/repo.private" ;; esac
    printf '%s\\n' "$*" >> "$d/gh.repoview"
    if [ -f "$f" ]; then cat "$f"; else echo "gh: HTTP 404: Not Found" >&2; exit 1; fi
    ;;
  "run download")
    if [ -f "$d/dl.fail" ]; then echo "no valid artifacts found to download" >&2; exit 1; fi
    shift 2; dir=
    while [ $# -gt 0 ]; do case "$1" in -D) dir=$2 ;; esac; shift; done
    mkdir -p "$dir" && echo app > "$dir/app.zip"
    ;;
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
        git(self.work, "init", "-q", "-b", "main")
        git(self.work, "config", "user.name", "t")
        git(self.work, "config", "user.email", "t@example.invalid")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "init")
        self.remote = tmp_path / "remote.git"
        git(tmp_path, "init", "-q", "--bare", str(self.remote))
        git(self.work, "remote", "add", "origin", str(self.remote))
        git(self.work, "push", "-q", "origin", "main")  # HEAD is on the remote: nothing unpushed
        # origin (a local bare repo) stands in for github.com/djbclark/stubrepo, as a path and as a file:// url
        self.alias = f"{self.remote} {STUB_REPO};file://{self.remote} {STUB_REPO}"
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
             "BG_OFFLOAD_AFTER": "1", "BG_PING_CMD": "/usr/bin/true", "BG_WATCH_POLL": "1",
             # fakebin is a $PATH directory, like a real tool's: its build-app is not "another tree" (F6)
             "PATH": f"{self.home / 'fakebin'}:{os.environ['PATH']}", "BG_OFFLOAD_URL_ALIAS": self.alias, **env}
        e = {k: v for k, v in e.items() if v is not None}
        e.pop("BG_LOAD_WAIT", None)  # 0 would skip the gate under test
        cmd = argv or (str(self.home / "fakebin" / "pytest"), "tests/test_a.py")
        return subprocess.run([str(BG), *cmd], cwd=self.work, env=e, capture_output=True, text=True, timeout=120)

    def commit_all(self, msg, on_remote=True):
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", msg)
        if on_remote:
            git(self.work, "push", "-q", "origin", "HEAD:main")

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


def test_a_full_suite_in_a_ci_repo_goes_to_ci_at_once(s):
    # 2026-11-01: a non-targeted run (here a bare suite) no longer exits 3 when the repo has a CI route
    r = s.bg(str(s.home / "fakebin" / "pytest"))
    assert r.returncode == 0, r.stderr
    assert not s.marker.exists()
    assert "running it on CI now" in r.stderr and "CI workflow PASSED" in r.stdout
    assert s.read("admit.calls") == ""  # no load gate


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
    # four failures, a good poll that sees the run still going, four more failures, then it finishes: the error
    # count must reset on the good poll, or the 5th failure overall would end it with 77. The stub re-arms itself
    # after serving the good poll (gh.rearm), so the sequence does not depend on a timer or on machine load.
    (s.state / "gh.fail").write_text("4\n")
    (s.state / "gh.rearm").write_text("4\n")
    (s.state / "runs.json").write_text(json.dumps([run(23, status="in_progress", conclusion=None)]))
    (s.state / "runs.final").write_text(json.dumps([run(23)]))
    r = s.bg(BG_OFFLOAD_WAIT="60")
    assert r.returncode == 0, r.stderr
    assert len([c for c in s.read("gh.calls").splitlines() if c.startswith("run list")]) == 10  # 4 + 1 + 4 + 1


def test_killing_bg_stops_the_offload_poller(s):
    (s.state / "runs.json").write_text(json.dumps([run(24, status="in_progress", conclusion=None)]))
    e = {**os.environ, "HOME": str(s.home), "BASH_ENV": str(s.state / "sleep-shim.sh"),
         "BG_OFFLOAD_TESTING": "1", "BG_GH": str(s.home / "fakebin" / "gh"), "BG_MAX_LOAD_PER_CORE": "1000", "BG_MAX_WAIT": "60",
         "BG_OFFLOAD_AFTER": "1", "BG_PING_CMD": "/usr/bin/true", "BG_OFFLOAD_WAIT": "120", "BG_OFFLOAD_URL_ALIAS": s.alias}
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


def test_killing_bg_stops_an_in_flight_push(s):
    (s.state / "runner.slow").write_text("")
    e = {**os.environ, "HOME": str(s.home), "BASH_ENV": str(s.state / "sleep-shim.sh"), "BG_OFFLOAD_TESTING": "1",
         "BG_GH": str(s.home / "fakebin" / "gh"), "BG_MAX_LOAD_PER_CORE": "1000", "BG_MAX_WAIT": "60",
         "BG_OFFLOAD_AFTER": "1", "BG_PING_CMD": "/usr/bin/true", "BG_OFFLOAD_URL_ALIAS": s.alias}
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


# --- bg-offload publishes nothing that is not already on the remote (ruling 2026-10-23) ---------------------

def _refused(s, r, *needles):
    assert r.returncode == 75, r.stderr  # fell back to waiting at the gate; the command never ran
    assert s.read("runner.calls") == ""  # nothing was pushed or built
    assert s.read("gh.calls") == ""
    assert not s.marker.exists()
    assert "could not offload to CI" in r.stderr
    assert "commit and push" in r.stderr
    for n in needles:
        assert n in r.stderr, (n, r.stderr)


def test_a_modified_tracked_file_is_not_offloaded(s):
    (s.work / "tests" / "test_a.py").write_text("def test_x(): assert 1 == 1  # edited\n")
    r = s.bg(BG_MAX_WAIT="4")
    _refused(s, r, "1 tracked file(s) with uncommitted changes", "tests/test_a.py")
    assert "BG_OFFLOAD_DIRTY" not in r.stderr  # there is no opt-in any more


def test_a_modified_tracked_file_that_is_not_the_named_test_is_not_offloaded_either(s):
    (s.work / "README").write_text("x\n")
    s.commit_all("add README")
    (s.work / "README").write_text("y\n")
    _refused(s, s.bg(BG_MAX_WAIT="4"), "README")


def test_a_staged_change_is_not_offloaded(s):
    (s.work / "tests" / "test_a.py").write_text("def test_x(): assert 1 == 1  # staged\n")
    git(s.work, "add", "tests/test_a.py")
    _refused(s, s.bg(BG_MAX_WAIT="4"), "tests/test_a.py")


def test_a_newly_added_file_in_the_index_is_not_offloaded(s):
    (s.work / "new.txt").write_text("new\n")
    git(s.work, "add", "new.txt")
    _refused(s, s.bg(BG_MAX_WAIT="4"), "new.txt")


def test_an_unpushed_commit_is_not_offloaded(s):
    (s.work / "feature.txt").write_text("work in progress\n")
    s.commit_all("local feature", on_remote=False)
    r = s.bg(BG_MAX_WAIT="4")
    _refused(s, r, "1 commit(s) in HEAD are not on the remote origin", "local feature")


def test_ci_base_ahead_of_the_remote_is_not_offloaded(s):
    git(s.work, "checkout", "-q", "-b", "ci/base")
    (s.work / "overlay.txt").write_text("overlay\n")
    git(s.work, "add", "-A")
    git(s.work, "commit", "-q", "-m", "overlay content")
    git(s.work, "checkout", "-q", "main")  # HEAD is clean and pushed; only ci/base is local-only
    _refused(s, s.bg(BG_MAX_WAIT="4"), "refs/heads/ci/base (overlaid onto the run) has 1 commit(s) that are not on the remote")


def test_ci_base_ahead_of_a_pushed_ci_base_is_not_offloaded(s):
    git(s.work, "checkout", "-q", "-b", "ci/base")
    git(s.work, "push", "-q", "origin", "ci/base")
    (s.work / "overlay.txt").write_text("overlay\n")
    git(s.work, "add", "-A")
    git(s.work, "commit", "-q", "-m", "more overlay")
    git(s.work, "checkout", "-q", "main")
    _refused(s, s.bg(BG_MAX_WAIT="4"), "refs/heads/ci/base (overlaid onto the run) has 1 commit(s) that are not on the remote")


def test_ci_base_that_is_pushed_does_not_block(s):
    git(s.work, "checkout", "-q", "-b", "ci/base")
    (s.work / "overlay.txt").write_text("overlay\n")
    git(s.work, "add", "-A")
    git(s.work, "commit", "-q", "-m", "overlay content")
    git(s.work, "push", "-q", "origin", "ci/base")
    git(s.work, "checkout", "-q", "main")
    r = s.bg()
    assert r.returncode == 0, r.stderr
    assert s.read("runner.calls").strip() == f"--no-wait {s.read('head').strip()}"


def test_a_ci_base_at_an_already_pushed_commit_does_not_block(s):
    git(s.work, "branch", "ci/base")  # a local branch with no remote copy, but all its commits are public
    r = s.bg()
    assert r.returncode == 0, r.stderr


def test_a_head_that_is_only_on_a_remote_branch_is_offloaded(s):
    git(s.work, "checkout", "-q", "-b", "feature")
    (s.work / "tests" / "test_a.py").write_text("def test_x(): assert True  # pushed on feature\n")
    git(s.work, "add", "-A")
    git(s.work, "commit", "-q", "-m", "feature work")
    git(s.work, "push", "-q", "origin", "feature")
    git(s.work, "checkout", "-q", "main")
    git(s.work, "checkout", "-q", "--detach", "origin/feature")
    r = s.bg()
    assert r.returncode == 0, r.stderr
    assert s.read("ref").strip() == s.read("head").strip()  # HEAD itself, never a new commit
    assert "already on origin" in r.stderr


def test_untracked_files_do_not_block_and_are_not_pushed(s):
    (s.work / "notes.txt").write_text("SECRETXYZ untracked\n")
    r = s.bg()
    assert r.returncode == 0, r.stderr
    assert s.read("ref").strip() == s.read("head").strip()  # HEAD itself
    assert s.read("ref.hassecret").strip() == "no"
    assert "?? notes.txt" in r.stderr and "untracked files" in r.stderr
    assert (s.work / "notes.txt").exists()


def test_a_refusal_reports_every_reason_and_caps_the_dirty_list(s):
    for i in range(25):
        (s.work / f"f{i:02d}.txt").write_text("a\n")
    s.commit_all("many files")
    for i in range(25):
        (s.work / f"f{i:02d}.txt").write_text("b\n")
    (s.work / "unpushed.txt").write_text("u\n")
    git(s.work, "add", "unpushed.txt")
    git(s.work, "commit", "-q", "-m", "unpushed one")
    git(s.work, "branch", "ci/base")
    git(s.work, "checkout", "-q", "ci/base")
    (s.work / "o.txt").write_text("o\n")
    git(s.work, "add", "o.txt")
    git(s.work, "commit", "-q", "-m", "overlay")
    git(s.work, "checkout", "-q", "main")
    r = s.bg(BG_MAX_WAIT="4")
    _refused(s, r, "25 tracked file(s) with uncommitted changes", "... and 5 more", "unpushed one", "refs/heads/ci/base (overlaid onto the run) has 2 commit(s) that are not on the remote")


def test_hooks_are_ignored_without_the_testing_variable(s):
    # BG_OFFLOAD_RUNNER must not give a repo without a route one: only with BG_OFFLOAD_TESTING=1.
    s.route(False)
    hook = s.root / "hook-runner"
    hook.write_text("#!/bin/bash\nexit 0\n")
    hook.chmod(0o755)
    base = {**os.environ, "BG_GH": str(s.home / "fakebin" / "gh"), "BG_OFFLOAD_RUNNER": str(hook)}
    on = subprocess.run([str(OFFLOAD), "--probe", str(s.work)], env={**base, "BG_OFFLOAD_TESTING": "1"})
    assert on.returncode == 0  # control: with the variable the hook is the route
    off = subprocess.run([str(OFFLOAD), "--probe", str(s.work)], env={k: v for k, v in base.items() if k != "BG_OFFLOAD_TESTING"})
    assert off.returncode != 0


def test_a_ci_base_ahead_of_the_remotes_ci_base_by_commits_that_are_public_offloads(s):
    # What is checked is what the push target advertises (any ref), not the remote-tracking name: these commits are on main.
    git(s.work, "branch", "ci/base")
    git(s.work, "push", "-q", "origin", "ci/base")
    (s.work / "more.txt").write_text("m\n")
    s.commit_all("more on main")  # pushed to main
    git(s.work, "branch", "-f", "ci/base", "HEAD")
    r = s.bg()
    assert r.returncode == 0, r.stderr


def test_the_remote_is_the_one_the_runners_use(s):
    other = s.root / "mirror.git"
    git(s.root, "init", "-q", "--bare", str(other))
    git(s.work, "remote", "add", "mirror", str(other))
    git(s.work, "fetch", "-q", "mirror")  # an empty remote: HEAD is on origin, not on mirror
    _refused(s, s.bg(BG_MAX_WAIT="4", GITHUB_CI_REMOTE="mirror"), "not on the remote mirror")
    r = s.bg()  # control: origin (the default)
    assert r.returncode == 0, r.stderr


def test_commit_and_push_then_retry_offloads(s):
    (s.work / "tests" / "test_a.py").write_text("def test_x(): assert 1 == 1  # edited\n")
    _refused(s, s.bg(BG_MAX_WAIT="4"), "tests/test_a.py")
    s.commit_all("edit test")  # the dev flow the refusal asks for
    r = s.bg()
    assert r.returncode == 0, r.stderr
    assert s.read("ref").strip() == subprocess.run(["git", "rev-parse", "HEAD"], cwd=s.work, capture_output=True, text=True).stdout.strip()


def test_a_failed_ci_base_comparison_counts_as_ahead(s):
    git(s.work, "branch", "ci/base")
    git(s.work, "push", "-q", "origin", "ci/base")
    ref = s.work / ".git" / "refs" / "heads" / "ci" / "base"
    ref.write_text("b" * 40 + "\n")  # a local ci/base whose object is missing: show-ref sees it, rev-list fails
    r = s.bg(BG_MAX_WAIT="4")
    _refused(s, r, "could not read ci/base")


def test_an_unreadable_remote_tracking_ci_base_is_refused_when_it_is_the_one_the_runner_uses(s):
    git(s.work, "branch", "ci/base")
    git(s.work, "push", "-q", "origin", "ci/base")
    git(s.work, "branch", "-D", "ci/base")  # no local ci/base: the runner falls back to origin/ci/base
    (s.work / ".git" / "refs" / "remotes" / "origin" / "ci" / "base").write_text("b" * 40 + "\n")
    r = s.bg(BG_MAX_WAIT="4")
    _refused(s, r, "could not read ci/base")


def test_a_remote_tracking_ci_base_that_is_on_the_remote_is_fine_without_a_local_one(s):
    git(s.work, "branch", "ci/base")
    git(s.work, "push", "-q", "origin", "ci/base")
    git(s.work, "branch", "-D", "ci/base")
    r = s.bg()
    assert r.returncode == 0, r.stderr


def test_a_stale_remote_tracking_ci_base_is_refused(s):
    # origin/ci/base carries a commit that another clone has since removed from the remote.
    git(s.work, "checkout", "-q", "-b", "ci/base")
    (s.work / "overlay.txt").write_text("overlay\n")
    git(s.work, "add", "-A")
    git(s.work, "commit", "-q", "-m", "overlay content")
    git(s.work, "push", "-q", "origin", "ci/base")
    git(s.work, "checkout", "-q", "main")
    git(s.work, "branch", "-D", "ci/base")
    git(s.remote, "update-ref", "-d", "refs/heads/ci/base")  # the remote no longer has it; the tracking ref stays
    _refused(s, s.bg(BG_MAX_WAIT="4"), "refs/remotes/origin/ci/base (overlaid onto the run) has 1 commit(s)")


def test_a_ci_base_whose_history_cannot_be_walked_counts_as_ahead(s):
    git(s.work, "branch", "ci/base")
    git(s.work, "push", "-q", "origin", "ci/base")  # origin/ci/base is readable
    tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=s.work, capture_output=True, text=True).stdout.strip()
    body = f"tree {tree}\nparent {'c' * 40}\nauthor t <t@example.invalid> 1 +0000\ncommitter t <t@example.invalid> 1 +0000\n\nbroken\n"
    sha = subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin", "--literally"], cwd=s.work, input=body,
                         capture_output=True, text=True, check=True).stdout.strip()
    git(s.work, "update-ref", "refs/heads/ci/base", sha)  # readable ref, but its parent object is missing: rev-list fails
    r = s.bg(BG_MAX_WAIT="4")
    _refused(s, r, "could not compare refs/heads/ci/base")


# --- review 4 (ae917f7): the push target is asked, not guessed; push config cannot widen the push -------------

def _bare(s, name):
    p = s.root / name
    git(s.root, "init", "-q", "--bare", str(p))
    return p


def _commit_on_new_branch(s, branch, name="private.txt"):
    git(s.work, "checkout", "-q", "-b", branch)
    (s.work / name).write_text("private\n")
    git(s.work, "add", "-A")
    git(s.work, "commit", "-q", "-m", f"work on {branch}")


def test_a_commit_removed_from_the_remote_by_another_clone_is_not_on_the_remote(s):
    _commit_on_new_branch(s, "oops")
    git(s.work, "push", "-q", "origin", "oops")  # refs/remotes/origin/oops now exists here
    git(s.remote, "update-ref", "-d", "refs/heads/oops")  # another clone deleted the branch on the remote
    git(s.work, "checkout", "-q", "--detach", "oops")
    assert subprocess.run(["git", "rev-parse", "--verify", "-q", "refs/remotes/origin/oops"], cwd=s.work).returncode == 0
    _refused(s, s.bg(BG_MAX_WAIT="4"), "commit(s) in HEAD are not on the remote origin", "work on oops")


def test_after_set_url_the_old_remote_tracking_refs_prove_nothing(s):
    public = _bare(s, "public.git")
    _commit_on_new_branch(s, "private-work")
    git(s.work, "push", "-q", "origin", "private-work")  # pushed to the PRIVATE origin
    git(s.work, "remote", "set-url", "origin", str(public))  # origin is now the public repo; old tracking refs stay
    _refused(s, s.bg(BG_MAX_WAIT="4"), "not on the remote origin", "work on private-work")
    assert subprocess.run(["git", "branch", "-a", "--list"], cwd=public, capture_output=True, text=True).stdout.strip() == ""


def test_a_separate_pushurl_is_refused(s):
    public = _bare(s, "public.git")
    git(s.work, "config", "remote.origin.pushurl", str(public))
    _refused(s, s.bg(BG_MAX_WAIT="4"), "does not have exactly one url")


def test_several_push_urls_are_refused(s):
    git(s.work, "config", "--add", "remote.origin.pushurl", str(s.remote))
    git(s.work, "config", "--add", "remote.origin.pushurl", str(_bare(s, "other.git")))
    _refused(s, s.bg(BG_MAX_WAIT="4"), "does not have exactly one url")


def test_a_push_insteadof_rewrite_is_refused(s):
    other = _bare(s, "rewritten.git")
    git(s.work, "config", f"url.{other}/.pushInsteadOf", str(s.remote))
    _refused(s, s.bg(BG_MAX_WAIT="4"), "does not have exactly one url")


def test_an_unreachable_push_target_fails_closed(s):
    git(s.work, "remote", "set-url", "origin", str(s.root / "no-such-remote.git"))
    _refused(s, s.bg(BG_MAX_WAIT="4"), "could not list the refs at the push target")


def test_the_url_of_a_failing_remote_is_not_echoed_with_credentials(s):
    # git prints a failing local-path url as given (it masks https passwords itself, so this is the form that can leak)
    git(s.work, "remote", "set-url", "origin", f"{s.root}/nowhere//user:s3cr3t@host/x.git")
    r = s.bg(BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert "could not list the refs" in r.stderr
    assert "s3cr3t" not in r.stderr and "s3cr3t" not in r.stdout
    assert s.read("runner.calls") == ""


def test_the_runner_push_cannot_carry_tags_or_submodule_commits_whatever_the_config_says(s):
    git(s.work, "config", "push.followTags", "true")
    git(s.work, "config", "push.recurseSubmodules", "on-demand")
    git(s.work, "tag", "-a", "v-internal", "-m", "internal tag", "HEAD")
    (s.state / "runner.push").write_text("")  # the stub really pushes HEAD to ci/run/x-abc, like the real runners
    # sanity: the same push WITHOUT the helper's override does carry the tag (so the test can see the leak)
    subprocess.run(["git", "push", "-q", "--force", "origin", "HEAD:refs/heads/ci/run/probe"], cwd=s.work, check=True, capture_output=True)
    assert "v-internal" in subprocess.run(["git", "tag", "-l"], cwd=s.remote, capture_output=True, text=True).stdout
    git(s.remote, "tag", "-d", "v-internal")
    r = s.bg()
    assert r.returncode == 0, r.stderr
    assert s.read("cfg.followTags").strip() == "false" and s.read("cfg.recurse").strip() == "no"
    assert subprocess.run(["git", "tag", "-l"], cwd=s.remote, capture_output=True, text=True).stdout.strip() == ""
    assert "ci/run/x-abc" in subprocess.run(["git", "branch", "--list"], cwd=s.remote, capture_output=True, text=True).stdout


def test_the_callers_own_git_config_env_entries_are_kept(s):
    r = s.bg(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.testmarker", GIT_CONFIG_VALUE_0="kept")
    assert r.returncode == 0, r.stderr
    assert s.read("cfg.marker").strip() == "kept"
    assert s.read("cfg.followTags").strip() == "false"


def test_an_untracked_route_script_is_never_used(s):
    mark = s.root / "untracked-route-ran"
    (s.work / "scripts" / "bg-offload-run").write_text(f"#!/bin/bash\ntouch {shlex.quote(str(mark))}\n"
                                                      f"echo 'overlay {COMMIT} for x -> origin ci/run/x-abc'\n"
                                                      "echo 'pushed https://github.com/djbclark/stubrepo/tree/ci/run/x-abc'\n")
    (s.work / "scripts" / "bg-offload-run").chmod(0o755)
    r = s.bg()
    assert r.returncode == 0, r.stderr
    assert not mark.exists()
    assert s.read("runner.calls").strip() == f"--no-wait {s.read('head').strip()}"  # the tracked github-ci-run


def test_an_untracked_route_script_alone_is_no_route(s):
    # the tracked route is removed from git and the work tree: only an untracked script is left
    git(s.work, "rm", "-q", "-f", "scripts/github-ci-run")
    git(s.work, "commit", "-q", "-m", "drop route")
    git(s.work, "push", "-q", "origin", "HEAD:main")
    (s.work / "scripts").mkdir(exist_ok=True)
    (s.work / "scripts" / "bg-offload-run").write_text("#!/bin/bash\nexit 0\n")
    (s.work / "scripts" / "bg-offload-run").chmod(0o755)
    r = s.bg(BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert "unless the load gate" not in r.stderr


def test_a_missing_required_tool_refuses_instead_of_passing(s):
    e = {**os.environ, "HOME": str(s.home), "BG_OFFLOAD_TESTING": "1", "BG_GH": str(s.home / "fakebin" / "gh"),
         "BG_OFFLOAD_TOOLS_EXTRA": "no-such-tool-xyz"}
    r = subprocess.run([str(OFFLOAD), str(s.work), "--", "pytest", "tests/test_a.py"], cwd=s.work, env=e, capture_output=True, text=True, timeout=60)
    assert r.returncode == 69, r.stderr
    assert "required tool 'no-such-tool-xyz' not found" in r.stderr
    assert s.read("runner.calls") == "" and s.read("gh.calls") == ""
    p = subprocess.run([str(OFFLOAD), "--probe", str(s.work)], env=e, capture_output=True, text=True)
    assert p.returncode != 0  # and bg's up-front probe says no
    e.pop("BG_OFFLOAD_TOOLS_EXTRA")
    assert subprocess.run([str(OFFLOAD), "--probe", str(s.work)], env=e).returncode == 0  # control


@pytest.mark.parametrize("remote", ["*", "-x", "a b", "o;touch x"])
def test_an_odd_remote_name_is_refused(s, remote):
    r = s.bg(BG_MAX_WAIT="4", GITHUB_CI_REMOTE=remote)
    assert r.returncode == 75, r.stderr
    assert "odd remote name" in r.stderr
    assert s.read("runner.calls") == ""


@pytest.mark.parametrize("cmd", [("python3", "-m", "pytest"), ("python3", "-m", "unittest"), ("py.test",), ("pytest",), ("/usr/local/bin/pytest",)])
def test_an_untracked_test_is_found_whichever_way_pytest_is_spelled(s, cmd):
    (s.work / "tests" / "test_new.py").write_text("def test_n(): pass\n")
    r = s.bg(*cmd, "tests/test_new.py", BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert "tests/test_new.py is untracked" in r.stderr
    assert s.read("runner.calls") == ""


def test_a_head_whose_history_cannot_be_walked_is_refused(s):
    tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=s.work, capture_output=True, text=True).stdout.strip()
    body = f"tree {tree}\nparent {'c' * 40}\nauthor t <t@example.invalid> 1 +0000\ncommitter t <t@example.invalid> 1 +0000\n\nbroken\n"
    sha = subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin", "--literally"], cwd=s.work, input=body,
                         capture_output=True, text=True, check=True).stdout.strip()
    git(s.work, "update-ref", "--no-deref", "HEAD", sha)
    r = s.bg(BG_MAX_WAIT="4")
    assert r.returncode == 75, r.stderr
    assert s.read("runner.calls") == ""


def test_a_remote_with_two_urls_is_refused(s):
    # `git push origin` goes to every url of a remote: fetch url == push url but there are two of them.
    git(s.work, "config", "--add", "remote.origin.url", str(_bare(s, "second.git")))
    _refused(s, s.bg(BG_MAX_WAIT="4"), "does not have exactly one url")


def test_a_head_that_is_only_reachable_from_a_pushed_annotated_tag_is_on_the_remote(s):
    _commit_on_new_branch(s, "tagged-work")
    git(s.work, "tag", "-a", "v9", "-m", "release")
    git(s.work, "push", "-q", "origin", "v9")  # the tag only; no branch has the commit
    git(s.work, "checkout", "-q", "--detach", "v9")
    git(s.work, "branch", "-D", "tagged-work")
    r = s.bg()
    assert r.returncode == 0, r.stderr
    assert "already on origin" in r.stderr


# --- review 5 (75dbe21): the checked target is the pushed target; the walked history is the pushed history ------

def _tags(repo):
    return subprocess.run(["git", "tag", "-l"], cwd=repo, capture_output=True, text=True).stdout.strip()


def _has(repo, sha):
    return subprocess.run(["git", "cat-file", "-e", sha], cwd=repo, capture_output=True).returncode == 0


def _head(repo):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def test_an_insteadof_chain_cannot_make_ls_remote_ask_another_repo_than_the_push(s):
    # origin = stubalias:x -> (insteadOf) public; public -> (insteadOf) the private remote. get-url prints the public
    # path; ls-remote of that STRING is rewritten again, to the private remote, which has the commit. `git push origin`
    # (the runner) rewrites once and goes to public.
    public = _bare(s, "public.git")
    (s.work / "private.txt").write_text("SECRETXYZ\n")
    s.commit_all("private commit")  # on the private remote (s.remote) only
    p = _head(s.work)
    git(s.work, "remote", "set-url", "origin", "stubalias:x")
    git(s.work, "config", f"url.{public}.insteadOf", "stubalias:x")
    git(s.work, "config", f"url.{s.remote}.insteadOf", str(public))
    (s.state / "runner.push").write_text("")
    _refused(s, s.bg(BG_MAX_WAIT="4"), "not on the remote origin", "private commit")
    assert not _has(public, p)


def test_a_replace_ref_cannot_hide_a_private_parent(s):
    t = _head(s.work)  # on the remote
    _commit_on_new_branch(s, "priv")
    p = _head(s.work)
    tree = subprocess.run(["git", "rev-parse", f"{t}^{{tree}}"], cwd=s.work, capture_output=True, text=True, check=True).stdout.strip()
    r = subprocess.run(["git", "commit-tree", tree, "-p", p, "-m", "base"], cwd=s.work, capture_output=True, text=True, check=True).stdout.strip()
    git(s.work, "replace", t, r)  # t now "has" parent p, so `rev-list HEAD ^t` counts 0
    assert subprocess.run(["git", "rev-list", "--count", "HEAD", f"^{t}"], cwd=s.work, capture_output=True, text=True).stdout.strip() == "0"
    (s.state / "runner.push").write_text("")
    _refused(s, s.bg(BG_MAX_WAIT="4"), "1 commit(s) in HEAD are not on the remote origin", "work on priv")
    assert not _has(s.remote, p)


@pytest.mark.parametrize("where", ["info", "env"])
def test_a_graft_file_is_refused(s, where):
    t = _head(s.work)
    _commit_on_new_branch(s, "priv")
    p = _head(s.work)
    if where == "info":
        graft, env = s.work / ".git" / "info" / "grafts", {}
    else:
        graft = s.root / "grafts"
        env = {"GIT_GRAFT_FILE": str(graft)}
    graft.parent.mkdir(exist_ok=True)
    graft.write_text(f"{t} {p}\n")  # t "has" parent p
    (s.state / "runner.push").write_text("")
    _refused(s, s.bg(BG_MAX_WAIT="4", **env), "a graft file", str(graft.name))
    assert not _has(s.remote, p)


def test_a_callers_git_config_parameters_cannot_turn_follow_tags_back_on(s):
    git(s.work, "tag", "-a", "v9-private", "-m", "unpublished tag", "HEAD")
    (s.state / "runner.push").write_text("")
    r = s.bg(GIT_CONFIG_PARAMETERS="'push.followtags'='true' 'push.recursesubmodules'='on-demand' 'core.testmarker'='kept'")
    assert r.returncode == 0, r.stderr
    assert s.read("cfg.followTags").strip() == "false" and s.read("cfg.recurse").strip() == "no"
    assert s.read("cfg.marker").strip() == "kept"  # the caller's other entries stay
    assert _tags(s.remote) == ""
    assert "ci/run/x-abc" in subprocess.run(["git", "branch", "--list"], cwd=s.remote, capture_output=True, text=True).stdout


def test_a_leading_zero_git_config_count_still_gets_the_override(s):
    env = {"GIT_CONFIG_COUNT": "08", **{f"GIT_CONFIG_KEY_{i}": f"core.x{i}" for i in range(8)},
           **{f"GIT_CONFIG_VALUE_{i}": "v" for i in range(8)}, "GIT_CONFIG_KEY_7": "push.followTags", "GIT_CONFIG_VALUE_7": "true"}
    git(s.work, "tag", "-a", "v9-private", "-m", "unpublished tag", "HEAD")
    (s.state / "runner.push").write_text("")
    r = s.bg(**env)
    assert r.returncode == 0, r.stderr
    assert "value too great" not in r.stderr
    assert s.read("cfg.followTags").strip() == "false"
    assert _tags(s.remote) == ""


def _offload(s, cwd, cmd=("pytest", "tests/test_a.py"), **env):
    e = {**os.environ, "HOME": str(s.home), "BG_OFFLOAD_TESTING": "1", "BG_GH": str(s.home / "fakebin" / "gh"),
         "BG_OFFLOAD_RUNNER": str(s.work / "scripts" / "github-ci-run"), "BG_OFFLOAD_POLL": "0",
         "BG_OFFLOAD_URL_ALIAS": s.alias, **env}
    return subprocess.run([str(OFFLOAD), str(cwd), "--", *cmd], cwd=cwd, env=e,
                          capture_output=True, text=True, timeout=60)


def test_a_failing_git_status_refuses(s):
    (s.work / ".git" / "index").write_bytes(b"garbage")  # every index read fails; HEAD and the remote are fine
    r = _offload(s, s.work, cmd=("pytest",))  # no test path: the path check (which reads the index too) is not reached
    assert r.returncode == 69, r.stderr
    assert "git status failed" in r.stderr
    assert s.read("runner.calls") == "" and s.read("gh.calls") == ""


def _other_clone_pushes(s, branch="other"):
    other = s.root / "other"
    git(s.root, "clone", "-q", str(s.remote), str(other))
    git(other, "config", "user.name", "o")
    git(other, "config", "user.email", "o@example.invalid")
    (other / "o.txt").write_text("o\n")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "other")
    git(other, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
    return _head(other)


def test_an_advertised_tip_missing_here_is_skipped_not_fatal(s):
    x = _other_clone_pushes(s)
    assert not _has(s.work, x)
    r = s.bg()
    assert r.returncode == 0, r.stderr  # HEAD is on the remote; the unknown tip is not an exclusion, nor an error
    assert "already on origin" in r.stderr
    assert not _has(s.work, x)


def test_a_partial_clone_never_lazy_fetches_an_advertised_tip(s):
    git(s.remote, "config", "uploadpack.allowFilter", "true")
    git(s.remote, "config", "uploadpack.allowAnySHA1InWant", "true")
    part = s.root / "partial"
    git(s.root, "clone", "-q", "-b", "main", "--filter=blob:none", f"file://{s.remote}", str(part))
    x = _other_clone_pushes(s)
    r = _offload(s, part)
    assert r.returncode == 0, r.stderr
    assert subprocess.run(["git", "cat-file", "-e", x], cwd=part, capture_output=True,
                          env={**os.environ, "GIT_NO_LAZY_FETCH": "1"}).returncode != 0


# --- review 6 (2d037f7): the runner reads the ci/base overlay in a partial clone; nothing it reads may be missing ---

def _partial_clone_with_a_base_only_blob(s, allow_any_want=True):
    git(s.work, "checkout", "-q", "-b", "ci/base")
    (s.work / "base-only.txt").write_text("overlay from ci/base\n")
    git(s.work, "add", "-A")
    git(s.work, "commit", "-q", "-m", "ci/base overlay")
    git(s.work, "push", "-q", "origin", "ci/base")
    git(s.work, "checkout", "-q", "main")
    git(s.remote, "config", "uploadpack.allowFilter", "true")
    git(s.remote, "config", "uploadpack.allowAnySHA1InWant", "true" if allow_any_want else "false")
    part = s.root / "partial"
    git(s.root, "clone", "-q", "-b", "main", "--filter=blob:none", f"file://{s.remote}", str(part))
    git(part, "branch", "-q", "ci/base", "origin/ci/base")  # fetched, never checked out: its blob is not here
    objs = subprocess.run(["git", "rev-list", "--objects", "--missing=print", "ci/base^{tree}"], cwd=part,
                          capture_output=True, text=True, check=True, env={**os.environ, "GIT_NO_LAZY_FETCH": "1"}).stdout
    assert any(l.startswith("?") for l in objs.splitlines())  # the test really has a missing overlay blob
    (s.state / "runner.overlay").write_text("ci/base:base-only.txt\n")
    return part


def test_the_runner_can_read_the_ci_base_overlay_in_a_partial_clone(s):
    part = _partial_clone_with_a_base_only_blob(s)
    r = _offload(s, part)
    assert r.returncode == 0, r.stderr
    assert s.read("overlay.out") == "overlay from ci/base\n"  # 2d037f7: MISSING (GIT_NO_LAZY_FETCH reached the runner)
    assert "fetching them" in r.stderr


def test_an_overlay_object_that_cannot_be_fetched_refuses_before_the_runner(s):
    part = _partial_clone_with_a_base_only_blob(s, allow_any_want=False)
    git(part, "config", "protocol.version", "0")  # v0 refuses a want for an unadvertised blob: the fetch fails
    r = _offload(s, part)
    assert r.returncode == 69, r.stderr
    assert "are missing here and could not be fetched" in r.stderr
    assert s.read("runner.calls") == "" and s.read("gh.calls") == ""


# --- 2026-11-01: builds and full suites in a `ci` repo go to CI at once (A); route (3) Forgejo and route (4) generic
# GitHub (B); GitHub macOS runners for public repos only (C); artifacts after a success (D); and the fixes for the
# adversary review of 9090cc2 (F1-F12) ---

STUB_REPO = "https://github.com/djbclark/stubrepo.git"

# scripts/forgejo-ci-run only opts a repo into route (3); bg-offload never runs it (F3)
FORGEJO_RUNNER = """#!/bin/bash
touch {state}/fj.ran
"""

# the Forgejo wait tool (wait-run.sh SHA OUT): writes OUT and OUT.status like the real one
FORGEJO_WAIT = """#!/bin/bash
d={state}
printf '%s %s RP=%s WAIT_MAX=%s\\n' "$1" "$2" "$RP" "$WAIT_MAX" >> "$d/wait.calls"
[ -f "$d/wait.slow" ] && /bin/sleep 5
[ -f "$d/wait.nostatus" ] && {{ echo "forgejo-api: broker failed" >&2; exit 1; }}
st=$(cat "$d/wait.status" 2>/dev/null || echo "run=7 status=success")
for i in $(seq 1 80); do echo "job log $i"; done > "$2"
echo "$st" > "$2.status"
case "$st" in timeout*) exit 1 ;; esac
exit 0
"""

GIT_FORGEJO = """#!/bin/bash
d={state}
printf '%s\\n' "$*" >> "$d/git-forgejo.calls"
[ "$3" = push ] && [ -f "$d/gf.pushfail" ] && {{ echo "git-forgejo: secret broker did not start git" >&2; exit 1; }}
exec git "$@"
"""


def _build(s):
    """A build command (not a targeted test run, not a release) that marks when it runs here."""
    b = s.home / "fakebin" / "build-app"
    b.write_text(f"#!/bin/bash\ntouch {shlex.quote(str(s.marker))}\necho FAKE-BUILD\n")
    b.chmod(0o755)
    return str(b)


def _drop_github_route(s):
    git(s.work, "rm", "-q", "-f", "scripts/github-ci-run")
    s.commit_all("drop scripts/github-ci-run")


def _wf(runs_on="ubuntu-latest", trigger="['ci/run/**']", jobs=None):
    jobs = jobs or f"  build:\n    runs-on: {runs_on}\n    steps:\n      - run: echo hi\n"
    return f"name: agent ci\non:\n  push:\n    branches: {trigger}\njobs:\n{jobs}"


def _ci_base(s, remote="origin", keep_local=True, body=None, **kw):
    """Publish a ci/base holding .github/workflows/agent-ci.yml (BODY, else _wf(**kw)) on REMOTE."""
    git(s.work, "checkout", "-q", "-b", "ci/base")
    wf = s.work / ".github" / "workflows" / "agent-ci.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(body or _wf(**kw))
    git(s.work, "add", "-A")
    git(s.work, "commit", "-q", "-m", "ci/base")
    git(s.work, "push", "-q", remote, "ci/base")
    git(s.work, "checkout", "-q", "main")
    if not keep_local:
        git(s.work, "branch", "-q", "-D", "ci/base")
        git(s.work, "update-ref", "-d", f"refs/remotes/{remote}/ci/base")


def _head_workflow(s, name, text):
    """Commit (and push) a workflow file on HEAD: github-ci-run keeps it unless it fires on the ci/run push."""
    wf = s.work / ".github" / "workflows" / name
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(text)
    s.commit_all(f"workflow {name}")


def _generic_runner(s):
    runner = s.root / "generic-runner"
    runner.write_text(RUNNER_STUB.format(state=shlex.quote(str(s.state)), commit=COMMIT))
    runner.chmod(0o755)
    return str(runner)


def _generic(s, **kw):
    """Route (4): no tracked runner, origin stands in for github.com/djbclark/stubrepo, ci/base has agent-ci.yml."""
    _drop_github_route(s)
    _ci_base(s, **kw)
    return {"BG_OFFLOAD_GENERIC_RUNNER": _generic_runner(s)}


def _forgejo(s, host="forgejo.mit.edu", push_forgejo=True, keep_github=False):
    """Route (3): a tracked scripts/forgejo-ci-run and a `forgejo` remote standing in for https://HOST/djbclark/stub."""
    fj = _bare(s, "forgejo.git")
    git(s.work, "remote", "add", "forgejo", str(fj))
    if not keep_github:
        _drop_github_route(s)
    (s.work / "scripts").mkdir(exist_ok=True)
    runner = s.work / "scripts" / "forgejo-ci-run"
    runner.write_text(FORGEJO_RUNNER.format(state=shlex.quote(str(s.state))))
    runner.chmod(0o755)
    s.commit_all("add scripts/forgejo-ci-run")
    if push_forgejo:
        git(s.work, "push", "-q", "forgejo", "HEAD:main")
    gf = s.home / "fakebin" / "git-forgejo"
    gf.write_text(GIT_FORGEJO.format(state=shlex.quote(str(s.state))))
    gf.chmod(0o755)
    wait = s.root / "wait-run.sh"
    wait.write_text(FORGEJO_WAIT.format(state=shlex.quote(str(s.state))))
    wait.chmod(0o755)
    s.fj = fj
    return {"BG_OFFLOAD_GIT_FORGEJO": str(gf), "BG_OFFLOAD_FORGEJO_WAIT": str(wait),
            "BG_OFFLOAD_URL_ALIAS": f"{s.alias};{fj} https://{host}/djbclark/stub.git"}


def _never_ran(s, r, code=3):
    assert r.returncode == code, r.stderr
    assert not s.marker.exists() and "FAKE-BUILD" not in r.stdout


def _probe(s, **env):
    e = {**os.environ, "HOME": str(s.home), "BG_OFFLOAD_TESTING": "1", "BG_GH": str(s.home / "fakebin" / "gh"),
         "BG_OFFLOAD_URL_ALIAS": s.alias, **env}
    return subprocess.run([str(OFFLOAD), "--probe", str(s.work)], env=e, capture_output=True, text=True, timeout=60)


# A: a build goes to CI at once, exits with the verdict, never runs here

def test_a_build_in_a_ci_repo_goes_to_ci_at_once_and_never_runs_here(s):
    r = s.bg(_build(s))
    _never_ran(s, r, 0)
    assert "running it on CI now" in r.stderr and "CI workflow PASSED" in r.stdout
    assert s.read("admit.calls") == ""  # no load gate, no wait
    assert s.read("runner.calls").strip() == f"--no-wait {_head(s.work)}"


@pytest.mark.parametrize("runs,env,code", [
    ([run(12, conclusion="failure")], {}, 1),
    ([run(13, status="in_progress", conclusion=None)], {"BG_OFFLOAD_WAIT": "1"}, 76),
    ([run(15, conclusion="cancelled")], {}, 77),
])
def test_a_build_exits_with_cis_verdict(s, runs, env, code):
    (s.state / "runs.json").write_text(json.dumps(runs))
    _never_ran(s, s.bg(_build(s), **env), code)


def test_a_build_without_a_route_is_refused_as_before(s):
    s.route(False)
    r = s.bg(_build(s))
    _never_ran(s, r)
    assert "run instead: scripts/github-ci-run REF" in r.stderr
    assert "no CI route was found to run it there now:" in r.stderr and "generic GitHub runner" in r.stderr
    assert s.read("runner.calls") == ""


def test_a_build_whose_offload_is_refused_is_refused_here_too(s):
    (s.work / "tests" / "test_a.py").write_text("def test_x(): assert 1  # edited\n")
    r = s.bg(_build(s))
    _never_ran(s, r)
    assert "1 tracked file(s) with uncommitted changes" in r.stderr and "the offload was refused" in r.stderr
    assert s.read("runner.calls") == ""


def test_a_build_with_offload_off_is_refused(s):
    r = s.bg(_build(s), BG_OFFLOAD="0")
    _never_ran(s, r)
    assert "no CI route was found to run it there now: BG_OFFLOAD=0" in r.stderr
    assert s.read("runner.calls") == ""


# B4: generic GitHub route

def test_generic_github_route_runs_the_canonical_runner(s):
    r = s.bg(_build(s), **_generic(s))
    _never_ran(s, r, 0)
    assert s.read("runner.calls").strip() == f"--no-wait {_head(s.work)}"
    assert s.read("runner.remote").strip() == "origin"
    assert "generic-runner" in r.stderr


def test_generic_route_fetches_a_ci_base_it_does_not_have(s):
    env = _generic(s, keep_local=False)
    r = s.bg(_build(s), **env)
    _never_ran(s, r, 0)
    assert subprocess.run(["git", "rev-parse", "--verify", "-q", "refs/remotes/origin/ci/base"], cwd=s.work).returncode == 0


def test_generic_route_uses_the_bgoffload_remote(s):
    fork = _bare(s, "fork.git")
    git(s.work, "remote", "add", "fork", str(fork))
    _drop_github_route(s)
    git(s.work, "push", "-q", "fork", "HEAD:main")
    _ci_base(s, remote="fork")
    env = {"BG_OFFLOAD_GENERIC_RUNNER": _generic_runner(s), "BG_OFFLOAD_URL_ALIAS": f"{fork} {STUB_REPO}"}
    _never_ran(s, s.bg(_build(s), **env))  # control: origin (upstream here) is not a github.com repo
    git(s.work, "config", "bgoffload.remote", "fork")
    r = s.bg(_build(s), **env)
    _never_ran(s, r, 0)
    assert s.read("runner.remote").strip() == "fork"


def test_generic_route_needs_a_ci_run_push_trigger(s):
    r = s.bg(_build(s), **_generic(s, trigger="['main']"))
    _never_ran(s, r)
    assert "with a push trigger on ci/run/**" in r.stderr
    assert s.read("runner.calls") == ""


def test_generic_route_needs_ci_base_on_the_remote(s):
    _drop_github_route(s)
    r = s.bg(_build(s), BG_OFFLOAD_GENERIC_RUNNER=_generic_runner(s))
    _never_ran(s, r)
    assert "has no ci/base branch" in r.stderr


def test_generic_route_needs_a_github_remote(s):
    r = s.bg(_build(s), BG_OFFLOAD_URL_ALIAS="", **_generic(s))
    _never_ran(s, r)
    assert "is not one github.com repo" in r.stderr
    assert s.read("runner.calls") == ""


def test_generic_route_keeps_the_publish_checks(s):
    env = _generic(s)
    (s.work / "feature.txt").write_text("unpushed\n")
    s.commit_all("local feature", on_remote=False)
    r = s.bg(_build(s), **env)
    _never_ran(s, r)
    assert "1 commit(s) in HEAD are not on the remote origin" in r.stderr
    assert s.read("runner.calls") == ""


def test_generic_route_refuses_a_local_ci_base_ahead_of_the_remote(s):
    env = _generic(s)
    git(s.work, "checkout", "-q", "ci/base")
    (s.work / "overlay.txt").write_text("private overlay\n")
    git(s.work, "add", "-A")
    git(s.work, "commit", "-q", "-m", "unpushed overlay")
    git(s.work, "checkout", "-q", "main")
    r = s.bg(_build(s), **env)
    _never_ran(s, r)
    assert "overlaid onto the run" in r.stderr
    assert s.read("runner.calls") == ""


# F5: the default generic runner must be committed, unmodified code; the override is a test hook only

def _ade_runner(s, tracked=True):
    ade = s.home / "src" / "djbclark-ade"
    (ade / "scripts").mkdir(parents=True, exist_ok=True)
    r = ade / "scripts" / "github-ci-run"
    r.write_text(RUNNER_STUB.format(state=shlex.quote(str(s.state)), commit=COMMIT))
    r.chmod(0o755)
    git(ade, "init", "-q", "-b", "main")
    git(ade, "config", "user.name", "t")
    git(ade, "config", "user.email", "t@example.invalid")
    if tracked:
        git(ade, "add", "scripts/github-ci-run")
        git(ade, "commit", "-q", "-m", "runner")
    return r


def test_the_default_generic_runner_is_used_when_committed(s):
    _generic(s)
    _ade_runner(s)
    _never_ran(s, s.bg(_build(s)), 0)
    assert s.read("runner.calls") != ""


def test_a_modified_default_generic_runner_is_no_route(s):
    _generic(s)
    r = _ade_runner(s)
    r.write_text(r.read_text() + "# another session's edit\n")
    res = s.bg(_build(s))
    _never_ran(s, res)
    assert "missing, untracked or modified" in res.stderr
    assert s.read("runner.calls") == ""


def test_an_untracked_default_generic_runner_is_no_route(s):
    _generic(s)
    _ade_runner(s, tracked=False)
    res = s.bg(_build(s))
    _never_ran(s, res)
    assert "missing, untracked or modified" in res.stderr


# F12: route (4) pushes only to djbclark's repos, ones he administers, or an explicit bgoffload.remote; the URL alias
# hook only aliases local paths

def _someone_elses(s):
    env = _generic(s)
    env["BG_OFFLOAD_URL_ALIAS"] = f"{s.remote} https://github.com/someone/stubrepo.git"
    (s.state / "runner.repo").write_text("someone/stubrepo\n")
    return env


def test_generic_route_refuses_someone_elses_repo(s):
    r = s.bg(_build(s), **_someone_elses(s))
    _never_ran(s, r)
    assert "someone/stubrepo is not djbclark's" in r.stderr
    assert s.read("runner.calls") == ""


def test_generic_route_takes_a_repo_djbclark_administers(s):
    env = _someone_elses(s)
    (s.state / "repo.perm").write_text("ADMIN\n")
    _never_ran(s, s.bg(_build(s), **env), 0)


def test_generic_route_takes_someone_elses_repo_named_in_bgoffload_remote(s):
    env = _someone_elses(s)
    git(s.work, "config", "bgoffload.remote", "origin")
    _never_ran(s, s.bg(_build(s), **env), 0)


def test_the_url_alias_hook_never_aliases_a_network_url(s):
    env = _forgejo(s)
    git(s.work, "remote", "set-url", "forgejo", "https://codeberg.org/djbclark/stub.git")
    env["BG_OFFLOAD_URL_ALIAS"] = f"{s.alias};https://codeberg.org/djbclark/stub.git https://forgejo.mit.edu/djbclark/stub.git"
    r = s.bg(_build(s), **env)
    _never_ran(s, r)
    assert "is not a repository on a Forgejo host" in r.stderr


# F11: the run is followed on the CI remote's repo, and only if the runner says it pushed there

def test_a_runner_that_names_another_repo_gets_no_verdict(s):
    (s.state / "runner.repo").write_text("djbclark/other\n")
    r = s.bg(_build(s))
    _never_ran(s, r, 77)
    assert "the runner says it pushed to djbclark/other" in r.stderr
    assert "run list" not in s.read("gh.calls")


def test_a_trailing_slash_in_the_runners_repo_is_the_same_repo(s):
    (s.state / "runner.repo").write_text("djbclark/stubrepo/\n")
    _never_ran(s, s.bg(_build(s)), 0)
    assert all("-R djbclark/stubrepo " in c or c.endswith("-R djbclark/stubrepo") for c in s.read("gh.calls").splitlines()
               if c.startswith("run "))


def test_a_github_route_whose_remote_is_not_github_is_refused_before_the_runner(s):
    r = s.bg(_build(s), BG_OFFLOAD_URL_ALIAS="")
    _never_ran(s, r)
    assert "is not one github.com repo, so its CI run could not be followed" in r.stderr
    assert s.read("runner.calls") == ""


# B3 / F3 / F4 / F8: route (3) pushes the checked commit itself and waits with the Forgejo wait tool

def test_forgejo_route_pushes_the_checked_commit_and_waits(s):
    env = _forgejo(s)
    r = s.bg(_build(s), **env)
    _never_ran(s, r, 0)
    head = _head(s.work)
    assert "CI workflow PASSED" in r.stdout and "https://forgejo.mit.edu/djbclark/stub/actions/runs/7" in r.stdout
    assert subprocess.run(["git", "rev-parse", "refs/heads/ci-run"], cwd=s.fj, capture_output=True, text=True).stdout.strip() == head
    calls = s.read("git-forgejo.calls")
    assert "ls-remote --refs forgejo" in calls  # the publish checks asked forgejo, with the token
    assert f"push --force --no-follow-tags --no-recurse-submodules forgejo {head}:refs/heads/ci-run" in calls
    assert s.read("wait.calls").split()[0] == head and "RP=djbclark/stub WAIT_MAX=2400" in s.read("wait.calls")
    assert not (s.state / "fj.ran").exists()  # the repo's own forgejo-ci-run is never run
    assert s.read("runner.calls") == "" and "run list" not in s.read("gh.calls")


@pytest.mark.parametrize("status,code,needle", [
    ("run=8 status=failure", 1, "job log 80"),
    ("run=8 status=cancelled", 77, "ended 'cancelled'"),
    ("timeout id=8", 76, "had not finished after BG_OFFLOAD_WAIT"),
])
def test_forgejo_route_verdicts(s, status, code, needle):
    env = _forgejo(s)
    (s.state / "wait.status").write_text(status + "\n")
    r = s.bg(_build(s), **env)
    _never_ran(s, r, code)
    assert needle in r.stdout + r.stderr


def test_forgejo_route_wait_tool_failing_without_a_status_is_no_verdict(s):
    env = _forgejo(s)
    (s.state / "wait.nostatus").write_text("")
    r = s.bg(_build(s), **env)
    _never_ran(s, r, 77)
    assert "gave no verdict" in r.stderr


def test_forgejo_route_our_own_bound_firing_is_76(s):
    env = _forgejo(s)
    (s.state / "wait.slow").write_text("")
    _never_ran(s, s.bg(_build(s), BG_OFFLOAD_WAIT="1", BG_OFFLOAD_FORGEJO_GRACE="1", **env), 76)


def test_forgejo_route_push_failure_is_a_refusal_not_a_red_ci(s):
    env = _forgejo(s)
    (s.state / "gf.pushfail").write_text("")
    r = s.bg(_build(s), **env)
    _never_ran(s, r)  # 69 from bg-offload, so bg refuses (3)
    assert "pushing" in r.stderr and "failed" in r.stderr and "CI FAILED" not in r.stdout
    assert s.read("wait.calls") == ""


def test_forgejo_route_without_its_wait_tool_is_no_route(s):
    env = _forgejo(s)
    env["BG_OFFLOAD_FORGEJO_WAIT"] = str(s.root / "no-such-wait-run.sh")
    r = s.bg(_build(s), **env)
    _never_ran(s, r)
    assert "the wait tool forgejo-ci-run uses" in r.stderr
    assert s.read("git-forgejo.calls") == ""


@pytest.mark.parametrize("key,value", [("push.followTags", "true"), ("submodule.recurse", "true"),
                                       ("push.recurseSubmodules", "on-demand")])
def test_forgejo_route_refuses_config_that_could_carry_more_than_the_commit(s, key, value):
    env = _forgejo(s)
    git(s.work, "config", key, value)
    r = s.bg(_build(s), **env)
    _never_ran(s, r)
    assert "route (3) refuses" in r.stderr
    assert "push" not in s.read("git-forgejo.calls")


def test_forgejo_route_refuses_a_host_the_forgejo_skill_does_not_use(s):
    r = s.bg(_build(s), **_forgejo(s, host="codeberg.org"))
    _never_ran(s, r)
    assert "is not a repository on a Forgejo host" in r.stderr


def test_forgejo_route_checks_the_forgejo_remote_not_origin(s):
    r = s.bg(_build(s), **_forgejo(s, push_forgejo=False))  # HEAD is on origin, not on forgejo
    _never_ran(s, r)
    assert "not on the remote forgejo" in r.stderr
    assert "push" not in s.read("git-forgejo.calls")


# F7: order by visibility

def test_a_public_repo_builds_on_github_even_with_forgejo_ci_run(s):
    env = _forgejo(s, keep_github=True)
    (s.state / "repo.private").write_text("false\n")
    _never_ran(s, s.bg(_build(s), **env), 0)
    assert s.read("runner.calls") != "" and s.read("wait.calls") == ""


@pytest.mark.parametrize("private", ["true", None])  # private, or visibility unreadable
def test_a_private_repo_builds_on_forgejo_first(s, private):
    env = _forgejo(s, keep_github=True)
    if private:
        (s.state / "repo.private").write_text(private + "\n")
    _never_ran(s, s.bg(_build(s), **env), 0)
    assert s.read("runner.calls") == "" and s.read("wait.calls") != ""


def test_a_public_repo_without_a_github_route_falls_back_to_forgejo(s):
    env = _forgejo(s)  # no github-ci-run, no ci/base: neither (2) nor (4)
    (s.state / "repo.private").write_text("false\n")
    _never_ran(s, s.bg(_build(s), **env), 0)
    assert s.read("wait.calls") != ""


def test_forgejo_ci_run_without_a_forgejo_remote_falls_through_to_github(s):
    env = _forgejo(s)
    git(s.work, "remote", "remove", "forgejo")
    _ci_base(s)
    env["BG_OFFLOAD_GENERIC_RUNNER"] = _generic_runner(s)
    _never_ran(s, s.bg(_build(s), **env), 0)
    assert s.read("runner.calls") != "" and s.read("wait.calls") == ""


# C / F1 / F2: GitHub macOS runners for public repos only; a private repo needs provably Linux workflows

@pytest.mark.parametrize("runs_on", ["macos-14", "xcode-27", "${{ matrix.os }}", "${{ vars.RUNNER }}", "[self-hosted, macOS]"])
def test_a_private_repo_never_gets_github_macos_runners(s, runs_on):
    env = _generic(s, runs_on=runs_on)
    (s.state / "repo.private").write_text("true\n")
    r = s.bg(_build(s), **env)
    _never_ran(s, r)
    assert "is PRIVATE" in r.stderr
    assert "repo view djbclark/stubrepo --json isPrivate" in s.read("gh.calls")
    assert s.read("runner.calls") == ""


MAC_JOB = "  m:\n    runs-on: macos-14\n    steps:\n      - run: echo hi\n"


@pytest.mark.parametrize("case", ["reusable", "workflow_run", "remote_reusable", "flow_mapping", "anchor"])
def test_a_private_repo_is_refused_for_every_indirect_macos_shape(s, case):
    """The adversary's repro cases (F1): the macOS job is not in linux-ci.yml/agent-ci.yml, or not a literal label."""
    if case == "reusable":
        _head_workflow(s, "build.yml", f"on: workflow_call\njobs:\n{MAC_JOB}")
        body = _wf(jobs="  b:\n    uses: ./.github/workflows/build.yml\n")
    elif case == "workflow_run":
        _head_workflow(s, "mac.yml", f"on:\n  workflow_run:\n    workflows: [ci]\n    types: [completed]\njobs:\n{MAC_JOB}")
        body = None
    elif case == "remote_reusable":
        body = _wf(jobs="  b:\n    uses: someone/repo/.github/workflows/mac.yml@v1\n")
    elif case == "flow_mapping":
        body = _wf(jobs="  b: {runs-on: macos-14, steps: [{run: echo hi}]}\n")
    else:
        body = "x: &mac macos-14\n" + _wf(runs_on="*mac")
    env = _generic(s, body=body)
    (s.state / "repo.private").write_text("true\n")
    r = s.bg(_build(s), **env)
    _never_ran(s, r)
    assert "is PRIVATE" in r.stderr
    assert s.read("runner.calls") == ""


def test_a_public_repo_gets_github_macos_runners(s):
    env = _generic(s, runs_on="macos-14")
    (s.state / "repo.private").write_text("false\n")
    _never_ran(s, s.bg(_build(s), **env), 0)
    assert s.read("runner.calls") != ""


def test_unreadable_visibility_refuses_a_macos_workflow(s):
    env = _generic(s, runs_on="macos-14")  # no repo.private: gh repo view fails
    r = s.bg(_build(s), **env)
    _never_ran(s, r)
    assert "could not read whether djbclark/stubrepo is private" in r.stderr
    assert s.read("runner.calls") == ""


def test_a_private_repo_with_provably_linux_workflows_is_not_asked(s):
    _head_workflow(s, "build.yml", "on: workflow_call\njobs:\n  b:\n    runs-on: [self-hosted, linux]\n    steps:\n      - run: echo hi\n")
    env = _generic(s, body=_wf(jobs="  b:\n    uses: './.github/workflows/build.yml'  # local\n"))
    (s.state / "repo.private").write_text("true\n")
    _never_ran(s, s.bg(_build(s), **env), 0)
    assert s.read("gh.repoview") == ""


def test_route_2_is_guarded_too(s):
    _ci_base(s, runs_on="macos-14")  # the tracked scripts/github-ci-run overlays this
    (s.state / "repo.private").write_text("true\n")
    r = s.bg(_build(s))
    _never_ran(s, r)
    assert "is PRIVATE" in r.stderr
    assert s.read("runner.calls") == ""


def test_route_1_is_guarded_too(s):
    _drop_github_route(s)
    custom = s.work / "scripts" / "bg-offload-run"
    custom.parent.mkdir(exist_ok=True)
    custom.write_text(RUNNER_STUB.format(state=shlex.quote(str(s.state)), commit=COMMIT))
    custom.chmod(0o755)
    _head_workflow(s, "linux-ci.yml", _wf(runs_on="macos-14"))  # commits bg-offload-run too
    (s.state / "repo.private").write_text("true\n")
    r = s.bg(_build(s))
    _never_ran(s, r)
    assert "is PRIVATE" in r.stderr
    assert s.read("runner.calls") == ""
    (s.state / "repo.private").write_text("false\n")
    _never_ran(s, s.bg(_build(s)), 0)  # control: public


def test_route_2_macos_workflow_on_a_remote_that_is_not_github_refuses(s):
    _ci_base(s, runs_on="macos-14")
    (s.state / "repo.private").write_text("false\n")
    r = s.bg(_build(s), BG_OFFLOAD_URL_ALIAS="")
    _never_ran(s, r)
    assert "is not one github.com repo" in r.stderr
    assert s.read("runner.calls") == ""


# F9: the probe's network answers are cached, timeouts of 0 mean the default, and a partial clone's workflow blobs are
# fetched with a bound, never lazily

def test_the_probe_caches_its_answer_until_head_changes(s):
    env = {**_generic(s, runs_on="macos-14"), "BG_OFFLOAD_PROBE_TTL": "300"}
    (s.state / "repo.private").write_text("true\n")
    a = _probe(s, **env)
    b = _probe(s, **env)
    assert a.returncode == b.returncode == 69 and "is PRIVATE" in b.stderr
    assert len(s.read("gh.repoview").splitlines()) == 1  # the second answer came from the cache
    (s.work / "more.txt").write_text("x\n")
    s.commit_all("new HEAD")
    assert _probe(s, **env).returncode == 69
    assert len(s.read("gh.repoview").splitlines()) == 2


def test_a_failed_gh_answer_is_not_cached(s):
    env = {**_generic(s, runs_on="macos-14"), "BG_OFFLOAD_PROBE_TTL": "300"}  # no repo.private: gh fails
    assert _probe(s, **env).returncode == 69
    assert _probe(s, **env).returncode == 69
    assert len(s.read("gh.repoview").splitlines()) == 2


def test_a_timeout_of_zero_means_the_default_not_no_limit(s):
    env = _generic(s, keep_local=False)
    r = s.bg(_build(s), BG_OFFLOAD_LSREMOTE_TIMEOUT="0", BG_OFFLOAD_FETCH_TIMEOUT="0", BG_OFFLOAD_PUSH_TIMEOUT="0",
             BG_OFFLOAD_WAIT="0", **env)
    _never_ran(s, r, 0)


def test_a_partial_clone_gets_its_ci_base_workflow_with_a_bounded_fetch(s):
    env = _generic(s, keep_local=False)
    git(s.remote, "config", "uploadpack.allowFilter", "true")
    git(s.remote, "config", "uploadpack.allowAnySHA1InWant", "true")
    part = s.root / "partial"
    git(s.root, "clone", "-q", "-b", "main", "--filter=blob:none", f"file://{s.remote}", str(part))
    r = subprocess.run([str(OFFLOAD), "--probe", str(part)], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "HOME": str(s.home), "BG_OFFLOAD_TESTING": "1",
                            "BG_GH": str(s.home / "fakebin" / "gh"), "BG_OFFLOAD_URL_ALIAS": s.alias, **env})
    assert r.returncode == 0, r.stderr


# D / F10: artifacts after a GitHub success

def _artifacts(s, rid=11):
    return s.home / ".local" / "state" / "bg-offload" / "artifacts" / "djbclark__stubrepo" / str(rid)


def test_artifacts_are_downloaded_after_a_success(s):
    r = s.bg(_build(s))
    assert r.returncode == 0, r.stderr
    d = _artifacts(s)
    assert (d / "app.zip").exists()
    assert f"artifacts of run 11: {d}" in r.stdout
    assert "run download 11 -R djbclark/stubrepo -D" in s.read("gh.calls")


def test_a_rerun_with_the_same_id_replaces_the_download(s):
    assert s.bg(_build(s)).returncode == 0
    r = s.bg(_build(s))
    assert r.returncode == 0, r.stderr
    assert "artifacts of run 11:" in r.stdout and "warning" not in r.stderr
    assert sorted(p.name for p in _artifacts(s).parent.iterdir()) == ["11"]  # no partial download left behind


def test_a_failed_download_is_only_a_warning_naming_the_path(s):
    (s.state / "dl.fail").write_text("")
    r = s.bg(_build(s))
    assert r.returncode == 0, r.stderr
    assert f"warning: could not download the artifacts of run 11 to {_artifacts(s)}" in r.stderr
    assert not _artifacts(s).exists()
    assert [p for p in _artifacts(s).parent.iterdir()] == []


def test_old_and_surplus_downloads_are_pruned(s):
    base = _artifacts(s).parent
    now = time.time()
    for i in range(100, 125):
        (base / str(i)).mkdir(parents=True)
        os.utime(base / str(i), (now - 3600 + i, now - 3600 + i))
    os.utime(base / "124", (now - 8 * 86400, now - 8 * 86400))  # newest id, but 8 days old
    assert s.bg(_build(s)).returncode == 0
    left = {p.name for p in base.iterdir()}
    assert "11" in left and "124" not in left and len(left) == 20
    assert "100" not in left  # the oldest beyond 20 went


def test_no_download_after_a_failure(s):
    (s.state / "runs.json").write_text(json.dumps([run(12, conclusion="failure")]))
    assert s.bg(_build(s)).returncode == 1
    assert "run download" not in s.read("gh.calls")


def test_artifacts_can_be_turned_off(s):
    assert s.bg(_build(s), BG_OFFLOAD_ARTIFACTS="0").returncode == 0
    assert "run download" not in s.read("gh.calls")


# F6 (adversary review of 9090cc2): a build that names another tree is never offloaded, so it cannot get this repo's
# green verdict for a build that never ran anywhere.

@pytest.mark.parametrize("argv", [
    ("make", "-C", "{other}"),
    ("make", "-C{other}"),
    ("{other}/build.sh",),
    ("./gradlew", "-p", "../other", "build"),
    ("cargo", "build", "--manifest-path={other}/Cargo.toml"),
    ("bash", "{other}/build.sh"),
])
def test_a_build_naming_another_tree_is_refused_not_offloaded(s, argv):
    other = s.root / "other"
    other.mkdir()
    (other / "build.sh").write_text(f"#!/bin/bash\ntouch {shlex.quote(str(s.marker))}\n")
    (other / "build.sh").chmod(0o755)
    (other / "Cargo.toml").write_text("[package]\n")
    r = s.bg(*[a.format(other=other) for a in argv])
    _never_ran(s, r)
    assert "the command names another tree" in r.stderr
    assert "run instead: scripts/github-ci-run REF" in r.stderr
    assert s.read("runner.calls") == ""


def test_a_build_script_inside_the_repo_is_offloaded(s):
    b = s.work / "build.sh"
    b.write_text(f"#!/bin/bash\ntouch {shlex.quote(str(s.marker))}\n")
    b.chmod(0o755)
    _never_ran(s, s.bg("./build.sh"), 0)
    assert s.read("runner.calls") != ""
