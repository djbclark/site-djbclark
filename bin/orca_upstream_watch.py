#!/usr/bin/env python3
"""Watch for Orca shipping worktree adoption, so we can stop working around it.

Orca dispatch cannot target a directory it did not create: every worktree
selector resolves against its own registry, so a cow pasture is invisible and
`worker-start --worktree path:<pasture>` fails with `selector_not_found`
(tested 2026-08-23 on v1.4.188). Today that forces an either/or — let Orca own
the workspace, or use cow and drive the agent directly.

Upstream already has this specced, so the sane move is to wait rather than
fork:

- stablyai/orca#10671 — "Add CLI support to selectively adopt an existing Git
  worktree" (enhancement, open since 2026-07-26)
- stablyai/orca#2654 — "Support creating workspaces decoupled from new
  worktrees", which describes an *Open existing* mode that adopts an
  on-disk worktree without creating a second checkout

This checks whether either has shipped, and whether a newer Orca release
exists than the one installed. Exit 10 means something changed and is worth
acting on; 0 means keep waiting.

Silence is the expected state, so it prints one line either way rather than
going quiet and leaving you unsure whether it ran.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

REPO = "stablyai/orca"
ISSUES = (10671, 2654)


def gh_json(args: list[str]) -> Any:
    out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200] or "gh failed")
    return json.loads(out.stdout or "null")


def installed_version() -> str | None:
    """Version of the Orca actually installed, from its app bundle."""
    try:
        out = subprocess.run(
            ["defaults", "read", "/Applications/Orca.app/Contents/Info.plist",
             "CFBundleShortVersionString"],
            capture_output=True, text=True, timeout=30)
        v = out.stdout.strip()
        return v or None
    except (OSError, subprocess.SubprocessError):
        return None


def check() -> dict[str, Any]:
    report: dict[str, Any] = {"issues": {}, "shipped": [], "notes": []}

    for number in ISSUES:
        try:
            data = gh_json(["issue", "view", str(number), "--repo", REPO,
                            "--json", "state,title,updatedAt,stateReason"])
        except (RuntimeError, subprocess.SubprocessError, ValueError) as exc:
            report["issues"][number] = {"error": str(exc)}
            continue
        report["issues"][number] = {
            "state": data.get("state"), "updated": str(data.get("updatedAt"))[:10],
            "title": (data.get("title") or "")[:70],
        }
        if str(data.get("state")).upper() == "CLOSED":
            report["shipped"].append(number)

    installed = installed_version()
    report["installed"] = installed
    try:
        rel = gh_json(["release", "view", "--repo", REPO,
                       "--json", "tagName,publishedAt"])
        latest = str(rel.get("tagName") or "").lstrip("v")
        report["latest_release"] = latest
        report["latest_published"] = str(rel.get("publishedAt"))[:10]
        if installed and latest and _newer(latest, installed):
            report["notes"].append(f"newer Orca available: {latest} (installed {installed})")
    except (RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        report["latest_release"] = None
        report["notes"].append(f"release check failed: {exc}")

    report["actionable"] = bool(report["shipped"] or report["notes"])
    return report


def _newer(a: str, b: str) -> bool:
    def parts(v: str) -> list[int]:
        return [int(x) for x in re.findall(r"\d+", v)] or [0]
    pa, pb = parts(a), parts(b)
    return pa > pb[: len(pa)] + [0] * max(0, len(pa) - len(pb))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Watch Orca upstream for worktree adoption")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = check()
    if args.json:
        print(json.dumps(report, indent=2))
        return 10 if report["actionable"] else 0

    if report["shipped"]:
        nums = ", ".join(f"#{n}" for n in report["shipped"])
        print(f"🐋 Orca worktree adoption may have shipped — {nums} now CLOSED. "
              "Re-test `worker-start --worktree path:<cow pasture>`; if it works, "
              "drop the either/or note in djbclark-ade/docs/orca-integration.md.")
    for note in report["notes"]:
        print(f"🐋 {note}")
    if not report["actionable"]:
        states = ", ".join(f"#{n} {v.get('state', '?')}" for n, v in report["issues"].items())
        print(f"Orca upstream unchanged — {states}; installed "
              f"{report.get('installed')} is current. Still either/or with cow.")
    return 10 if report["actionable"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
