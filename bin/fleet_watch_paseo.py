#!/usr/bin/env python3
"""Native Paseo delivery for fleet-watch's notices.

Read queries (agent listing and inspect) use the shared zero-subprocess loopback
daemon client (`~/src/djbclark-ade/bin/ade_paseo_client.py`) by default and fail
closed on daemon or module-load errors; CLI fallback is used only when
`FLEET_WATCH_PASEO`, `PASEO_CLI`, `PASEO_HOST` (without forced daemon mode), or
`ADE_PASEO_TRANSPORT=cli` is set, or when `ade_paseo_client.py` is absent under
non-forced mode. Inspection and `paseo send --prompt-file` are always bound to
the same resolved daemon target; conflicting target configurations fail closed.
"""

import argparse
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

TARGET = re.compile(r"(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{4,32})\Z")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class PendingDelivery(ValueError):
    """Send was accepted or its outcome is unknown; never automatically resend."""


class _PaseoClientLoadError(ValueError):
    """Installed ade_paseo_client.py failed to load/initialize."""


def save_receipt(path, status):
    if path:
        record = Path(path)
        with tempfile.NamedTemporaryFile(mode="w", dir=record.parent, delete=False) as stream:
            json.dump({"status": status}, stream)
            temporary = stream.name
        os.replace(temporary, record)


STEER_PROVIDERS = {"claude", "codex", "opencode", "omp", "pi"}


def call(cli, *args, timeout=20, env=None):
    kwargs = {"capture_output": True, "text": True, "timeout": timeout}
    if env is not None:
        kwargs["env"] = env
    result = subprocess.run([cli, *args], **kwargs)
    if result.returncode:
        raise ValueError(f"Paseo {args[0]} exited {result.returncode}")
    return json.loads(result.stdout)


def _resolve_cli_bin(env=None):
    """Choose CLI executable matching transport_mode's cli_env_vars scan.

    A literal "paseo" or whitespace value in FLEET_WATCH_PASEO must not suppress
    a custom PASEO_CLI executable that triggered CLI mode.
    """
    e = os.environ if env is None else env
    fw = (e.get("FLEET_WATCH_PASEO") or "").strip()
    pc = (e.get("PASEO_CLI") or "").strip()
    if fw and fw != "paseo":
        return fw
    if pc and pc != "paseo":
        return pc
    return fw or pc or "paseo"


def _want_daemon_transport(env=None):
    """Mirror ade_paseo_client.transport_mode() before import.

    Returns (use_daemon: bool, forced_daemon: bool).
    Explicit CLI opt-in skips importing ade_paseo_client.py so CLI remains an
    escape hatch if the installed module is broken; CLI-specific PASEO_HOST
    targets route wholly through CLI unless daemon mode is explicitly forced.
    """
    e = os.environ if env is None else env
    if (e.get("ADE_PASEO_URL") or "").strip():
        return True, True
    explicit = (e.get("ADE_PASEO_TRANSPORT") or "").strip().lower()
    if explicit in ("daemon", "http", "ws"):
        return True, True
    if explicit == "cli":
        return False, False
    for key in ("FLEET_WATCH_PASEO", "PASEO_CLI"):
        val = (e.get(key) or "").strip()
        if val and val != "paseo":
            return False, False
    if (e.get("PASEO_HOST") or "").strip():
        return False, False
    return True, False


