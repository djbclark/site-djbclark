#!/usr/bin/env python3
"""Deploy coordinated, immutable releases to the three ~/ops checkouts."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPOSITORIES = ("stayturgid", "site-djbclark", "site-private")
RELEASE_FILE = "ops-release.json"
TAG_RE = re.compile(r"^ops-v(?P<version>0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


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
        raise ReleaseError(f"invalid release {value!r}; expected MAJOR.MINOR.PATCH or ops-vMAJOR.MINOR.PATCH")
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
        raise ReleaseError(f"{path.name} {ref}:{RELEASE_FILE} is invalid JSON: {exc}") from exc
    if document.get("schema") != 1 or document.get("suite") != "djbclark-ops":
        raise ReleaseError(f"{path.name} {ref}:{RELEASE_FILE} is not a djbclark-ops schema-1 manifest")
    version = document.get("version")
    if not isinstance(version, str):
        raise ReleaseError(f"{path.name} {ref}:{RELEASE_FILE} has no string version")
    return version


def is_ancestor(path: Path, ancestor: str, descendant: str) -> bool:
    return run("git", "merge-base", "--is-ancestor", ancestor, descendant, cwd=path, check=False).returncode == 0


def require_annotated_tag(path: Path, tag: str) -> None:
    if git(path, "cat-file", "-t", f"refs/tags/{tag}") != "tag":
        raise ReleaseError(f"{path.name} {tag} is not an annotated tag")


def require_clean_master(path: Path) -> None:
    if git(path, "status", "--porcelain"):
        raise ReleaseError(f"{path} is dirty; release deployment requires a clean checkout")
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
    if release.get("tagName") != tag or release.get("isDraft") or release.get("isPrerelease"):
        raise ReleaseError(f"djbclark/{name} {tag} is not a published stable GitHub release")


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
    if not is_ancestor(path, current_commit, target_commit):
        if (
            name == "site-private"
            and is_ancestor(path, target_commit, current_commit)
            and all(item.startswith("memory/") for item in changed_paths(path, tag, "HEAD"))
        ):
            memory_ahead = True
        else:
            raise ReleaseError(f"{name} cannot fast-forward from {current_commit[:12]} to {tag}")
    if verify_github:
        verify_github_release(name, tag, path)
    return ReleasePlan(name, path, tag, current_commit, target_commit, memory_ahead)


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
        suffix = " + existing memory commits" if plan.memory_ahead else ""
        print(f"{plan.name}: {action} {plan.tag} ({plan.target_commit[:12]}){suffix}")
    if not apply:
        return plans
    for plan in plans:
        if not plan.memory_ahead:
            run("git", "merge", "--ff-only", plan.target_commit, cwd=plan.path)
        deployed = git(plan.path, "rev-parse", "HEAD")
        if plan.memory_ahead:
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
    return [line for line in git(path, "diff", "--name-only", f"{old_ref}..{new_ref}").splitlines() if line]


def status(
    ops_root: Path,
    *,
    fetch: bool = True,
    verify_github: bool = True,
) -> None:
    failed = False
    for name in REPOSITORIES:
        path = ops_root / name
        require_clean_master(path)
        if fetch:
            run("git", "fetch", "origin", "--prune", "--tags", cwd=path)
        tag = latest_release_tag(path)
        require_annotated_tag(path, tag)
        expected_version = version_from_tag(tag)
        if declared_version(path, tag) != expected_version:
            raise ReleaseError(f"{name} {tag} does not declare version {expected_version}")
        if verify_github:
            verify_github_release(name, tag, path)
        changed = changed_paths(path, tag, "HEAD")
        if not changed:
            print(f"{name}: {tag}")
            continue
        if name == "site-private" and all(item.startswith("memory/") for item in changed):
            print(f"{name}: {tag} + {len(changed)} memory-only path(s)")
            continue
        failed = True
        print(f"{name}: ERROR unversioned paths after {tag}: {', '.join(changed)}", file=sys.stderr)
    if failed:
        raise ReleaseError("one or more deploy checkouts contain unversioned code/config")


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
        item for item in changed_paths(path, tag, "HEAD") if not item.startswith("memory/")
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ops-root",
        type=Path,
        default=Path(os.environ.get("OPS_ROOT", Path.home() / "ops")).expanduser(),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check", help="preflight a coordinated release")
    check_parser.add_argument("version")
    deploy_parser = subparsers.add_parser("deploy", help="fast-forward all checkouts to a release")
    deploy_parser.add_argument("version")
    subparsers.add_parser("status", help="verify deployed code/config is versioned")
    subparsers.add_parser("memory-sync", help="sync site-private only when remote drift is memory-only")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "check":
            deploy_release(args.ops_root, normalize_tag(args.version), apply=False)
        elif args.command == "deploy":
            deploy_release(args.ops_root, normalize_tag(args.version), apply=True)
        elif args.command == "status":
            status(args.ops_root)
        else:
            memory_sync(args.ops_root)
    except (OSError, ReleaseError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
