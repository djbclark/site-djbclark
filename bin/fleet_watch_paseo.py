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
import ctypes
import datetime
import importlib.util
import json
import os
import re
import stat
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

TARGET = re.compile(r"(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{4,32})\Z")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
BOOT_TOLERANCE_S = 5.0


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


def _parse_local_endpoint(raw):
    """Parse a local-only endpoint into (canonical_ident, cli_spelling, daemon_url); else None.

    Uses canonical identity (`realpath` for Unix sockets) for security/equality
    comparisons while preserving the verified Unix path spelling (without
    `realpath` rewriting `/tmp` -> `/private/tmp`) for CLI `--host` so Paseo's
    `readLocalCredentialForTarget` matches `paseo.pid.listen`.
    """
    text = raw.strip()
    if not text:
        return None
    if text.startswith("unix://") or text.startswith("/") or text.startswith("~"):
        sock = text[len("unix://"):].strip() if text.startswith("unix://") else text
        if not sock or "\x00" in sock:
            return None
        expanded = os.path.expanduser(sock)
        if not expanded.startswith("/") or ".." in Path(expanded).parts:
            return None
        resolved = os.path.realpath(expanded)
        if not resolved.startswith("/"):
            return None
        spelling = f"unix://{expanded}"
        return (("unix", resolved), spelling, spelling)
    if text.isdigit():
        port = int(text)
        if not (1 <= port <= 65535):
            return None
        return (("tcp", "127.0.0.1", port), f"127.0.0.1:{port}", f"http://127.0.0.1:{port}")
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
    spelling = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    return (("tcp", host, port), spelling, f"http://{spelling}")


def _parse_local_paseo_host(raw):
    parsed = _parse_local_endpoint(raw)
    return parsed[0] if parsed is not None else None


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


def _target_cli_spelling(target):
    """Preserve PaseoClient.target's un-canonicalized spelling for CLI `--host`."""
    kind = getattr(target, "kind", None)
    if kind == "unix":
        sock = getattr(target, "socket_path", "")
        if isinstance(sock, str) and sock.strip():
            return f"unix://{sock.strip()}"
        return None
    if kind == "tcp":
        host = getattr(target, "host", "")
        port = getattr(target, "port", None)
        if isinstance(host, str) and isinstance(port, int):
            h = host.strip().lower()
            return f"[{h}]:{port}" if ":" in h else f"{h}:{port}"
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


def _host_boot_epoch():
    """Return host boot time in epoch seconds (macOS kern.boottime or Linux /proc/uptime), or None."""
    if sys.platform == "darwin":
        try:
            libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            buf = ctypes.create_string_buffer(16)
            size = ctypes.c_size_t(16)
            if libc.sysctlbyname(b"kern.boottime", buf, ctypes.byref(size), None, 0) == 0 and size.value >= 12:
                sec, usec = struct.unpack("qi", buf.raw[:12])
                return sec + usec / 1_000_000.0
        except OSError:
            pass
    try:
        uptime_s = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        return time.time() - uptime_s
    except (OSError, ValueError, IndexError):
        return None


