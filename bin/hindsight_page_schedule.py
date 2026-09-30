#!/usr/bin/env python3
"""Put every Hindsight knowledge page on a staggered cron refresh instead of refresh-after-consolidation.

The coding-agent plugin creates its knowledge pages (mental models tagged
"knowledge:*") with refresh_after_consolidation: true, so every consolidation
re-runs a 1-5 minute reflect for each of a bank's pages. Measured 2026-09-30:
~90 refreshes in 8.5 h, 17 in one hour for one bank, holding the worker's
shared slots while retains queued. A cron refresh only runs when the page is
stale, so an active bank refreshes at most once per interval.

Each bank gets its own minute and hour offset (crc32 of the bank id) so banks
do not all refresh at once. Idempotent: only pages whose trigger differs are
patched. Non-knowledge mental models are left alone.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
import zlib


def call(method: str, url: str, body: object = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else {}


def cron_for(bank: str, every_hours: int) -> str:
    h = zlib.crc32(bank.encode())
    minute, offset = h % 60, (h // 60) % every_hours
    hours = ",".join(str(x) for x in range(offset, 24, every_hours))
    return f"{minute} {hours} * * *"


def main() -> int:
    ap = argparse.ArgumentParser(description="Stagger Hindsight knowledge-page refreshes on a cron schedule.")
    ap.add_argument("--api", default="http://127.0.0.1:8888")
    ap.add_argument("--every-hours", type=int, default=6, choices=[1, 2, 3, 4, 6, 8, 12, 24])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    banks_resp = call("GET", f"{a.api}/v1/default/banks")
    banks = [b.get("bank_id") or b.get("id") for b in (banks_resp.get("banks") or banks_resp.get("items") or [])]
    patched = kept = 0
    for bank in banks:
        base = f"{a.api}/v1/default/banks/{urllib.parse.quote(bank, safe='')}/mental-models"
        cron = cron_for(bank, a.every_hours)
        for mm in call("GET", base).get("items", []):
            if not any(t.startswith("knowledge:") for t in mm.get("tags") or []):
                continue
            trig = dict(mm.get("trigger") or {})
            want = {**trig, "refresh_after_consolidation": False, "refresh_cron": cron, "exclude_mental_models": True}
            if trig == want:
                kept += 1
                continue
            print(f"{bank}: {mm['name']!r} -> {cron}")
            if not a.dry_run:
                call("PATCH", f"{base}/{urllib.parse.quote(mm['id'], safe='')}", {"trigger": want})
            patched += 1
    print(f"page-schedule: patched={patched} already={kept} every={a.every_hours}h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
