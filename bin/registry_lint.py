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

import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
REQUIRED_PORT_KEYS = {"port", "owner", "service", "status"}
VALID_STATUS = {"active", "planned", "default-claim"}

# Site-owned Ansible roles that declare their own port default, each
# cross-checked against the registry/ports.yml entry with the matching
# `service` name (any host). Catches the same drift class that motivated
# registry/ports.yml's caddy_path field: two independently hand-maintained
# literals silently disagreeing (litellm_port/open_webui_port had no
# automated check at all until this lint was added, 2026-08-03).
# stayturgid-owned roles get an equivalent guarantee from stayturgid's own
# control/site_contract/generate_registry_seeds.py --check; these two
# site-djbclark-owned roles aren't covered by that generator (it only
# resolves file paths inside the stayturgid repo).
ROLE_DEFAULT_PORT_SOURCES: list[dict[str, str]] = [
    {"file": "roles/litellm/defaults/main.yml", "yaml_key": "litellm_port", "service": "litellm-proxy"},
    {"file": "roles/open_webui/defaults/main.yml", "yaml_key": "open_webui_port", "service": "open-webui"},
]


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
        # A wildcard bind covers every address: the same port under both a
        # wildcard and a specific bind is a real listen conflict even though
        # the (port, bind) keys differ.
        by_port: dict[int, set[str]] = defaultdict(set)
        for port, bind in seen:
            by_port[port].add(bind)
        for port, binds in by_port.items():
            if len(binds) > 1 and binds & {"*", "0.0.0.0", "::"}:
                findings.append(
                    f"{host}: port {port} claimed under wildcard and specific binds "
                    f"({', '.join(sorted(binds))}) — wildcard covers all addresses"
                )


def lint_role_default_ports(findings: list[str]) -> None:
    ports_data = yaml.safe_load((REPO / "registry" / "ports.yml").read_text())
    hosts = ports_data.get("hosts") or {}

    for spec in ROLE_DEFAULT_PORT_SOURCES:
        path = REPO / spec["file"]
        try:
            role_defaults = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as exc:
            findings.append(f"role defaults {spec['file']}: cannot read/parse: {exc}")
            continue
        if not isinstance(role_defaults, dict) or spec["yaml_key"] not in role_defaults:
            findings.append(f"role defaults {spec['file']}: missing key {spec['yaml_key']!r}")
            continue
        role_port = role_defaults[spec["yaml_key"]]
        if not isinstance(role_port, int) or isinstance(role_port, bool):
            findings.append(
                f"role defaults {spec['file']}: {spec['yaml_key']} is not a plain integer "
                f"({role_port!r}) -- the registry drift lint needs a literal, not a Jinja expression"
            )
            continue

        matched = False
        for host, hostdata in hosts.items():
            for entry in hostdata.get("ports") or []:
                if entry.get("service") != spec["service"]:
                    continue
                matched = True
                if entry.get("port") != role_port:
                    findings.append(
                        f"{spec['file']}: {spec['yaml_key']}={role_port} does not match "
                        f"registry/ports.yml host {host!r} service {spec['service']!r} "
                        f"port={entry.get('port')!r} -- keep the role default and the registry entry in sync"
                    )
        if not matched:
            findings.append(
                f"{spec['file']}: no registry/ports.yml entry found for service {spec['service']!r} "
                f"(role default {spec['yaml_key']}={role_port})"
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


def lint_generated_paths() -> None:
    """Drift guard for stayturgid#100: reject absolute paths in path-bearing artifacts."""
    artifacts = [
        "generated/stayturgid/fragments/grafana/dashboards/provider.yaml",
        "generated/stayturgid/fragments/olivetin/stayturgid_actions.yaml",
    ]
    for rel_path in artifacts:
        path = REPO / rel_path
        if not path.exists():
            continue
        if not path.is_file():
            fail(f"{rel_path} exists but is not a regular file")
            sys.exit(2)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            fail(f"cannot read {rel_path}: {exc}")
            sys.exit(2)
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if re.match(r'^(?:path:|cd)\s+["\']?/', stripped):
                fail(f"{rel_path}:{i} contains an absolute path (must use portable ${{OPS_ROOT...}} form)")
                sys.exit(2)


def main() -> int:
    findings: list[str] = []
    try:
        lint_ports(findings)
        lint_role_default_ports(findings)
        lint_paths(findings)
        lint_generated_paths()
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
