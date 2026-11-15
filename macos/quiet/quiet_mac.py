#!/usr/bin/env python3
"""Keep a Mac from spending RAM and CPU on Apple background daemons.

SIGSTOP does not free RAM a process already holds. It stops that process
from allocating more, and launchd will not start a second copy while the
job has not exited. The memory win is freezing them early, TERMing the
one-shots, keeping Spotlight indexing off, and emptying the CoreSpotlight
semantic caches. A stopped process cannot answer launchd's shutdown
SIGTERM, so install also loads a thaw agent.

People without the rest of ~/ops run this via the justfile in macos/.
This machine's site watchdog (bin/apple_daemon_ban.sh) calls `empty-stores`
and otherwise keeps its own freeze loop; tests/test_quiet_mac.py checks
that both sides name the same daemons.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import grp
import os
import plistlib
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

LABEL_ENFORCE = "com.quiet-mac.enforce"
LABEL_THAW = "com.quiet-mac.thaw"
SITE_THAW = "com.djbclark.shutdown-thaw"
ROOT_LIB = Path("/usr/local/libexec/quiet-mac")
SUDOERS = Path("/etc/sudoers.d/quiet-mac")
HELPER = ROOT_LIB / "quiet-mac-root"
HELPER_REVERT = ROOT_LIB / "quiet-mac-root-revert"
INTERVAL_S = 60
UNFROZEN_LIMIT_S = 120
STORE_CAP_BYTES = 50 * 1024 * 1024
SEMANTIC_STORES = (
    "Library/Metadata/CoreSpotlight/DocumentProcessing",
    "Library/Metadata/CoreSpotlight/SpotlightKnowledgeEvents",
    "Library/Metadata/CoreSpotlight/SpotlightKnowledge",
)
NIGHTLY_NAMES = (
    "neofinder-stub-export.py",
    "neofinder-spotlight-batch.sh",
    "neofinder-catalog-update",
)
ACTIONS = frozenset({"freeze", "term", "flag"})
DOMAINS = frozenset({"gui", "user", "system"})

HELP = """\
quiet-mac — freeze the Apple daemons that grow in the background

  status                 one screen: anything not in the desired state
  check                  exit 0 and no output when healthy; else exit 1
  enforce                one fix pass (the 60s agent runs this)
  install                flags, 60s fixer, shutdown thaw, root helper
  revert                 turn the daemons back on and remove quiet-mac
  uninstall              remove quiet-mac and continue anything it froze
  empty-stores           empty CoreSpotlight semantic caches over 50 MiB
  thaw-wait              stay running; on SIGTERM, thaw stopped processes

Needs python3.9+. `just install` from macos/ is the supported entry.
"""


@dataclass(frozen=True)
class Job:
    action: str
    domain: str
    label: str
    why: str


@dataclass(frozen=True)
class Live:
    disabled: bool
    pid: int | None
    frozen: bool
    age_s: int | None
    rss_kb: int | None


@dataclass(frozen=True)
class Action:
    kind: str  # disable, stop, term
    domain: str
    label: str
    pid: int | None = None


def policy_path() -> Path:
    override = os.environ.get("QUIET_MAC_POLICY")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "daemons.tsv"


def load_policy(path: Path | None = None) -> list[Job]:
    path = path or policy_path()
    jobs: list[Job] = []
    seen: set[tuple[str, str]] = set()
    text = path.read_text(encoding="utf-8")
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 4:
            raise ValueError(f"{path}:{lineno}: need action, domain, label, why")
        action, domain, label, why = parts[0], parts[1], parts[2], parts[3]
        if action not in ACTIONS or domain not in DOMAINS:
            raise ValueError(f"{path}:{lineno}: bad action or domain")
        if not label.startswith("com.apple."):
            raise ValueError(f"{path}:{lineno}: label must start with com.apple.")
        if action == "freeze" and domain == "system":
            raise ValueError(f"{path}:{lineno}: refusing to freeze a root daemon")
        key = (domain, label)
        if key in seen:
            raise ValueError(f"{path}:{lineno}: duplicate {domain}/{label}")
        seen.add(key)
        jobs.append(Job(action, domain, label, why))
    if not jobs:
        raise ValueError(f"{path}: no daemons")
    return jobs


def actions_for(job: Job, live: Live) -> list[Action]:
    """What the user-level pass should do. System jobs are the root helper's."""
    if job.domain == "system":
        return []
    out: list[Action] = []
    if not live.disabled:
        out.append(Action("disable", job.domain, job.label))
    if job.action == "flag" or live.pid is None:
        return out
    # A frozen process is already the steady state, including one-shots.
    # TERMing a stopped process does not deliver, and the KILL that follows
    # would respawn it.
    if live.frozen:
        return out
    if job.action == "freeze":
        out.append(Action("stop", job.domain, job.label, live.pid))
    elif job.action == "term":
        out.append(Action("term", job.domain, job.label, live.pid))
    return out


