#!/usr/bin/env -S uv run --quiet --with pyyaml python3
"""Render /etc/mac-dns.allow from inventory/group_vars/all.yml.

One fact per line, exact-match checked by mac-dns-apply:
  resolver <tailnet_magicdns_suffix>
  nameserver <each tailnet_magicdns_nameservers>
  search <each tailnet_search_domains>
Sorted, so the file is byte-stable for the drift comparison.
"""
from __future__ import annotations

import sys

import yaml


def render(group_vars: dict) -> str:
    lines = [f"resolver {group_vars['tailnet_magicdns_suffix']}"]
    lines += [f"nameserver {ns}" for ns in group_vars["tailnet_magicdns_nameservers"]]
    lines += [f"search {d}" for d in group_vars.get("tailnet_search_domains", [])]
    return "".join(f"{line}\n" for line in sorted(set(lines)))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: render-allow-list.py inventory/group_vars/all.yml", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    sys.stdout.write(render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
