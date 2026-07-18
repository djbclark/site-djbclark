#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Lint the site registry (registry/ports.yml, registry/paths.yml).

Checks:
  ports.yml — parses; every entry has port/owner/service/status; no duplicate
  (port, bind) per host with conflicting owners; ports in valid range.
  paths.yml — parses; prefixes have exactly one owner (no prefix listed under
  two stacks).

Exit 0 clean, 1 findings, 2 cannot read/parse.
Run from repo root:  bin/registry_lint.py   (or: uv run bin/registry_lint.py)
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
REQUIRED_PORT_KEYS = {"port", "owner", "service", "status"}
VALID_STATUS = {"active", "planned", "default-claim"}


def fail(msg: str) -> None:
    print(f"registry-lint: FAIL: {msg}")


def lint_ports(findings: list[str]) -> None:
    data = yaml.safe_load((REPO / "registry" / "ports.yml").read_text())
    for host, hostdata in (data.get("hosts") or {}).items():
        seen: dict[tuple[int, str], list[dict]] = defaultdict(list)
        for entry in hostdata.get("ports") or []:
            missing = REQUIRED_PORT_KEYS - entry.keys()
            if missing:
                findings.append(f"{host}: entry {entry} missing keys {sorted(missing)}")
                continue
            port = entry["port"]
            if not isinstance(port, int) or not 1 <= port <= 65535:
                findings.append(f"{host}: invalid port {port!r}")
                continue
            if entry["status"] not in VALID_STATUS:
                findings.append(f"{host}: port {port} invalid status {entry['status']!r}")
            seen[(port, str(entry.get("bind", "*")))].append(entry)
        for (port, bind), entries in seen.items():
            if len(entries) > 1:
                owners = sorted({e["owner"] for e in entries})
                findings.append(
                    f"{host}: port {port} bind {bind} claimed {len(entries)}x "
                    f"(owners: {', '.join(owners)})"
                )


def lint_paths(findings: list[str]) -> None:
    data = yaml.safe_load((REPO / "registry" / "paths.yml").read_text())
    owner_by_prefix: dict[str, str] = {}
    for stack, prefixes in (data.get("prefixes") or {}).items():
        for p in prefixes:
            if not isinstance(p, str):  # brew_services entries are dicts
                continue
            prev = owner_by_prefix.setdefault(p, stack)
            if prev != stack:
                findings.append(f"prefix {p!r} claimed by both {prev} and {stack}")


def main() -> int:
    findings: list[str] = []
    try:
        lint_ports(findings)
        lint_paths(findings)
    except (OSError, yaml.YAMLError) as exc:
        fail(str(exc))
        return 2
    for f in findings:
        fail(f)
    if findings:
        return 1
    print("registry-lint: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
