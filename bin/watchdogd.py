#!/usr/bin/env python3
"""watchdogd: one launchd watchdog for every site service.

launchd runs this every ~60 s as com.djbclark.watchdogd (roles/watchdogd). Each
watched service is one file, watchdogd.d/<service>.toml; the role's README has
the schema. Global settings (stress thresholds, alert command) live in
watchdogd.toml beside that directory. It replaces six separate watchdogs
(roles/watchdogd/README.md lists them), after one of them caused the
2026-10-06 litellm outage (site-private memory
project_litellm_watchdog_restart_orphans_2026-10-06): it restarted a proxy
that had already healed, launchd SIGKILLed the log wrapper before it could
stop the proxy, the orphan kept :4000, cold starts under load took 10 min and
were kicked again mid-start, the budget was per finding kind and one clean run
wiped it, and a kickstart that exited 0 counted as success.

Rules every service gets (C2):
  1. Cold-start grace: never restart an instance younger than `grace_s`
     (except to kill an ORPHAN holding its port).
  2. Machine stress (load per CPU or swap over the thresholds) defers restarts.
     Strays and port orphans are still killed; launchd does the restart.
  3. Health is a real request (`probe`). A timeout is "slow", a refused or
     failed connection is "down"; each has its own consecutive threshold. A
     log-stall signature never restarts a service whose probe passes.
  4. A per-service restart budget, reset only after `healthy_reset_s` of
     unbroken health.
  5. A restart is "pending verification" until the probe passes; still failing
     after the grace period is reported once as UNVERIFIED.
  6. Strays (processes matching `strays.match`, ppid 1, not launchd's current
     instance or its descendants, not any launchd job) are killed, SIGTERM then
     SIGKILL, and each kill is reported.

Alerts go through ~/.local/bin/hermes-ping with a short timeout and fall back
to the log, so a dead Hermes never stops the watchdog; they fire on state
changes only. Stdlib only (tomllib needs Python 3.11+: launchd runs Homebrew
python3 via /usr/bin/env).

  watchdogd.py --once --dry-run   # what it would do now, acting on nothing
"""

from __future__ import annotations

import argparse
import dataclasses
import fcntl
import json
import logging
import logging.handlers
import os
import plistlib
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Apple's /usr/bin/python3 is 3.9
    tomllib = None

HOME = Path.home()
DEFAULT_CONFIG_DIR = HOME / ".config/djbclark"
DEFAULT_STATE_DIR = HOME / ".local/state/watchdogd"
DEFAULT_LOG_DIR = HOME / "Library/Logs/watchdogd"
DUE_SLACK_S = 5  # launchd's StartInterval drifts; don't skip a check by a second

log = logging.getLogger("watchdogd")


# --------------------------------------------------------------------------
# Configuration


def expand(p: str) -> str:
    return os.path.expanduser(p) if isinstance(p, str) else p


@dataclass
class GlobalCfg:
    load_per_cpu: float = 3.0
    load_window_min: int = 1  # 1, 5 or 15 (os.getloadavg index)
    swap_percent: float = 70.0  # 0 disables the swap test
    memory_pressure_level: int = 0  # kern.memorystatus_vm_pressure_level >= N; 0 = off
    alert_command: list[str] = field(
        default_factory=lambda: [str(HOME / ".local/bin/hermes-ping")]
    )
    alert_prefix: str = "watchdogd: "
    alert_timeout_s: float = 20.0
    log_max_bytes: int = 2_000_000
    log_backups: int = 3


@dataclass
class ProbeCfg:
    kind: str = "none"  # http | tcp | unix | command | none
    url: str = ""
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    bearer_from_plist_env: str = ""  # read from [launchd].plist EnvironmentVariables
    ok_status: list[str] = field(default_factory=lambda: ["200-299"])
    expect_body: str = ""
    host: str = "127.0.0.1"
    port: int = 0
    path: str = ""  # unix socket; {launchd_pid} is substituted
    expect: str = ""  # unix: bytes the peer must send first
    command: list[str] = field(default_factory=list)
    skip_exit_codes: list[int] = field(default_factory=lambda: [75])
    timeout_s: float = 30.0


@dataclass
class ServiceCfg:
    name: str
    enabled: bool = True
    interval_s: float = 60.0
    label: str = ""
    plist: str = ""
    port: int = 0
    probe: ProbeCfg = field(default_factory=ProbeCfg)
    slow_before_action: int = 3
    down_before_action: int = 2
    grace_s: float = 300.0
    action: str = "kickstart"  # kickstart | command | alert
    action_command: list[str] = field(default_factory=list)
    action_timeout_s: float = 120.0
    min_action_interval_s: float = 0.0
    max_restarts: int = 3
    healthy_reset_s: float = 21600.0
    renotify_s: float = 21600.0
    stall_log: str = ""
    stall_pattern: str = ""
    stall_min_count: int = 1
    stray_match: str = ""
    stray_term_wait_s: float = 10.0
    request_file: str = ""
    request_max_age_s: float = 3600.0
    request_cooldown_s: float = 600.0
    request_cooldown_file: str = ""
    request_command: list[str] = field(default_factory=list)
    request_env: dict[str, str] = field(default_factory=dict)
    request_unset_env: list[str] = field(default_factory=list)
    notify: dict[str, str] = field(default_factory=dict)


def _fill(dc_type, data: dict, where: str):
    names = {f.name for f in dataclasses.fields(dc_type)}
    unknown = set(data) - names
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {sorted(unknown)}")
    return dc_type(**data)


