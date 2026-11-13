#!/usr/bin/env python3
"""Native Paseo delivery and dispatch for fleet-watch; no ADE relay/acp-dispatch dependency."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

TARGET = re.compile(r"(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{4,32})\Z")


class PendingDelivery(ValueError):
    """Send was accepted or its outcome is unknown; never automatically resend."""


class LaunchUnknown(ValueError):
    """The launch may have created a worker; never retry automatically."""


class QuotaUnavailable(ValueError):
    """No pool available with required headroom."""


def save_receipt(path, status):
    if path:
        record = Path(path)
        with tempfile.NamedTemporaryFile(mode="w", dir=record.parent, delete=False) as stream:
            json.dump({"status": status}, stream)
            temporary = stream.name
        os.replace(temporary, record)


STEER_PROVIDERS = {"claude", "codex", "opencode", "omp", "pi"}


# Caller placement that must never steer a worker: `paseo run --workspace` ignores
# --cwd, and a caller agent id lets the new workspace inherit its background flag.
AMBIENT_PASEO_ENV = ("PASEO_AGENT_ID", "PASEO_AGENT_CWD", "PASEO_WORKSPACE_ID")
FINISHED = {"idle", "closed"}
FREE = 10  # upstream-busy: no worker holds dispatch. Any other exit (also a crash) means busy.


def clean_env():
    return {k: v for k, v in os.environ.items() if k not in AMBIENT_PASEO_ENV}


def call(cli, *args, timeout=20, env=None):
    result = subprocess.run([cli, *args], capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode:
        raise ValueError(f"Paseo {args[0]} exited {result.returncode}")
    return json.loads(result.stdout)


def count_running_agents(cli=None):
    cli = cli or os.environ.get("FLEET_WATCH_PASEO") or os.environ.get("PASEO_CLI") or "paseo"
    try:
        rows = call(cli, "ls", "-g", "--background", "--json", timeout=20)
        if isinstance(rows, dict):
            rows = rows.get("agents")
        if isinstance(rows, list):
            return sum(1 for a in rows if isinstance(a, dict) and a.get("status") == "running")
    except Exception:
        pass
    return 0


def age_seconds(created):
    """Seconds since an ISO-8601 createdAt (agent inspect's CreatedAt); None when unreadable."""
    try:
        moment = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - moment).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def worker_age(cli, agent_id):
    """Age of a worker from `agent inspect` (ls rows carry only a relative `created` text)."""
    try:
        info = call(cli, "agent", "inspect", str(agent_id), "--json", timeout=20)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return age_seconds(info.get("CreatedAt")) if isinstance(info, dict) else None


def upstream_busy(task, max_age=None):
    """Exit FREE (10) when no native worker holds dispatch; anything else holds.

    The listing is non-archived (-g) with background agents (--background), so
    archiving a worker releases the gate. `ls --json` rows have no timestamps:
    a running worker's age comes from `agent inspect`. A worker past max_age
    seconds is "overdue", an `error` worker "errored"; both still hold and
    name the id to archive by hand (stopping paid work is the operator's call).
    """
    cli = os.environ.get("FLEET_WATCH_PASEO") or os.environ.get("PASEO_CLI") or "paseo"
    try:
        rows = call(cli, "ls", "-g", "--background", "--label", f"ade.task={task}",
                    "--label", "ade.via=fleet-watch", "--json")
        if isinstance(rows, dict):
            rows = rows.get("agents")
        if not isinstance(rows, list):
            raise ValueError("invalid Paseo agent listing")
        for row in rows:
            if isinstance(row, dict) and row.get("status") in FINISHED:
                continue
            ident = row.get("id") if isinstance(row, dict) else None
            status = row.get("status") if isinstance(row, dict) else None
            if status == "error":
                print(f"native Paseo worker errored ({ident or '?'}): it holds dispatch until archived: "
                      f"paseo agent archive {ident or '<id>'}")
                return 0
            if ident and max_age:
                age = worker_age(cli, ident)
                if age is not None and age > max_age:
                    print(f"native Paseo worker overdue ({ident}, {int(age // 60)} min running, bound "
                          f"{int(max_age // 60)} min): archive it by hand if hung: paseo agent archive {ident}")
                    return 0
            print("native Paseo worker active (or status unknown)")
            return 0
        return FREE
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"native Paseo worker state unavailable: {error}")
        return 0


