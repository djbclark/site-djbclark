#!/usr/bin/env python3
"""Compare discovered issues to .github/tracked-issues.json and append new ones.

The tracked list lives in a data file, not a workflow, so the nightly job can
open a PR with GITHUB_TOKEN (which cannot push changes to workflow files).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_TRACKED = Path(".github/tracked-issues.json")
DEFAULT_DISCOVERED = Path("/tmp/discovered-issues.txt")
DEFAULT_NEW = Path("/tmp/new-issues.json")


def load_tracked(path: Path = DEFAULT_TRACKED) -> list[dict]:
    data = json.loads(path.read_text())
    issues = data.get("issue")
    if not isinstance(issues, list):
        raise ValueError(f"{path} must contain an 'issue' list")
    return issues


def tracked_keys(issues: list[dict]) -> set[str]:
    return {f"{item['repo']}#{item['number']}" for item in issues}


def parse_discovered(path: Path = DEFAULT_DISCOVERED) -> list[dict]:
    items = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("|||")
        if len(parts) < 3:
            continue
        repo, num, title = parts[0], parts[1], parts[2]
        url = parts[4] if len(parts) > 4 else f"https://github.com/{repo}/issues/{num}"
        items.append({"repo": repo, "number": str(num), "title": title, "url": url})
    return items


def find_new(discovered: list[dict], tracked: list[dict]) -> list[dict]:
    seen = tracked_keys(tracked)
    new = []
    for item in discovered:
        key = f"{item['repo']}#{item['number']}"
        if key not in seen:
            new.append(item)
            seen.add(key)
    return new


def slug_for(repo: str, number: str) -> str:
    safe = repo.lower().replace("/", "-").replace(".", "-").replace("_", "-")
    return f"{safe}-{number}"


def make_entry(item: dict) -> dict:
    repo = item["repo"]
    number = str(item["number"])
    entry = {"repo": repo, "number": number, "slug": slug_for(repo, number)}
    if item.get("type"):
        entry["type"] = item["type"]
    return entry


def write_tracked(path: Path, issues: list[dict]) -> None:
    path.write_text(json.dumps({"issue": issues}, indent=2) + "\n")


def append_new(tracked_path: Path, new_issues: list[dict]) -> list[dict]:
    issues = load_tracked(tracked_path)
    seen = tracked_keys(issues)
    added = []
    for item in new_issues:
        key = f"{item['repo']}#{item['number']}"
        if key in seen:
            continue
        issues.append(make_entry(item))
        seen.add(key)
        added.append(item)
    write_tracked(tracked_path, issues)
    return added


def cmd_compare(args: argparse.Namespace) -> int:
    new_issues = find_new(parse_discovered(args.discovered), load_tracked(args.tracked))
    args.new.write_text(json.dumps(new_issues, indent=2) + "\n")
    print(f"new_count={len(new_issues)}")
    for item in new_issues:
        print(f"  {item['repo']}#{item['number']} - {item['title']}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    new_issues = json.loads(args.new.read_text())
    added = append_new(args.tracked, new_issues)
    print(f"Added {len(added)} new issue(s) to {args.tracked}")
    print(f"Total tracked: {len(load_tracked(args.tracked))} issues")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--tracked", type=Path, default=DEFAULT_TRACKED)
    common.add_argument("--new", type=Path, default=DEFAULT_NEW)
    p_cmp = sub.add_parser("compare", parents=[common])
    p_cmp.add_argument("--discovered", type=Path, default=DEFAULT_DISCOVERED)
    p_cmp.set_defaults(func=cmd_compare)
    p_upd = sub.add_parser("update", parents=[common])
    p_upd.set_defaults(func=cmd_update)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
