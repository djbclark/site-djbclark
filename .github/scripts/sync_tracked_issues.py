#!/usr/bin/env python3
"""Compare discovered issues to .github/tracked-issues.json and append new ones.

The tracked list lives in a data file, not a workflow, so the nightly job can
open a PR with GITHUB_TOKEN (which cannot push changes to workflow files).
Discovery skips repos owned by Daniel's user and orgs (owner-level, plus the
existing exact-repo exclusions).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_TRACKED = Path(".github/tracked-issues.json")
DEFAULT_DISCOVERED = Path("/tmp/discovered-issues.txt")
DEFAULT_NEW = Path("/tmp/new-issues.json")
DEFAULT_RAW = Path("/tmp/raw-issues.json")

# GitHub Search API returns at most 1,000 results (10 pages of 100).
SEARCH_PAGE_SIZE = 100
SEARCH_RESULT_CEILING = 1000

# Daniel's GitHub login, plus every org from `gh api user/orgs` on 2026-11-23
# (America/New_York). The workflow's GITHUB_TOKEN cannot list those orgs as
# him, so the list is maintained here rather than fetched at runtime.
DANIEL_USER = "djbclark"
DANIEL_ORGS = (
    "Bcfg2",
    "Maynard-Daycare",
    "djbcsipb",
    "frdminc",
    "pikans",
    "pkb-rocks",
)
OWNED_OWNERS = frozenset({DANIEL_USER.lower(), *(org.lower() for org in DANIEL_ORGS)})

# Existing exact-repo exclusions; kept even though the owner filter already
# covers these (they are all under djbclark).
EXCLUDED_REPOS = frozenset(
    {
        "djbclark/stayturgid",
        "djbclark/site-djbclark",
        "djbclark/site-private",
    }
)


def search_qualifiers() -> list[str]:
    """GitHub search qualifiers that skip Daniel's user and orgs."""
    return [f"-user:{DANIEL_USER}", *(f"-org:{org}" for org in DANIEL_ORGS)]


def search_query(author: str = DANIEL_USER) -> str:
    """Lexical issue search matching the old `gh search issues --author` call."""
    return " ".join(["is:issue", f"author:{author}", *search_qualifiers()])


def normalize_search_item(item: dict) -> dict:
    """Map a Search API or `gh search` item to the discover script's raw shape."""
    nwo = ""
    repo = item.get("repository")
    if isinstance(repo, dict):
        nwo = str(repo.get("nameWithOwner") or "")
    if not nwo:
        repo_url = str(item.get("repository_url") or "")
        marker = "/repos/"
        if marker in repo_url:
            nwo = repo_url.split(marker, 1)[1].strip("/")
    number = item.get("number")
    url = item.get("url") or item.get("html_url") or ""
    if not url and nwo and number is not None:
        url = f"https://github.com/{nwo}/issues/{number}"
    return {
        "repository": {"nameWithOwner": nwo},
        "number": number,
        "title": item.get("title", ""),
        "state": item.get("state", "open"),
        "url": url,
    }


def fetch_search_page(query: str, page: int, per_page: int = SEARCH_PAGE_SIZE) -> dict:
    """Fetch one Search API page via `gh api`. Does not print the token."""
    proc = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "GET",
            "search/issues",
            "-f",
            f"q={query}",
            "-F",
            f"per_page={per_page}",
            "-F",
            f"page={page}",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"gh api search/issues failed (page {page}): {err}")
    data = json.loads(proc.stdout or "{}")
    if not isinstance(data, dict):
        raise ValueError("search/issues response must be an object")
    return data


def search_all_issue_pages(
    query: str,
    *,
    fetch_page=None,
    page_size: int = SEARCH_PAGE_SIZE,
    ceiling: int = SEARCH_RESULT_CEILING,
) -> tuple[list[dict], dict]:
    """Walk every Search API page up to GitHub's 1,000-result ceiling.

    fetch_page(query, page, per_page) must return a Search API payload
    ({total_count, items, incomplete_results}). Tests inject a fake.
    """
    fetch = fetch_page or fetch_search_page
    if page_size < 1 or ceiling < 1:
        raise ValueError("page_size and ceiling must be positive")
    items: list[dict] = []
    total_count = 0
    incomplete = False
    page = 1
    max_pages = (ceiling + page_size - 1) // page_size
    while page <= max_pages and len(items) < ceiling:
        payload = fetch(query, page, page_size)
        total_count = int(payload.get("total_count") or 0)
        if payload.get("incomplete_results"):
            incomplete = True
        raw_items = payload.get("items") or []
        if not isinstance(raw_items, list):
            raise ValueError(f"search/issues page {page} items must be a list")
        if not raw_items:
            break
        remaining = ceiling - len(items)
        items.extend(raw_items[:remaining])
        if len(raw_items) < page_size or len(items) >= ceiling:
            break
        page += 1
    stats = {
        "total_count": total_count,
        "fetched": len(items),
        "pages": page,
        "hit_ceiling": total_count > ceiling,
        "incomplete_results": incomplete,
    }
    return [normalize_search_item(item) for item in items], stats