def check_headroom(min_headroom=10.0):
    if min_headroom <= 0:
        return
    aiuse_bin = os.environ.get("FLEET_WATCH_AIUSE") or shutil.which("aiuse") or str(Path.home() / ".local/bin/aiuse")
    if not aiuse_bin or not Path(aiuse_bin).exists():
        return
    try:
        res = subprocess.run([aiuse_bin, "--available", "--json"], capture_output=True, text=True, timeout=20)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            pools = data.get("available") if isinstance(data, dict) else []
            has_pool = any(
                isinstance(p, dict) and p.get("provider") == "claude"
                and p.get("pool_family") != "fable" and p.get("usable_now") is True
                and (p.get("headroom_percent") or 0) >= min_headroom
                for p in pools
            )
            if not has_pool and len(pools) > 0:
                raise QuotaUnavailable(f"no Claude pool with {min_headroom}% headroom left")
        elif res.returncode == 3:
            raise QuotaUnavailable("aiuse: nothing usable")
    except QuotaUnavailable:
        raise
    except Exception:
        pass


def resolve_workspace(cli, target_dir, explicit=None):
    """A workspace id only when its directory is the target; else None (new workspace).

    `paseo run --workspace` ignores --cwd, so an id whose directory differs would
    land the worker elsewhere. The ambient PASEO_WORKSPACE_ID is never consulted;
    an explicit id (argument or FLEET_WATCH_PASEO_WORKSPACE) must match too.
    """
    target_real = os.path.realpath(os.path.expanduser(target_dir))
    ws_id = explicit or os.environ.get("FLEET_WATCH_PASEO_WORKSPACE")
    try:
        rows = call(cli, "workspace", "ls", "--json", timeout=20, env=clean_env())
        if isinstance(rows, dict):
            rows = rows.get("workspaces")
        if isinstance(rows, list):
            matches = []
            for w in rows:
                if isinstance(w, dict):
                    w_cwd = w.get("cwd")
                    wid = w.get("workspaceId") or w.get("id")
                    if wid and w_cwd and os.path.realpath(os.path.expanduser(w_cwd)) == target_real:
                        matches.append(wid)
            if ws_id and ws_id in matches:
                return ws_id
            if matches:
                return matches[0]
    except Exception:
        pass
    return None


def find_worker(cli, name):
    """Id of the worker labelled ade.name=NAME; "" when none; None when the lookup fails."""
    try:
        rows = call(cli, "ls", "-a", "-g", "--label", f"ade.name={name}", "--json", timeout=30, env=clean_env())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if isinstance(rows, dict):
        rows = rows.get("agents")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and row.get("id"):
            return str(row["id"])
    return ""


