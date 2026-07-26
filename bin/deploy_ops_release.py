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
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPOSITORIES = ("stayturgid", "site-djbclark", "site-private")
RELEASE_FILE = "ops-release.json"
TAG_RE = re.compile(r"^ops-v(?P<version>0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
EX_TEMPFAIL = 75


class ReleaseError(RuntimeError):
    """A release precondition failed."""


@dataclass(frozen=True)
class ReleasePlan:
    name: str
    path: Path
    tag: str
    current_commit: str
    target_commit: str
    memory_ahead: bool = False
    memory_rebase_from: str | None = None


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


def require_clean_master(path: Path) -> None:
    if git(path, "status", "--porcelain"):
        raise ReleaseError(
            f"{path} is dirty; release deployment requires a clean checkout"
        )
    branch = git(path, "symbolic-ref", "--short", "HEAD", check=False)
    if branch != "master":
        raise ReleaseError(f"{path} is on {branch or 'detached HEAD'}, expected master")


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
    require_clean_master(path)
    if fetch:
        run("git", "fetch", "origin", "--prune", "--tags", cwd=path)
    require_annotated_tag(path, tag)
    target_commit = git(path, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    current_commit = git(path, "rev-parse", "HEAD")
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
    )


def deploy_release(
    ops_root: Path,
    tag: str,
    *,
    apply: bool,
    fetch: bool = True,
    verify_github: bool = True,
) -> list[ReleasePlan]:
    plans = [
        inspect_release(ops_root, name, tag, fetch=fetch, verify_github=verify_github)
        for name in REPOSITORIES
    ]
    for plan in plans:
        action = "would deploy" if not apply else "deploying"
        if plan.memory_rebase_from:
            suffix = f" + rebased memory commits after {plan.memory_rebase_from}"
        elif plan.memory_ahead:
            suffix = " + existing memory commits"
        else:
            suffix = ""
        print(f"{plan.name}: {action} {plan.tag} ({plan.target_commit[:12]}){suffix}")
    if not apply:
        return plans
    for plan in plans:
        require_clean_master(plan.path)
        if git(plan.path, "rev-parse", "HEAD") != plan.current_commit:
            raise ReleaseError(
                f"{plan.name} changed after release preflight; nothing was deployed"
            )
    apply_plans = sorted(plans, key=lambda plan: plan.memory_rebase_from is None)
    for plan in apply_plans:
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

    def __enter__(self) -> OpsReleaseLock:
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
                raise ReleaseError(f"could not acquire ops-release lock: {exc}") from exc
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
