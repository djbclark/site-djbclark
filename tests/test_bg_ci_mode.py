"""bin/bg in `ci` mode (load-watch ci): targeted test runs stay local, suites and builds go to CI (2026-10-18)."""

import os
import re
import subprocess
from pathlib import Path

import pytest

BG = Path(__file__).resolve().parent.parent / "bin" / "bg"


def ci_targeted(tmp_path, *argv):
    """Run bg's ci_targeted() on ARGV, from a repo with tests/test_a.py and a tests/ directory."""
    body = re.search(r"^ci_targeted\(\) \{.*?^\}", BG.read_text(), re.M | re.S).group(0)
    script = body + '\nci_targeted "$@"\n'
    return subprocess.run(["bash", "-c", script, "bg", *argv], cwd=tmp_path).returncode == 0


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_x(): pass\n")
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
])
def test_suites_directories_and_builds_are_not(repo, argv):
    assert not ci_targeted(repo, *argv)


def run_bg(repo, tmp_path_factory, *argv):
    """bg end to end in a throwaway HOME whose load-watch says the repo is `ci`."""
    home = tmp_path_factory.mktemp("home")
    lw = home / "src" / "djbclark-ade" / "bin" / "load-watch"
    lw.parent.mkdir(parents=True)
    lw.write_text('#!/bin/bash\nprintf "ci\\tscripts/github-test-ref REF\\t2026-10-18\\n"\n')
    lw.chmod(0o755)
    fake = home / "fakebin"
    fake.mkdir()
    (fake / "pytest").write_text('#!/bin/bash\necho "FAKE-PYTEST $*"\n')
    (fake / "pytest").chmod(0o755)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    env = {**os.environ, "HOME": str(home), "PATH": f"{fake}:{os.environ['PATH']}",
           "BG_LOAD_WAIT": "0", "BG_MAX_WAIT": "30", "BG_PING_CMD": "/usr/bin/true"}
    return subprocess.run([str(BG), *argv], cwd=repo, env=env, capture_output=True, text=True, timeout=120)


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
