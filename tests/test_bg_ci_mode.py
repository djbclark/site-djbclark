"""bin/bg in `ci` mode (load-watch ci): targeted test runs stay local, suites and builds go to CI (2026-10-18)."""

import os
import re
import subprocess
from pathlib import Path

import pytest

BG = Path(__file__).resolve().parent.parent / "bin" / "bg"


def ci_targeted(tmp_path, *argv):
    """Run bg's ci_targeted() on ARGV, from a repo with tests/test_a.py and a tests/ directory."""
    text = BG.read_text()
    body = "\n".join(re.search(rf"^{name}\(\) \{{.*?^\}}", text, re.M | re.S).group(0) for name in ("ci_pm_script_ok", "ci_targeted"))
    script = body + '\nci_targeted "$@"\n'
    return subprocess.run(["bash", "-c", script, "bg", *argv], cwd=tmp_path).returncode == 0


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_x(): pass\n")
    (tmp_path / "tests" / "foo.test.ts").write_text("// js\n")
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "bar.spec.js").write_text("// js\n")
    (tmp_path / "vitest.config.ts").write_text("export default {}\n")
    (tmp_path / "tests" / "jest.config.js").write_text("module.exports = {}\n")
    (tmp_path / "test" / "setup.ts").write_text("// setup\n")
    (tmp_path / "tests" / "bun").mkdir()
    (tmp_path / "tests" / "jest").mkdir()
    (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest run", "test:unit": "vitest run --dir=src"}}\n')
    return tmp_path


@pytest.mark.parametrize("argv", [
    ["pytest", "tests/test_a.py"],
    ["pytest", "tests/test_a.py::test_x"],
    [".venv/bin/python", "-m", "pytest", "-p", "no:xdist", "-q", "tests/test_a.py"],
    ["nice", "-n", "15", "python3", "-m", "pytest", "-k", "foo"],
    ["pytest", "-kfoo"],
    ["python3", "-m", "unittest", "test_mod.TestX.test_y"],
    ["pytest", "tests", "-k", "foo"],
    ["pytest", "-k", "foo", "."],
    ["pytest", "tests", "tests/test_a.py::test_x"],
    ["./gradlew", "test", "--tests", "com.example.FooTest"],
    ["gradle", "test", "--tests=com.example.FooTest"],
    # JavaScript runners (2026-11-14): a test file, or a -t name filter (which also narrows a directory)
    ["bunx", "vitest", "run", "tests/foo.test.ts"],
    ["npx", "vitest", "run", "tests/foo.test.ts"],
    ["npx", "vitest", "run", "tests/foo.test.ts:12"],
    ["npx", "--no-install", "jest", "tests/foo.test.ts"],
    ["node_modules/.bin/vitest", "run", "--reporter", "dot", "tests/foo.test.ts"],
    ["pnpm", "exec", "vitest", "run", "tests/foo.test.ts"],
    ["pnpm", "vitest", "run", "-t", "name"],
    ["yarn", "vitest", "run", "--testNamePattern=name"],
    ["bun", "test", "tests/foo.test.ts"],
    ["bun", "test", "test/bar.spec.js"],
    ["bun", "test", "-t", "name"],
    ["bun", "test", "--test-name-pattern", "name"],
    ["bun", "run", "test", "tests/foo.test.ts"],
    ["npm", "run", "test", "--", "tests/foo.test.ts"],
    ["npm", "test", "--", "-t", "name"],
    ["yarn", "test:unit", "-t", "name"],
    ["pnpm", "run", "test", "tests", "-t", "name"],
    ["npx", "vitest", "run", "tests", "-t", "name"],
    ["npx", "jest", "--testPathPattern", "foo", "tests"],
    ["env", "CI=1", "npx", "vitest", "run", "tests/foo.test.ts"],
    ["nice", "-n", "15", "npx", "vitest", "run", "tests/foo.test.ts"],
    ["npx", "vitest", "run", "--pool", "threads", "tests/foo.test.ts"],
    ["pytest", "tests/jest", "-k", "foo"],  # a directory named jest does not turn a pytest run into a JS one
])
def test_targeted_runs_are_recognised(repo, argv):
    assert ci_targeted(repo, *argv)


@pytest.mark.parametrize("argv", [
    ["pytest"],
    ["pytest", "-q"],
    ["pytest", "tests"],
    ["pytest", "tests/test_a.py", "tests"],
    ["python3", "-m", "unittest"],
    # cargo stays out: a filtered cargo test still compiles the whole crate graph (review, 2026-10-18)
    ["cargo", "test", "my_filter"],
    ["cargo", "test", "-p", "mycrate", "my_filter"],
    ["cargo", "nextest", "run", "my_filter"],
    ["./gradlew", "assembleDebug"],
    ["./gradlew", "test"],
    ["make", "build"],
    ["swift", "build"],
    ["npm", "run", "build"],
    # JavaScript: a bare suite, a bare directory, a config file, or another script is not targeted
    ["bunx", "vitest", "run"],
    ["npx", "vitest"],
    ["npx", "vitest", "run", "tests"],
    ["npx", "vitest", "run", "--config", "vitest.config.ts"],
    ["npx", "jest", "--coverage"],
    ["bun", "test"],
    ["bun", "test", "tests"],
    ["bun", "run", "test"],
    ["npm", "test"],
    ["npm", "run", "test:coverage"],
    ["pnpm", "run", "test", "tests"],
    ["yarn", "test"],
    ["npm", "run", "build", "--", "tests/foo.test.ts"],
    ["npm", "install", "vitest"],
    ["pnpm", "exec", "tsc", "tests/foo.test.ts"],
    ["pnpm", "exec", "vitest", "run", "tests", "tests/foo.test.ts"],
    # lead adversary B2: an extra positional is a substring/regex filter that UNIONS with the file (the empty one matches all)
    ["npx", "vitest", "run", "tests/foo.test.ts", ""],
    ["npx", "jest", "tests/foo.test.ts", ""],
    ["npx", "vitest", "run", "tests/foo.test.ts", ".test"],
    ["npx", "vitest", "run", "tests/foo.test.ts", "integration"],
    ["npx", "vitest", "run", "tests/foo.test.ts", "tests/**"],
    ["npx", "vitest", "run", "tests/typo.test.ts"],
    ["npx", "vitest", "run", "tests/foo.test.ts", "tests/typo.test.ts"],  # a named file that does not exist is still a filter
    ["npx", "vitest", "run", "--pool", "threads"],
    # lead adversary B3: the runner counts only in command position
    ["make", "-j8", "vitest", "tests/foo.test.ts"],
    ["echo", "jest", "tests/foo.test.ts"],
    # review 2026-11-14: an option's value is not a test file (adversary W1)
    ["npx", "jest", "--config", "tests/jest.config.js"],
    ["npx", "vitest", "run", "--setupFiles", "test/setup.ts"],
    ["npx", "vitest", "run", "-c", "tests/jest.config.js"],
    ["npx", "vitest", "run", "--exclude", "tests/foo.test.ts"],  # a path to leave OUT is not a target (adversary W4)
    ["npx", "jest", "--testPathIgnorePatterns", "tests/foo.test.ts"],
    ["npx", "jest", "--setupFilesAfterEnv", "tests/foo.test.ts"],
    ["npx", "vitest", "run", "--coverage.exclude", "tests/foo.test.ts"],
    # pytest's -k and path::id are not JS filters (adversary round 3, N2)
    ["npx", "vitest", "run", "--", "a::b"],
    ["pnpm", "test", "--", "-k", "foo"],
    # after a `--` the runner's own parser sees the rest as its double-dash option, not as filters (adversary N8)
    ["npx", "vitest", "run", "--", "tests/foo.test.ts"],
    ["pnpm", "test", "--", "-t", "name"],
    ["pnpm", "run", "test", "--", "tests/foo.test.ts"],
    ["yarn", "test", "--", "-t", "name"],
    ["npm", "test", "--", "--", "-t", "name"],
    ["npm", "test", "--", "--", "tests/foo.test.ts"],
    ["npx", "vitest", "run", "--setupFiles", "tests/foo.test.ts"],
    ["npx", "vitest", "run", "--globalTeardown", "tests/foo.test.ts"],  # even a test-shaped name is only the option's value
    # npm reads flags before `--` itself and drops the filter: the whole suite would run here (adversary W2)
    ["npm", "test", "-t", "name"],
    ["npm", "run", "test", "--testNamePattern=foo"],
    # `bun`/`npm` as a directory name inside another runner's arguments must not hide a broad argument (adversary N5)
    ["pytest", "tests/bun", "tests/test_a.py"],
])
def test_suites_directories_and_builds_are_not(repo, argv):
    assert not ci_targeted(repo, *argv)


def make_home(tmp_path_factory, auth=None):
    """A throwaway HOME whose load-watch says `ci`. auth: None (no Touch ID helper), "allow" or "deny" (a stub sudo-ask)."""
    home = tmp_path_factory.mktemp("home")
    lw = home / "src" / "djbclark-ade" / "bin" / "load-watch"
    lw.parent.mkdir(parents=True)
    lw.write_text('#!/bin/bash\nprintf "ci\\tscripts/github-test-ref REF\\t2026-10-18\\n"\n')
    lw.chmod(0o755)
    fake = home / "fakebin"
    fake.mkdir()
    for name in ("pytest", "vitest"):
        (fake / name).write_text(f'#!/bin/bash\necho "FAKE-{name.upper()} $*"\n')
        (fake / name).chmod(0o755)
    if auth:
        sa = home / ".local" / "bin" / "sudo-ask"
        sa.parent.mkdir(parents=True)
        # never prompts: records its argv, then allows or denies
        sa.write_text(f'#!/bin/bash\necho "$@" >> "{home}/sudo-ask.calls"\nexit {0 if auth == "allow" else 1}\n')
        sa.chmod(0o755)
    return home


def bg_env(home, **extra):
    return {**os.environ, "HOME": str(home), "PATH": f"{home}/fakebin:{os.environ['PATH']}",
            "BG_LOAD_WAIT": "0", "BG_MAX_WAIT": "30", "BG_PING_CMD": "/usr/bin/true", "BG_NO_DEADLINE": "1", **extra}


def run_bg(repo, tmp_path_factory, *argv, home=None, **env):
    """bg end to end in a throwaway HOME whose load-watch says the repo is `ci`."""
    home = home or make_home(tmp_path_factory)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return subprocess.run([str(BG), *argv], cwd=repo, env=bg_env(home, **env), capture_output=True, text=True, timeout=120)


def test_bg_runs_a_targeted_test_in_a_ci_repo(repo, tmp_path_factory):
    r = run_bg(repo, tmp_path_factory, "pytest", "tests/test_a.py::test_x")
    assert r.returncode == 0, r.stderr
    # bg puts its own PATH first, so the real pytest may run tests/test_a.py instead of the fake
    assert "FAKE-PYTEST tests/test_a.py::test_x" in r.stdout or "1 passed" in r.stdout
    assert "this targeted test run stays here" in r.stderr


def test_bg_refuses_a_bare_suite_in_a_ci_repo(repo, tmp_path_factory):
    r = run_bg(repo, tmp_path_factory, "pytest")
    assert r.returncode == 3
    assert "FAKE-PYTEST" not in r.stdout
    assert "run instead: scripts/github-test-ref REF" in r.stderr
    assert "a targeted run may stay here" in r.stderr
    assert "no CI route was found to run it there now:" in r.stderr  # 2026-11-01: a route would have offloaded it


def ci_release(*argv):
    """Run bg's ci_release() on ARGV."""
    text = BG.read_text()
    body = re.search(r"^ci_release\(\) \{.*?^\}", text, re.M | re.S).group(0)
    return subprocess.run(["bash", "-c", body + '\nci_release "$@"\n', "bg", *argv]).returncode == 0


@pytest.mark.parametrize("argv", [
    ["just", "release", "0.19.1-sudo.26"],
    ["just", "release-dry", "0.19.1-sudo.26"],
    ["/opt/homebrew/bin/just", "--yes", "release", "1.0"],
    ["packaging/release.py", "--version", "1.0"],
    ["python3", "packaging/release.py", "--version", "1.0"],
])
def test_releases_are_recognised(argv):
    assert ci_release(*argv)


@pytest.mark.parametrize("argv", [
    ["just", "test"],
    ["just", "build", "release"],
    ["packaging/release.py", "--version", "1.0", "--local-tests"],
    ["just", "release", "1.0", "--local-tests"],
    ["cargo", "build", "--release"],
    ["./gradlew", "assembleRelease"],
])
def test_other_commands_are_not_releases(argv):
    assert not ci_release(*argv)


@pytest.mark.parametrize("gate,load,expected", [("16", "16", 0), ("16", "16.1", 75), ("bypass", "99", 0)])
def test_macos_retry_gate(tmp_path, gate, load, expected):
    home = tmp_path / "home"
    lw = home / "src/djbclark-ade/bin/load-watch"
    lw.parent.mkdir(parents=True)
    lw.write_text("#!/bin/bash\ncase \"$2\" in check) printf 'ci\\tci-run\\trepo\\n';; "
                  "route) printf 'local\\t" + gate + "\\t2\\n';; esac\n")
    lw.chmod(0o755)
    fake = tmp_path / "fake"
    fake.mkdir()
    for name, body in {"uname": "echo Darwin", "sysctl": "case $2 in hw.ncpu) echo 8;; vm.loadavg) echo '{ " + load + " 0 0 }';; esac",
                       "swift": "echo LOCAL-SWIFT", "taskpolicy": 'shift 2; exec "$@"'}.items():
        p = fake / name
        p.write_text("#!/bin/bash\n" + body + "\n")
        p.chmod(0o755)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    env = {**os.environ, "HOME": str(home), "PATH": f"{fake}:{os.environ['PATH']}",
           "BG_MAX_WAIT": "0", "BG_LOAD_WAIT": "0", "BG_NO_DEADLINE": "1", "BG_TEST_SLOTS": "0"}
    r = subprocess.run([str(BG), "swift", "test"], cwd=repo, env=env, capture_output=True, text=True, timeout=20)
    assert r.returncode == expected, r.stderr
    assert ("LOCAL-SWIFT" in r.stdout) == (expected == 0)


# --- JavaScript runners end to end, and the one-run approval (2026-11-14) ---


def test_bg_runs_a_targeted_vitest_file_in_a_ci_repo(repo, tmp_path_factory):
    r = run_bg(repo, tmp_path_factory, "vitest", "run", "tests/foo.test.ts")
    assert r.returncode == 0, r.stderr
    assert "FAKE-VITEST run tests/foo.test.ts" in r.stdout
    assert "this targeted test run stays here" in r.stderr


def test_bg_sends_a_bare_vitest_suite_to_ci_and_names_the_approval_path(repo, tmp_path_factory):
    r = run_bg(repo, tmp_path_factory, "vitest", "run")
    assert r.returncode == 3
    assert "FAKE-VITEST" not in r.stdout
    assert "ask djbclark to approve this one run" in r.stderr
    assert "approve-local -- vitest run" in r.stderr
    assert "Touch ID" in r.stderr
    assert "BG_ALLOW_LOCAL_CI_ONLY" not in r.stderr + r.stdout  # never advertised to agents (2026-11-14)
    assert "BG_ALLOW_LOCAL_CI_ONLY" not in subprocess.run([str(BG), "--help"], capture_output=True, text=True).stderr


def token_files(home):
    d = home / ".local" / "state" / "bg" / "approvals"
    return sorted(p for p in d.glob("*") if p.is_file()) if d.is_dir() else []


def approve(repo, home, *argv, ttl=None, **env):
    ttl_args = ["--ttl", ttl] if ttl else []
    return subprocess.run([str(BG), "approve-local", *ttl_args, "--", *argv], cwd=repo, env=bg_env(home, **env),
                          capture_output=True, text=True, timeout=60)


def test_approval_runs_one_refused_command_once(repo, tmp_path_factory):
    home = make_home(tmp_path_factory, "allow")
    a = approve(repo, home, "vitest", "run")
    assert a.returncode == 0, a.stderr
    assert "vitest run" in (home / "sudo-ask.calls").read_text()  # the helper's dialog shows the command
    [tok] = token_files(home)
    assert tok.stat().st_mode & 0o777 == 0o600
    assert tok.parent.stat().st_mode & 0o777 == 0o700
    r = run_bg(repo, tmp_path_factory, "vitest", "run", home=home)
    assert r.returncode == 0, r.stderr
    assert "FAKE-VITEST run" in r.stdout
    assert "approved this one local run" in r.stderr
    assert token_files(home) == []  # consumed: deleted before the run
    again = run_bg(repo, tmp_path_factory, "vitest", "run", home=home)
    assert again.returncode == 3 and "FAKE-VITEST" not in again.stdout
    log = (home / ".local" / "state" / "bg" / "approvals.log").read_text()
    events = [ln.split("\t")[1] for ln in log.splitlines()]
    assert events == ["approved", "consumed"]
    assert [ln.split("\t")[-1] for ln in log.splitlines()] == ["vitest", "vitest"]  # program name only, never the arguments


def test_approval_is_bound_to_the_argv(repo, tmp_path_factory):
    home = make_home(tmp_path_factory, "allow")
    assert approve(repo, home, "vitest", "run").returncode == 0
    r = run_bg(repo, tmp_path_factory, "vitest", "run", "--silent", home=home)
    assert r.returncode == 3 and "FAKE-VITEST" not in r.stdout
    assert len(token_files(home)) == 1  # a mismatch leaves it for the run it was meant for


def test_approval_is_bound_to_the_directory(repo, tmp_path, tmp_path_factory):
    home = make_home(tmp_path_factory, "allow")
    other = tmp_path / "other"
    other.mkdir()
    assert approve(repo, home, "vitest", "run").returncode == 0
    r = run_bg(other, tmp_path_factory, "vitest", "run", home=home)
    assert r.returncode == 3 and "FAKE-VITEST" not in r.stdout
    assert len(token_files(home)) == 1


def test_expired_approval_is_refused_and_removed(repo, tmp_path_factory):
    home = make_home(tmp_path_factory, "allow")
    assert approve(repo, home, "vitest", "run", ttl="1h").returncode == 0
    [tok] = token_files(home)
    text = tok.read_text().replace(next(ln for ln in tok.read_text().splitlines() if ln.startswith("expires=")), "expires=1")
    tok.write_text(text)
    r = run_bg(repo, tmp_path_factory, "vitest", "run", home=home)
    assert r.returncode == 3 and "FAKE-VITEST" not in r.stdout
    assert token_files(home) == []


def test_damaged_or_forged_token_is_refused(repo, tmp_path_factory):
    home = make_home(tmp_path_factory, "allow")
    assert approve(repo, home, "vitest", "run").returncode == 0
    [tok] = token_files(home)
    tok.write_text("garbage\n")
    r = run_bg(repo, tmp_path_factory, "vitest", "run", home=home)
    assert r.returncode == 3 and "FAKE-VITEST" not in r.stdout


def test_ttl_is_recorded_and_bounded(repo, tmp_path_factory):
    home = make_home(tmp_path_factory, "allow")
    assert approve(repo, home, "vitest", "run", ttl="2h").returncode == 0
    [tok] = token_files(home)
    kv = dict(ln.split("=", 1) for ln in tok.read_text().splitlines())
    assert int(kv["expires"]) - int(kv["created"]) == 7200
    for bad in ("0", "abc", "25h", "99d", "-5m"):
        r = approve(repo, home, "vitest", "run", ttl=bad)
        assert r.returncode == 2, bad


def test_denied_authentication_writes_nothing(repo, tmp_path_factory):
    home = make_home(tmp_path_factory, "deny")
    r = approve(repo, home, "vitest", "run")
    assert r.returncode != 0 and "nothing was written" in r.stderr
    assert token_files(home) == []


def test_approve_local_needs_a_command_after_double_dash(repo, tmp_path_factory):
    home = make_home(tmp_path_factory, "allow")
    for argv in (["approve-local"], ["approve-local", "--"], ["approve-local", "vitest", "run"]):
        r = subprocess.run([str(BG), *argv], cwd=repo, env=bg_env(home), capture_output=True, text=True, timeout=60)
        assert r.returncode == 2 and "usage: bg approve-local" in r.stderr, argv
    assert token_files(home) == []


def test_a_targeted_run_does_not_spend_the_approval(repo, tmp_path_factory):
    home = make_home(tmp_path_factory, "allow")
    assert approve(repo, home, "vitest", "run", "tests/foo.test.ts").returncode == 0
    r = run_bg(repo, tmp_path_factory, "vitest", "run", "tests/foo.test.ts", home=home)
    assert r.returncode == 0 and "stays here" in r.stderr
    assert len(token_files(home)) == 1


def test_a_token_copied_from_another_command_is_refused(repo, tmp_path_factory):
    home = make_home(tmp_path_factory, "allow")
    assert approve(repo, home, "vitest", "run").returncode == 0
    [a_tok] = token_files(home)
    assert approve(repo, home, "vitest", "run", "--silent").returncode == 0
    [b_tok] = [t for t in token_files(home) if t != a_tok]
    b_tok.write_text(a_tok.read_text())  # right file name for B, the approval written for A
    r = run_bg(repo, tmp_path_factory, "vitest", "run", "--silent", home=home)
    assert r.returncode == 3 and "FAKE-VITEST" not in r.stdout


def test_the_helper_is_asked_for_fresh_authentication(repo, tmp_path_factory):
    home = make_home(tmp_path_factory, "allow")
    assert approve(repo, home, "vitest", "run").returncode == 0
    assert (home / "sudo-ask.calls").read_text().startswith("-k /usr/bin/printf")  # -k: ignore a cached sudo ticket


def test_log_lines_cannot_be_forged_through_the_directory_name(tmp_path, tmp_path_factory):
    home = make_home(tmp_path_factory, "allow")
    evil = tmp_path / "a\tb\nforged\tconsumed"
    evil.mkdir()
    assert approve(evil, home, "vitest", "run").returncode == 0
    log = (home / ".local" / "state" / "bg" / "approvals.log").read_text()
    assert len(log.splitlines()) == 1 and len(log.splitlines()[0].split("\t")) == 5


# --- lead adversary B1: a package-manager test script is read, not assumed (2026-11-14) ---

SCRIPT_CASES = [
    ({"test": "vitest run"}, True),
    ({"test": "npx vitest run --dir=src --coverage"}, True),
    ({"test": "NODE_ENV=test jest"}, True),
    ({"test": "bun test"}, True),
    ({"test": "pnpm exec vitest run"}, True),
    ({"test": "pnpm -r test && vitest"}, False),
    ({"test": "bun test ./a && bun test ./b && bash x.sh"}, False),
    ({"pretest": "tsc -b", "test": "vitest"}, False),
    ({"test": "vitest", "posttest": "node cleanup.js"}, False),
    ({"test": "vitest run; echo done"}, False),
    ({"test": "vitest run | tee out.log"}, False),
    ({"test": "vitest run $(pwd)"}, False),
    ({"test": "pnpm run build"}, False),
    ({"test": "turbo run test"}, False),
    ({"test": "npm run lint && vitest"}, False),
    ({"test": "playwright test"}, False),
    ({"test": "bash test/unit.sh"}, False),
    ({"test": 7}, False),
    # the body's own arguments must not widen what the caller's file or -t narrows (lead adversary round 2, BLOCK2)
    ({"test": "vitest run src"}, False),
    ({"test": "bun test ./tests"}, False),
    ({"test": "jest tests/*"}, False),
    ({"test": "vitest run #"}, False),
    ({"test": "vitest run --"}, False),
    ({"test": "vitest run --dir src"}, False),
    ({"test": "vitest run ''"}, False),
    ({"test": "jest --testPathPattern=unit"}, False),  # jest ORs it with the caller's file
    ({"test": "jest --testMatch=**/x.js"}, False),
    ({"test": "jest --testPathIgnorePatterns"}, False),  # a trailing valued option would swallow the caller's file
    ({"test": "vitest run --project"}, False),
    ({}, False),
]


@pytest.mark.parametrize("scripts,expected", SCRIPT_CASES)
@pytest.mark.parametrize("argv", [
    ["npm", "test", "--", "tests/foo.test.ts"],
    ["pnpm", "test", "-t", "name"],
    ["yarn", "test", "-t", "name"],
    ["bun", "run", "test", "tests/foo.test.ts"],
])
def test_a_package_script_is_targeted_only_if_its_body_is_one_runner_call(repo, argv, scripts, expected):
    import json
    (repo / "package.json").write_text(json.dumps({"scripts": scripts}))
    assert ci_targeted(repo, *argv) == expected


@pytest.mark.parametrize("argv", [["npm", "test", "--", "tests/foo.test.ts"], ["bun", "run", "test", "-t", "x"]])
def test_a_missing_or_broken_package_json_is_not_targeted(repo, argv):
    (repo / "package.json").unlink()
    assert not ci_targeted(repo, *argv)
    (repo / "package.json").write_text("{not json")
    assert not ci_targeted(repo, *argv)


def test_bun_test_itself_does_not_read_package_json(repo):
    (repo / "package.json").write_text('{"scripts": {"test": "bun test ./a && bun test ./b"}}')
    assert ci_targeted(repo, "bun", "test", "tests/foo.test.ts")  # bun's own runner: scripts.test is not run
    assert not ci_targeted(repo, "bun", "run", "test", "tests/foo.test.ts")  # the script is


def test_the_sudo_fallback_leaves_the_ticket_alone():
    # Not run (it would prompt): the code path is read instead. `sudo -k` then `sudo -v` would cache a fresh global ticket (B4).
    code = [ln for ln in BG.read_text().splitlines() if not ln.lstrip().startswith("#")]
    assert any("/usr/bin/sudo -k /usr/bin/true" in ln for ln in code)
    assert not any(re.search(r"\bsudo -v\b", ln) for ln in code)


def test_the_refusal_quotes_an_argument_with_a_space(repo, tmp_path_factory):
    r = run_bg(repo, tmp_path_factory, "vitest", "run", "a b")
    assert r.returncode == 3
    assert "approve-local -- vitest run a\\ b" in r.stderr


def test_an_approval_follows_the_physical_directory(repo, tmp_path, tmp_path_factory):
    home = make_home(tmp_path_factory, "allow")
    link = tmp_path.parent / (tmp_path.name + "-link")
    link.symlink_to(repo)
    assert approve(repo, home, "vitest", "run", PWD=str(link)).returncode == 0  # approved from the symlinked path (logical PWD)
    r = run_bg(repo, tmp_path_factory, "vitest", "run", home=home)  # run from the physical one
    assert r.returncode == 0 and "FAKE-VITEST" in r.stdout


@pytest.mark.parametrize("argv", [
    ["pnpm", "-r", "test", "tests/foo.test.ts"],
    ["pnpm", "--recursive", "test", "tests/foo.test.ts"],
    ["pnpm", "--filter=a", "test", "tests/foo.test.ts"],
    ["pnpm", "--dir=packages/a", "test", "-t", "x"],
    ["pnpm", "-w", "test", "tests/foo.test.ts"],
    ["npm", "--prefix=packages/a", "test", "--", "tests/foo.test.ts"],
    ["npm", "--workspaces", "test", "--", "tests/foo.test.ts"],
    ["npm", "test", "--workspaces", "--", "tests/foo.test.ts"],
    ["npm", "--workspace=a", "test", "--", "tests/foo.test.ts"],
    ["yarn", "--cwd=x", "test", "tests/foo.test.ts"],
    ["bun", "--filter=a", "run", "test", "tests/foo.test.ts"],
    ["pnpm", "test", "--filter=a", "tests/foo.test.ts"],
    ["env", "npm_config_workspaces=true", "npm", "test", "tests/foo.test.ts"],  # an assignment in argv moves npm too
    ["env", "NPM_CONFIG_WORKSPACE=pkg-a", "npm", "test", "tests/foo.test.ts"],
    ["env", "--chdir=/elsewhere", "npm", "test", "tests/foo.test.ts"],
    ["env", "-C", "/elsewhere", "npm", "test", "tests/foo.test.ts"],
    ["npm", "test", "--some-npm-option", "--", "tests/foo.test.ts"],  # npm eats every flag before its `--`: unknown, so CI
])
def test_a_package_manager_workspace_option_is_never_targeted(repo, argv):
    # these pick another package's script (or all of them); bg reads only ./package.json (lead adversary round 2, BLOCK1)
    assert not ci_targeted(repo, *argv)


@pytest.mark.parametrize("argv", [
    ["pnpm", "--silent", "test", "tests/foo.test.ts"],
    ["npm", "run", "--silent", "test", "--", "tests/foo.test.ts"],
    ["yarn", "test", "tests/foo.test.ts", "--silent"],
])
def test_a_harmless_package_manager_option_is_still_targeted(repo, argv):
    assert ci_targeted(repo, *argv)


def test_a_workspace_setting_in_npmrc_or_env_is_never_targeted(repo):
    assert ci_targeted(repo, "npm", "test", "--", "tests/foo.test.ts")
    (repo / ".npmrc").write_text("workspaces=true\n")
    assert not ci_targeted(repo, "npm", "test", "--", "tests/foo.test.ts")
    (repo / ".npmrc").write_text("workspace[]=pkg-a\n")
    assert not ci_targeted(repo, "npm", "test", "--", "tests/foo.test.ts")
    (repo / ".npmrc").write_text('"workspaces" = true\n')
    assert not ci_targeted(repo, "npm", "test", "--", "tests/foo.test.ts")
    (repo / ".npmrc").write_text("registry=https://example.invalid/\n")
    assert ci_targeted(repo, "npm", "test", "--", "tests/foo.test.ts")
    os.environ["npm_config_workspaces"] = "true"
    try:
        assert not ci_targeted(repo, "npm", "test", "--", "tests/foo.test.ts")
    finally:
        del os.environ["npm_config_workspaces"]


@pytest.mark.parametrize("argv", [
    ["npx", "jest", "gradle", "--tests", "x"],
    ["npx", "vitest", "run", "pytest", "-k", "x"],
])
def test_pytest_and_gradle_words_never_replace_a_js_runner(repo, argv):
    # `jest gradle --tests x` would otherwise read as a gradle run and stay local while jest runs everything (round 2, WARN2)
    assert not ci_targeted(repo, *argv)