def _load_paseo_client():
    """Load ade_paseo_client from ~/src/djbclark-ade/bin; None only if absent.

    Raises _PaseoClientLoadError when the file exists on disk but fails to load.
    """
    path = Path.home() / "src/djbclark-ade/bin/ade_paseo_client.py"
    if "ade_paseo_client" in sys.modules:
        existing = sys.modules["ade_paseo_client"]
        if existing is None:
            return None
        existing_file = getattr(existing, "__file__", None)
        if existing_file is None:
            return existing
        try:
            if path.is_file() and Path(existing_file).resolve() == path.resolve():
                return existing
        except OSError:
            pass
    if not path.exists():
        return None
    if not path.is_file():
        raise _PaseoClientLoadError(f"ade_paseo_client path is not a regular file: {path}")
    spec = importlib.util.spec_from_file_location("ade_paseo_client", path)
    if spec is None or spec.loader is None:
        raise _PaseoClientLoadError(f"could not load module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["ade_paseo_client"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        sys.modules.pop("ade_paseo_client", None)
        raise _PaseoClientLoadError(
            f"failed to load ade_paseo_client: {type(error).__name__}: {error}"
        ) from error
    return module


def _parse_local_paseo_host(raw):
    """Parse a local-only PASEO_HOST value into ('tcp', host, port) or ('unix', realpath); else None."""
    text = raw.strip()
    if not text:
        return None
    if text.startswith("unix://") or text.startswith("/") or text.startswith("~"):
        sock = text[len("unix://"):].strip() if text.startswith("unix://") else text
        if not sock or "\x00" in sock:
            return None
        resolved = os.path.realpath(os.path.expanduser(sock))
        if not resolved.startswith("/"):
            return None
        return ("unix", resolved)
    if text.isdigit():
        port = int(text)
        return ("tcp", "127.0.0.1", port) if 1 <= port <= 65535 else None
    if "://" in text:
        parsed = urllib.parse.urlsplit(text)
        if parsed.scheme not in ("tcp", "http", "ws"):
            return None
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            return None
        if parsed.path not in ("", "/", "/ws", "/mcp/agents"):
            return None
    else:
        if "/" in text or "?" in text or "#" in text or "@" in text:
            return None
        parsed = urllib.parse.urlsplit(f"tcp://{text}")
    host = (parsed.hostname or "").strip().lower()
    if host not in LOOPBACK_HOSTS:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is None or not (1 <= port <= 65535):
        return None
    return ("tcp", host, port)


def _target_identity(target):
    """Normalize a PaseoClient.target (or DaemonTarget) into ('tcp', host, port) or ('unix', realpath)."""
    kind = getattr(target, "kind", None)
    if kind == "unix":
        sock = getattr(target, "socket_path", "")
        if not isinstance(sock, str) or not sock.strip():
            return None
        return ("unix", os.path.realpath(sock))
    if kind == "tcp":
        host = getattr(target, "host", "")
        port = getattr(target, "port", None)
        if not isinstance(host, str) or not isinstance(port, int):
            return None
        return ("tcp", host.strip().lower(), port)
    return None


def _identity_to_paseo_host(ident):
    if ident[0] == "unix":
        return f"unix://{ident[1]}"
    _, host, port = ident
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _read_bounded_regular(path, max_bytes=65536):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(str(path), flags)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError(f"unreadable Paseo PID lock {path}: {type(error).__name__}") from error
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > max_bytes:
            raise ValueError(f"invalid Paseo PID lock {path}")
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, max_bytes + 1 - total)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"oversized Paseo PID lock {path}")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _is_pid_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False


def _current_linux_boot_id():
    try:
        text = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        return text or None
    except OSError:
        return None


def _identity_to_daemon_url(ident):
    if ident[0] == "unix":
        return f"unix://{ident[1]}"
    _, host, port = ident
    return f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"


def _resolve_runtime_url_from_pid_lock(paseo_home):
    """Read live runtime listen endpoint from <PASEO_HOME>/paseo.pid (matching Paseo CLI).

    Returns None only when paseo.pid does not exist; fails closed on malformed,
    stale (dead PID / previous boot), not-ready (listen=null), or non-local locks.
    """
    pid_path = Path(paseo_home) / "paseo.pid"
    raw = _read_bounded_regular(pid_path)
    if raw is None:
        return None
    try:
        lock = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("malformed Paseo PID lock") from error
    if not isinstance(lock, dict):
        raise ValueError("invalid Paseo PID lock")
    pid = lock.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ValueError("invalid PID in Paseo PID lock")
    lock_boot = lock.get("bootId")
    cur_boot = _current_linux_boot_id()
    if isinstance(lock_boot, str) and lock_boot and cur_boot and lock_boot != cur_boot:
        raise ValueError(f"Paseo daemon PID lock in {paseo_home} is from a previous boot")
    if not _is_pid_running(pid):
        raise ValueError(f"Paseo daemon PID lock in {paseo_home} is stale (PID {pid} not running)")
    listen = lock.get("listen")
    if not isinstance(listen, str) or not listen.strip():
        raise ValueError(f"Paseo daemon PID {pid} has not published a listen address yet")
    ident = _parse_local_paseo_host(listen)
    if ident is None:
        raise ValueError(f"Paseo PID lock listen address is not a local loopback/unix target: {listen!r}")
    return _identity_to_daemon_url(ident)