def _parse_iso_epoch(stamp):
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    try:
        dt = datetime.datetime.fromisoformat(stamp.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.timestamp()


def _resolve_runtime_endpoint_from_pid_lock(paseo_home):
    """Read live runtime listen endpoint from <PASEO_HOME>/paseo.pid (matching Paseo CLI).

    Returns (canonical_ident, cli_spelling, daemon_url) or None when paseo.pid
    does not exist. Fails closed on malformed, stale (dead PID or predating
    current host boot), not-ready (listen=null), or non-local locks without
    echoing raw rejected listen text.
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
    if isinstance(lock_boot, str) and lock_boot and cur_boot:
        if lock_boot != cur_boot:
            raise ValueError(f"Paseo daemon PID lock in {paseo_home} is from a previous boot")
    else:
        started_ts = _parse_iso_epoch(lock.get("startedAt"))
        boot_epoch = _host_boot_epoch() if started_ts is not None else None
        if started_ts is not None and boot_epoch is not None and started_ts < boot_epoch - BOOT_TOLERANCE_S:
            raise ValueError(f"Paseo daemon PID lock in {paseo_home} predates current host boot")
    if not _is_pid_running(pid):
        raise ValueError(f"Paseo daemon PID lock in {paseo_home} is stale (PID {pid} not running)")
    listen = lock.get("listen")
    if not isinstance(listen, str) or not listen.strip():
        raise ValueError(f"Paseo daemon PID {pid} has not published a listen address yet")
    parsed = _parse_local_endpoint(listen)
    if parsed is None:
        raise ValueError("Paseo PID lock listen address is not a valid local loopback or unix target")
    return parsed


def _resolve_paseo_home(env):
    raw = (env.get("PASEO_HOME") or "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".paseo"


def _resolve_send_host(pc, client, env, *, preferred_host=None):
    """Return the exact CLI `--host` endpoint matching `client.target`, or fail closed.

    Preserves the verified un-canonicalized Unix path spelling (so Paseo CLI's
    `readLocalCredentialForTarget(home, host)` matches `paseo.pid.listen`) while
    using canonical identity for target-agreement checks.
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

    if preferred_host:
        pref_parsed = _parse_local_endpoint(preferred_host)
        if pref_parsed is not None and pref_parsed[0] == ident:
            return pref_parsed[1]

    spelling = _target_cli_spelling(target_obj)
    if spelling is not None:
        return spelling
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


def _resolve_and_inspect(target, cli, *, expected_host=None):
    """Resolve TARGET to (aid, inspect_dict, bound_host) via PaseoClient or CLI."""
    env = os.environ
    if (env.get("PASEO_HOME") or "").strip() and (env.get("PASEO_HOST") or "").strip():
        raise ValueError("PASEO_HOME and PASEO_HOST cannot both be set")

    expected = None
    if expected_host is not None:
        expected = _parse_local_endpoint(expected_host)
        if expected is None:
            raise ValueError("bound --host is not a valid local loopback or unix target")

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
        preferred_host = None
        if not ade_url:
            paseo_home = _resolve_paseo_home(env)
            runtime = _resolve_runtime_endpoint_from_pid_lock(paseo_home)
            if runtime is not None:
                runtime_ident, runtime_spelling, runtime_url = runtime
                if expected is not None and runtime_ident != expected[0]:
                    raise ValueError("bound --host disagrees with live Paseo daemon endpoint")
                client_kwargs["url"] = runtime_url
                preferred_host = runtime_spelling
            elif expected is not None:
                client_kwargs["url"] = expected[2]
                preferred_host = expected[1]
        elif expected is not None:
            ade_parsed = _parse_local_endpoint(ade_url)
            if ade_parsed is None or ade_parsed[0] != expected[0]:
                raise ValueError("bound --host disagrees with ADE_PASEO_URL")
            preferred_host = expected[1]
        try:
            client = pc.PaseoClient(**client_kwargs)
        except pc.DaemonError as error:
            raise ValueError(f"Paseo daemon unavailable: {error}") from error
        bound_host = _resolve_send_host(pc, client, env, preferred_host=preferred_host)
        if expected is not None:
            bound_ident = _parse_local_paseo_host(bound_host)
            if bound_ident != expected[0]:
                raise ValueError("bound --host disagrees with resolved Paseo daemon target")
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

    host_flags = ["--host", expected[1]] if expected is not None else []
    rows = call(cli, "ls", "-a", "-g", "--json", *host_flags)
    aid = _resolve_target_from_rows(target, rows)
    info = call(cli, "agent", "inspect", aid, "--json", *host_flags)
    return aid, info, (expected[1] if expected is not None else None)


def send(target, text, label="fleet-watch", receipt_file=None, host=None):
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
    aid, info, bound_host = _resolve_and_inspect(target, cli, expected_host=host)
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
    parser.add_argument("--host", help="optional expected local daemon endpoint (fail closed if live endpoint differs)")
    args = parser.parse_args()
    try:
        return send(args.target, args.text, args.label, args.receipt_file, host=args.host)
    except PendingDelivery as error:
        print(f"fleet-watch Paseo send pending: {error}", file=sys.stderr)
        return 5
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"fleet-watch Paseo send: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