def dispatch(name, brief, cwd=".", provider="claude/sonnet", mode="bypassPermissions",
             kind="judgment", task="upstream-pr", min_headroom=10.0,
             lead=None, workspace=None):
    """Launch asynchronously with standard labels; no worker runtime timeout.

    The 120-second subprocess timeout bounds launch acknowledgement only.
    Detached workers run until completion; their live status gates further dispatch.
    """
    check_headroom(min_headroom)
    brief_path = Path(brief).expanduser()
    if not brief_path.is_file():
        raise ValueError(f"brief file does not exist: {brief}")
    prompt_text = brief_path.read_text(encoding="utf-8")

    cwd_path = Path(cwd).expanduser().resolve()
    if not cwd_path.is_dir():
        raise ValueError(f"worker directory does not exist: {cwd_path}")

    cli = os.environ.get("FLEET_WATCH_PASEO") or os.environ.get("PASEO_CLI") or "paseo"
    ws = resolve_workspace(cli, str(cwd_path), workspace)

    lead_id = lead or os.environ.get("PASEO_AGENT_ID", "").strip() or "main"
    labels = [
        f"ade.kind={kind}",
        f"ade.name={name}",
        f"ade.task={task}",
        f"ade.lead={lead_id}",
        "ade.via=fleet-watch",
    ]

    argv = [
        cli, "run",
        "--provider", provider,
        "--mode", mode,
        "--title", name,
        "--cwd", str(cwd_path),
        "--no-wait",
        "--json",
    ]
    if ws:
        argv.extend(["--workspace", ws])
    else:
        argv.extend(["--new-workspace", "local"])
    for lb in labels:
        argv.extend(["--label", lb])
    argv.extend(["--", prompt_text])

    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=120, env=clean_env())
        failure = f"paseo run exited {result.returncode}: {(result.stderr or result.stdout).strip()}" if result.returncode else None
    except subprocess.TimeoutExpired:
        result, failure = None, "paseo run timed out"
    if failure:
        # The agent may already exist: never let fleet-watch dispatch it a second time.
        worker = find_worker(cli, name)
        if worker:
            print(f"detached\t{name}\tagent: {worker} (found after: {failure})")
            return 0
        if worker is None or result is None:
            raise LaunchUnknown(f"{failure}; worker {name} lookup "
                                f"{'failed' if worker is None else 'found nothing'}: outcome unknown")
        raise ValueError(failure)
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except ValueError:
        data = {}
    aid = data.get("agentId") if isinstance(data, dict) else None
    if not aid and isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        aid = data[0].get("agentId") or data[0].get("id")
    print(f"detached\t{name}\tagent: {aid or 'ok'}")
    return 0


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
    if len(sys.argv) > 1 and sys.argv[1] == "dispatch":
        parser = argparse.ArgumentParser(description="Native Paseo dispatch for fleet-watch workers")
        parser.add_argument("dispatch")  # absorbs "dispatch"
        parser.add_argument("--name", required=True, help="Agent/slice name")
        parser.add_argument("--brief", required=True, help="Path to brief markdown file")
        parser.add_argument("--cwd", default=".", help="Working directory for the agent")
        parser.add_argument("--provider", default="claude/sonnet", help="Provider/model (default: claude/sonnet)")
        parser.add_argument("--mode", default="bypassPermissions", help="Provider mode (default: bypassPermissions)")
        parser.add_argument("--kind", default="judgment", help="Task kind label (default: judgment)")
        parser.add_argument("--task", default="upstream-pr", help="Task name label (default: upstream-pr)")
        parser.add_argument("--min-headroom", type=float, default=10.0, help="Minimum quota headroom percent")
        parser.add_argument("--lead", help="Lead agent id (defaults to PASEO_AGENT_ID or main)")
        parser.add_argument("--workspace", help="Explicit Paseo workspace id")
        args = parser.parse_args()
        try:
            return dispatch(
                name=args.name,
                brief=args.brief,
                cwd=args.cwd,
                provider=args.provider,
                mode=args.mode,
                kind=args.kind,
                task=args.task,
                min_headroom=args.min_headroom,
                lead=args.lead,
                workspace=args.workspace,
            )
        except QuotaUnavailable as error:
            print(f"fleet-watch Paseo dispatch no quota: {error}", file=sys.stderr)
            return 5
        except LaunchUnknown as error:
            print(f"fleet-watch Paseo dispatch unknown: {error}", file=sys.stderr)
            return 6
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            print(f"fleet-watch Paseo dispatch failed: {error}", file=sys.stderr)
            return 1
    elif len(sys.argv) > 1 and sys.argv[1] == "upstream-busy":
        parser = argparse.ArgumentParser(description=upstream_busy.__doc__)
        parser.add_argument("upstream-busy")
        parser.add_argument("--task", required=True)
        parser.add_argument("--max-age", type=float, default=None, help="seconds before a running worker is reported overdue")
        opts = parser.parse_args()
        return upstream_busy(opts.task, opts.max_age)
    elif len(sys.argv) > 1 and sys.argv[1] in ("agents", "count-agents"):
        print(count_running_agents())
        return 0
    else:
        # Default: send mode
        parser = argparse.ArgumentParser(description=__doc__)
        if len(sys.argv) > 1 and sys.argv[1] == "send":
            parser.add_argument("send")
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