def _resolve_paseo_home(env):
    raw = (env.get("PASEO_HOME") or "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".paseo"


def _resolve_send_host(pc, client, env):
    """Return the exact CLI `--host` endpoint matching `client.target`, or fail closed.

    Always binds CLI `paseo send` to the exact inspected endpoint — including on
    default and `PASEO_HOME`-only paths — while retaining `PASEO_HOME` in the
    subprocess environment so Paseo CLI's `readLocalCredentialForTarget(home, host)`
    can load local-credential auth for custom homes.
    """
    ade_url = (env.get("ADE_PASEO_URL") or "").strip()
    paseo_host = (env.get("PASEO_HOST") or "").strip()
    paseo_home = (env.get("PASEO_HOME") or "").strip()

    if paseo_host and paseo_home:
        raise ValueError("PASEO_HOME and PASEO_HOST cannot both be set")

    target_obj = getattr(client, "target", None)
    ident = _target_identity(target_obj)
    if ident is None and ade_url:
        parse_url = getattr(pc, "parse_daemon_url", None)
        if callable(parse_url):
            try:
                target_obj = parse_url(ade_url)
            except pc.DaemonError as error:
                raise ValueError(f"invalid ADE_PASEO_URL: {error}") from error
            ident = _target_identity(target_obj)
    if ident is None:
        raise ValueError("unable to determine daemon endpoint to bind CLI send")

    if paseo_host:
        parsed_host = _parse_local_paseo_host(paseo_host)
        if parsed_host is None or parsed_host != ident:
            raise ValueError("PASEO_HOST disagrees with daemon target; refusing split inspect/send")

    return _identity_to_paseo_host(ident)


def _resolve_target_from_rows(target, rows):
    if isinstance(rows, dict):
        rows = rows.get("agents")
    if not isinstance(rows, list):
        raise ValueError("invalid Paseo agent listing")
    hits = [r for r in rows if isinstance(r, dict) and r.get("id") == target]
    if not hits:
        hits = [r for r in rows if isinstance(r, dict) and str(r.get("shortId") or "").startswith(target)]
    if len(hits) != 1 or not isinstance(hits[0].get("id"), str):
        raise ValueError("target did not resolve to exactly one agent")
    return hits[0]["id"]


def _resolve_and_inspect(target, cli):
    """Resolve TARGET to (aid, inspect_dict, bound_host) via PaseoClient or CLI."""
    env = os.environ
    if (env.get("PASEO_HOME") or "").strip() and (env.get("PASEO_HOST") or "").strip():
        raise ValueError("PASEO_HOME and PASEO_HOST cannot both be set")

    want_daemon, forced_daemon = _want_daemon_transport(env)
    pc = None
    if want_daemon:
        pc = _load_paseo_client()
        if pc is None and forced_daemon:
            raise ValueError("ade_paseo_client unavailable under forced daemon transport")

    use_daemon = (
        want_daemon
        and pc is not None
        and pc.transport_mode(cli_env_vars=("FLEET_WATCH_PASEO", "PASEO_CLI")) == "daemon"
    )
    if use_daemon:
        not_found_err = getattr(pc, "AgentNotFoundError", ())
        ade_url = (env.get("ADE_PASEO_URL") or "").strip()
        client_kwargs = {"timeout": 20}
        if not ade_url:
            paseo_home = _resolve_paseo_home(env)
            runtime_url = _resolve_runtime_url_from_pid_lock(paseo_home)
            if runtime_url is not None:
                client_kwargs["url"] = runtime_url
        try:
            client = pc.PaseoClient(**client_kwargs)
        except pc.DaemonError as error:
            raise ValueError(f"Paseo daemon unavailable: {error}") from error
        bound_host = _resolve_send_host(pc, client, env)
        if UUID_RE.fullmatch(target):
            try:
                info = client.inspect_agent(target, cli_shape=True)
            except not_found_err as error:
                raise ValueError("target did not resolve to exactly one agent") from error
            except pc.DaemonError as error:
                raise ValueError(f"Paseo daemon inspect failed: {error}") from error
            return target, info, bound_host
        if getattr(getattr(client, "target", None), "mcp_only", False) is True:
            raise ValueError("MCP-only daemon URL cannot safely resolve shortId prefixes")
        try:
            rows = client.list_agents(include_background=True, include_archived=True, cli_rows=True)
        except pc.DaemonError as error:
            raise ValueError(f"Paseo daemon ls failed: {error}") from error
        aid = _resolve_target_from_rows(target, rows)
        try:
            info = client.inspect_agent(aid, cli_shape=True)
        except not_found_err as error:
            raise ValueError("target is unavailable, archived, or awaiting permission/question") from error
        except pc.DaemonError as error:
            raise ValueError(f"Paseo daemon inspect failed: {error}") from error
        return aid, info, bound_host

    rows = call(cli, "ls", "-a", "-g", "--json")
    aid = _resolve_target_from_rows(target, rows)
    info = call(cli, "agent", "inspect", aid, "--json")
    return aid, info, None


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
    cli = _resolve_cli_bin()
    aid, info, bound_host = _resolve_and_inspect(target, cli)
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
            send_args = ["send", aid]
            if bound_host is not None:
                send_args.extend(["--host", bound_host])
            send_args.extend(["--prompt-file", str(prompt), "--behavior", "steer", "--no-wait", "--json"])
            receipt = call(cli, *send_args, timeout=60)
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
