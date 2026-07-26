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


def commit_all(path: Path, message: str) -> str:
    git(path, "add", "--all")
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


def make_repo(path: Path, *, tracked_codex_config: bool = False) -> str:
    path.mkdir()
    git(path, "init", "-b", "master")
    commit_file(path, "README.md", "test repo\n", "initial")
    if tracked_codex_config:
        commit_file(
            path,
            release.LOCAL_CODEX_CONFIG,
            'model = "released"\n',
            "tracked codex config",
        )
    manifest = {"schema": 1, "suite": "djbclark-ops", "version": "1.0.0"}
    commit = commit_file(path, "ops-release.json", json.dumps(manifest), "release")
    tag_release(path, "1.0.0")
    return commit


def tag_release(path: Path, version: str) -> None:
    git(
        path,
        "-c",
        "user.name=Release Test",
        "-c",
        "user.email=release-test@example.invalid",
        "tag",
        "-a",
        f"ops-v{version}",
        "-m",
        f"ops v{version}",
    )


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
                git(
                    ops_root / name,
                    "update-ref",
                    "refs/remotes/origin/master",
                    targets[name],
                )

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

            self.assertTrue(
                next(plan for plan in plans if plan.name == "site-private").memory_ahead
            )
            self.assertEqual(
                git(ops_root / "site-private", "rev-parse", "HEAD"), memory_commit
            )
            for name in ("stayturgid", "site-djbclark"):
                self.assertEqual(
                    git(ops_root / name, "rev-parse", "HEAD"), targets[name]
                )

    def test_deploy_rebases_divergent_site_private_memory_onto_later_release(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            targets: dict[str, str] = {}
            for name in release.REPOSITORIES:
                path = ops_root / name
                make_repo(path)
                manifest = {"schema": 1, "suite": "djbclark-ops", "version": "1.1.0"}
                targets[name] = commit_file(
                    path,
                    "ops-release.json",
                    json.dumps(manifest),
                    "release 1.1",
                )
                tag_release(path, "1.1.0")
                git(path, "update-ref", "refs/remotes/origin/master", targets[name])
                git(path, "reset", "--hard", "ops-v1.0.0")
            memory_commit = commit_file(
                ops_root / "site-private",
                "memory/fact.md",
                "fact\n",
                "memory",
            )

            plans = release.deploy_release(
                ops_root,
                "ops-v1.1.0",
                apply=True,
                fetch=False,
                verify_github=False,
            )

            private_plan = next(plan for plan in plans if plan.name == "site-private")
            self.assertEqual(private_plan.memory_rebase_from, "ops-v1.0.0")
            private_head = git(ops_root / "site-private", "rev-parse", "HEAD")
            self.assertNotEqual(private_head, memory_commit)
            self.assertTrue(
                release.is_ancestor(
                    ops_root / "site-private",
                    targets["site-private"],
                    private_head,
                )
            )
            self.assertEqual(
                release.changed_paths(
                    ops_root / "site-private",
                    "ops-v1.1.0",
                    "HEAD",
                ),
                ["memory/fact.md"],
            )

    def test_deploy_localizes_and_preserves_codex_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            targets: dict[str, str] = {}
            for name in release.REPOSITORIES:
                path = ops_root / name
                make_repo(path, tracked_codex_config=name == "site-private")
                manifest = {"schema": 1, "suite": "djbclark-ops", "version": "1.1.0"}
                (path / "ops-release.json").write_text(
                    json.dumps(manifest),
                    encoding="utf-8",
                )
                if name == "site-private":
                    (path / release.LOCAL_CODEX_CONFIG).unlink()
                    (path / ".gitignore").write_text(
                        f"/{release.LOCAL_CODEX_CONFIG}\n",
                        encoding="utf-8",
                    )
                    example = path / f"{release.LOCAL_CODEX_CONFIG}.example"
                    example.parent.mkdir(parents=True, exist_ok=True)
                    example.write_text('model = "example"\n', encoding="utf-8")
                targets[name] = commit_all(path, "release 1.1")
                tag_release(path, "1.1.0")
                git(path, "update-ref", "refs/remotes/origin/master", targets[name])
                git(path, "reset", "--hard", "ops-v1.0.0")

            private_path = ops_root / "site-private"
            local_config = private_path / release.LOCAL_CODEX_CONFIG
            local_config.write_text('model = "local-choice"\n', encoding="utf-8")
            local_config.chmod(0o600)

            plans = release.deploy_release(
                ops_root,
                "ops-v1.1.0",
                apply=True,
                fetch=False,
                verify_github=False,
            )

            private_plan = next(plan for plan in plans if plan.name == "site-private")
            self.assertIsNotNone(private_plan.local_file_migration)
            self.assertEqual(
                local_config.read_text(encoding="utf-8"), 'model = "local-choice"\n'
            )
            self.assertEqual(local_config.stat().st_mode & 0o777, 0o600)
            self.assertEqual(git(private_path, "status", "--porcelain"), "")
            self.assertEqual(
                git(private_path, "check-ignore", release.LOCAL_CODEX_CONFIG),
                release.LOCAL_CODEX_CONFIG,
            )
            for name, target in targets.items():
                self.assertEqual(git(ops_root / name, "rev-parse", "HEAD"), target)

            later_targets: dict[str, str] = {}
            for name in release.REPOSITORIES:
                path = ops_root / name
                manifest = {"schema": 1, "suite": "djbclark-ops", "version": "1.2.0"}
                later_targets[name] = commit_file(
                    path,
                    "ops-release.json",
                    json.dumps(manifest),
                    "release 1.2",
                )
                tag_release(path, "1.2.0")
                git(
                    path,
                    "update-ref",
                    "refs/remotes/origin/master",
                    later_targets[name],
                )

            later_plans = release.deploy_release(
                ops_root,
                "ops-v1.2.0",
                apply=True,
                fetch=False,
                verify_github=False,
            )

            later_private_plan = next(
                plan for plan in later_plans if plan.name == "site-private"
            )
            self.assertIsNone(later_private_plan.local_file_migration)
            self.assertEqual(
                local_config.read_text(encoding="utf-8"),
                'model = "local-choice"\n',
            )
            self.assertEqual(git(private_path, "status", "--porcelain"), "")
            for name, target in later_targets.items():
                self.assertEqual(git(ops_root / name, "rev-parse", "HEAD"), target)

    def test_deploy_rejects_dirty_codex_config_while_target_tracks_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            for name in release.REPOSITORIES:
                make_repo(
                    ops_root / name,
                    tracked_codex_config=name == "site-private",
                )
                git(
                    ops_root / name,
                    "update-ref",
                    "refs/remotes/origin/master",
                    git(ops_root / name, "rev-parse", "HEAD"),
                )
            (ops_root / "site-private" / release.LOCAL_CODEX_CONFIG).write_text(
                'model = "local-choice"\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(release.ReleaseError, "dirty"):
                release.deploy_release(
                    ops_root,
                    "ops-v1.0.0",
                    apply=False,
                    fetch=False,
                    verify_github=False,
                )

    def test_codex_config_migration_rejects_other_dirty_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            for name in release.REPOSITORIES:
                path = ops_root / name
                make_repo(path, tracked_codex_config=name == "site-private")
                manifest = {"schema": 1, "suite": "djbclark-ops", "version": "1.1.0"}
                (path / "ops-release.json").write_text(
                    json.dumps(manifest),
                    encoding="utf-8",
                )
                if name == "site-private":
                    (path / release.LOCAL_CODEX_CONFIG).unlink()
                    (path / ".gitignore").write_text(
                        f"/{release.LOCAL_CODEX_CONFIG}\n",
                        encoding="utf-8",
                    )
                    example = path / release.LOCAL_CODEX_CONFIG_EXAMPLE
                    example.parent.mkdir(parents=True, exist_ok=True)
                    example.write_text('model = "example"\n', encoding="utf-8")
                target = commit_all(path, "release 1.1")
                tag_release(path, "1.1.0")
                git(path, "update-ref", "refs/remotes/origin/master", target)
                git(path, "reset", "--hard", "ops-v1.0.0")
            private_path = ops_root / "site-private"
            (private_path / release.LOCAL_CODEX_CONFIG).write_text(
                'model = "local-choice"\n',
                encoding="utf-8",
            )
            (private_path / "README.md").write_text(
                "unexpected drift\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(release.ReleaseError, "dirty"):
                release.deploy_release(
                    ops_root,
                    "ops-v1.1.0",
                    apply=False,
                    fetch=False,
                    verify_github=False,
                )

    def test_status_rejects_unversioned_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            for name in release.REPOSITORIES:
                make_repo(ops_root / name)
            commit_file(ops_root / "stayturgid", "code.txt", "drift\n", "unreleased")

            with self.assertRaisesRegex(
                release.ReleaseError, "unversioned code/config"
            ):
                release.status(ops_root, fetch=False, verify_github=False)

    def test_status_rejects_mismatched_release_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            for name in release.REPOSITORIES:
                make_repo(ops_root / name)
            path = ops_root / "stayturgid"
            manifest = {"schema": 1, "suite": "djbclark-ops", "version": "1.1.0"}
            commit_file(path, "ops-release.json", json.dumps(manifest), "release 1.1")
            tag_release(path, "1.1.0")

            with self.assertRaisesRegex(
                release.ReleaseError, "unversioned code/config"
            ):
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
