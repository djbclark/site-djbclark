from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "deploy_ops_release.py"
SPEC = importlib.util.spec_from_file_location("deploy_ops_release", SCRIPT)
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release
SPEC.loader.exec_module(release)


def git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def commit_file(path: Path, relative: str, text: str, message: str) -> str:
    target = path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(path, "add", relative)
    git(
        path,
        "-c",
        "user.name=Release Test",
        "-c",
        "user.email=release-test@example.invalid",
        "commit",
        "-m",
        message,
    )
    return git(path, "rev-parse", "HEAD")


def make_repo(path: Path) -> str:
    path.mkdir()
    git(path, "init", "-b", "master")
    commit_file(path, "README.md", "test repo\n", "initial")
    manifest = {"schema": 1, "suite": "djbclark-ops", "version": "1.0.0"}
    commit = commit_file(path, "ops-release.json", json.dumps(manifest), "release")
    git(path, "tag", "-a", "ops-v1.0.0", "-m", "ops v1.0.0")
    return commit


class DeployOpsReleaseTest(unittest.TestCase):
    def test_normalize_tag(self) -> None:
        self.assertEqual(release.normalize_tag("1.2.3"), "ops-v1.2.3")
        self.assertEqual(release.normalize_tag("ops-v1.2.3"), "ops-v1.2.3")

    def test_inspect_release_and_fast_forward(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            targets: dict[str, str] = {}
            for name in release.REPOSITORIES:
                targets[name] = make_repo(ops_root / name)
                git(ops_root / name, "checkout", "--detach", "HEAD^")
                git(ops_root / name, "checkout", "-B", "master")
                git(ops_root / name, "update-ref", "refs/remotes/origin/master", targets[name])

            plans = release.deploy_release(
                ops_root,
                "ops-v1.0.0",
                apply=True,
                fetch=False,
                verify_github=False,
            )

            self.assertEqual(len(plans), 3)
            for name, target in targets.items():
                self.assertEqual(git(ops_root / name, "rev-parse", "HEAD"), target)

    def test_status_allows_only_site_private_memory_after_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            for name in release.REPOSITORIES:
                make_repo(ops_root / name)
            commit_file(ops_root / "site-private", "memory/fact.md", "fact\n", "memory")

            release.status(ops_root, fetch=False, verify_github=False)

    def test_deploy_preserves_site_private_memory_after_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            targets: dict[str, str] = {}
            for name in release.REPOSITORIES:
                targets[name] = make_repo(ops_root / name)
            memory_commit = commit_file(
                ops_root / "site-private",
                "memory/fact.md",
                "fact\n",
                "memory",
            )
            for name in release.REPOSITORIES:
                git(
                    ops_root / name,
                    "update-ref",
                    "refs/remotes/origin/master",
                    git(ops_root / name, "rev-parse", "HEAD"),
                )

            plans = release.deploy_release(
                ops_root,
                "ops-v1.0.0",
                apply=True,
                fetch=False,
                verify_github=False,
            )

            self.assertTrue(next(plan for plan in plans if plan.name == "site-private").memory_ahead)
            self.assertEqual(git(ops_root / "site-private", "rev-parse", "HEAD"), memory_commit)
            for name in ("stayturgid", "site-djbclark"):
                self.assertEqual(git(ops_root / name, "rev-parse", "HEAD"), targets[name])

    def test_status_rejects_unversioned_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            for name in release.REPOSITORIES:
                make_repo(ops_root / name)
            commit_file(ops_root / "stayturgid", "code.txt", "drift\n", "unreleased")

            with self.assertRaisesRegex(release.ReleaseError, "unversioned code/config"):
                release.status(ops_root, fetch=False, verify_github=False)

    def test_memory_sync_accepts_only_memory_remote_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            path = ops_root / "site-private"
            make_repo(path)
            released = git(path, "rev-parse", "HEAD")
            memory_commit = commit_file(path, "memory/fact.md", "fact\n", "memory")
            git(path, "update-ref", "refs/remotes/origin/master", memory_commit)
            git(path, "reset", "--hard", released)

            release.memory_sync(ops_root, fetch=False, verify_github=False)

            self.assertEqual(git(path, "rev-parse", "HEAD"), memory_commit)

    def test_memory_sync_rejects_unreleased_remote_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            path = ops_root / "site-private"
            make_repo(path)
            released = git(path, "rev-parse", "HEAD")
            code_commit = commit_file(path, "AGENTS.md", "changed\n", "code")
            git(path, "update-ref", "refs/remotes/origin/master", code_commit)
            git(path, "reset", "--hard", released)

            with self.assertRaisesRegex(release.ReleaseError, "unreleased code/config"):
                release.memory_sync(ops_root, fetch=False, verify_github=False)
