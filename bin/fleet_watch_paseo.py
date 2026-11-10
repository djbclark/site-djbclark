#!/usr/bin/env python3
"""Native Paseo delivery for fleet-watch's notices; no ADE relay dependency."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TARGET = re.compile(r"(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{4,32})\Z")
STEER_PROVIDERS = {"claude", "codex", "opencode", "omp", "pi"}


def call(cli, *args, timeout=20):
    result = subprocess.run([cli, *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise ValueError(f"Paseo {args[0]} exited {result.returncode}")
    return json.loads(result.stdout)


def send(target, text, label="fleet-watch"):
    """Return zero only for a successful CLI call with a sent/completed receipt.

    Keep agent identity when called manually: queued agent sends require a peer
    ack and must never clear fleet-watch's pending work as delivered.
    """
    if not TARGET.fullmatch(target):
        raise ValueError("target must be a Paseo id or unique shortId prefix")
    cli = os.environ.get("FLEET_WATCH_PASEO") or os.environ.get("PASEO_CLI") or "paseo"
    rows = call(cli, "ls", "-a", "-g", "--json")
    if isinstance(rows, dict):
        rows = rows.get("agents")
    if not isinstance(rows, list):
        raise ValueError("invalid Paseo agent listing")
    hits = [r for r in rows if isinstance(r, dict) and r.get("id") == target]
    if not hits:
        hits = [r for r in rows if isinstance(r, dict) and str(r.get("shortId") or "").startswith(target)]
    if len(hits) != 1 or not isinstance(hits[0].get("id"), str):
        raise ValueError("target did not resolve to exactly one agent")
    aid = hits[0]["id"]
    info = call(cli, "agent", "inspect", aid, "--json")
    if (not isinstance(info, dict) or info.get("Id") != aid
            or info.get("Archived") is not False or info.get("PendingPermissions") != []
            or info.get("Status") not in {"idle", "running", "closed"}):
        raise ValueError("target is unavailable, archived, or awaiting permission/question")
    if info["Status"] == "running":
        caps = info.get("Capabilities")
        steer = [v for k, v in caps.items() if "steer" in str(k).lower()] if isinstance(caps, dict) else []
        provider = str(info.get("Provider") or "").split("/")[0]
        if not (steer[0] is True if steer else provider in STEER_PROVIDERS):
            raise ValueError("target's running provider cannot safely steer")
    # A file keeps notice text out of process listings and option parsing.
    with tempfile.TemporaryDirectory(prefix="fleet-watch-send-") as directory:
        prompt = Path(directory) / "notice.txt"
        prompt.write_text(f"[{label}] {text}", encoding="utf-8")
        receipt = call(cli, "send", aid, "--prompt-file", str(prompt), "--behavior", "steer",
                       "--no-wait", "--json", timeout=60)
    status = receipt.get("status") if isinstance(receipt, dict) else None
    if status not in {"sent", "completed"}:
        raise ValueError(f"not delivered: Paseo receipt status {status!r}; queued/accepted requires peer ack")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("text")
    parser.add_argument("--label", default="fleet-watch", choices=("fleet-watch", "fleet-watch-phantom"))
    args = parser.parse_args()
    try:
        return send(args.target, args.text, args.label)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"fleet-watch Paseo send: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