def warn_search_limits(stats: dict, file=None) -> None:
    """Log when the 1,000-result ceiling or incomplete_results was hit."""
    out = sys.stderr if file is None else file
    if stats.get("hit_ceiling"):
        print(
            "warning: GitHub issue search reported "
            f"total_count={stats['total_count']} but only the first "
            f"{SEARCH_RESULT_CEILING} results are available; later matches "
            "were skipped",
            file=out,
        )
    if stats.get("incomplete_results"):
        print(
            "warning: GitHub issue search returned incomplete_results=true; "
            "some matches may be missing",
            file=out,
        )


def cmd_search(args: argparse.Namespace) -> int:
    issues, stats = search_all_issue_pages(search_query(), fetch_page=getattr(args, "fetch_page", None))
    args.raw.write_text(json.dumps(issues, indent=2) + "\n")
    warn_search_limits(stats)
    print(
        f"Fetched {stats['fetched']} issues "
        f"(total_count={stats['total_count']}, pages={stats['pages']})"
    )
    return 0


def repo_owner(name_with_owner: str) -> str:
    return name_with_owner.split("/", 1)[0].lower()


def is_excluded_repo(name_with_owner: str) -> bool:
    nwo = name_with_owner.strip()
    if not nwo or "/" not in nwo:
        return False
    if nwo.lower() in EXCLUDED_REPOS:
        return True
    return repo_owner(nwo) in OWNED_OWNERS


def raw_item_repo(item: dict) -> str:
    repo = item.get("repository") or {}
    if isinstance(repo, dict):
        return str(repo.get("nameWithOwner") or "")
    return str(item.get("repo") or "")


def filter_raw_issues(issues: list[dict]) -> list[dict]:
    kept = []
    for item in issues:
        nwo = raw_item_repo(item)
        if nwo and not is_excluded_repo(nwo):
            kept.append(item)
    return kept


def write_discovered_outputs(issues: list[dict], json_path: Path, txt_path: Path) -> None:
    json_path.write_text(json.dumps(issues, indent=2) + "\n")
    lines = []
    for item in issues:
        repo = raw_item_repo(item)
        num = item["number"]
        title = item.get("title", "")
        url = item.get("url") or f"https://github.com/{repo}/issues/{num}"
        state = item.get("state", "open")
        lines.append(f"{repo}|||{num}|||{title}|||{state}|||{url}")
    txt_path.write_text("\n".join(lines) + ("\n" if lines else ""))


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


def cmd_discover(args: argparse.Namespace) -> int:
    raw = args.raw.read_text() if args.raw.exists() else "[]"
    issues = json.loads(raw or "[]")
    if not isinstance(issues, list):
        raise ValueError(f"{args.raw} must contain a JSON list")
    kept = filter_raw_issues(issues)
    write_discovered_outputs(kept, args.discovered_json, args.discovered)
    print(f"Found {len(kept)} third-party issues")
    return 0


def cmd_search_qualifiers(_args: argparse.Namespace) -> int:
    for qualifier in search_qualifiers():
        print(qualifier)
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
    p_disc = sub.add_parser("discover")
    p_disc.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    p_disc.add_argument("--discovered", type=Path, default=DEFAULT_DISCOVERED)
    p_disc.add_argument(
        "--discovered-json", type=Path, default=Path("/tmp/discovered-issues.json")
    )
    p_disc.set_defaults(func=cmd_discover)
    p_search = sub.add_parser("search")
    p_search.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    p_search.set_defaults(func=cmd_search)
    p_qual = sub.add_parser("search-qualifiers")
    p_qual.set_defaults(func=cmd_search_qualifiers)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
