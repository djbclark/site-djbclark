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
class PendingDelivery(ValueError):
    """Send was accepted or its outcome is unknown; never automatically resend."""


def save_receipt(path, status):
    if path:
        record = Path(path)
        with tempfile.NamedTemporaryFile(mode="w", dir=record.parent, delete=False) as stream:
            json.dump({"status": status}, stream)
            temporary = stream.name
        os.replace(temporary, record)


STEER_PROVIDERS = {"claude", "codex", "opencode", "omp", "pi"}


def call(cli, *args, timeout=20):
    result = subprocess.run([cli, *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise ValueError(f"Paseo {args[0]} exited {result.returncode}")
    return json.loads(result.stdout)


def send(target, text, label="fleet-watch", receipt_file=None):
    """Return zero only for a successful CLI call with a sent/completed receipt.

    Keep agent identity when called manually: queued agent sends require a peer
    ack and must never clear fleet-watch's pending work as delivered.
    """
    if receipt_file and Path(receipt_file).exists():
        try:
            previous = json.loads(Path(receipt_file).read_text())
        except (OSError, ValueError) as error:
            raise PendingDelivery("unreadable send receipt; reconciliation required") from error
        if not isinstance(previous, dict):
            raise PendingDelivery("invalid send receipt; reconciliation required")
        if previous.get("status") in {"sent", "completed"}:
            return 0
        if previous.get("status") != "failed":
            raise PendingDelivery("existing send pending; inspect receipt/peer ack before resolving")
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
    source = os.environ.get("PASEO_AGENT_ID", "").strip()
    if source:
        text += f"\n\nPlease reply: ack {source}"
    # A file keeps notice text out of process listings and option parsing.
    with tempfile.TemporaryDirectory(prefix="fleet-watch-send-") as directory:
        prompt = Path(directory) / "notice.txt"
        prompt.write_text(f"[{label}] {text}", encoding="utf-8")
        # Write ahead before handing a prompt to Paseo. A crash leaves sending,
        # which requires manual receipt/ack reconciliation and is never replayed.
        save_receipt(receipt_file, "sending")
        try:
            receipt = call(cli, "send", aid, "--prompt-file", str(prompt), "--behavior", "steer",
                           "--no-wait", "--json", timeout=60)
        except (subprocess.TimeoutExpired, OSError, ValueError) as error:
            raise PendingDelivery(f"send outcome unknown: {error}") from error
    status = receipt.get("status") if isinstance(receipt, dict) else None
    if status in {"sent", "completed"}:
        try:
            save_receipt(receipt_file, status)
        except OSError as error:
            raise PendingDelivery("delivery receipt could not be persisted; do not replay") from error
        return 0
    if status in {"permission", "error"}:
        save_receipt(receipt_file, "failed")
        raise ValueError(f"not delivered: Paseo receipt status {status!r}")
    try:
        save_receipt(receipt_file, "accepted" if status in {"queued", "accepted"} else "unknown")
    except OSError as error:
        raise PendingDelivery("pending receipt could not be persisted; do not replay") from error
    raise PendingDelivery(f"not delivered: Paseo receipt status {status!r}; hold pending for receipt/peer ack")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("text")
    parser.add_argument("--label", default="fleet-watch", choices=("fleet-watch", "fleet-watch-phantom"))
    parser.add_argument("--receipt-file", help="per-event write-ahead record; pending outcomes require manual reconciliation")
    args = parser.parse_args()
    try:
        return send(args.target, args.text, args.label, args.receipt_file)
    except PendingDelivery as error:
        print(f"fleet-watch Paseo send pending: {error}", file=sys.stderr)
        return 5
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"fleet-watch Paseo send: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