def parse_service(data: dict, name: str) -> ServiceCfg:
    """Flatten one watchdogd.d/<name>.toml into a ServiceCfg."""
    d = dict(data)
    flat: dict[str, Any] = {"name": d.pop("name", name)}
    for key in ("enabled", "interval_s"):
        if key in d:
            flat[key] = d.pop(key)
    launchd = d.pop("launchd", {})
    for k in ("label", "plist", "port"):
        if k in launchd:
            flat[k] = launchd.pop(k)
    if launchd:
        raise ValueError(f"{name}: unknown [launchd] key(s) {sorted(launchd)}")
    if "probe" in d:
        flat["probe"] = _fill(ProbeCfg, d.pop("probe"), f"{name} [probe]")
    policy = d.pop("policy", {})
    rename = {"command": "action_command", "timeout_s": "action_timeout_s"}
    for k, v in policy.items():
        flat[rename.get(k, k)] = v
    for section, prefix in (
        ("stall", "stall_"),
        ("strays", "stray_"),
        ("restart_request", "request_"),
    ):
        for k, v in d.pop(section, {}).items():
            flat[prefix + k] = v
    if "notify" in d:
        flat["notify"] = d.pop("notify")
    if d:
        raise ValueError(f"{name}: unknown section(s) {sorted(d)}")
    cfg = _fill(ServiceCfg, flat, name)
    if cfg.action not in ("kickstart", "command", "alert"):
        raise ValueError(f"{name}: policy.action must be kickstart, command or alert")
    if cfg.action == "kickstart" and not cfg.label:
        raise ValueError(f"{name}: action kickstart needs [launchd].label")
    if cfg.action == "command" and not cfg.action_command:
        raise ValueError(f"{name}: action command needs policy.command")
    if cfg.stall_pattern:
        re.compile(cfg.stall_pattern)
    if cfg.stray_match:
        re.compile(cfg.stray_match)
    return cfg


def load_config(config_dir: Path) -> tuple[GlobalCfg, list[ServiceCfg]]:
    if tomllib is None:
        raise RuntimeError(
            f"watchdogd needs Python 3.11+ for tomllib; this is {sys.version.split()[0]} "
            f"({sys.executable}). launchd must resolve Homebrew python3 first on PATH."
        )
    gcfg = GlobalCfg()
    gpath = config_dir / "watchdogd.toml"
    if gpath.exists():
        gcfg = _fill(GlobalCfg, tomllib.loads(gpath.read_text()), str(gpath))
    services = []
    for path in sorted((config_dir / "watchdogd.d").glob("*.toml")):
        services.append(parse_service(tomllib.loads(path.read_text()), path.stem))
    return gcfg, services


# --------------------------------------------------------------------------
# Live state of the machine (everything a test replaces with a fake)


@dataclass
class Proc:
    pid: int
    ppid: int
    age_s: float
    command: str


