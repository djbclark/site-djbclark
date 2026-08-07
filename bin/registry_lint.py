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

--reconcile mode (site-djbclark#107): diffs registry/ports.yml's `mac` host
against this machine's actual TCP listeners (`lsof`). Opt-in and advisory
only — never part of the default lint gate above, and always exits 0 — since
the default path also runs in CI, where the host's listeners are meaningless,
and several legitimately-ephemeral listeners (see `ephemeral_processes` in
ports.yml) would otherwise churn it every run.
Run from repo root:  bin/registry_lint.py --reconcile
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
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


def live_listen_ports() -> dict[int, list[tuple[str, str]]]:
    """Return {port: [(pid, command), ...]} for this machine's live TCP
    listeners, via `lsof -F` (machine-readable field output -- robust to the
    column-width variation in lsof's default human-readable format)."""
    proc = subprocess.run(
        ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-F", "pcn"],
        capture_output=True,
        text=True,
        check=True,
    )
    ports: dict[int, list[tuple[str, str]]] = defaultdict(list)
    pid = command = None
    for line in proc.stdout.splitlines():
        tag, value = line[0], line[1:]
        if tag == "p":
            pid = value
        elif tag == "c":
            command = value
        elif tag == "n" and pid is not None and command is not None:
            m = re.search(r":(\d+)$", value)
            if m:
                ports[int(m.group(1))].append((pid, command))
    return ports


def pid_cmdline(pid: str) -> str:
    try:
        proc = subprocess.run(
            ["ps", "-p", pid, "-o", "command="],
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def reconcile(host: str = "mac") -> int:
    """Diff registry/ports.yml[host] against this machine's real listeners.
    Advisory only (site-djbclark#107): always returns 0, never participates
    in the default lint gate's exit code."""
    if sys.platform != "darwin" or shutil.which("lsof") is None:
        print("registry-reconcile: skipped (requires macOS + lsof)")
        return 0

    data = yaml.safe_load((REPO / "registry" / "ports.yml").read_text())
    hostdata = (data.get("hosts") or {}).get(host)
    if hostdata is None:
        print(f"registry-reconcile: no host {host!r} in registry/ports.yml")
        return 0

    declared: dict[int, dict] = {e["port"]: e for e in hostdata.get("ports") or [] if "port" in e}
    ephemeral_patterns = [e["pattern"] for e in hostdata.get("ephemeral_processes") or []]

    try:
        live = live_listen_ports()
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"registry-reconcile: could not run lsof: {exc}")
        return 0

    # Advisory note per the release-vs-deployed-skew case in #107: this
    # checkout's registry/ports.yml may lag origin/master (e.g. running from
    # a deploy checkout still on an older release), which would otherwise
    # read as false "live but undeclared" drift.
    try:
        head = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        origin_master = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--short", "origin/master"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if head and origin_master and head != origin_master:
            print(
                f"registry-reconcile: NOTE this checkout ({head}) differs from "
                f"origin/master ({origin_master}) -- undeclared-live findings below "
                f"may reflect release/branch lag rather than real drift"
            )
    except (subprocess.CalledProcessError, OSError):
        pass  # advisory only; not knowing origin/master is not itself a finding

    undeclared: list[str] = []
    for port, holders in sorted(live.items()):
        if port in declared:
            continue
        cmdlines = [pid_cmdline(pid) or cmd for pid, cmd in holders]
        if any(pat in cmdline for pat in ephemeral_patterns for cmdline in cmdlines):
            continue
        who = ", ".join(sorted(set(cmdlines))) or "?"
        undeclared.append(f"{port} ({who})")

    stale: list[str] = []
    for port, entry in sorted(declared.items()):
        if entry.get("status") == "active" and port not in live:
            stale.append(f"{port} ({entry.get('service', '?')})")

    print(f"registry-reconcile: host={host!r} declared={len(declared)} live={len(live)}")
    if undeclared:
        print("  live but undeclared (possible new/unregistered listener):")
        for line in undeclared:
            print(f"    - {line}")
    if stale:
        print("  declared status:active but not currently listening (stale claim):")
        for line in stale:
            print(f"    - {line}")
    if not undeclared and not stale:
        print("  no differences found")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="diff registry/ports.yml against this machine's live TCP listeners (advisory, always exits 0)",
    )
    parser.add_argument("--host", default="mac", help="host key in registry/ports.yml to reconcile against (default: mac)")
    args = parser.parse_args()

    if args.reconcile:
        return reconcile(args.host)

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