def desired(job: Job, live: Live) -> bool:
    if not live.disabled:
        return False
    if job.action == "flag":
        return True
    if job.domain == "system":
        return live.pid is None
    return live.pid is None or live.frozen


def problem(job: Job, live: Live, now_age_limit: int = UNFROZEN_LIMIT_S) -> str | None:
    if not live.disabled:
        return f"flag not set: {job.domain}/{job.label}"
    if job.action == "flag":
        return None
    if live.pid is None:
        return None
    # A frozen gui/user job is the steady state. A frozen root job is not:
    # nothing in this kit stops root processes, and the thaw agent cannot
    # continue them, so a stopped root process stalls shutdown.
    if job.domain != "system" and live.frozen:
        return None
    if job.domain == "system" and live.frozen:
        return f"frozen root process: {job.domain}/{job.label}"
    if (live.age_s or 0) > now_age_limit:
        return f"running unfrozen: {job.domain}/{job.label}"
    return None


def in_nightly_window(when: dt.datetime) -> bool:
    minutes = when.hour * 60 + when.minute
    return 60 <= minutes <= 345


def neofinder_present(home: Path, command_lines: list[str]) -> bool:
    if (home / "Library/Application Support/neofinder-stub-export").is_dir():
        return True
    if (home / "nfbatch.sparseimage").exists():
        return True
    blob = "\n".join(command_lines)
    return any(name in blob for name in NIGHTLY_NAMES)


def skip_indexing_off(
    home: Path,
    when: dt.datetime,
    lock_held: bool,
    command_lines: list[str],
) -> bool:
    """Leave Spotlight indexing alone during a NeoFinder batch window."""
    if not neofinder_present(home, command_lines):
        return False
    if lock_held or in_nightly_window(when):
        return True
    blob = "\n".join(command_lines)
    return any(name in blob for name in NIGHTLY_NAMES)


def stopped_from_ps(text: str) -> list[tuple[int, str, str]]:
    """Parse `ps -axo pid=,stat=,comm=` and return stopped rows."""
    rows: list[tuple[int, str, str]] = []
    for line in text.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid_s, stat, comm = parts
        if not pid_s.isdigit() or not stat.startswith("T"):
            continue
        rows.append((int(pid_s), stat, comm))
    return rows


def store_size(root: Path) -> int:
    total = 0
    if not root.is_dir() or root.is_symlink():
        return 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Do not descend through a symlinked directory.
        dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def empty_store(home: Path, rel: str, only_over: int | None) -> int:
    """Delete children of one semantic store. Returns how many names removed."""
    if rel not in SEMANTIC_STORES:
        raise ValueError(rel)
    if ".." in Path(rel).parts or rel.startswith("/"):
        raise ValueError(rel)
    home_s = str(home)
    if not home_s.startswith("/Users/") or home_s == "/Users":
        raise ValueError(f"refusing home {home}")
    root = home / rel
    if root.is_symlink():
        raise ValueError(f"refusing symlink {root}")
    if not root.exists():
        return 0
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    resolved_home = home.resolve()
    resolved = root.resolve()
    if resolved != resolved_home / rel:
        raise ValueError(f"store path escaped home: {root}")
    if only_over is not None and store_size(root) <= only_over:
        return 0
    removed = 0
    for child in list(root.iterdir()):
        # Unlink a symlink as a symlink. Resolving it first would treat an
        # outside target as an escape and would also risk operating on it.
        if child.is_symlink():
            child.unlink()
            removed += 1
            continue
        child_resolved = child.resolve()
        if os.path.commonpath([str(resolved), str(child_resolved)]) != str(resolved):
            raise ValueError(f"refusing to remove {child}")
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    return removed