def parse_etime(s: str) -> float:
    """ps etime: [[dd-]hh:]mm:ss."""
    days = 0
    if "-" in s:
        d, s = s.split("-", 1)
        days = int(d)
    parts = [int(x) for x in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, sec = parts
    return days * 86400 + h * 3600 + m * 60 + sec


@dataclass
class ProbeResult:
    status: str  # ok | slow | down | bad | skip
    detail: str = ""
    output: str = ""


class System:
    """Read and act on the live machine. Tests pass a fake with the same methods."""

    def now(self) -> float:
        return time.time()

    def processes(self) -> dict[int, Proc]:
        out = subprocess.run(
            ["ps", "-axww", "-o", "pid=,ppid=,etime=,command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
        procs = {}
        for line in out.splitlines():
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            try:
                procs[int(parts[0])] = Proc(
                    int(parts[0]), int(parts[1]), parse_etime(parts[2]), parts[3]
                )
            except ValueError:
                continue
        return procs

    def launchd_jobs(self) -> dict[str, int | None]:
        """label -> running pid (None when loaded but not running)."""
        out = subprocess.run(
            ["launchctl", "list"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
        jobs: dict[str, int | None] = {}
        for line in out.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) == 3:
                jobs[parts[2]] = int(parts[0]) if parts[0].isdigit() else None
        return jobs

    def port_listeners(self, port: int) -> list[int]:
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
        return sorted({int(x) for x in out.split() if x.isdigit()})

    def stress(self, g: GlobalCfg) -> dict[str, Any]:
        load = os.getloadavg()[{1: 0, 5: 1, 15: 2}.get(g.load_window_min, 0)]
        ncpu = os.cpu_count() or 1
        swap_pct = 0.0
        try:
            out = subprocess.run(
                ["sysctl", "-n", "vm.swapusage"],
                check=False,
                capture_output=True,
                text=True,
            ).stdout
            total = float(re.search(r"total = ([\d.]+)M", out).group(1))
            used = float(re.search(r"used = ([\d.]+)M", out).group(1))
            swap_pct = 100.0 * used / total if total else 0.0
        except (AttributeError, ValueError, OSError):
            pass
        pressure = 0
        try:
            pressure = int(
                subprocess.run(
                    ["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                    check=False,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                or 0
            )
        except (ValueError, OSError):
            pass
        return assess_stress(g, load / ncpu, swap_pct, pressure)

    def kill(self, pid: int, sig: int) -> bool:
        try:
            os.kill(pid, sig)
            return True
        except ProcessLookupError:
            return False

    def alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def sleep(self, s: float) -> None:
        time.sleep(s)

    def run(
        self, cmd: list[str], timeout: float, env: dict | None = None
    ) -> tuple[int | None, str]:
        """(exit code or None on timeout, merged output). Kills the group on timeout."""
        try:
            p = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                start_new_session=True,
            )
        except OSError as e:
            return 127, str(e)
        try:
            out, _ = p.communicate(timeout=timeout)
            return p.returncode, out or ""
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, _ = p.communicate()
            return None, out or ""

    def spawn_detached(
        self, cmd: list[str], env: dict | None, log_path: Path, exit_file: Path
    ) -> int:
        """Run cmd in its own session, outliving this run; its exit code lands in exit_file."""
        exit_file.unlink(missing_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        wrapper = [
            "/bin/sh",
            "-c",
            '"$@"; echo $? > "$WATCHDOGD_EXIT_FILE"',
            "sh",
            *cmd,
        ]
        env = dict(env or os.environ)
        env["WATCHDOGD_EXIT_FILE"] = str(exit_file)
        with open(log_path, "a") as out:
            p = subprocess.Popen(
                wrapper,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
        return p.pid

    def kickstart(self, label: str) -> tuple[int | None, str]:
        return self.run(
            ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"], 60
        )

    def read_text(self, path: str) -> str | None:
        try:
            return Path(path).read_text()
        except OSError:
            return None

    def read_log_since(
        self, path: str, offset: int, inode: int
    ) -> tuple[str, int, int]:
        """New bytes of a log since (offset, inode); restarts at 0 after rotation."""
        try:
            st = os.stat(path)
        except OSError:
            return "", 0, 0
        if st.st_ino != inode or st.st_size < offset:
            offset = 0 if inode else st.st_size  # first sight: start at the end
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read(4_000_000)
        return data.decode("utf-8", "replace"), offset + len(data), st.st_ino

    def plist_env(self, plist: str, key: str) -> str | None:
        try:
            with open(plist, "rb") as f:
                return (plistlib.load(f).get("EnvironmentVariables") or {}).get(key)
        except (OSError, plistlib.InvalidFileException, ValueError):
            return None


def assess_stress(g: GlobalCfg, load_per_cpu: float, swap_pct: float, pressure: int):
    reasons = []
    if g.load_per_cpu and load_per_cpu > g.load_per_cpu:
        reasons.append(f"load/cpu {load_per_cpu:.1f} > {g.load_per_cpu:g}")
    if g.swap_percent and swap_pct > g.swap_percent:
        reasons.append(f"swap {swap_pct:.0f}% > {g.swap_percent:g}%")
    if g.memory_pressure_level and pressure >= g.memory_pressure_level:
        reasons.append(f"memory pressure level {pressure} >= {g.memory_pressure_level}")
    return {
        "stressed": bool(reasons),
        "why": "; ".join(reasons),
        "load_per_cpu": round(load_per_cpu, 2),
        "swap_percent": round(swap_pct, 1),
        "memory_pressure_level": pressure,
    }


# --------------------------------------------------------------------------
# Probes


def status_ok(code: int, specs: list[str]) -> bool:
    for spec in specs:
        spec = str(spec)
        if "-" in spec:
            lo, hi = spec.split("-", 1)
            if int(lo) <= code <= int(hi):
                return True
        elif code == int(spec):
            return True
    return False


def _is_timeout(e: BaseException) -> bool:
    return isinstance(e, (TimeoutError, socket.timeout)) or "timed out" in str(e)


def _is_refused(e: BaseException) -> bool:
    return isinstance(e, ConnectionRefusedError) or getattr(e, "errno", None) in (
        61,
        111,
    )


def probe_http(p: ProbeCfg, bearer: str | None) -> ProbeResult:
    headers = dict(p.headers)
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    data = p.body.encode() if p.body is not None else None
    req = urllib.request.Request(p.url, data=data, method=p.method, headers=headers)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=p.timeout_s) as resp:
            code, body = resp.status, resp.read(65536).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            body = e.read(65536).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - the status code is what matters
            body = ""
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, BaseException):
            if _is_timeout(reason):
                return ProbeResult("slow", f"timed out after {p.timeout_s:g}s")
            if _is_refused(reason):
                return ProbeResult("down", "connection refused")
        elif "timed out" in str(reason):
            return ProbeResult("slow", f"timed out after {p.timeout_s:g}s")
        return ProbeResult("down", f"{reason}")
    except TimeoutError:
        return ProbeResult("slow", f"timed out after {p.timeout_s:g}s")
    except OSError as e:
        if _is_refused(e):
            return ProbeResult("down", "connection refused")
        return ProbeResult("down", repr(e))
    took = f"{time.monotonic() - t0:.1f}s"
    if status_ok(code, p.ok_status):
        if p.expect_body and p.expect_body not in body:
            return ProbeResult(
                "down", f"HTTP {code} without {p.expect_body!r} ({took})"
            )
        return ProbeResult("ok", f"HTTP {code} in {took}")
    snippet = re.sub(r"\s+", " ", body)[:160]
    if 500 <= code <= 599:
        return ProbeResult("down", f"HTTP {code} ({took}): {snippet}")
    # A 4xx the probe did not expect: the server answered, so the process is
    # alive and the probe itself is wrong (bad key, unknown model). Never a
    # reason to restart.
    return ProbeResult("bad", f"HTTP {code} ({took}): {snippet}")


def probe_socket(family: int, address, p: ProbeCfg) -> ProbeResult:
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(p.timeout_s)
    try:
        s.connect(address)
        if p.expect:
            got = s.recv(len(p.expect.encode()))
            if got != p.expect.encode():
                return ProbeResult("down", f"answered {got!r}, expected {p.expect!r}")
        return ProbeResult("ok", "answered" if p.expect else "connected")
    except TimeoutError:
        return ProbeResult("slow", f"timed out after {p.timeout_s:g}s")
    except FileNotFoundError:
        return ProbeResult("down", f"no socket at {address}")
    except OSError as e:
        if _is_refused(e):
            return ProbeResult("down", "connection refused")
        return ProbeResult("down", repr(e))
    finally:
        s.close()


def run_probe(svc: ServiceCfg, system: System, lpid: int | None) -> ProbeResult:
    p = svc.probe
    if p.kind == "http":
        bearer = None
        if p.bearer_from_plist_env:
            bearer = system.plist_env(expand(svc.plist), p.bearer_from_plist_env)
            if not bearer:
                return ProbeResult(
                    "bad",
                    f"no {p.bearer_from_plist_env} in {svc.plist} EnvironmentVariables",
                )
        return probe_http(p, bearer)
    if p.kind == "tcp":
        return probe_socket(socket.AF_INET, (p.host, p.port or svc.port), p)
    if p.kind == "unix":
        if "{launchd_pid}" in p.path and lpid is None:
            return ProbeResult("down", "no launchd instance to probe")
        return probe_socket(
            socket.AF_UNIX, expand(p.path.replace("{launchd_pid}", str(lpid))), p
        )
    if p.kind == "command":
        rc, out = system.run([expand(a) for a in p.command], p.timeout_s)
        first = next((ln for ln in out.splitlines() if ln.strip()), "")[:200]
        if rc is None:
            return ProbeResult("slow", f"timed out after {p.timeout_s:g}s", out)
        if rc == 0:
            return ProbeResult("ok", first or "exit 0", out)
        if rc in p.skip_exit_codes:
            return ProbeResult("skip", first or f"exit {rc}", out)
        return ProbeResult("down", f"exit {rc}: {first}", out)
    return ProbeResult("skip", "no probe")


# --------------------------------------------------------------------------
# Decisions (pure: no I/O, so the tests can drive them with fakes)


@dataclass
class Obs:
    now: float
    stress: dict[str, Any]
    probe: ProbeResult | None = None  # None: not due this run
    loaded: bool | None = None  # None: no launchd label
    lpid: int | None = None
    instance_age: float | None = None
    port_holders: list[int] = field(default_factory=list)
    orphans: list[Proc] = field(default_factory=list)
    unknown_holders: list[int] = field(default_factory=list)
    strays: list[Proc] = field(default_factory=list)
    stray_jobs: list[Proc] = field(default_factory=list)  # match, but another job's pid
    stall_hits: list[str] = field(default_factory=list)
    request: dict | None = None
    request_problem: str = ""
    cooldown_at: float | None = None  # last_restart_at in the shared cooldown file
    detached_rc: int | None = None


@dataclass
class Action:
    kind: str  # kill | kickstart | command | request_restart | drop_request
    pid: int = 0
    note: str = ""
    alert: str = ""  # sent after the action, with its result


@dataclass
class Decision:
    verdict: str
    actions: list[Action] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def fresh_state() -> dict[str, Any]:
    return {
        "health": "unknown",
        "consecutive_slow": 0,
        "consecutive_down": 0,
        "last_check": None,
        "last_result": None,
        "healthy_since": None,
        "restarts": [],
        "last_action_at": None,
        "pending": None,
        "budget_alerted_at": None,
        "conditions": {},
        "request_last_at": None,
        "detached": None,
    }


def descendants(procs: dict[int, Proc], root: int) -> set[int]:
    kids: dict[int, list[int]] = {}
    for p in procs.values():
        kids.setdefault(p.ppid, []).append(p.pid)
    seen, todo = set(), [root]
    while todo:
        pid = todo.pop()
        for k in kids.get(pid, []):
            if k not in seen:
                seen.add(k)
                todo.append(k)
    return seen


def classify_processes(
    svc: ServiceCfg,
    procs: dict[int, Proc],
    jobs: dict[str, int | None],
    port_holders: list[int],
    self_pid: int,
) -> tuple[list[Proc], list[Proc], list[Proc], list[int]]:
    """(strays, stray_jobs, orphans, unknown_holders) for one service.

    Stray: command matches, ppid 1, not launchd's current instance or one of
    its descendants, and not the main pid of any launchd job (another job's
    process is a conflict to report, not a stray: killing it would just make
    launchd respawn it). With no launchd instance nothing is a stray: the
    process may be an intentional manual fallback (UNSUPERVISED).
    Orphan: a port listener outside the current instance's tree.
    """
    lpid = jobs.get(svc.label) if svc.label else None
    tree = {lpid} | descendants(procs, lpid) if lpid else set()
    job_pids = {pid for pid in jobs.values() if pid}
    job_trees = set()
    for pid in job_pids - {lpid}:
        job_trees |= {pid} | descendants(procs, pid)
    strays, stray_jobs = [], []
    if svc.stray_match and lpid:
        pat = re.compile(svc.stray_match)
        for p in procs.values():
            if p.pid in tree or p.pid == self_pid or not pat.search(p.command):
                continue
            if p.ppid != 1:
                continue
            (stray_jobs if p.pid in job_trees else strays).append(p)
    orphans, unknown = [], []
    if lpid:
        for pid in port_holders:
            if pid in tree:
                continue
            if pid not in procs:
                unknown.append(pid)  # appeared after the ps snapshot
            elif pid in job_trees:
                unknown.append(pid)  # another job holds our port: report only
            else:
                orphans.append(procs[pid])
    orphan_pids = {p.pid for p in orphans}
    strays = [p for p in strays if p.pid not in orphan_pids]  # ORPHAN wins
    return strays, stray_jobs, orphans, unknown


def stall_matches(text: str, pattern: str, min_count: int) -> list[str]:
    hits = []
    pat = re.compile(pattern)
    for line in text.splitlines():
        m = pat.search(line)
        if not m:
            continue
        count = m.groupdict().get("count")
        if count is not None and int(count) < min_count:
            continue
        hits.append(line.strip()[:200])
    return hits


def _note(svc: ServiceCfg, key: str, default: str, **kw) -> str:
    text = svc.notify.get(key, default)
    try:
        return text.format(name=svc.name, **kw)
    except (KeyError, IndexError):
        return text


def _condition(state: dict, key: str, active: bool) -> bool:
    """True when a condition just became active (alert once per episode)."""
    was = state["conditions"].get(key, False)
    state["conditions"][key] = active
    return active and not was


def decide(svc: ServiceCfg, state: dict, obs: Obs) -> Decision:
    now = obs.now
    d = Decision(verdict="")
    stressed = obs.stress.get("stressed", False)

    # Budget decay: only an unbroken healthy stretch gives restarts back.
    if (
        state["restarts"]
        and state["healthy_since"] is not None
        and now - state["healthy_since"] >= svc.healthy_reset_s
    ):
        d.notes.append(
            f"budget reset after {svc.healthy_reset_s / 3600:g}h healthy "
            f"({len(state['restarts'])} restart(s) forgiven)"
        )
        state["restarts"] = []
        state["budget_alerted_at"] = None

    # A detached action (e.g. `hermes gateway restart`) finished since last run.
    if state.get("detached") and obs.detached_rc is not None:
        what = state["detached"].get("what", "command")
        if obs.detached_rc != 0:
            d.alerts.append(f"{svc.name} {what} exited {obs.detached_rc}")
        d.notes.append(f"{what} exited {obs.detached_rc}")
        state["detached"] = None

    # Strays and port orphans: killed whatever the stress or grace.
    for p in obs.strays:
        d.actions.append(
            Action(
                "kill",
                p.pid,
                f"stray pid {p.pid} (ppid 1, age {p.age_s:.0f}s): {p.command[:120]}",
                alert=f"{svc.name} STRAY killed pid {p.pid} (ppid 1, not launchd's instance)",
            )
        )
    if _condition(state, "stray_job", bool(obs.stray_jobs)):
        pids = ", ".join(str(p.pid) for p in obs.stray_jobs)
        d.alerts.append(
            f"{svc.name} CONFLICT: pid(s) {pids} match this service but belong to "
            f"another launchd job; not killed"
        )
    for p in obs.orphans:
        d.actions.append(
            Action(
                "kill",
                p.pid,
                f"ORPHAN pid {p.pid} holds port {svc.port} outside launchd's instance "
                f"{obs.lpid}",
                alert=f"{svc.name} ORPHAN killed pid {p.pid} holding port {svc.port}; "
                f"launchd restarts the service",
            )
        )
    if _condition(state, "port_conflict", bool(obs.unknown_holders)):
        d.notes.append(
            f"port {svc.port} held by {obs.unknown_holders} (not ours; left alone)"
        )
    unsupervised = (
        bool(svc.label)
        and obs.lpid is None
        and bool(obs.port_holders)
        and obs.loaded is not None
    )
    if _condition(state, "unsupervised", unsupervised):
        d.alerts.append(
            f"{svc.name} UNSUPERVISED: port {svc.port} served by pid "
            f"{obs.port_holders[0]} but launchd has no instance of {svc.label}"
        )
    if _condition(state, "not_loaded", bool(svc.label) and obs.loaded is False):
        d.alerts.append(f"{svc.name} NOT LOADED: launchd has no job {svc.label}")
    if svc.port and obs.lpid and not obs.port_holders:
        d.notes.append(
            f"NOPORT: launchd instance {obs.lpid} runs but nothing listens on {svc.port}"
        )

    # Restart requests (e.g. the Hermes gateway-restart plugin).
    if obs.request_problem:
        d.notes.append(obs.request_problem)
        d.actions.append(Action("drop_request", note=obs.request_problem))
    elif obs.request is not None:
        # The shared cooldown file counts too, so a restart done by anyone else
        # (e.g. the old gateway-restart-watcher during cutover) is respected.
        stamps = [t for t in (state.get("request_last_at"), obs.cooldown_at) if t]
        last = max(stamps) if stamps else None
        reason = str(obs.request.get("reason", ""))[:160]
        if last is not None and now - last < svc.request_cooldown_s:
            msg = (
                f"restart request dropped: cooldown ({now - last:.0f}s < "
                f"{svc.request_cooldown_s:g}s since the last one); reason was: {reason}"
            )
            d.notes.append(msg)
            d.actions.append(Action("drop_request", note=msg))
        elif stressed:
            d.notes.append(f"restart request deferred: {obs.stress['why']}")
        else:
            d.actions.append(
                Action("request_restart", note=f"requested restart; reason: {reason}")
            )
            # Not "pending": a graceful gateway restart waits for in-flight runs
            # (up to ~30 min), so the next passing probe proves nothing. Its exit
            # code is reported when the detached command ends; the probe keeps
            # watching health as usual.
            state["request_last_at"] = now

    if obs.probe is None:
        d.verdict = "not due"
        return d

    r = obs.probe
    state["last_check"] = now
    state["last_result"] = f"{r.status}: {r.detail}"
    stall = bool(obs.stall_hits)
    if stall and r.status == "ok":
        d.notes.append(
            f"log stall signature ignored, real probe passes: {obs.stall_hits[-1]}"
        )
    if r.status == "slow" and stall:
        d.notes.append(f"slow + log stall ({obs.stall_hits[-1]}): counted as down")
        r = ProbeResult("down", f"{r.detail}; log: {obs.stall_hits[-1]}")

    if r.status == "skip":
        d.verdict = f"SKIP ({r.detail})"
        return d
    if r.status == "bad":
        if _condition(state, "probe_bad", True):
            d.alerts.append(
                f"{svc.name} PROBE BROKEN (never restarts on this): {r.detail}"
            )
        d.verdict = f"PROBE BROKEN ({r.detail}); not acting"
        return d
    _condition(state, "probe_bad", False)

    if r.status == "ok":
        was_down = state["health"] == "down"
        pending = state["pending"]
        state.update(consecutive_slow=0, consecutive_down=0, health="up")
        if state["healthy_since"] is None:
            state["healthy_since"] = now
        if pending:
            state["pending"] = None
            d.notes.append(
                f"verified: probe passes {now - pending['at']:.0f}s after {pending['why']}"
            )
        if was_down or (pending and pending.get("unverified")):
            d.alerts.append(
                _note(svc, "recovered", "{name} RECOVERED: {detail}", detail=r.detail)
            )
        d.verdict = f"OK ({r.detail})"
        return d

    # slow or down
    state["healthy_since"] = None
    if r.status == "slow":
        state["consecutive_slow"] += 1
    else:
        state["consecutive_down"] += 1
    counts = (
        f"slow {state['consecutive_slow']}/{svc.slow_before_action}, "
        f"down {state['consecutive_down']}/{svc.down_before_action}"
    )
    declared = (
        state["consecutive_slow"] >= svc.slow_before_action
        or state["consecutive_down"] >= svc.down_before_action
    )

    pending = state["pending"]
    age = obs.instance_age
    since_action = now - state["last_action_at"] if state["last_action_at"] else None
    young = min(x for x in (age, since_action, float("inf")) if x is not None)
    if pending and now - pending["at"] >= svc.grace_s and not pending.get("unverified"):
        pending["unverified"] = True
        d.alerts.append(
            f"{svc.name} UNVERIFIED: still failing {now - pending['at']:.0f}s after "
            f"{pending['why']} ({r.detail})"
        )

    if not declared:
        d.verdict = f"{r.status.upper()} ({r.detail}); {counts}; waiting"
        return d

    first_down = state["health"] != "down"
    state["health"] = "down"
    used = len(state["restarts"])

    def down_alert(tail: str) -> None:
        if first_down:
            d.alerts.append(
                _note(
                    svc,
                    "down",
                    "{name} DOWN ({detail}; {counts}){tail}",
                    detail=r.detail,
                    counts=counts,
                    tail=tail,
                )
            )

    if svc.action == "alert":
        down_alert("")
        d.verdict = f"DOWN ({r.detail}; {counts}); alert only"
        return d
    if young < svc.grace_s:
        down_alert(f"; in {svc.grace_s:g}s grace, not restarting yet")
        d.verdict = (
            f"DOWN ({r.detail}; {counts}); WAIT: instance {young:.0f}s old < grace "
            f"{svc.grace_s:g}s"
        )
        return d
    if svc.label and obs.loaded is False:
        down_alert(f"; {svc.label} is not loaded, nothing to restart")
        d.verdict = f"DOWN ({r.detail}); NOT LOADED, not restarting"
        return d
    if svc.label and obs.lpid is None and obs.port_holders:
        down_alert("; port served outside launchd, not restarting")
        d.verdict = f"DOWN ({r.detail}); UNSUPERVISED, not restarting"
        return d
    if stressed:
        down_alert(f"; restart deferred ({obs.stress['why']})")
        d.verdict = f"DOWN ({r.detail}; {counts}); DEFER: {obs.stress['why']}"
        return d
    if used >= svc.max_restarts:
        last = state["budget_alerted_at"]
        if last is None or now - last >= svc.renotify_s:
            state["budget_alerted_at"] = now
            d.alerts.append(
                _note(
                    svc,
                    "exhausted",
                    "{name} BUDGET EXHAUSTED: {used} restart(s) without "
                    "{hours:g}h of health; not restarting until it recovers or "
                    "someone looks ({detail})",
                    used=used,
                    hours=svc.healthy_reset_s / 3600,
                    detail=r.detail,
                )
            )
        d.verdict = f"DOWN ({r.detail}); BUDGET EXHAUSTED ({used}/{svc.max_restarts})"
        return d
    if since_action is not None and since_action < svc.min_action_interval_s:
        d.verdict = (
            f"DOWN ({r.detail}); WAIT: last action {since_action:.0f}s ago < "
            f"{svc.min_action_interval_s:g}s"
        )
        return d

    n = used + 1
    down_alert(f"; restarting ({n}/{svc.max_restarts})")
    if not first_down:
        d.alerts.append(
            f"{svc.name} still down ({r.detail}); restart {n}/{svc.max_restarts}"
        )
    d.actions.append(
        Action(
            svc.action,
            note=f"restart {n}/{svc.max_restarts} after {r.status} ({r.detail}; {counts})",
        )
    )
    state["restarts"].append(now)
    state["last_action_at"] = now
    state["pending"] = {"at": now, "why": f"restart {n}", "unverified": False}
    state["consecutive_slow"] = 0
    state["consecutive_down"] = 0
    d.verdict = f"DOWN ({r.detail}; {counts}); RESTART {n}/{svc.max_restarts}"
    return d


# --------------------------------------------------------------------------
# Running one service


class Runner:
    def __init__(
        self,
        gcfg: GlobalCfg,
        system: System,
        state_dir: Path,
        log_dir: Path,
        dry_run: bool,
        alert_fn: Callable[[str], None] | None = None,
        force_due: bool = False,
    ):
        self.g = gcfg
        self.sys = system
        self.state_dir = state_dir
        self.log_dir = log_dir
        self.dry = dry_run
        self.force_due = force_due
        self.alert_fn = alert_fn or self.alert
        self.out: dict[str, list[str]] = {}  # dry run: per-service report lines

    def say(self, svc: ServiceCfg, line: str) -> None:
        self.out.setdefault(svc.name, []).append(line)

    # -- state
    def state_path(self, svc: ServiceCfg) -> Path:
        return self.state_dir / f"{svc.name}.json"

    def load_state(self, svc: ServiceCfg) -> dict:
        st = fresh_state()
        try:
            data = json.loads(self.state_path(svc).read_text())
            if isinstance(data, dict):
                st.update(data)
        except (OSError, ValueError):
            pass
        return st

    def save_state(self, svc: ServiceCfg, state: dict) -> None:
        if self.dry:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path(svc).with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
        os.replace(tmp, self.state_path(svc))

    # -- alerts
    def alert(self, text: str, svc: ServiceCfg | None = None) -> None:
        line = (self.g.alert_prefix + text).replace("\n", " ")[:600]
        if self.dry:
            if svc is not None:
                self.say(svc, f"    WOULD ALERT: {line}")
            return
        rc, out = self.sys.run([*self.g.alert_command, line], self.g.alert_timeout_s)
        if rc == 0:
            log.info("ALERT sent: %s", line)
        else:
            why = "timed out" if rc is None else f"exit {rc}"
            log.warning(
                "ALERT NOT DELIVERED (%s; %s): %s", why, out.strip()[:200], line
            )

    # -- observation
    def observe(
        self,
        svc: ServiceCfg,
        state: dict,
        procs: dict[int, Proc],
        jobs: dict[str, int | None],
        stress: dict,
    ) -> Obs:
        now = self.sys.now()
        obs = Obs(now=now, stress=stress)
        if svc.label:
            obs.loaded = svc.label in jobs
            obs.lpid = jobs.get(svc.label)
            if obs.lpid and obs.lpid in procs:
                obs.instance_age = procs[obs.lpid].age_s
        if svc.port:
            obs.port_holders = self.sys.port_listeners(svc.port)
        obs.strays, obs.stray_jobs, obs.orphans, obs.unknown_holders = (
            classify_processes(svc, procs, jobs, obs.port_holders, os.getpid())
        )
        det = state.get("detached")
        if det:
            txt = self.sys.read_text(det["exit_file"])
            if txt is not None and txt.strip().lstrip("-").isdigit():
                obs.detached_rc = int(txt.strip())
        if svc.request_file:
            self._observe_request(svc, obs, now)
        last = state.get("last_check")
        due = (
            self.force_due or last is None or now - last >= svc.interval_s - DUE_SLACK_S
        )
        if due and svc.probe.kind != "none":
            obs.probe = run_probe(svc, self.sys, obs.lpid)
            if svc.stall_log and svc.stall_pattern:
                text, off, ino = self.sys.read_log_since(
                    expand(svc.stall_log),
                    state.get("stall_offset", 0),
                    state.get("stall_inode", 0),
                )
                obs.stall_hits = stall_matches(
                    text, svc.stall_pattern, svc.stall_min_count
                )
                state["stall_offset"], state["stall_inode"] = off, ino
        return obs

    def _observe_request(self, svc: ServiceCfg, obs: Obs, now: float) -> None:
        raw = self.sys.read_text(expand(svc.request_file))
        if raw is None:
            return
        try:
            req = json.loads(raw)
            at = float(req.get("requested_at", 0))
        except (ValueError, TypeError, AttributeError):
            obs.request_problem = f"restart request unreadable, dropped: {raw[:120]!r}"
            return
        if now - at > svc.request_max_age_s:
            obs.request_problem = (
                f"restart request {now - at:.0f}s old (> {svc.request_max_age_s:g}s), "
                f"stale; dropped. reason was: {str(req.get('reason', ''))[:120]}"
            )
            return
        obs.request = req
        if svc.request_cooldown_file:
            try:
                cd = json.loads(
                    self.sys.read_text(expand(svc.request_cooldown_file)) or "{}"
                )
                obs.cooldown_at = float(cd.get("last_restart_at") or 0) or None
            except (ValueError, TypeError, AttributeError):
                pass

    # -- actions
    def execute(self, svc: ServiceCfg, state: dict, actions: list[Action]) -> None:
        for a in actions:
            if self.dry:
                self.say(svc, f"    WOULD {a.kind.upper()}: {a.note}")
                if a.alert:
                    self.send(svc, a.alert)
                continue
            log.info("%s %s: %s", svc.name, a.kind, a.note)
            if a.kind == "kill":
                result = self.kill(a.pid, svc.stray_term_wait_s)
                self.send(svc, f"{a.alert} ({result})")
            elif a.kind == "kickstart":
                # rc 0 only means launchd accepted it; the probe verifies (pending).
                rc, out = self.sys.kickstart(svc.label)
                log.info("%s kickstart rc=%s %s", svc.name, rc, out.strip()[:200])
                if rc != 0:
                    self.send(
                        svc,
                        f"{svc.name} kickstart FAILED (rc={rc}): {out.strip()[:120]}",
                    )
            elif a.kind == "command":
                cmd = [expand(x) for x in svc.action_command]
                rc, out = self.sys.run(cmd, svc.action_timeout_s)
                log.info("%s action rc=%s %s", svc.name, rc, out.strip()[:300])
                if rc != 0:
                    self.send(
                        svc,
                        f"{svc.name} restart command FAILED (rc={rc}): {out.strip()[:120]}",
                    )
            elif a.kind == "request_restart":
                self.request_restart(svc, state, a.note)
            elif a.kind == "drop_request":
                Path(expand(svc.request_file)).unlink(missing_ok=True)

    def send(self, svc: ServiceCfg, text: str) -> None:
        if self.alert_fn == self.alert:
            self.alert(text, svc)
        else:
            self.alert_fn(text)

    def kill(self, pid: int, wait_s: float) -> str:
        if not self.sys.kill(pid, signal.SIGTERM):
            return "already gone"
        deadline = self.sys.now() + wait_s
        while self.sys.alive(pid) and self.sys.now() < deadline:
            self.sys.sleep(0.5)
        if not self.sys.alive(pid):
            return "exited on SIGTERM"
        self.sys.kill(pid, signal.SIGKILL)
        return f"SIGKILL after {wait_s:g}s"

    def request_restart(self, svc: ServiceCfg, state: dict, note: str) -> None:
        req_path = Path(expand(svc.request_file))
        try:
            reason = json.loads(req_path.read_text()).get("reason", "")
        except (OSError, ValueError, AttributeError):
            reason = ""
        req_path.unlink(missing_ok=True)  # never act twice on one request
        env = dict(os.environ)
        for k in svc.request_unset_env:
            env.pop(k, None)
        env.update({k: expand(v) for k, v in svc.request_env.items()})
        exit_file = self.state_dir / f"{svc.name}.request.exit"
        pid = self.sys.spawn_detached(
            [expand(x) for x in svc.request_command],
            env,
            self.log_dir / f"{svc.name}-restart.log",
            exit_file,
        )
        state["detached"] = {
            "pid": pid,
            "exit_file": str(exit_file),
            "what": "requested restart",
        }
        log.info("%s requested restart started (pid %s): %s", svc.name, pid, note)
        if svc.request_cooldown_file:
            # The Hermes gateway-restart plugin reads this to report the cooldown.
            cf = Path(expand(svc.request_cooldown_file))
            tmp = cf.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "last_restart_at": self.sys.now(),
                        "reason": reason,
                        "exit_code": None,
                    }
                )
            )
            os.replace(tmp, cf)

    # -- one service, end to end
    def run_service(self, svc, procs, jobs, stress) -> tuple[str, Decision]:
        state = self.load_state(svc)
        try:
            obs = self.observe(svc, state, procs, jobs, stress)
            dec = decide(svc, state, obs)
        except Exception as e:  # one broken entry must not stop the others
            log.exception("%s: check failed", svc.name)
            return svc.name, Decision(verdict=f"ERROR {e!r}")
        line = f"{svc.name}: {dec.verdict}"
        if obs.lpid or obs.loaded is not None:
            age = f"{obs.instance_age:.0f}s" if obs.instance_age is not None else "?"
            line += f" [launchd pid {obs.lpid or '-'}, age {age}"
            line += (
                f", port {svc.port} holders {obs.port_holders}]" if svc.port else "]"
            )
        if self.dry:
            self.say(svc, line)
            for n in dec.notes:
                self.say(svc, f"    note: {n}")
        else:
            if obs.probe is not None or dec.actions or dec.alerts:
                log.info(line)
            for n in dec.notes:
                log.info("%s: %s", svc.name, n)
            if obs.probe and obs.probe.status != "ok" and obs.probe.output:
                log.info(
                    "%s probe output:\n%s", svc.name, obs.probe.output.strip()[:4000]
                )
        self.execute(svc, state, dec.actions)
        for a in dec.alerts:
            self.send(svc, a)
        if obs.detached_rc is not None and svc.request_cooldown_file and not self.dry:
            self._record_exit(svc, obs.detached_rc)
        self.save_state(svc, state)
        return svc.name, dec

    def _record_exit(self, svc: ServiceCfg, rc: int) -> None:
        cf = Path(expand(svc.request_cooldown_file))
        try:
            data = json.loads(cf.read_text())
            data["exit_code"] = rc
            tmp = cf.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, cf)
        except (OSError, ValueError, TypeError):
            pass


def setup_logging(log_dir: Path, g: GlobalCfg, dry: bool) -> None:
    log.setLevel(logging.INFO)
    if dry:
        h: logging.Handler = logging.StreamHandler(sys.stderr)
        h.setLevel(logging.WARNING)
    else:
        log_dir.mkdir(parents=True, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(
            log_dir / "watchdogd.log",
            maxBytes=g.log_max_bytes,
            backupCount=g.log_backups,
        )
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)


def config_error_alert(a: argparse.Namespace, msg: str) -> None:
    """Log a config error, and ping once per distinct error (nothing is watched)."""
    a.log_dir.mkdir(parents=True, exist_ok=True)
    with open(a.log_dir / "watchdogd.log", "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} ERROR {msg}\n")
    marker = a.state_dir / "config_error"
    try:
        if marker.read_text() == msg:
            return
    except OSError:
        pass
    a.state_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(msg)
    System().run([str(HOME / ".local/bin/hermes-ping"), f"watchdogd: {msg[:300]}"], 20)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--once", action="store_true", help="one pass (what launchd runs)")
    ap.add_argument(
        "--dry-run", action="store_true", help="print decisions, act on nothing"
    )
    ap.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    ap.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    ap.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    ap.add_argument("--service", action="append", help="only these services")
    ap.add_argument("--all-due", action="store_true", help="probe every service now")
    ap.add_argument(
        "--check-config", action="store_true", help="parse the config, print it, exit"
    )
    a = ap.parse_args(argv)

    try:
        gcfg, services = load_config(a.config_dir)
    except Exception as e:  # noqa: BLE001 - any config error: log it, check nothing
        msg = f"config error, nothing checked: {e}"
        print(f"watchdogd: {msg}", file=sys.stderr)
        if not (a.dry_run or a.check_config):
            config_error_alert(a, msg)
        return 2
    if a.check_config:
        for svc in services:
            print(
                f"{svc.name}: {'enabled' if svc.enabled else 'disabled'}, "
                f"every {svc.interval_s:g}s, probe {svc.probe.kind}, action {svc.action}"
            )
        return 0
    (a.state_dir / "config_error").unlink(missing_ok=True)
    setup_logging(a.log_dir, gcfg, a.dry_run)
    services = [
        s for s in services if s.enabled and (not a.service or s.name in a.service)
    ]

    lock = None
    if not a.dry_run:
        a.state_dir.mkdir(parents=True, exist_ok=True)
        lock = open(a.state_dir / "lock", "w")  # noqa: SIM115 - held for the whole run
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.info("another watchdogd run holds the lock; skipping")
            return 0

    system = System()
    runner = Runner(
        gcfg, system, a.state_dir, a.log_dir, a.dry_run, force_due=a.all_due
    )
    procs = system.processes()
    jobs = system.launchd_jobs()
    stress = system.stress(gcfg)
    if a.dry_run:
        print(
            f"watchdogd dry run {time.strftime('%Y-%m-%d %H:%M:%S %z')}: "
            f"{len(services)} service(s); stress: "
            f"{'STRESSED (' + stress['why'] + ')' if stress['stressed'] else 'normal'} "
            f"[load/cpu {stress['load_per_cpu']}, swap {stress['swap_percent']}%, "
            f"memory pressure {stress['memory_pressure_level']}]"
        )
    # One thread per service: a slow probe (up to its timeout) never delays the others.
    with ThreadPoolExecutor(max_workers=max(1, len(services))) as pool:
        results = list(
            pool.map(lambda s: runner.run_service(s, procs, jobs, stress), services)
        )
    if a.dry_run:
        for svc in services:
            print("\n".join(runner.out.get(svc.name, [f"{svc.name}: (no output)"])))
        print("(dry run: no state written, no process signalled, no alert sent)")
    return 0 if all(not d.verdict.startswith("ERROR") for _, d in results) else 1


if __name__ == "__main__":
    sys.exit(main())
