#!/usr/bin/env python3
"""Watch for the moment Basic Memory becomes worth installing.

Decision recorded 2026-08-23 (djbclark-ade `docs/ai-memory-landscape.md`):
adopt [Basic Memory](https://github.com/basicmachines-co/basic-memory) — AGPL,
agents write directly with no review step, markdown, local, full-text and
semantic search — but **not yet**, because the curated layer is small enough
that agents just read the `AGENTS.md` pointers. Retrieval is not the
bottleneck at a dozen documents.

Rather than trust anyone to notice when that stops being true, this checks
the two signals that would mean it has, and says so. The operator asked to
err on the side of *sooner*, so the thresholds are deliberately low: being
told a month early costs one message, being told late costs the period where
memory was quietly failing to accumulate.

Signals:

1. **Size** — curated pages across the doc roots. Past ~25 files or ~250KB,
   reading pointers stops being how anyone finds things.
2. **Growth** — pages added in the last 14 days. A layer growing quickly will
   cross the size line soon regardless of where it is today.

Exit code 10 means "install it now"; 0 means not yet. Prints one line either
way, so a scheduler can deliver it verbatim.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

DOC_ROOTS = [
    Path.home() / "orca/projects/djbclark-ade/docs",
    Path.home() / "ops/site-private/memory",
    Path.home() / "ops/site-djbclark/research",
]
FILE_THRESHOLD = 25
BYTES_THRESHOLD = 250_000
RECENT_DAYS = 14
RECENT_THRESHOLD = 8


def git_recent(root: Path, days: int) -> int:
    """Markdown files touched in the last `days`, via git so edits count."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", f"--since={days}.days", "--name-only",
             "--pretty=format:", "--", "."],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return 0
        return len({l for l in out.stdout.split() if l.endswith(".md")})
    except (OSError, subprocess.SubprocessError):
        return 0


def survey() -> dict[str, Any]:
    files = 0
    total = 0
    recent = 0
    per_root = {}
    for root in DOC_ROOTS:
        if not root.is_dir():
            continue
        docs = [p for p in root.rglob("*.md") if p.is_file()]
        size = sum(p.stat().st_size for p in docs)
        files += len(docs)
        total += size
        r = git_recent(root, RECENT_DAYS)
        recent += r
        per_root[str(root)] = {"files": len(docs), "bytes": size, "recent": r}
    return {"files": files, "bytes": total, "recent": recent, "roots": per_root}


def verdict(s: dict[str, Any]) -> tuple[bool, str]:
    reasons = []
    if s["files"] >= FILE_THRESHOLD:
        reasons.append(f"{s['files']} curated pages (>= {FILE_THRESHOLD})")
    if s["bytes"] >= BYTES_THRESHOLD:
        reasons.append(f"{s['bytes'] // 1024}KB of curated docs (>= {BYTES_THRESHOLD // 1024}KB)")
    if s["recent"] >= RECENT_THRESHOLD:
        reasons.append(f"{s['recent']} pages changed in {RECENT_DAYS}d (>= {RECENT_THRESHOLD})")
    return bool(reasons), "; ".join(reasons)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Is it time to install Basic Memory?")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--force-notify", action="store_true",
                        help="print the notification regardless (for testing delivery)")
    args = parser.parse_args(argv)

    s = survey()
    ready, why = verdict(s)
    if args.json:
        print(json.dumps({**s, "ready": ready, "why": why}, indent=2))
        return 10 if ready else 0

    if ready or args.force_notify:
        print(
            "📚 Time to install Basic Memory — the curated memory layer has outgrown "
            f"reading pointers. Trigger: {why or 'forced'}.\n"
            "   brew-free install:  uv tool install basic-memory\n"
            "   then register MCP:  claude mcp add --scope user basic-memory -- uvx basic-memory mcp\n"
            "   Rationale and the comparison against Link: "
            "~/orca/projects/djbclark-ade/docs/ai-memory-landscape.md"
        )
        return 10
    print(f"Basic Memory not needed yet — {s['files']} pages, {s['bytes'] // 1024}KB, "
          f"{s['recent']} changed in {RECENT_DAYS}d "
          f"(thresholds {FILE_THRESHOLD} / {BYTES_THRESHOLD // 1024}KB / {RECENT_THRESHOLD}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
