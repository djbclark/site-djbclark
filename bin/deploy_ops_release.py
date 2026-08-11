#!/usr/bin/env python3
"""Deploy coordinated, immutable releases to the three ~/ops checkouts.

Mutating commands (check preflight that takes the lock, deploy, memory-sync)
take an exclusive ops-release flock so concurrent agents cannot interleave
fast-forwards. Multi-step cut/deploy series should also take a version claim
via ``bin/ops_release_lock.py claim begin|end`` (see docs/OPS-RELEASES.md).
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import socket
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

REPOSITORIES = ("stayturgid", "site-djbclark", "site-private")
RELEASE_FILE = "ops-release.json"
LOCAL_CODEX_CONFIG = "codex/config.toml"
LOCAL_CODEX_CONFIG_EXAMPLE = f"{LOCAL_CODEX_CONFIG}.example"
LOCAL_CODEX_CONFIG_BACKUP = "ops-release/codex-config.toml.backup"
LOCAL_SECRETSPEC = "secretspec.toml"
LOCAL_SECRETSPEC_EXAMPLE = f"{LOCAL_SECRETSPEC}.example"
LOCAL_SECRETSPEC_BACKUP = "ops-release/secretspec.toml.backup"
TAG_RE = re.compile(r"^ops-v(?P<version>0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
EX_TEMPFAIL = 75


class ReleaseError(RuntimeError):
    """A release precondition failed."""


@dataclass(frozen=True)
class LocalFileMigration:
    relative_path: str
    content: bytes
    mode: int


@dataclass(frozen=True)
class RenameFileMigration:
    """A tracked file becoming ignored runtime state, preserved without reading."""

    relative_path: str
    device: int
    inode: int


@dataclass(frozen=True)
class ReleasePlan:
    name: str
    path: Path
    tag: str
    current_commit: str
    target_commit: str
    memory_ahead: bool = False
    memory_rebase_from: str | None = None
    local_file_migration: LocalFileMigration | None = None
    rename_file_migration: RenameFileMigration | None = None


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ReleaseError(f"{' '.join(args)} failed in {cwd}: {detail}")
    return result


def git(path: Path, *args: str, check: bool = True) -> str:
    return run("git", *args, cwd=path, check=check).stdout.strip()


def normalize_tag(value: str) -> str:
    tag = value if value.startswith("ops-v") else f"ops-v{value}"
    if not TAG_RE.fullmatch(tag):
        raise ReleaseError(
            f"invalid release {value!r}; expected MAJOR.MINOR.PATCH or ops-vMAJOR.MINOR.PATCH"
        )
    return tag


def version_from_tag(tag: str) -> str:
    match = TAG_RE.fullmatch(tag)
    if not match:
        raise ReleaseError(f"invalid coordinated release tag: {tag}")
    return match.group("version") + f".{match.group(2)}.{match.group(3)}"


def declared_version(path: Path, ref: str) -> str:
    raw = git(path, "show", f"{ref}:{RELEASE_FILE}")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReleaseError(
            f"{path.name} {ref}:{RELEASE_FILE} is invalid JSON: {exc}"
        ) from exc
    if document.get("schema") != 1 or document.get("suite") != "djbclark-ops":
        raise ReleaseError(
            f"{path.name} {ref}:{RELEASE_FILE} is not a djbclark-ops schema-1 manifest"
        )
    version = document.get("version")
    if not isinstance(version, str):
        raise ReleaseError(f"{path.name} {ref}:{RELEASE_FILE} has no string version")
    return version


def is_ancestor(path: Path, ancestor: str, descendant: str) -> bool:
    return (
        run(
            "git",
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
            cwd=path,
            check=False,
        ).returncode
        == 0
    )


def require_annotated_tag(path: Path, tag: str) -> None:
    if git(path, "cat-file", "-t", f"refs/tags/{tag}") != "tag":
        raise ReleaseError(f"{path.name} {tag} is not an annotated tag")


def require_clean_master(
    path: Path,
    *,
    allowed_dirty_paths: tuple[str, ...] = (),
) -> None:
    pathspecs = [".", *(f":(exclude){item}" for item in allowed_dirty_paths)]
    if git(path, "status", "--porcelain", "--untracked-files=all", "--", *pathspecs):
        raise ReleaseError(
            f"{path} is dirty; release deployment requires a clean checkout"
        )
    branch = git(path, "symbolic-ref", "--short", "HEAD", check=False)
    if branch != "master":
        raise ReleaseError(f"{path} is on {branch or 'detached HEAD'}, expected master")


def ref_tracks_path(path: Path, ref: str, relative_path: str) -> bool:
    return (
        run(
            "git",
            "cat-file",
            "-e",
            f"{ref}:{relative_path}",
            cwd=path,
            check=False,
        ).returncode
        == 0
    )


def ref_ignores_path(path: Path, ref: str, relative_path: str) -> bool:
    with tempfile.TemporaryDirectory(prefix="ops-release-ignore-") as directory:
        worktree = Path(directory) / "target"
        run(
            "git",
            "worktree",
            "add",
            "--detach",
            "--quiet",
            str(worktree),
            ref,
            cwd=path,
        )
        try:
            return (
                run(
                    "git",
                    "check-ignore",
                    "--no-index",
                    "-q",
                    "--",
                    relative_path,
                    cwd=worktree,
                    check=False,
                ).returncode
                == 0
            )
        finally:
            run(
                "git",
                "worktree",
                "remove",
                "--force",
                str(worktree),
                cwd=path,
                check=False,
            )


def inspect_local_file_migration(
    name: str,
    path: Path,
    current_commit: str,
    target_commit: str,
) -> LocalFileMigration | None:
    if (
        name != "site-private"
        or not ref_tracks_path(path, current_commit, LOCAL_CODEX_CONFIG)
        or ref_tracks_path(path, target_commit, LOCAL_CODEX_CONFIG)
    ):
        return None
    if not ref_ignores_path(path, target_commit, LOCAL_CODEX_CONFIG):
        raise ReleaseError(
            f"{name} target removes {LOCAL_CODEX_CONFIG} without ignoring it"
        )
    if not ref_tracks_path(path, target_commit, LOCAL_CODEX_CONFIG_EXAMPLE):
        raise ReleaseError(
            f"{name} target removes {LOCAL_CODEX_CONFIG} without a tracked "
            f"{LOCAL_CODEX_CONFIG_EXAMPLE}"
        )
    if git(
        path,
        "diff",
        "--cached",
        "--name-only",
        "--",
        LOCAL_CODEX_CONFIG,
    ):
        raise ReleaseError(
            f"{name} {LOCAL_CODEX_CONFIG} is staged; unstage it before deployment"
        )
    local_path = path / LOCAL_CODEX_CONFIG
    if not local_path.is_file() or local_path.is_symlink():
        raise ReleaseError(
            f"{name} cannot preserve missing or non-regular {LOCAL_CODEX_CONFIG}"
        )
    return LocalFileMigration(
        LOCAL_CODEX_CONFIG,
        local_path.read_bytes(),
        stat.S_IMODE(local_path.stat().st_mode),
    )


def inspect_rename_file_migration(
    name: str,
    path: Path,
    current_commit: str,
    target_commit: str,
) -> RenameFileMigration | None:
    if (
        name != "site-private"
        or not ref_tracks_path(path, current_commit, LOCAL_SECRETSPEC)
        or ref_tracks_path(path, target_commit, LOCAL_SECRETSPEC)
    ):
        return None
    if not ref_ignores_path(path, target_commit, LOCAL_SECRETSPEC):
        raise ReleaseError(
            f"{name} target removes {LOCAL_SECRETSPEC} without ignoring it"
        )
    if not ref_tracks_path(path, target_commit, LOCAL_SECRETSPEC_EXAMPLE):
        raise ReleaseError(
            f"{name} target removes {LOCAL_SECRETSPEC} without a tracked "
            f"{LOCAL_SECRETSPEC_EXAMPLE}"
        )
    if git(path, "diff", "--cached", "--name-only", "--", LOCAL_SECRETSPEC):
        raise ReleaseError(
            f"{name} {LOCAL_SECRETSPEC} is staged; unstage it before deployment"
        )
    local_path = path / LOCAL_SECRETSPEC
    try:
        info = local_path.lstat()
    except FileNotFoundError as exc:
        raise ReleaseError(f"{name} cannot preserve missing {LOCAL_SECRETSPEC}") from exc
    if not stat.S_ISREG(info.st_mode) or local_path.is_symlink():
        raise ReleaseError(
            f"{name} cannot preserve non-regular {LOCAL_SECRETSPEC}"
        )
    if not os.access(local_path.parent, os.W_OK | os.X_OK):
        raise ReleaseError(
            f"{name} cannot rename protected {LOCAL_SECRETSPEC}; "
            "the checkout directory is not writable"
        )
    return RenameFileMigration(LOCAL_SECRETSPEC, info.st_dev, info.st_ino)


def rename_file_backup_dir(path: Path) -> Path:
    raw = git(path, "rev-parse", "--git-dir")
    git_dir = Path(raw)
    if not git_dir.is_absolute():
        git_dir = path / git_dir
    try:
        git_dir = git_dir.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise ReleaseError(f"{path.name} has an invalid Git directory") from exc
    if not git_dir.is_dir():
        raise ReleaseError(f"{path.name} Git directory is not a directory")
    backup_dir = git_dir / "ops-release"
    if os.path.lexists(backup_dir):
        info = backup_dir.lstat()
        if not stat.S_ISDIR(info.st_mode) or backup_dir.is_symlink():
            raise ReleaseError(f"{path.name} protected backup directory is not a real directory")
    else:
        backup_dir.mkdir(mode=0o700)
    info = backup_dir.lstat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise ReleaseError(f"{path.name} protected backup directory has unsafe ownership or mode")
    return backup_dir


def rename_file_backup_path(path: Path) -> Path:
    return rename_file_backup_dir(path) / Path(LOCAL_SECRETSPEC_BACKUP).name


def rename_file_backup_metadata_path(path: Path) -> Path:
    return rename_file_backup_path(path).with_suffix(".metadata.json")


def _open_directory_nofollow(path: Path) -> int:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise ReleaseError(f"unsafe directory for protected manifest operation: {path}") from exc
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        os.close(descriptor)
        raise ReleaseError(f"unsafe directory for protected manifest operation: {path}")
    return descriptor


def _stat_at(descriptor: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _rename_backup_metadata(migration: RenameFileMigration) -> bytes:
    return (
        json.dumps(
            {
                "schema": 1,
                "relative_path": migration.relative_path,
                "device": migration.device,
                "inode": migration.inode,
            },
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_exclusive_at(descriptor: int, name: str, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    file_descriptor = os.open(name, flags, 0o600, dir_fd=descriptor)
    try:
        os.write(file_descriptor, content)
        os.fsync(file_descriptor)
    finally:
        os.close(file_descriptor)


def _read_metadata_at(descriptor: int, name: str) -> dict[str, Any]:
    file_descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
    try:
        raw = os.read(file_descriptor, 4097)
    finally:
        os.close(file_descriptor)
    if len(raw) > 4096:
        raise ReleaseError("protected manifest backup metadata is oversized")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseError("protected manifest backup metadata is invalid") from exc
    if not isinstance(value, dict):
        raise ReleaseError("protected manifest backup metadata is invalid")
    return value


def _validated_backup_migration(path: Path, descriptor: int) -> RenameFileMigration | None:
    backup_name = Path(LOCAL_SECRETSPEC_BACKUP).name
    metadata_name = rename_file_backup_metadata_path(path).name
    backup_info = _stat_at(descriptor, backup_name)
    metadata_info = _stat_at(descriptor, metadata_name)
    if backup_info is None and metadata_info is None:
        return None
    if backup_info is None or metadata_info is None:
        raise ReleaseError(f"{path.name} has an incomplete protected manifest backup")
    if not stat.S_ISREG(backup_info.st_mode) or not stat.S_ISREG(metadata_info.st_mode):
        raise ReleaseError(f"{path.name} protected manifest backup is not regular")
    value = _read_metadata_at(descriptor, metadata_name)
    try:
        migration = RenameFileMigration(
            str(value["relative_path"]), int(value["device"]), int(value["inode"])
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise ReleaseError(f"{path.name} protected manifest backup metadata is invalid") from exc
    if migration.relative_path != LOCAL_SECRETSPEC or (
        backup_info.st_dev,
        backup_info.st_ino,
    ) != (migration.device, migration.inode):
        raise ReleaseError(f"{path.name} protected manifest backup identity does not match")
    return migration


def persist_rename_file_backup(path: Path, migration: RenameFileMigration) -> Path:
    if Path(migration.relative_path).name != migration.relative_path:
        raise ReleaseError("protected manifest path must be a single filename")
    backup_dir = rename_file_backup_dir(path)
    source_descriptor = _open_directory_nofollow(path)
    backup_descriptor = _open_directory_nofollow(backup_dir)
    backup_name = Path(LOCAL_SECRETSPEC_BACKUP).name
    metadata_name = rename_file_backup_metadata_path(path).name
    try:
        info = _stat_at(source_descriptor, migration.relative_path)
        if info is None:
            raise ReleaseError(f"{path.name} protected manifest disappeared before rename")
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (
            migration.device,
            migration.inode,
        ):
            raise ReleaseError(f"{path.name} protected manifest changed before rename")
        if _stat_at(backup_descriptor, backup_name) or _stat_at(backup_descriptor, metadata_name):
            raise ReleaseError(f"{path.name} has an unrecovered protected manifest backup")
        _write_exclusive_at(backup_descriptor, metadata_name, _rename_backup_metadata(migration))
        try:
            os.rename(
                migration.relative_path,
                backup_name,
                src_dir_fd=source_descriptor,
                dst_dir_fd=backup_descriptor,
            )
            os.fsync(backup_descriptor)
        except OSError:
            os.unlink(metadata_name, dir_fd=backup_descriptor)
            raise
    except OSError as exc:
        raise ReleaseError(f"{path.name} could not preserve protected manifest: {exc}") from exc
    finally:
        os.close(backup_descriptor)
        os.close(source_descriptor)
    return backup_dir / backup_name


def restore_rename_file_backup(path: Path) -> bool:
    backup_dir = rename_file_backup_dir(path)
    source_descriptor = _open_directory_nofollow(path)
    backup_descriptor = _open_directory_nofollow(backup_dir)
    backup_name = Path(LOCAL_SECRETSPEC_BACKUP).name
    metadata_name = rename_file_backup_metadata_path(path).name
    try:
        migration = _validated_backup_migration(path, backup_descriptor)
        if migration is None:
            return False
        if _stat_at(source_descriptor, migration.relative_path) is not None:
            raise ReleaseError(
                f"{path.name} cannot recover {migration.relative_path}: both target and backup exist"
            )
        os.rename(
            backup_name,
            migration.relative_path,
            src_dir_fd=backup_descriptor,
            dst_dir_fd=source_descriptor,
        )
        os.unlink(metadata_name, dir_fd=backup_descriptor)
        os.fsync(backup_descriptor)
        os.fsync(source_descriptor)
        return True
    finally:
        os.close(backup_descriptor)
        os.close(source_descriptor)


def recover_rename_file_backup(path: Path) -> None:
    if restore_rename_file_backup(path):
        print(f"{path.name}: recovered protected {LOCAL_SECRETSPEC} from interrupted deploy")

def write_file_atomically(target: Path, content: bytes, mode: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.release-",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def restore_local_file(path: Path, migration: LocalFileMigration) -> None:
    write_file_atomically(
        path / migration.relative_path,
        migration.content,
        migration.mode,
    )


def local_file_backup_path(path: Path) -> Path:
    raw = git(path, "rev-parse", "--git-path", LOCAL_CODEX_CONFIG_BACKUP)
    backup = Path(raw)
    return backup if backup.is_absolute() else path / backup


def persist_local_file_backup(path: Path, migration: LocalFileMigration) -> Path:
    backup = local_file_backup_path(path)
    if backup.exists():
        raise ReleaseError(
            f"{path.name} has an unrecovered local config backup at {backup}"
        )
    write_file_atomically(backup, migration.content, migration.mode)
    return backup


def recover_local_file_backup(path: Path) -> None:
    backup = local_file_backup_path(path)
    if not backup.exists():
        return
    if not backup.is_file() or backup.is_symlink():
        raise ReleaseError(
            f"{path.name} local config backup is not a regular file: {backup}"
        )
    migration = LocalFileMigration(
        LOCAL_CODEX_CONFIG,
        backup.read_bytes(),
        stat.S_IMODE(backup.stat().st_mode),
    )
    restore_local_file(path, migration)
    if not local_file_matches(path, migration):
        raise ReleaseError(
            f"{path.name} could not recover local {LOCAL_CODEX_CONFIG} from {backup}"
        )
    backup.unlink()
    print(f"{path.name}: recovered local {LOCAL_CODEX_CONFIG} from interrupted deploy")


def local_file_matches(path: Path, migration: LocalFileMigration) -> bool:
    local_path = path / migration.relative_path
    return (
        local_path.is_file()
        and not local_path.is_symlink()
        and local_path.read_bytes() == migration.content
        and stat.S_IMODE(local_path.stat().st_mode) == migration.mode
    )


def verify_github_release(name: str, tag: str, path: Path) -> None:
    result = run(
        "gh",
        "release",
        "view",
        tag,
        "--repo",
        f"djbclark/{name}",
        "--json",
        "tagName,isDraft,isPrerelease",
        cwd=path,
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseError(f"djbclark/{name} has no GitHub release for {tag}")
    release = json.loads(result.stdout)
    if (
        release.get("tagName") != tag
        or release.get("isDraft")
        or release.get("isPrerelease")
    ):
        raise ReleaseError(
            f"djbclark/{name} {tag} is not a published stable GitHub release"
        )


def inspect_release(
    ops_root: Path,
    name: str,
    tag: str,
    *,
    fetch: bool = True,
    verify_github: bool = True,
) -> ReleasePlan:
    path = ops_root / name
    if not path.exists():
        raise ReleaseError(f"missing deploy checkout: {path}")
    if fetch:
        run("git", "fetch", "origin", "--prune", "--tags", cwd=path)
    require_annotated_tag(path, tag)
    target_commit = git(path, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    current_commit = git(path, "rev-parse", "HEAD")
    local_file_migration = inspect_local_file_migration(
        name,
        path,
        current_commit,
        target_commit,
    )
    rename_file_migration = inspect_rename_file_migration(
        name,
        path,
        current_commit,
        target_commit,
    )
    allowed_dirty_paths = tuple(
        migration.relative_path
        for migration in (local_file_migration, rename_file_migration)
        if migration
    )
    require_clean_master(path, allowed_dirty_paths=allowed_dirty_paths)
    remote_master = git(path, "rev-parse", "origin/master")
    expected_version = version_from_tag(tag)
    actual_version = declared_version(path, tag)
    if actual_version != expected_version:
        raise ReleaseError(
            f"{name} {tag} declares version {actual_version!r}, expected {expected_version!r}"
        )
    if not is_ancestor(path, target_commit, remote_master):
        raise ReleaseError(f"{name} {tag} is not reachable from origin/master")
    memory_ahead = False
    memory_rebase_from = None
    if not is_ancestor(path, current_commit, target_commit):
        if (
            name == "site-private"
            and is_ancestor(path, target_commit, current_commit)
            and all(
                item.startswith("memory/") for item in changed_paths(path, tag, "HEAD")
            )
        ):
            memory_ahead = True
        elif name == "site-private":
            prior_tag = latest_release_tag(path, current_commit)
            require_annotated_tag(path, prior_tag)
            memory_paths = changed_paths(path, prior_tag, current_commit)
            if (
                is_ancestor(path, prior_tag, target_commit)
                and memory_paths
                and all(item.startswith("memory/") for item in memory_paths)
            ):
                memory_rebase_from = prior_tag
            else:
                raise ReleaseError(
                    f"{name} cannot fast-forward from {current_commit[:12]} to {tag}"
                )
        else:
            raise ReleaseError(
                f"{name} cannot fast-forward from {current_commit[:12]} to {tag}"
            )
    if verify_github:
        verify_github_release(name, tag, path)
    return ReleasePlan(
        name,
        path,
        tag,
        current_commit,
        target_commit,
        memory_ahead,
        memory_rebase_from,
        local_file_migration,
        rename_file_migration,
    )


def apply_release_plan(plan: ReleasePlan) -> None:
    migration = plan.local_file_migration
    rename_migration = plan.rename_file_migration
    backup: Path | None = None
    if migration:
        backup = persist_local_file_backup(plan.path, migration)
        run(
            "git",
            "restore",
            "--worktree",
            "--",
            migration.relative_path,
            cwd=plan.path,
        )
    if rename_migration:
        persist_rename_file_backup(plan.path, rename_migration)
    try:
        if plan.memory_rebase_from:
            run(
                "git",
                "rebase",
                "--onto",
                plan.target_commit,
                plan.memory_rebase_from,
                cwd=plan.path,
            )
        elif not plan.memory_ahead:
            run("git", "merge", "--ff-only", plan.target_commit, cwd=plan.path)
    finally:
        if rename_migration:
            if not restore_rename_file_backup(plan.path):
                raise ReleaseError(
                    f"{plan.name} lost protected {rename_migration.relative_path} backup"
                )
        if migration:
            restore_local_file(plan.path, migration)
            if not local_file_matches(plan.path, migration):
                raise ReleaseError(
                    f"{plan.name} did not restore local {migration.relative_path}"
                )
            if backup:
                backup.unlink()
    deployed = git(plan.path, "rev-parse", "HEAD")
    if plan.memory_ahead or plan.memory_rebase_from:
        drift = changed_paths(plan.path, plan.tag, "HEAD")
        valid = is_ancestor(plan.path, plan.target_commit, deployed) and all(
            item.startswith("memory/") for item in drift
        )
    else:
        valid = deployed == plan.target_commit
    if not valid:
        raise ReleaseError(f"{plan.name} did not land on {plan.target_commit}")
    if migration and not local_file_matches(plan.path, migration):
        raise ReleaseError(
            f"{plan.name} did not preserve local {migration.relative_path}"
        )
    if rename_migration:
        protected = plan.path / rename_migration.relative_path
        if not protected.exists() or protected.is_symlink():
            raise ReleaseError(
                f"{plan.name} did not restore protected "
                f"{rename_migration.relative_path}"
            )
    require_clean_master(plan.path)


def rollback_release_plan(plan: ReleasePlan) -> None:
    migration = plan.local_file_migration
    rename_migration = plan.rename_file_migration
    local_backup: Path | None = None
    if migration:
        local_backup = persist_local_file_backup(plan.path, migration)
    if rename_migration:
        persist_rename_file_backup(plan.path, rename_migration)
    if migration:
        local_target = plan.path / migration.relative_path
        if os.path.lexists(local_target):
            info = local_target.lstat()
            if not stat.S_ISREG(info.st_mode) or local_target.is_symlink():
                raise ReleaseError(f"{plan.name} rollback found unsafe local config")
            local_target.unlink()
    try:
        run("git", "rebase", "--abort", cwd=plan.path, check=False)
        result = run("git", "reset", "--hard", plan.current_commit, cwd=plan.path, check=False)
        if result.returncode != 0:
            raise ReleaseError(f"{plan.name} rollback reset failed")
    finally:
        if rename_migration:
            generated = plan.path / rename_migration.relative_path
            if os.path.lexists(generated):
                info = generated.lstat()
                if not stat.S_ISREG(info.st_mode) or generated.is_symlink():
                    raise ReleaseError(f"{plan.name} rollback created unsafe protected path")
                generated.unlink()
            if not restore_rename_file_backup(plan.path):
                raise ReleaseError(f"{plan.name} rollback lost protected manifest backup")
        if migration:
            restore_local_file(plan.path, migration)
            if local_backup:
                local_backup.unlink()
    if git(plan.path, "rev-parse", "HEAD") != plan.current_commit:
        raise ReleaseError(f"{plan.name} rollback did not restore original commit")


def deploy_release(
    ops_root: Path,
    tag: str,
    *,
    apply: bool,
    fetch: bool = True,
    verify_github: bool = True,
) -> list[ReleasePlan]:
    private_path = ops_root / "site-private"
    if private_path.exists():
        recover_local_file_backup(private_path)
        recover_rename_file_backup(private_path)
    plans = [
        inspect_release(ops_root, name, tag, fetch=fetch, verify_github=verify_github)
        for name in REPOSITORIES
    ]
    for plan in plans:
        action = "would deploy" if not apply else "deploying"
        details = []
        if plan.memory_rebase_from:
            details.append(f"rebased memory commits after {plan.memory_rebase_from}")
        elif plan.memory_ahead:
            details.append("existing memory commits")
        if plan.local_file_migration:
            details.append(f"preserved local {plan.local_file_migration.relative_path}")
        if plan.rename_file_migration:
            details.append(
                f"preserved protected {plan.rename_file_migration.relative_path}"
            )
        suffix = "".join(f" + {detail}" for detail in details)
        print(f"{plan.name}: {action} {plan.tag} ({plan.target_commit[:12]}){suffix}")
    if not apply:
        return plans
    for plan in plans:
        allowed_dirty_paths = tuple(
            migration.relative_path
            for migration in (plan.local_file_migration, plan.rename_file_migration)
            if migration
        )
        require_clean_master(
            plan.path,
            allowed_dirty_paths=allowed_dirty_paths,
        )
        if git(plan.path, "rev-parse", "HEAD") != plan.current_commit:
            raise ReleaseError(
                f"{plan.name} changed after release preflight; nothing was deployed"
            )
        if plan.local_file_migration and not local_file_matches(
            plan.path,
            plan.local_file_migration,
        ):
            raise ReleaseError(
                f"{plan.name} {plan.local_file_migration.relative_path} "
                "changed after release preflight; nothing was deployed"
            )
        if plan.rename_file_migration:
            protected = plan.path / plan.rename_file_migration.relative_path
            try:
                protected_info = protected.lstat()
            except FileNotFoundError as exc:
                raise ReleaseError(
                    f"{plan.name} protected manifest disappeared after preflight"
                ) from exc
            if (
                not stat.S_ISREG(protected_info.st_mode)
                or protected.is_symlink()
                or (protected_info.st_dev, protected_info.st_ino)
                != (plan.rename_file_migration.device, plan.rename_file_migration.inode)
            ):
                raise ReleaseError(
                    f"{plan.name} protected manifest changed after preflight"
                )
    apply_plans = sorted(
        plans,
        key=lambda plan: (
            plan.memory_rebase_from is None,
            plan.local_file_migration is not None,
            plan.rename_file_migration is not None,
        ),
    )
    attempted: list[ReleasePlan] = []
    try:
        for plan in apply_plans:
            attempted.append(plan)
            apply_release_plan(plan)
    except Exception as deployment_error:
        rollback_errors: list[str] = []
        for attempted_plan in reversed(attempted):
            try:
                rollback_release_plan(attempted_plan)
            except Exception as rollback_error:
                rollback_errors.append(f"{attempted_plan.name}: {rollback_error}")
        if rollback_errors:
            raise ReleaseError(
                f"deployment failed ({deployment_error}); rollback also failed: "
                + "; ".join(rollback_errors)
            ) from deployment_error
        raise
    return plans


def reachable_release_tags(path: Path, ref: str = "HEAD") -> list[str]:
    tags = git(path, "tag", "--merged", ref, "--list", "ops-v*").splitlines()

    def key(tag: str) -> tuple[int, int, int]:
        match = TAG_RE.fullmatch(tag)
        return tuple(int(part) for part in match.groups()) if match else (-1, -1, -1)

    return sorted((tag for tag in tags if TAG_RE.fullmatch(tag)), key=key, reverse=True)


def latest_release_tag(path: Path, ref: str = "HEAD") -> str:
    tags = reachable_release_tags(path, ref)
    if not tags:
        raise ReleaseError(f"{path} has no reachable ops-vMAJOR.MINOR.PATCH release")
    return tags[0]


def changed_paths(path: Path, old_ref: str, new_ref: str) -> list[str]:
    return [
        line
        for line in git(
            path, "diff", "--name-only", f"{old_ref}..{new_ref}"
        ).splitlines()
        if line
    ]


def status(
    ops_root: Path,
    *,
    fetch: bool = True,
    verify_github: bool = True,
) -> None:
    failed = False
    deployed_tags: dict[str, str] = {}
    for name in REPOSITORIES:
        path = ops_root / name
        require_clean_master(path)
        if fetch:
            run("git", "fetch", "origin", "--prune", "--tags", cwd=path)
        tag = latest_release_tag(path)
        deployed_tags[name] = tag
        require_annotated_tag(path, tag)
        expected_version = version_from_tag(tag)
        if declared_version(path, tag) != expected_version:
            raise ReleaseError(
                f"{name} {tag} does not declare version {expected_version}"
            )
        if verify_github:
            verify_github_release(name, tag, path)
        changed = changed_paths(path, tag, "HEAD")
        if not changed:
            print(f"{name}: {tag}")
            continue
        if name == "site-private" and all(
            item.startswith("memory/") for item in changed
        ):
            print(f"{name}: {tag} + {len(changed)} memory-only path(s)")
            continue
        failed = True
        print(
            f"{name}: ERROR unversioned paths after {tag}: {', '.join(changed)}",
            file=sys.stderr,
        )
    if len(set(deployed_tags.values())) != 1:
        failed = True
        summary = ", ".join(f"{name}={tag}" for name, tag in deployed_tags.items())
        print(
            f"ERROR: deploy checkouts are on different releases: {summary}",
            file=sys.stderr,
        )
    if failed:
        raise ReleaseError(
            "one or more deploy checkouts contain unversioned code/config"
        )


def memory_sync(
    ops_root: Path,
    *,
    fetch: bool = True,
    verify_github: bool = True,
) -> None:
    path = ops_root / "site-private"
    require_clean_master(path)
    if fetch:
        run("git", "fetch", "origin", "--prune", "--tags", cwd=path)
    tag = latest_release_tag(path)
    require_annotated_tag(path, tag)
    if verify_github:
        verify_github_release("site-private", tag, path)
    local_non_memory = [
        item
        for item in changed_paths(path, tag, "HEAD")
        if not item.startswith("memory/")
    ]
    if local_non_memory:
        raise ReleaseError(
            f"local master contains unversioned code/config after {tag}: {', '.join(local_non_memory)}"
        )
    changed = changed_paths(path, tag, "origin/master")
    non_memory = [item for item in changed if not item.startswith("memory/")]
    if non_memory:
        raise ReleaseError(
            f"origin/master contains unreleased code/config after {tag}: {', '.join(non_memory)}"
        )
    run("git", "rebase", "origin/master", cwd=path)
    print(f"site-private: synchronized {len(changed)} memory-only path(s) after {tag}")


def default_lock_path() -> Path:
    if env := os.environ.get("SITE_OPS_RELEASE_LOCK"):
        return Path(env).expanduser()
    if env := os.environ.get("SITE_OPS_RELEASE_STATE"):
        return Path(env).expanduser() / "ops-release.lock"
    xdg_state = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    return Path(xdg_state) / "site-djbclark" / "ops-release.lock"


def default_claim_path() -> Path:
    if env := os.environ.get("SITE_OPS_RELEASE_CLAIM"):
        return Path(env).expanduser()
    if env := os.environ.get("SITE_OPS_RELEASE_STATE"):
        return Path(env).expanduser() / "ops-release.claim.json"
    xdg_state = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    return Path(xdg_state) / "site-djbclark" / "ops-release.claim.json"


def read_active_claim() -> dict | None:
    path = default_claim_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != 1:
        return None
    return data


def assert_claim_allows(version: str | None, *, require_claim: bool) -> None:
    """Refuse when another live claim owns a different version.

    When require_claim is True, a live matching claim must already exist
    (used by deploy when OPS_RELEASE_REQUIRE_CLAIM=1).
    """
    claim = read_active_claim()
    if claim is None:
        if require_claim:
            raise ReleaseError(
                "no ops-release claim; run: bin/ops_release_lock.py claim begin "
                f"{version or 'VERSION'} --operation deploy"
            )
        return
    claim_version = str(claim.get("version") or "")
    # Claims outlive the begin CLI process; PID death alone is not stale.
    # Conflicting live claims always block until end/force/age expiry.
    if version is not None and claim_version and claim_version != version:
        raise ReleaseError(
            f"active ops-release claim is for {claim_version}, not {version}; "
            "wait for that cut/deploy to finish (bin/ops_release_lock.py claim status)"
        )
    if require_claim and version is not None and claim_version != version:
        raise ReleaseError(
            f"ops-release claim version {claim_version!r} does not match {version!r}"
        )


class OpsReleaseLock:
    """Exclusive fcntl flock for the duration of a deploy/check/memory-sync."""

    def __init__(self, *, enabled: bool = True, note: str = "") -> None:
        self.enabled = enabled
        self.note = note
        self.path = default_lock_path()
        self.fd = -1

    def __enter__(self) -> Self:
        if not self.enabled:
            return self
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        self.fd = os.open(self.path, flags, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # Block after announcing contention.
            print(
                f"deploy_ops_release: waiting for exclusive lock ({self.path})…",
                file=sys.stderr,
            )
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX)
            except OSError as exc:
                os.close(self.fd)
                self.fd = -1
                raise ReleaseError(
                    f"could not acquire ops-release lock: {exc}"
                ) from exc
        try:
            os.ftruncate(self.fd, 0)
            os.lseek(self.fd, 0, os.SEEK_SET)
            os.write(
                self.fd,
                (
                    f"pid={os.getpid()} host={socket.gethostname()} {self.note}\n"
                ).encode(),
            )
        except OSError:
            pass
        return self

    def __exit__(self, *exc: object) -> None:
        if self.fd >= 0:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(self.fd)
            self.fd = -1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ops-root",
        type=Path,
        default=Path(os.environ.get("OPS_ROOT", Path.home() / "ops")).expanduser(),
    )
    parser.add_argument(
        "--no-lock",
        action="store_true",
        help="skip exclusive flock (tests only; never use for live deploys)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser(
        "check", help="preflight a coordinated release"
    )
    check_parser.add_argument("version")
    deploy_parser = subparsers.add_parser(
        "deploy", help="fast-forward all checkouts to a release"
    )
    deploy_parser.add_argument("version")
    subparsers.add_parser("status", help="verify deployed code/config is versioned")
    subparsers.add_parser(
        "memory-sync", help="sync site-private only when remote drift is memory-only"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    require_claim = os.environ.get("OPS_RELEASE_REQUIRE_CLAIM", "").lower() in {
        "1",
        "true",
        "yes",
    }
    try:
        if args.command == "check":
            tag = normalize_tag(args.version)
            version = version_from_tag(tag)
            assert_claim_allows(version, require_claim=False)
            with OpsReleaseLock(enabled=not args.no_lock, note=f"check {version}"):
                deploy_release(args.ops_root, tag, apply=False)
        elif args.command == "deploy":
            tag = normalize_tag(args.version)
            version = version_from_tag(tag)
            assert_claim_allows(version, require_claim=require_claim)
            with OpsReleaseLock(enabled=not args.no_lock, note=f"deploy {version}"):
                deploy_release(args.ops_root, tag, apply=True)
        elif args.command == "status":
            # Read-only; no flock (status must stay cheap for concurrent agents).
            status(args.ops_root)
        else:
            with OpsReleaseLock(enabled=not args.no_lock, note="memory-sync"):
                memory_sync(args.ops_root)
    except (OSError, ReleaseError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        # Map "active claim" collisions to EX_TEMPFAIL for scripting.
        message = str(exc)
        if "active ops-release claim" in message or "no ops-release claim" in message:
            return EX_TEMPFAIL
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