def sudoers_text(user: str) -> str:
    if not user or any(c in user for c in " \t\n#,\\"):
        raise ValueError(f"refusing sudoers user {user!r}")
    return (
        "# quiet-mac: system-domain half. Exactly these paths, no arguments.\n"
        f"{user} ALL=(root) NOPASSWD: {HELPER}\n"
        f"{user} ALL=(root) NOPASSWD: {HELPER_REVERT}\n"
        f"{user} ALL=(root) NOPASSWD: /usr/bin/mdutil -a -i off\n"
    )


def agent_python() -> str:
    candidates = [
        os.environ.get("QUIET_MAC_PYTHON") or "",
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        sys.executable,
        "/usr/bin/python3",
    ]
    for path in candidates:
        if path and _python_works(path):
            return path
    raise SystemExit("quiet-mac: no working python3 found")


def _python_works(path: str) -> bool:
    if not os.path.isfile(path) or not os.access(path, os.X_OK):
        return False
    try:
        result = subprocess.run(
            [
                path,
                "-c",
                "import sys; raise SystemExit(0 if sys.version_info>=(3,9) else 1)",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def enforce_plist(python: str, script: str, home: Path, logs: Path) -> dict:
    return {
        "Label": LABEL_ENFORCE,
        "ProgramArguments": [python, script, "enforce"],
        "RunAtLoad": True,
        "StartInterval": INTERVAL_S,
        "ExitTimeOut": 30,
        "StandardOutPath": str(logs / "enforce.launchd.log"),
        "StandardErrorPath": str(logs / "enforce.launchd.log"),
        "EnvironmentVariables": {
            "HOME": str(home),
            "PATH": "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
    }


def thaw_plist(python: str, script: str, home: Path, logs: Path) -> dict:
    return {
        "Label": LABEL_THAW,
        "ProgramArguments": [python, script, "thaw-wait"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ExitTimeOut": 10,
        "StandardOutPath": str(logs / "thaw.launchd.log"),
        "StandardErrorPath": str(logs / "thaw.launchd.log"),
        "EnvironmentVariables": {
            "HOME": str(home),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        },
    }


def home_dir() -> Path:
    override = os.environ.get("QUIET_MAC_HOME")
    return Path(override) if override else Path.home()


def libexec_dir() -> Path:
    return home_dir() / ".local/libexec/quiet-mac"


def logs_dir() -> Path:
    return home_dir() / "Library/Logs/quiet-mac"


def state_dir() -> Path:
    return home_dir() / ".local/state/quiet-mac"


def agents_dir() -> Path:
    return home_dir() / "Library/LaunchAgents"


def console_uid() -> int | None:
    try:
        uid = os.stat("/dev/console").st_uid
    except OSError:
        return None
    if uid == 0:
        return None
    return uid


def _run(argv: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, check=False
    )


def job_pid(domain: str, label: str) -> int | None:
    try:
        result = _run(["launchctl", "print", f"{domain}/{label}"])
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in result.stdout.splitlines():
        if line.startswith("\tpid = "):
            value = line.split("=", 1)[1].strip()
            if value.isdigit() and int(value) > 0:
                return int(value)
            return None
    return None


def is_disabled(domain: str, label: str) -> bool:
    try:
        result = _run(["launchctl", "print-disabled", domain])
    except (OSError, subprocess.TimeoutExpired):
        return False
    needle_disabled = f'"{label}" => disabled'
    needle_true = f'"{label}" => true'
    return needle_disabled in result.stdout or needle_true in result.stdout


def proc_info(pid: int) -> tuple[bool, int | None, int | None]:
    """Return frozen, age_s, rss_kb. age is None when ps cannot say."""
    try:
        result = _run(["ps", "-o", "stat=,etime=,rss=", "-p", str(pid)])
    except (OSError, subprocess.TimeoutExpired):
        return False, None, None
    line = result.stdout.strip()
    if not line:
        return False, None, None
    parts = line.split()
    stat = parts[0] if parts else ""
    etime = parts[1] if len(parts) > 1 else ""
    rss = parts[2] if len(parts) > 2 else ""
    frozen = stat.startswith("T")
    rss_kb = int(rss) if rss.isdigit() else None
    return frozen, _etime_seconds(etime), rss_kb


def _etime_seconds(etime: str) -> int | None:
    # ps etime: [[dd-]hh:]mm:ss
    if not etime:
        return None
    days = 0
    clock = etime
    if "-" in etime:
        day_s, clock = etime.split("-", 1)
        if not day_s.isdigit():
            return None
        days = int(day_s)
    pieces = clock.split(":")
    if not all(piece.isdigit() for piece in pieces):
        return None
    nums = [int(piece) for piece in pieces]
    if len(nums) == 1:
        seconds = nums[0]
    elif len(nums) == 2:
        seconds = nums[0] * 60 + nums[1]
    elif len(nums) == 3:
        seconds = nums[0] * 3600 + nums[1] * 60 + nums[2]
    else:
        return None
    return days * 86400 + seconds


def probe(domain: str, label: str) -> Live:
    pid = job_pid(domain, label)
    frozen, age, rss = (False, None, None)
    if pid is not None:
        frozen, age, rss = proc_info(pid)
    return Live(is_disabled(domain, label), pid, frozen, age, rss)


def domain_name(job: Job, uid: int) -> str:
    if job.domain == "system":
        return "system"
    return f"{job.domain}/{uid}"


def log_line(name: str, message: str) -> None:
    directory = logs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    try:
        if path.exists() and path.stat().st_size > 1_000_000:
            path.replace(path.with_suffix(path.suffix + ".1"))
    except OSError:
        pass
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {message}\n")


def _signal(pid: int, sig: int) -> bool:
    try:
        os.kill(pid, sig)
    except OSError:
        return False
    return True


def apply_user_action(action: Action, uid: int) -> None:
    domain = f"{action.domain}/{uid}"
    target = f"{domain}/{action.label}"
    if action.kind == "disable":
        _run(["launchctl", "disable", target])
        log_line("enforce.log", f"disable {target}")
        return
    if action.pid is None:
        return
    if action.kind == "stop":
        if _signal(action.pid, signal.SIGSTOP):
            log_line("enforce.log", f"STOP {target} pid {action.pid}")
        return
    if action.kind == "term":
        if not _signal(action.pid, signal.SIGTERM):
            return
        time.sleep(1)
        if job_pid(domain, action.label) == action.pid:
            _signal(action.pid, signal.SIGKILL)
            log_line("enforce.log", f"KILL {target} pid {action.pid}")
        else:
            log_line("enforce.log", f"TERM {target} pid {action.pid}")


def agent_loaded(label: str, uid: int | None = None) -> bool:
    uid = os.getuid() if uid is None else uid
    try:
        result = _run(["launchctl", "print", f"gui/{uid}/{label}"])
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def thaw_available(uid: int) -> bool:
    return agent_loaded(LABEL_THAW, uid) or agent_loaded(SITE_THAW, uid)


def command_lines() -> list[str]:
    try:
        result = _run(["ps", "-axo", "command="], timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return result.stdout.splitlines()


def lock_held(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        result = _run(["lsof", "-t", str(path)])
    except (OSError, subprocess.TimeoutExpired):
        return False
    me = str(os.getpid())
    return any(token.isdigit() and token != me for token in result.stdout.split())


def indexing_enabled() -> bool:
    for volume in ("/", "/System/Volumes/Data"):
        try:
            result = _run(["mdutil", "-s", volume])
        except (OSError, subprocess.TimeoutExpired):
            continue
        if "Indexing enabled" in result.stdout:
            return True
    return False


def indexing_off() -> bool:
    result = _run(["sudo", "-n", "/usr/bin/mdutil", "-a", "-i", "off"], timeout=60)
    if result.returncode != 0:
        log_line(
            "enforce.log",
            f"mdutil off failed: {result.stderr.strip() or result.stdout.strip()}",
        )
        return False
    log_line("enforce.log", "mdutil -a -i off")
    return True


def run_root_helper(revert: bool = False) -> tuple[int, str]:
    path = HELPER_REVERT if revert else HELPER
    if not path.is_file():
        return 1, f"missing {path}"
    try:
        result = _run(["sudo", "-n", str(path)], timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    text = (result.stdout or "") + (result.stderr or "")
    return result.returncode, text.strip()


def with_lock(name: str):
    state_dir().mkdir(parents=True, exist_ok=True)
    handle = (state_dir() / name).open("a", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def cmd_enforce() -> int:
    uid = console_uid()
    if uid is None or uid != os.getuid():
        print("skip: no console user")
        return 75
    lock = with_lock("enforce.lock")
    if lock is None:
        print("skip: another enforce is running")
        return 0
    try:
        return _enforce(uid)
    finally:
        lock.close()


def _enforce(uid: int) -> int:
    policy = load_policy()
    home = home_dir()
    thaw_ok = thaw_available(uid)
    stopped = 0
    termed = 0
    disabled = 0
    skipped_freeze = 0
    for job in policy:
        if job.domain == "system":
            continue
        live = probe(domain_name(job, uid), job.label)
        for action in actions_for(job, live):
            if action.kind == "stop" and not thaw_ok:
                skipped_freeze += 1
                continue
            apply_user_action(action, uid)
            if action.kind == "stop":
                stopped += 1
            elif action.kind == "term":
                termed += 1
            elif action.kind == "disable":
                disabled += 1
    root_rc, root_out = run_root_helper(revert=False)
    if root_out:
        log_line("enforce.log", root_out.replace("\n", " | "))
    index_note = ""
    when = dt.datetime.now()
    commands = command_lines()
    lock_path = home / "Library/Application Support/neofinder-stub-export/nightly.lock"
    if indexing_enabled() and not skip_indexing_off(
        home, when, lock_held(lock_path), commands
    ):
        index_note = " indexing:off" if indexing_off() else " indexing:FAILED"
    removed = cmd_empty_stores(only_over=STORE_CAP_BYTES, quiet_ok=True)
    parts = [f"stopped:{stopped}", f"termed:{termed}", f"disabled:{disabled}"]
    if removed:
        parts.append(f"stores:{removed}")
    if skipped_freeze:
        parts.append(f"freeze-skipped:{skipped_freeze}")
    line = " ".join(parts) + index_note
    print(line)
    if skipped_freeze:
        print(
            "not freezing: no shutdown thaw is loaded. Run: just install",
            file=sys.stderr,
        )
        return 2
    if root_rc != 0:
        print(f"root helper: {root_out or 'failed'}", file=sys.stderr)
        return 1
    return 0


def cmd_empty_stores(
    only_over: int | None = STORE_CAP_BYTES, quiet_ok: bool = False
) -> int:
    home = home_dir()
    removed = 0
    for rel in SEMANTIC_STORES:
        try:
            count = empty_store(home, rel, only_over)
        except (OSError, ValueError) as exc:
            log_line("enforce.log", f"empty {rel} failed: {exc}")
            print(f"empty {rel} failed: {exc}", file=sys.stderr)
            continue
        if count:
            removed += count
            message = f"emptied {count} names from ~/{rel}"
            log_line("enforce.log", message)
            print(message)
        elif not quiet_ok:
            print(f"~/{rel}: under cap or absent")
    return removed


def cmd_check() -> int:
    uid = console_uid()
    if uid is None:
        return 0
    if uid != os.getuid():
        print("check: not the console user")
        return 1
    problems: list[str] = []
    for job in load_policy():
        live = probe(domain_name(job, uid), job.label)
        found = problem(job, live)
        if found:
            problems.append(found)
    home = home_dir()
    when = dt.datetime.now()
    commands = command_lines()
    lock_path = home / "Library/Application Support/neofinder-stub-export/nightly.lock"
    if indexing_enabled() and not skip_indexing_off(
        home, when, lock_held(lock_path), commands
    ):
        problems.append("Spotlight indexing is enabled")
    for rel in SEMANTIC_STORES:
        root = home / rel
        try:
            size = store_size(root)
        except OSError:
            continue
        if size > STORE_CAP_BYTES:
            problems.append(f"semantic store {size // (1024 * 1024)} MiB: ~/{rel}")
    if not problems:
        return 0
    print(f"quiet-mac: {len(problems)} problem(s)")
    for item in problems:
        print(f"  {item}")
    print("Fix: just enforce    (or just install, if the 60s agent is not loaded)")
    return 1


def cmd_status(full: bool = False) -> int:
    uid = console_uid()
    if uid is None:
        print("no console user")
        return 0
    policy = load_policy()
    bad: list[str] = []
    good = 0
    frozen_rss = 0
    frozen_n = 0
    for job in policy:
        if uid != os.getuid() and job.domain != "system":
            continue
        live = probe(domain_name(job, uid), job.label)
        if live.frozen and live.rss_kb:
            frozen_rss += live.rss_kb
            frozen_n += 1
        line = _status_line(job, live)
        if desired(job, live):
            good += 1
            if full:
                print(line)
        else:
            bad.append(line)
    print(f"quiet-mac: {good} in the desired state, {len(bad)} not")
    for line in bad:
        print(line)
    if frozen_n:
        print(f"frozen now: {frozen_n} processes, {frozen_rss / 1024:.1f} MiB RSS")
    home = home_dir()
    index = "enabled" if indexing_enabled() else "disabled"
    print(f"Spotlight indexing: {index}")
    for rel in SEMANTIC_STORES:
        size = store_size(home / rel)
        print(f"store ~/{rel}: {size / (1024 * 1024):.1f} MiB")
    if uid == os.getuid():
        thaw = "loaded" if thaw_available(uid) else "MISSING"
        fixer = "loaded" if agent_loaded(LABEL_ENFORCE, uid) else "not loaded"
        print(f"agents: enforce {fixer}, thaw {thaw}")
    helper = "installed" if HELPER.is_file() else "not installed"
    print(f"root helper: {helper}")
    return 0


def _status_line(job: Job, live: Live) -> str:
    flag = "disabled" if live.disabled else "ENABLED"
    if live.pid is None:
        state = "not running"
    elif live.frozen:
        rss = f" {live.rss_kb}KB" if live.rss_kb is not None else ""
        state = f"frozen pid {live.pid}{rss}"
    else:
        state = f"RUNNING pid {live.pid}"
    return f"  {job.action:6} {job.domain:6} {job.label}: {flag}, {state}"


def _write_plist(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML))


def prepare_user_files(python: str) -> tuple[Path, Path]:
    """Copy the kit into ~/.local and write the two LaunchAgent plists."""
    source = Path(__file__).resolve().parent
    dest = libexec_dir()
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("quiet_mac.py", "daemons.tsv", "quiet-mac-root.sh"):
        shutil.copy2(source / name, dest / name)
    os.chmod(dest / "quiet_mac.py", 0o755)
    os.chmod(dest / "quiet-mac-root.sh", 0o755)
    logs = logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    home = home_dir()
    script = str(dest / "quiet_mac.py")
    enforce = agents_dir() / f"{LABEL_ENFORCE}.plist"
    thaw = agents_dir() / f"{LABEL_THAW}.plist"
    _write_plist(enforce, enforce_plist(python, script, home, logs))
    _write_plist(thaw, thaw_plist(python, script, home, logs))
    return enforce, thaw


def reload_agent(label: str, plist: Path) -> None:
    uid = os.getuid()
    target = f"gui/{uid}/{label}"
    _run(["launchctl", "bootout", target])
    result = _run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(f"launchctl bootstrap {label} failed: {detail}")
    _run(["launchctl", "enable", target])


def bootout_agent(label: str) -> None:
    uid = os.getuid()
    _run(["launchctl", "bootout", f"gui/{uid}/{label}"])
    plist = agents_dir() / f"{label}.plist"
    if plist.exists():
        plist.unlink()


def _sudo_prefix() -> list[str]:
    if shutil.which("sudo-ask"):
        return ["sudo-ask"]
    return ["sudo"]


def install_root_as_root(user: str) -> int:
    if os.geteuid() != 0:
        print("quiet-mac: --install-root must run as root", file=sys.stderr)
        return 1
    if not user:
        print("quiet-mac: --install-root needs --user", file=sys.stderr)
        return 1
    source = Path(__file__).resolve().parent
    ROOT_LIB.mkdir(parents=True, exist_ok=True)
    script = (source / "quiet-mac-root.sh").read_bytes()
    policy = (source / "daemons.tsv").read_bytes()
    for path in (HELPER, HELPER_REVERT):
        path.write_bytes(script)
        os.chmod(path, 0o755)
    policy_dest = ROOT_LIB / "daemons.tsv"
    policy_dest.write_bytes(policy)
    os.chmod(policy_dest, 0o444)
    wheel = grp.getgrnam("wheel").gr_gid
    for path in (ROOT_LIB, HELPER, HELPER_REVERT, policy_dest):
        os.chown(path, 0, wheel)
    text = sudoers_text(user)
    tmp = SUDOERS.with_suffix(".quiet-mac.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o440)
    os.chown(tmp, 0, wheel)
    check = subprocess.run(
        ["visudo", "-cf", str(tmp)],
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode != 0:
        tmp.unlink(missing_ok=True)
        print(check.stderr or check.stdout, file=sys.stderr)
        return 1
    tmp.replace(SUDOERS)
    full = subprocess.run(["visudo", "-c"], capture_output=True, text=True, check=False)
    if full.returncode != 0:
        SUDOERS.unlink(missing_ok=True)
        print(full.stderr or full.stdout, file=sys.stderr)
        return 1
    print(f"installed {HELPER} and {SUDOERS} for {user}")
    return 0


def cmd_install() -> int:
    uid = console_uid()
    if uid is None or uid != os.getuid():
        print(
            "install: log in at the console and run this as that user", file=sys.stderr
        )
        return 1
    print(
        "quiet-mac disables iCloud (cloudd), Photos analysis, Spotlight semantic\n"
        "search, Siri, Shortcuts, widgets, Weather, Screen Time, AirDrop, Handoff\n"
        "and Contacts. BiomeAgent is left running so sudo can still prompt.\n"
        "A shutdown thaw is installed with the freezer; without it, reboot stalls."
    )
    if agent_loaded(SITE_THAW, uid):
        print(
            "This Mac already has the site shutdown thaw. quiet-mac adds its own\n"
            "60s fixer beside it. Both are safe to run; the site one is enough if\n"
            "you only wanted the thaw."
        )
    python = agent_python()
    enforce_plist_path, thaw_plist_path = prepare_user_files(python)
    reload_agent(LABEL_THAW, thaw_plist_path)
    user = _current_user()
    root = subprocess.run(
        [
            *_sudo_prefix(),
            python,
            str(Path(__file__).resolve()),
            "--install-root",
            "--user",
            user,
        ],
        text=True,
        check=False,
    )
    if root.returncode != 0:
        print(
            "root install did not finish; the 60s freezer was not started",
            file=sys.stderr,
        )
        return root.returncode
    reload_agent(LABEL_ENFORCE, enforce_plist_path)
    # install empties the semantic caches once, even under the cap.
    cmd_empty_stores(only_over=None, quiet_ok=True)
    print("install: thaw and enforcer loaded. `just status` shows the result.")
    return 0


def _current_user() -> str:
    import pwd

    return pwd.getpwuid(os.getuid()).pw_name


def _continue_policy(uid: int) -> None:
    for job in load_policy():
        if job.domain == "system":
            continue
        domain = domain_name(job, uid)
        pid = job_pid(domain, job.label)
        if pid is None:
            continue
        frozen, _, _ = proc_info(pid)
        if frozen and _signal(pid, signal.SIGCONT):
            print(f"continued {job.label} pid {pid}")


def _enable_user(uid: int) -> None:
    for job in load_policy():
        if job.domain == "system":
            continue
        target = f"{domain_name(job, uid)}/{job.label}"
        _run(["launchctl", "enable", target])


def remove_root_files() -> None:
    if not HELPER.exists() and not SUDOERS.exists():
        return
    subprocess.run(
        [
            *_sudo_prefix(),
            "/bin/rm",
            "-f",
            str(SUDOERS),
            str(HELPER),
            str(HELPER_REVERT),
            str(ROOT_LIB / "daemons.tsv"),
        ],
        check=False,
    )


def cmd_uninstall(continue_jobs: bool = True) -> int:
    uid = console_uid() or os.getuid()
    bootout_agent(LABEL_ENFORCE)
    if continue_jobs and uid == os.getuid():
        _continue_policy(uid)
    bootout_agent(LABEL_THAW)
    remove_root_files()
    dest = libexec_dir()
    if dest.is_dir():
        shutil.rmtree(dest)
    print("uninstall: agents removed. Disable flags were left set.")
    print("Without the fixer, launchd will start those daemons again on demand.")
    return 0


def cmd_revert() -> int:
    uid = console_uid()
    if uid is None or uid != os.getuid():
        print(
            "revert: log in at the console and run this as that user", file=sys.stderr
        )
        return 1
    bootout_agent(LABEL_ENFORCE)
    _enable_user(uid)
    _continue_policy(uid)
    root_rc, root_out = run_root_helper(revert=True)
    if root_rc != 0:
        print(f"root revert: {root_out or 'failed'}", file=sys.stderr)
        print("system-domain flags may still be disabled", file=sys.stderr)
    elif root_out:
        print(root_out)
    bootout_agent(LABEL_THAW)
    remove_root_files()
    print("revert: flags enabled, frozen jobs continued, quiet-mac removed.")
    return 0 if root_rc == 0 else 1


def thaw_once() -> int:
    """CONT, TERM, then KILL every stopped process of this user.

    Any stopped process stalls a Mac shutdown, not only the ones quiet-mac
    froze. This matches bin/shutdown-thaw.sh.
    """
    try:
        result = _run(
            ["ps", "-axo", "pid=,stat=,comm=", "-U", str(os.getuid())], timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log_line("thaw.log", f"ps failed: {exc}")
        return 0
    rows = [
        (pid, stat, comm)
        for pid, stat, comm in stopped_from_ps(result.stdout)
        if pid != os.getpid()
    ]
    for pid, stat, comm in rows:
        _signal(pid, signal.SIGCONT)
        _signal(pid, signal.SIGTERM)
        log_line("thaw.log", f"CONT+TERM {pid} {comm} (was {stat})")
    if rows:
        time.sleep(3)
        for pid, _stat, comm in rows:
            try:
                os.kill(pid, 0)
            except OSError:
                continue
            if _signal(pid, signal.SIGKILL):
                log_line("thaw.log", f"KILL {pid} {comm}")
    log_line("thaw.log", f"thawed {len(rows)} stopped process(es)")
    return len(rows)


def cmd_thaw_wait() -> int:
    stop = False

    def _mark(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _mark)
    signal.signal(signal.SIGHUP, _mark)
    signal.signal(signal.SIGINT, _mark)
    log_line("thaw.log", f"started pid {os.getpid()}")
    while not stop:
        try:
            time.sleep(86400)
        except InterruptedError:
            break
    thaw_once()
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--install-root":
        user = ""
        if "--user" in argv:
            user = argv[argv.index("--user") + 1]
        return install_root_as_root(user)
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd in ("-h", "--help", "help"):
        print(HELP)
        return 0
    if cmd == "status":
        return cmd_status(full="--full" in argv)
    if cmd == "check":
        return cmd_check()
    if cmd == "enforce":
        return cmd_enforce()
    if cmd == "install":
        return cmd_install()
    if cmd == "revert":
        return cmd_revert()
    if cmd == "uninstall":
        return cmd_uninstall()
    if cmd == "empty-stores":
        cmd_empty_stores(only_over=STORE_CAP_BYTES, quiet_ok=True)
        return 0
    if cmd == "thaw-wait":
        return cmd_thaw_wait()
    if cmd == "thaw-once":
        print(f"thawed {thaw_once()}")
        return 0
    print(HELP, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except BrokenPipeError:
        raise SystemExit(0) from None
