from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


def make_repo(
    path: Path,
    *,
    tracked_codex_config: bool = False,
) -> str:
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

    def test_later_repository_failure_rolls_back_entire_suite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            originals: dict[str, str] = {}
            for name in release.REPOSITORIES:
                target = make_repo(ops_root / name)
                git(ops_root / name, "checkout", "--detach", "HEAD^")
                git(ops_root / name, "checkout", "-B", "master")
                originals[name] = git(ops_root / name, "rev-parse", "HEAD")
                git(
                    ops_root / name,
                    "update-ref",
                    "refs/remotes/origin/master",
                    target,
                )
            real_apply = release.apply_release_plan

            def fail_last(plan):
                if plan.name == "site-private":
                    raise release.ReleaseError("injected staging failure")
                real_apply(plan)

            with patch.object(release, "apply_release_plan", side_effect=fail_last):
                with self.assertRaisesRegex(release.ReleaseError, "injected staging failure"):
                    release.deploy_release(
                        ops_root,
                        "ops-v1.0.0",
                        apply=True,
                        fetch=False,
                        verify_github=False,
                    )
            for name, original in originals.items():
                self.assertEqual(git(ops_root / name, "rev-parse", "HEAD"), original)

    def test_status_allows_only_site_private_memory_after_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            for name in release.REPOSITORIES:
                make_repo(ops_root / name)
            commit_file(ops_root / "site-private", "memory/fact.md", "fact\n", "memory")

            release.status(ops_root, fetch=False, verify_github=False)

    def test_status_allows_only_site_djbclark_research_after_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            for name in release.REPOSITORIES:
                make_repo(ops_root / name)
            commit_file(
                ops_root / "site-djbclark",
                "research/autonomy/notes.md",
                "notes\n",
                "research",
            )

            release.status(ops_root, fetch=False, verify_github=False)

    def test_status_rejects_data_dir_of_wrong_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            for name in release.REPOSITORIES:
                make_repo(ops_root / name)
            commit_file(
                ops_root / "stayturgid",
                "research/autonomy/notes.md",
                "notes\n",
                "research",
            )

            with self.assertRaisesRegex(
                release.ReleaseError, "unversioned code/config"
            ):
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
                next(plan for plan in plans if plan.name == "site-private").data_ahead
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
            self.assertEqual(private_plan.data_rebase_from, "ops-v1.0.0")
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
            originals: dict[str, str] = {}
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
                originals[name] = git(path, "rev-parse", "HEAD")

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

            for plan in reversed(plans):
                release.rollback_release_plan(plan)
            self.assertEqual(local_config.read_text(encoding="utf-8"), 'model = "local-choice"\n')
            self.assertEqual(local_config.stat().st_mode & 0o777, 0o600)
            for name, original in originals.items():
                self.assertEqual(git(ops_root / name, "rev-parse", "HEAD"), original)
            plans = release.deploy_release(
                ops_root,
                "ops-v1.1.0",
                apply=True,
                fetch=False,
                verify_github=False,
            )

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

    def test_codex_config_migration_requires_target_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "site-private"
            make_repo(path, tracked_codex_config=True)
            (path / release.LOCAL_CODEX_CONFIG).unlink()
            example = path / release.LOCAL_CODEX_CONFIG_EXAMPLE
            example.parent.mkdir(parents=True, exist_ok=True)
            example.write_text('model = "example"\n', encoding="utf-8")
            target = commit_all(path, "remove tracked config without gitignore")

            with self.assertRaisesRegex(
                release.ReleaseError,
                "target removes codex/config.toml without ignoring it",
            ):
                release.inspect_local_file_migration(
                    "site-private",
                    path,
                    "ops-v1.0.0",
                    target,
                )

    def test_interrupted_codex_config_migration_recovers_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "site-private"
            make_repo(path, tracked_codex_config=True)
            local_config = path / release.LOCAL_CODEX_CONFIG
            local_config.write_text('model = "local-choice"\n', encoding="utf-8")
            local_config.chmod(0o600)
            migration = release.LocalFileMigration(
                release.LOCAL_CODEX_CONFIG,
                local_config.read_bytes(),
                local_config.stat().st_mode & 0o777,
            )
            backup = release.persist_local_file_backup(path, migration)
            local_config.write_text('model = "released"\n', encoding="utf-8")
            local_config.chmod(0o644)

            release.recover_local_file_backup(path)

            self.assertFalse(backup.exists())
            self.assertEqual(
                local_config.read_text(encoding="utf-8"),
                'model = "local-choice"\n',
            )
            self.assertEqual(local_config.stat().st_mode & 0o777, 0o600)

    def test_target_ignore_check_uses_nested_git_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "repo"
            make_repo(path)
            (path / "nested").mkdir()
            commit_file(path, "nested/.gitignore", "*.toml\n", "nested ignore")
            self.assertTrue(
                release.ref_ignores_path(path, "HEAD", "nested/runtime.toml")
            )
            commit_file(
                path,
                "nested/.gitignore",
                "*.toml\n!runtime.toml\n",
                "nested negation",
            )
            self.assertFalse(
                release.ref_ignores_path(path, "HEAD", "nested/runtime.toml")
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

    def make_data_sync_repos(self, ops_root: Path) -> None:
        for name in release.DATA_DIRS:
            path = ops_root / name
            make_repo(path)
            git(
                path,
                "update-ref",
                "refs/remotes/origin/master",
                git(path, "rev-parse", "HEAD"),
            )

    def test_memory_sync_syncs_data_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            self.make_data_sync_repos(ops_root)
            data_commits: dict[str, str] = {}
            for name, prefix in release.DATA_DIRS.items():
                path = ops_root / name
                released = git(path, "rev-parse", "HEAD")
                data_commits[name] = commit_file(
                    path, f"{prefix}fact.md", "fact\n", "data"
                )
                git(
                    path,
                    "update-ref",
                    "refs/remotes/origin/master",
                    data_commits[name],
                )
                git(path, "reset", "--hard", released)

            release.memory_sync(ops_root, fetch=False, verify_github=False)

            for name, commit in data_commits.items():
                self.assertEqual(git(ops_root / name, "rev-parse", "HEAD"), commit)

    def test_memory_sync_syncs_code_drift_too(self) -> None:
        # Until 2026-08-23 this raised: memory-sync refused whenever origin/master
        # held any unreleased change outside the data dir. The coordinated-release
        # regime that justified the gate is retired, so a code commit on the remote
        # is now just something to rebase onto.
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            self.make_data_sync_repos(ops_root)
            path = ops_root / "site-private"
            released = git(path, "rev-parse", "HEAD")
            code_commit = commit_file(path, "AGENTS.md", "changed\n", "code")
            git(path, "update-ref", "refs/remotes/origin/master", code_commit)
            git(path, "reset", "--hard", released)

            release.memory_sync(ops_root, fetch=False, verify_github=False)

            self.assertEqual(git(path, "rev-parse", "HEAD"), code_commit)

    def test_memory_sync_requires_clean_tree(self) -> None:
        # The one guard that survives: never rebase over uncommitted work.
        with tempfile.TemporaryDirectory() as directory:
            ops_root = Path(directory) / "ops"
            ops_root.mkdir()
            self.make_data_sync_repos(ops_root)
            (ops_root / "site-private" / "AGENTS.md").write_text("dirty\n")

            with self.assertRaises(release.ReleaseError):
                release.memory_sync(ops_root, fetch=False, verify_github=False)


def completed(args: tuple[str, ...], returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout, "")


class VerifyGithubReleaseTest(unittest.TestCase):
    """Release verification must not depend on the REST get-by-tag index.

    See verify_github_release's docstring: that index 404'd for a release
    that existed, so `gh release list` is primary and by-tag is fallback.
    """

    def fake_run(
        self,
        *,
        list_payload: object | None = None,
        list_rc: int = 0,
        view_payload: object | None = None,
        view_rc: int = 0,
    ):
        calls: list[tuple[str, ...]] = []

        def _run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            if "list" in args:
                body = "" if list_payload is None else json.dumps(list_payload)
                return completed(args, list_rc, body)
            if "view" in args:
                body = "" if view_payload is None else json.dumps(view_payload)
                return completed(args, view_rc, body)
            raise AssertionError(f"unexpected command: {args}")

        return _run, calls

    def test_accepts_release_found_via_list_without_using_by_tag(self) -> None:
        _run, calls = self.fake_run(
            list_payload=[
                {"tagName": "ops-v1.3.26", "isDraft": False, "isPrerelease": False},
                {"tagName": "ops-v1.3.25", "isDraft": False, "isPrerelease": False},
            ],
            # by-tag is the broken endpoint; make it fail loudly if consulted
            view_rc=1,
        )
        with patch.object(release, "run", _run):
            release.verify_github_release("site-private", "ops-v1.3.25", Path("."))
        self.assertTrue(any("list" in call for call in calls))
        self.assertFalse(any("view" in call for call in calls))

    def test_list_lookup_includes_drafts(self) -> None:
        _run, calls = self.fake_run(list_payload=[])
        with patch.object(release, "run", _run), self.assertRaises(release.ReleaseError):
            release.verify_github_release("site-private", "ops-v1.3.25", Path("."))
        list_call = next(call for call in calls if "list" in call)
        self.assertNotIn("--exclude-drafts", list_call)
        self.assertNotIn("--exclude-pre-releases", list_call)

    def test_falls_back_to_by_tag_when_outside_list_window(self) -> None:
        _run, calls = self.fake_run(
            list_payload=[
                {"tagName": "ops-v9.9.9", "isDraft": False, "isPrerelease": False}
            ],
            view_payload={
                "tagName": "ops-v1.0.0",
                "isDraft": False,
                "isPrerelease": False,
            },
        )
        with patch.object(release, "run", _run):
            release.verify_github_release("stayturgid", "ops-v1.0.0", Path("."))
        self.assertTrue(any("view" in call for call in calls))

    def test_rejects_draft_found_via_list(self) -> None:
        _run, _ = self.fake_run(
            list_payload=[
                {"tagName": "ops-v1.3.25", "isDraft": True, "isPrerelease": False}
            ],
            view_rc=1,
        )
        with patch.object(release, "run", _run):
            with self.assertRaisesRegex(release.ReleaseError, "not a published stable"):
                release.verify_github_release("site-private", "ops-v1.3.25", Path("."))

    def test_rejects_prerelease_found_via_list(self) -> None:
        _run, _ = self.fake_run(
            list_payload=[
                {"tagName": "ops-v1.3.25", "isDraft": False, "isPrerelease": True}
            ],
            view_rc=1,
        )
        with patch.object(release, "run", _run):
            with self.assertRaisesRegex(release.ReleaseError, "not a published stable"):
                release.verify_github_release("site-private", "ops-v1.3.25", Path("."))

    def test_raises_when_neither_lookup_finds_the_release(self) -> None:
        _run, _ = self.fake_run(list_payload=[], view_rc=1)
        with patch.object(release, "run", _run):
            with self.assertRaisesRegex(release.ReleaseError, "has no GitHub release"):
                release.verify_github_release("site-private", "ops-v1.3.25", Path("."))

    def test_survives_unparseable_list_output(self) -> None:
        def _run(*args: str, cwd: Path, check: bool = True):
            if "list" in args:
                return completed(args, 0, "not json")
            return completed(
                args,
                0,
                json.dumps(
                    {"tagName": "ops-v1.3.25", "isDraft": False, "isPrerelease": False}
                ),
            )

        with patch.object(release, "run", _run):
            release.verify_github_release("site-private", "ops-v1.3.25", Path("."))
