#!/usr/bin/env python3
"""Per-bank Hindsight backups, so a mistaken delete is a one-bank restore.

Hindsight stores every bank in one Postgres instance
(`~/.pg0/instances/hindsight`). That means the only *database-level* recovery
from `DELETE /banks/<id>` is restoring the whole instance from Arq — hours of
work, and it rolls back every other bank to the snapshot time. On 2026-08-23
exactly that happened: `hermes-default-hermes` was deleted in a cleanup sweep,
and recovering 1 document and 5 facts would have meant standing up a second
Postgres instance from backup.

The fix does not need Postgres at all. Hindsight's `document-transfer`
endpoint exports one bank as a self-contained ZIP and imports it back, so a
scheduled per-bank export gives **granular** recovery: re-import the one zip,
touch nothing else. That composes with Arq rather than competing — Arq still
protects the instance; this protects against *our* mistakes, which are the
likelier failure.

Usage:
    hindsight_bank_backup.py run              # export every bank, rotate
    hindsight_bank_backup.py run --keep 14
    hindsight_bank_backup.py restore <bank> [--from <zip>]   # prints the command
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API = "http://127.0.0.1:8888/v1/default/banks"
DEST = Path.home() / "hindsight-backups"
KEEP_DAYS = 14


def banks() -> list[str]:
    with urllib.request.urlopen(API, timeout=60) as fh:
        payload = json.load(fh)
    items = payload if isinstance(payload, list) else (
        payload.get("banks") or payload.get("items") or [])
    return sorted(str(b.get("id") or b.get("bank_id")) for b in items if b)


def export_bank(bank: str, target: Path) -> int:
    """Export one bank to a ZIP. Returns bytes written (0 = failed)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".partial")
    url = f"{API}/{urllib.parse.quote(bank, safe='')}/document-transfer"
    # curl rather than urllib: these can be hundreds of MB and curl streams
    # to disk without holding the body in memory.
    result = subprocess.run(
        ["curl", "-sS", "-m", "900", url, "-o", str(tmp)],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        return 0
    tmp.replace(target)          # only a complete file gets the real name
    return target.stat().st_size


def rotate(keep: int) -> list[str]:
    """Drop snapshot directories beyond the newest `keep`."""
    snaps = sorted((p for p in DEST.glob("20*-*-*") if p.is_dir()), reverse=True)
    dropped = []
    for old in snaps[keep:]:
        shutil.rmtree(old, ignore_errors=True)
        dropped.append(old.name)
    return dropped


def run(keep: int = KEEP_DAYS) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = DEST / stamp
    results, failed, total = {}, [], 0
    for bank in banks():
        size = export_bank(bank, out / f"{bank.replace('/', '_')}.zip")
        results[bank] = size
        total += size
        if size == 0:
            failed.append(bank)
    report = {
        "snapshot": str(out),
        "banks": len(results),
        "bytes": total,
        "failed": failed,
        "rotated_out": rotate(keep),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-bank Hindsight backups")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--keep", type=int, default=KEEP_DAYS)
    s = sub.add_parser("restore", help="print the restore command for a bank")
    s.add_argument("bank")
    s.add_argument("--from", dest="src", default=None)

    args = parser.parse_args(argv)
    if args.command == "run":
        report = run(keep=args.keep)
        print(json.dumps(report, indent=2))
        # Non-zero on failure so the scheduler surfaces it rather than
        # reporting a green run that backed nothing up.
        return 1 if report["failed"] or not report["banks"] else 0

    src = args.src
    if not src:
        found = sorted(DEST.glob(f"20*-*-*/{args.bank.replace('/', '_')}.zip"), reverse=True)
        src = str(found[0]) if found else "<no snapshot found>"
    print(f"# restore {args.bank} without touching any other bank:")
    print(f"curl -sS -X POST '{API}/{urllib.parse.quote(args.bank, safe='')}"
          f"/document-transfer?on_conflict=skip' -F 'file=@{src}'")
    print("# then poll the returned operation_id until completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
