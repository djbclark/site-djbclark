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
import platform
import plistlib
import shutil
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Bump when the installed behavior changes. `just upgrade` re-runs install
# when the copy under ~/.local/libexec/quiet-mac is older than this.
VERSION = "1.1.0"
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
PLOCATE_DB_MAX_AGE_H = 36
PLOCATE_NIGHTLY_LABELS = (
    "com.djbclark.plocate-updatedb",
    "sh.brew.plocate",
    "homebrew.mxcl.plocate",
)
PROFILE_ID = "com.djbclark.no-apple-intelligence"
PROFILE_DISPLAY = "No Apple Intelligence (djbclark)"
PROFILE_SETTINGS_URL = "x-apple.systempreferences:com.apple.Profiles-Settings.extension"
PROFILE_WAIT_S = 8 * 60
NAG_INTERVAL_S = 6 * 3600
SUDO_NAG = (
    "NAG: the system-domain half has not been applied. It needs one\n"
    "administrator click (Touch ID works; Enter and Esc do not decide).\n"
    "  just install        # user half, root helper, system flags, plocate, profile\n"
    "  just system-flags   # only the root helper, after install wrote it\n"
    "doctor and status keep reporting this until those flags are set."
)
PROFILE_NAG = (
    "NAG: the Apple Intelligence profile is not installed. macOS will not\n"
    "install a configuration profile from the command line. just install\n"
    "opens it and prints the System Settings steps. doctor and status keep\n"
    "reporting this until the profile is installed."
)
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

HELP = (
    """\
quiet-mac — freeze the Apple daemons that grow in the background

  status                 desired state, then errors and warnings
  doctor                 errors, warnings, and the sudo nag; exit 1 on errors
  check                  exit 0 and no output when the daemon policy holds
  enforce                one fix pass (the 60s agent runs this)
  install                idempotent: flags, fixer, thaw, root helper, plocate, profile
  profile                open the Apple Intelligence profile and print the steps
  upgrade                install this checkout when it is newer
  system-flags           system-domain disable flags (the step that needs sudo)
  empty-stores           empty CoreSpotlight semantic caches over 50 MiB
  recovery               how to open Recovery on this Mac; does not reboot
  snapshot               write status and doctor to ~/.local/state/quiet-mac
  revert                 turn the daemons back on and remove quiet-mac
  factory                Apple's shipping behavior: flags, Spotlight, profile
  uninstall              remove quiet-mac and continue anything it froze
  thaw-wait              stay running; on SIGTERM, thaw stopped processes

Needs python3.9+ and Homebrew. `just install` from macos/ is the entry.
Version """
    + VERSION
    + """.
"""
)


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


@dataclass(frozen=True)
class Finding:
    level: str  # error, warning, info
    code: str
    message: str


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
        "# quiet-mac: system-domain half. Exactly these commands, no others.\n"
        f"{user} ALL=(root) NOPASSWD: {HELPER}\n"
        f"{user} ALL=(root) NOPASSWD: {HELPER_REVERT}\n"
        f"{user} ALL=(root) NOPASSWD: /usr/bin/mdutil -a -i off\n"
        f"{user} ALL=(root) NOPASSWD: /usr/bin/profiles list\n"
    )


def version_tuple(text: str) -> tuple[int, ...]:
    pieces = text.strip().split(".")
    if not pieces or not all(piece.isdigit() for piece in pieces):
        raise ValueError(f"bad version {text!r}")
    return tuple(int(piece) for piece in pieces)


def version_relation(installed: str | None, repo: str = VERSION) -> str:
    """missing, invalid, same, older, or newer. older means the install is behind."""
    if not installed:
        return "missing"
    try:
        left = version_tuple(installed)
        right = version_tuple(repo)
    except ValueError:
        return "invalid"
    if left == right:
        return "same"
    if left < right:
        return "older"
    return "newer"


def silicon_kind(machine: str) -> str:
    """apple or intel, from uname -m / platform.machine()."""
    return "apple" if machine == "arm64" else "intel"


def recovery_text(kind: str) -> str:
    """How to open Recovery. The diet itself does not need this."""
    common = (
        "The normal quiet-mac install does not boot into Recovery and does not\n"
        "turn SIP off. While SIP is on, launchctl bootout of Apple's own jobs is\n"
        "refused. The diet does not need that. It sets disable flags, SIGSTOPs\n"
        "this user's jobs, and SIGTERMs the short system jobs. The 60-second\n"
        "watchdog, com.quiet-mac.enforce, is what holds that. just install loads\n"
        "it. A Mac does not need roles/watchdogd or sip-doit-with-sudo.sh.\n"
        "\n"
        "Turning SIP off does not make the flags hold. bootout then unloads the\n"
        "jobs for this login only. They come back at the next login, flags or\n"
        "not. That path is sip-doit-with-sudo.sh --sip-disable, one boot, then\n"
        "--sip-enable. It is not a stronger version of the diet.\n"
    )
    if kind == "apple":
        steps = (
            "This Mac is Apple silicon. To open Recovery:\n"
            "1. Shut the Mac down.\n"
            "2. Press and hold the power button until Loading startup options appears.\n"
            "3. Click Options, then Continue.\n"
            "4. Choose a user and enter its password.\n"
            "5. Menu bar: Utilities, then Terminal.\n"
        )
    else:
        steps = (
            "This Mac is Intel. To open Recovery:\n"
            "1. Restart the Mac.\n"
            "2. Immediately hold Command-R until the Apple logo or a spinning globe.\n"
            "3. Menu bar: Utilities, then Terminal.\n"
            "If Command-R does not find a local Recovery, hold Option-Command-R\n"
            "instead. That starts internet Recovery and needs a network.\n"
        )
    return common + "\n" + steps


def macos_version() -> str:
    version = platform.mac_ver()[0]
    if version:
        return version
    try:
        result = _run(["sw_vers", "-productVersion"], timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return "0"
    return (result.stdout or "").strip() or "0"


def macos_major(version: str) -> int:
    piece = version.split(".")[0]
    return int(piece) if piece.isdigit() else 0


def profiles_settings_location(version: str) -> str:
    """The System Settings path for a downloaded configuration profile."""
    major = macos_major(version)
    if major >= 15:
        return "General → Device Management"
    if major >= 13:
        return "Privacy & Security → Profiles"
    return "System Preferences → Profiles"


def profile_install_steps(location: str) -> str:
    """What the person clicks. macOS 11 and later refuse `profiles install`."""
    return (
        f'Apple Intelligence is stopped by the profile "{PROFILE_DISPLAY}"\n'
        f"({PROFILE_ID}). Since macOS 11, the profiles command cannot install a\n"
        "configuration profile. System Settings has to. Do these steps now.\n"
        "macOS drops a downloaded profile after about 8 minutes. If it is gone,\n"
        "run just install again.\n"
        "1. System Settings opens to the profile pane. If it does not, choose\n"
        f"   Apple menu → System Settings → {location}.\n"
        "2. In the Downloaded section, double-click\n"
        f"   {PROFILE_DISPLAY}.\n"
        "3. Review the list, then click Continue or Install.\n"
        "4. Click Install on the confirmation sheet.\n"
        "5. Approve with Touch ID or the administrator password.\n"
        "   Enter and Esc do not install it.\n"
        "quiet-mac waits here until that profile is installed."
    )


def profile_mobileconfig_path() -> Path:
    here = Path(__file__).resolve().parent
    candidates = (
        here / "no-apple-intelligence.mobileconfig",
        here.parent / "no-apple-intelligence" / "no-apple-intelligence.mobileconfig",
    )
    for path in candidates:
        if path.is_file():
            return path
    return candidates[-1]


def disable_toml_service(text: str, name: str) -> tuple[str, str]:
    """Set enabled = false in a watchdogd service file. Idempotent.

    The second value is already, disabled, or inserted.
    """
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "enabled = false":
            return text, "already"
        if stripped == "enabled = true":
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = f"enabled = false{newline}"
            return "".join(lines), "disabled"
    needle = f'name = "{name}"'
    for index, line in enumerate(lines):
        if line.strip() == needle:
            lines.insert(index + 1, "enabled = false\n")
            return "".join(lines), "inserted"
    return "enabled = false\n" + text, "inserted"


def plocate_plan(binary: bool, nightly: str | None, brew: bool) -> str:
    """What install should do. keep means a nightly is already loaded."""
    if not brew:
        return "need-brew"
    if not binary and nightly:
        return "install-only"
    if not binary:
        return "install-and-start"
    if nightly:
        return "keep"
    return "start-nightly"


def render_findings(findings: list[Finding]) -> str:
    lines: list[str] = []
    for level, title in (
        ("error", "errors"),
        ("warning", "warnings"),
        ("info", "notes"),
    ):
        rows = [item for item in findings if item.level == level]
        if not rows:
            if level != "info":
                lines.append(f"{title}: none")
            continue
        lines.append(f"{title} ({len(rows)}):")
        for item in rows:
            lines.append(f"  {item.message}")
    if any(item.code == "sudo" and item.level == "error" for item in findings):
        lines.append(SUDO_NAG)
    if any(item.code == "profile" and item.level == "error" for item in findings):
        lines.append(PROFILE_NAG)
    return "\n".join(lines)


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


_disabled_cache: dict[str, str] = {}


def clear_probe_cache() -> None:
    _disabled_cache.clear()


def is_disabled(domain: str, label: str) -> bool:
    blob = _disabled_cache.get(domain)
    if blob is None:
        try:
            result = _run(["launchctl", "print-disabled", domain])
            blob = result.stdout
        except (OSError, subprocess.TimeoutExpired):
            blob = ""
        _disabled_cache[domain] = blob
    needle_disabled = f'"{label}" => disabled'
    needle_true = f'"{label}" => true'
    return needle_disabled in blob or needle_true in blob


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
        print(SUDO_NAG, file=sys.stderr)
        maybe_notify_sudo()
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


def _write_if_changed(path: Path, data: bytes, mode: int | None = None) -> bool:
    """Write data only when the bytes differ. Returns True when the file changed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    changed = not (path.is_file() and path.read_bytes() == data)
    if changed:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
    if mode is not None and stat.S_IMODE(path.stat().st_mode) != mode:
        os.chmod(path, mode)
        changed = True
    return changed


def installed_version() -> str | None:
    path = libexec_dir() / "VERSION"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def brew_exe() -> str | None:
    for candidate in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("brew")
    return found or None


def plocate_db_path() -> Path:
    brew = brew_exe() or ""
    if brew.startswith("/usr/local/"):
        return Path("/usr/local/var/lib/plocate/plocate.db")
    return Path("/opt/homebrew/var/lib/plocate/plocate.db")


def loaded_plocate_nightly() -> str | None:
    """A nightly that already rebuilds the plocate db. Do not add a second one."""
    uid = os.getuid()
    domains = [f"gui/{uid}", f"user/{uid}", "system"]
    for label in PLOCATE_NIGHTLY_LABELS:
        for domain in domains:
            try:
                result = _run(["launchctl", "print", f"{domain}/{label}"])
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0:
                return f"{domain}/{label}"
    return None


def neofinder_app_installed() -> bool:
    home = home_dir()
    return (
        Path("/Applications/NeoFinder.app").is_dir()
        or (home / "Applications/NeoFinder.app").is_dir()
    )


def _profiles_list_blob(argv: list[str]) -> tuple[int, str] | None:
    try:
        result = _run(argv, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def intelligence_profile_installed() -> bool | None:
    """True, False, or None when the computer-level list cannot be read.

    An unprivileged `profiles list` does not show a System-scope profile.
    The sudoers file allows exactly `/usr/bin/profiles list` with no password.
    A failed `sudo -n` means we cannot say, so doctor does not treat that as
    a missing profile.
    """
    user = _profiles_list_blob(["/usr/bin/profiles", "list"])
    if user is not None and user[0] == 0 and PROFILE_ID in user[1]:
        return True
    if os.geteuid() == 0:
        if user is None or user[0] != 0:
            return None
        return PROFILE_ID in user[1]
    root = _profiles_list_blob(["sudo", "-n", "/usr/bin/profiles", "list"])
    if root is None or root[0] != 0:
        return None
    return PROFILE_ID in root[1]


def ensure_intelligence_profile() -> int:
    """Open the profile and wait while the person installs it in System Settings.

    QUIET_MAC_HOME is the test redirect. It must not open System Settings.
    QUIET_MAC_NO_WAIT prints the steps and returns without waiting.
    """
    if os.environ.get("QUIET_MAC_HOME"):
        return 0
    state = intelligence_profile_installed()
    if state is True:
        print("Apple Intelligence profile: already installed")
        return 0
    path = profile_mobileconfig_path()
    if not path.is_file():
        print(f"profile file missing: {path}", file=sys.stderr)
        return 1
    location = profiles_settings_location(macos_version())
    print(profile_install_steps(location))
    _run(["open", str(path)])
    _run(["open", PROFILE_SETTINGS_URL])
    if state is None:
        print(
            "profile: this run cannot confirm the install yet. `sudo -n profiles list`\n"
            "starts working once the root helper's sudoers file includes it.\n"
            "Finish the System Settings steps, then run just install again.",
            file=sys.stderr,
        )
        return 1
    if os.environ.get("QUIET_MAC_NO_WAIT"):
        print(
            "profile: not installed yet. Finish the steps, then run just install again.",
            file=sys.stderr,
        )
        return 1
    print("profile: waiting until it shows up in `profiles list` (about 8 minutes).")
    deadline = time.time() + PROFILE_WAIT_S
    next_note = time.time() + 30
    while time.time() < deadline:
        if intelligence_profile_installed() is True:
            print("Apple Intelligence profile: installed")
            return 0
        if time.time() >= next_note:
            print(f"profile: still waiting. System Settings → {location}, Downloaded.")
            next_note = time.time() + 30
        time.sleep(2)
    print(
        "profile: still not installed. The downloaded profile expires after about\n"
        "8 minutes. Run just install again and finish the steps.",
        file=sys.stderr,
    )
    return 1


def recent_log_hits(limit: int = 5) -> list[str]:
    hits: list[str] = []
    for name in ("enforce.log", "thaw.log"):
        path = logs_dir() / name
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines[-80:]:
            if "failed" in line.lower():
                hits.append(f"{name}: {line[-180:]}")
    return hits[-limit:]


def maybe_notify_sudo() -> None:
    """One notification per six hours. Tests and snapshots set QUIET_MAC_HOME."""
    if os.environ.get("QUIET_MAC_NO_NOTIFY") or os.environ.get("QUIET_MAC_HOME"):
        return
    path = state_dir() / "sudo-nag"
    now = time.time()
    try:
        if path.is_file() and now - path.stat().st_mtime < NAG_INTERVAL_S:
            return
        state_dir().mkdir(parents=True, exist_ok=True)
        path.write_text(str(int(now)), encoding="utf-8")
    except OSError:
        return
    _run(
        [
            "osascript",
            "-e",
            (
                "display notification "
                '"System flags still need an admin click. Run: just doctor" '
                'with title "quiet-mac"'
            ),
        ]
    )


def maybe_notify_profile() -> None:
    """One notification per six hours until the Apple Intelligence profile is in."""
    if os.environ.get("QUIET_MAC_NO_NOTIFY") or os.environ.get("QUIET_MAC_HOME"):
        return
    path = state_dir() / "profile-nag"
    now = time.time()
    try:
        if path.is_file() and now - path.stat().st_mtime < NAG_INTERVAL_S:
            return
        state_dir().mkdir(parents=True, exist_ok=True)
        path.write_text(str(int(now)), encoding="utf-8")
    except OSError:
        return
    _run(
        [
            "osascript",
            "-e",
            (
                "display notification "
                '"Apple Intelligence profile still needs a click in System Settings. '
                'Run: just install" with title "quiet-mac"'
            ),
        ]
    )


def policy_findings(uid: int | None) -> list[Finding]:
    clear_probe_cache()
    if uid is None:
        return [Finding("error", "console", "no console user")]
    if uid != os.getuid():
        return [Finding("error", "console", "not the console user")]
    out: list[Finding] = []
    for job in load_policy():
        live = probe(domain_name(job, uid), job.label)
        found = problem(job, live)
        if not found:
            continue
        code = "regression"
        if job.domain == "system" and (
            not live.disabled or found.startswith("running unfrozen")
        ):
            code = "sudo"
        out.append(Finding("error", code, found))
    home = home_dir()
    when = dt.datetime.now()
    commands = command_lines()
    lock_path = home / "Library/Application Support/neofinder-stub-export/nightly.lock"
    if indexing_enabled() and not skip_indexing_off(
        home, when, lock_held(lock_path), commands
    ):
        out.append(Finding("error", "spotlight", "Spotlight indexing is enabled"))
    for rel in SEMANTIC_STORES:
        root = home / rel
        try:
            size = store_size(root)
        except OSError:
            continue
        if size > STORE_CAP_BYTES:
            mib = size // (1024 * 1024)
            out.append(
                Finding(
                    "error",
                    "stores",
                    f"semantic store {mib} MiB: ~/{rel} (just empty-stores)",
                )
            )
    return out


def infra_findings() -> list[Finding]:
    out: list[Finding] = []
    installed = installed_version()
    relation = version_relation(installed)
    if relation == "missing":
        out.append(
            Finding(
                "warning",
                "version",
                f"quiet-mac {VERSION} is not installed (just install)",
            )
        )
    elif relation == "older":
        out.append(
            Finding(
                "warning",
                "version",
                f"installed {installed} is older than {VERSION} (just upgrade)",
            )
        )
    elif relation == "newer":
        out.append(
            Finding(
                "warning",
                "version",
                f"installed {installed} is newer than this checkout {VERSION}",
            )
        )
    elif relation == "invalid":
        out.append(
            Finding(
                "warning", "version", f"installed version {installed!r} is unreadable"
            )
        )
    else:
        out.append(Finding("info", "version", f"version {VERSION}"))

    brew = brew_exe()
    if not brew:
        out.append(
            Finding(
                "error",
                "brew",
                "Homebrew is required and was not found. Install it from https://brew.sh",
            )
        )
    else:
        out.append(Finding("info", "brew", f"Homebrew: {brew}"))

    binary = shutil.which("plocate")
    nightly = loaded_plocate_nightly()
    if not binary:
        out.append(
            Finding(
                "error",
                "plocate",
                "plocate is required and is not on PATH (just install)",
            )
        )
    else:
        out.append(
            Finding(
                "info",
                "plocate",
                f"plocate: {binary}  (filename search: plocate -i NAME)",
            )
        )
    if nightly:
        out.append(Finding("info", "plocate-nightly", f"plocate nightly: {nightly}"))
    else:
        out.append(
            Finding(
                "error",
                "plocate-nightly",
                "plocate has no nightly service (just install starts the brew one)",
            )
        )
    database = plocate_db_path()
    if binary and not database.exists():
        out.append(
            Finding("error", "plocate-db", f"plocate database missing: {database}")
        )
    elif binary:
        age_h = (time.time() - database.stat().st_mtime) / 3600
        message = f"plocate database is {age_h:.0f}h old: {database}"
        if age_h > PLOCATE_DB_MAX_AGE_H:
            out.append(Finding("warning", "plocate-db", message))
        else:
            out.append(Finding("info", "plocate-db", message))

    uid = console_uid()
    if uid == os.getuid():
        if not thaw_available(uid):
            out.append(
                Finding("error", "thaw", "no shutdown thaw is loaded (just install)")
            )
        else:
            which = LABEL_THAW if agent_loaded(LABEL_THAW, uid) else SITE_THAW
            out.append(Finding("info", "thaw", f"thaw: {which}"))
        if agent_loaded(LABEL_ENFORCE, uid):
            out.append(
                Finding(
                    "info", "watchdog", "60s watchdog is loaded (com.quiet-mac.enforce)"
                )
            )
        else:
            out.append(
                Finding(
                    "error",
                    "watchdog",
                    "60s watchdog is not loaded (just install)",
                )
            )
    if HELPER.is_file():
        out.append(Finding("info", "root", f"root helper: {HELPER}"))
    else:
        out.append(
            Finding(
                "error",
                "sudo",
                f"root helper missing: {HELPER} (just install)",
            )
        )

    profile = intelligence_profile_installed()
    if profile is True:
        out.append(
            Finding("info", "profile", "Apple Intelligence profile is installed")
        )
    elif profile is False:
        out.append(
            Finding(
                "error",
                "profile",
                "Apple Intelligence profile is not installed (just install)",
            )
        )
    else:
        # sudo -n profiles list is what can see a System-scope profile. Until the
        # sudoers file allows that command, absence is not evidence.
        out.append(
            Finding(
                "info",
                "profile",
                "computer-level profiles are not visible yet. just install allows "
                "`profiles list` with no password, then opens the Apple Intelligence profile.",
            )
        )

    if neofinder_app_installed():
        out.append(
            Finding(
                "info",
                "neofinder",
                "NeoFinder.app is installed. Catalogue search: just neofinder-status",
            )
        )
    else:
        out.append(
            Finding(
                "info",
                "neofinder",
                "NeoFinder is not installed (optional). Filename search: plocate -i NAME",
            )
        )
    for hit in recent_log_hits():
        out.append(Finding("warning", "log", hit))
    try:
        result = _run(["csrutil", "status"], timeout=10)
        text = ((result.stdout or "") + (result.stderr or "")).strip()
        line = text.splitlines()[0] if text else "csrutil status unknown"
    except (OSError, subprocess.TimeoutExpired):
        line = "csrutil status failed"
    out.append(Finding("info", "sip", line))
    return out


def ensure_plocate() -> int:
    """Install plocate and a nightly brew service, unless a nightly already runs."""
    brew = brew_exe()
    nightly = loaded_plocate_nightly()
    plan = plocate_plan(bool(shutil.which("plocate")), nightly, bool(brew))
    if plan == "need-brew":
        print(
            "plocate: Homebrew is required and was not found.",
            file=sys.stderr,
        )
        return 1
    if plan == "keep":
        print(f"plocate: already installed; nightly already loaded ({nightly})")
        return 0
    if plan in ("install-and-start", "install-only"):
        print("plocate: installing with Homebrew")
        if not brew:
            return 1
        try:
            result = subprocess.run(
                [brew, "install", "plocate"], text=True, check=False, timeout=900
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"plocate: brew install failed: {exc}", file=sys.stderr)
            return 1
        if result.returncode != 0:
            print(
                "plocate: brew install plocate failed; tapping ylluminate/utilities",
                file=sys.stderr,
            )
            tap = subprocess.run(
                [brew, "tap", "ylluminate/utilities"],
                text=True,
                check=False,
                timeout=180,
            )
            if tap.returncode != 0:
                return tap.returncode or 1
            result = subprocess.run(
                [brew, "install", "ylluminate/utilities/plocate"],
                text=True,
                check=False,
                timeout=900,
            )
            if result.returncode != 0:
                return result.returncode or 1
    if plan == "install-only":
        print(f"plocate: binary installed; leaving the existing nightly ({nightly})")
        return 0
    print(
        "plocate: starting the Homebrew nightly (an administrator dialog).\n"
        "It rebuilds the filename index about once a day. Search: plocate -i NAME"
    )
    if not brew:
        return 1
    result = subprocess.run(
        [*_sudo_prefix(), brew, "services", "start", "plocate"],
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print("plocate: brew services start plocate failed", file=sys.stderr)
        return result.returncode or 1
    print("plocate: brew service started")
    return 0


def sudoers_is_current(text: str | None, profiles_allowed: bool, user: str) -> bool:
    """True when sudoers matches this tree.

    text is None when the file cannot be read (mode 0440). An unreadable file
    is current only when `sudo -n /usr/bin/profiles list` is already allowed.
    Treating "unreadable" as "current" hid the new profiles command.
    """
    if text is None:
        return profiles_allowed
    try:
        return text == sudoers_text(user)
    except ValueError:
        return False


def _sudo_profiles_list_allowed() -> bool:
    try:
        result = _run(["sudo", "-n", "/usr/bin/profiles", "list"], timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def root_kit_current(user: str) -> bool:
    """True when the root helper, its policy, and the sudoers file match this tree."""
    source = Path(__file__).resolve().parent
    try:
        script = (source / "quiet-mac-root.sh").read_bytes()
        policy = (source / "daemons.tsv").read_bytes()
    except OSError:
        return False
    for path in (HELPER, HELPER_REVERT):
        try:
            if not path.is_file() or path.read_bytes() != script:
                return False
        except OSError:
            return False
    policy_dest = ROOT_LIB / "daemons.tsv"
    try:
        if not policy_dest.is_file() or policy_dest.read_bytes() != policy:
            return False
    except OSError:
        return False
    if not SUDOERS.exists():
        return False
    try:
        current: str | None = SUDOERS.read_text(encoding="utf-8")
    except OSError:
        current = None
    return sudoers_is_current(current, _sudo_profiles_list_allowed(), user)


def cmd_check() -> int:
    uid = console_uid()
    if uid is None:
        return 0
    findings = [item for item in policy_findings(uid) if item.level == "error"]
    if not findings:
        return 0
    print(f"quiet-mac: {len(findings)} problem(s)")
    for item in findings:
        print(f"  {item.message}")
    if any(item.code == "sudo" for item in findings):
        print(SUDO_NAG)
        maybe_notify_sudo()
    else:
        print("Fix: just enforce")
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
    findings = [
        item
        for item in policy_findings(uid) + infra_findings()
        if item.level in ("error", "warning")
    ]
    print(render_findings(findings))
    if any(item.code == "sudo" for item in findings):
        maybe_notify_sudo()
    if any(item.code == "profile" for item in findings):
        maybe_notify_profile()
    return 1 if any(item.level == "error" for item in findings) else 0


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


def prepare_user_files(python: str) -> tuple[Path, Path, bool, bool]:
    """Copy the kit into ~/.local. The bools say whether each agent must reload.

    A second call with the same bytes changes nothing, including mtime.
    """
    source = Path(__file__).resolve().parent
    dest = libexec_dir()
    dest.mkdir(parents=True, exist_ok=True)
    kit_changed = _write_if_changed(
        dest / "VERSION", (VERSION + "\n").encode("utf-8"), 0o644
    )
    modes = {
        "quiet_mac.py": 0o755,
        "daemons.tsv": 0o644,
        "quiet-mac-root.sh": 0o755,
    }
    for name, mode in modes.items():
        if _write_if_changed(dest / name, (source / name).read_bytes(), mode):
            kit_changed = True
    profile_src = (
        source.parent / "no-apple-intelligence" / "no-apple-intelligence.mobileconfig"
    )
    if profile_src.is_file():
        _write_if_changed(
            dest / "no-apple-intelligence.mobileconfig",
            profile_src.read_bytes(),
            0o644,
        )
    logs = logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    home = home_dir()
    script = str(dest / "quiet_mac.py")
    enforce = agents_dir() / f"{LABEL_ENFORCE}.plist"
    thaw = agents_dir() / f"{LABEL_THAW}.plist"
    enforce_changed = _write_if_changed(
        enforce,
        plistlib.dumps(enforce_plist(python, script, home, logs), fmt=plistlib.FMT_XML),
        0o644,
    )
    thaw_changed = _write_if_changed(
        thaw,
        plistlib.dumps(thaw_plist(python, script, home, logs), fmt=plistlib.FMT_XML),
        0o644,
    )
    return (
        enforce,
        thaw,
        enforce_changed or kit_changed,
        thaw_changed or kit_changed,
    )


def ensure_agent(label: str, plist: Path, changed: bool) -> str:
    """Bootstrap only when the plist changed or the agent is not loaded."""
    if not changed and agent_loaded(label):
        return "unchanged"
    reload_agent(label, plist)
    return "loaded"


def reload_agent(label: str, plist: Path) -> None:
    """Boot out and bootstrap one agent.

    A KeepAlive job often answers the immediate bootstrap with
    "Bootstrap failed: 5: Input/output error" because launchd has not
    finished the bootout. Retry; if it is already loaded, that is success.
    """
    uid = os.getuid()
    target = f"gui/{uid}/{label}"
    domain = f"gui/{uid}"
    _run(["launchctl", "bootout", target])
    _run(["launchctl", "enable", target])
    last = ""
    for attempt in range(6):
        if attempt:
            time.sleep(0.5)
        result = _run(["launchctl", "bootstrap", domain, str(plist)])
        if result.returncode == 0 or agent_loaded(label, uid):
            _run(["launchctl", "enable", target])
            return
        last = (result.stderr or result.stdout).strip()
    raise SystemExit(f"launchctl bootstrap {label} failed: {last}")


def bootout_agent(label: str) -> None:
    uid = os.getuid()
    _run(["launchctl", "bootout", f"gui/{uid}/{label}"])
    plist = agents_dir() / f"{label}.plist"
    if plist.exists():
        plist.unlink()


def _sudo_prefix(fresh: bool = False) -> list[str]:
    cmd = ["sudo-ask"] if shutil.which("sudo-ask") else ["sudo"]
    if fresh:
        cmd.append("-k")
    return cmd


def install_root_as_root(user: str) -> int:
    if os.geteuid() != 0:
        print("quiet-mac: --install-root must run as root", file=sys.stderr)
        return 1
    if not user:
        print("quiet-mac: --install-root needs --user", file=sys.stderr)
        return 1
    if root_kit_current(user):
        print(f"root helper already matches this tree for {user}")
        return 0
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
    if not brew_exe():
        print(
            "install: Homebrew is required. Install it from https://brew.sh "
            "and run this again.",
            file=sys.stderr,
        )
        return 1
    print("snapshot before install:")
    cmd_snapshot()
    print(
        "quiet-mac disables iCloud (cloudd), Photos analysis, Spotlight semantic\n"
        "search, Siri, Shortcuts, widgets, Weather, Screen Time, AirDrop, Handoff\n"
        "and Contacts. BiomeAgent is left running so sudo can still prompt.\n"
        "A shutdown thaw is installed with the freezer; without it, reboot stalls.\n"
        "CoreSpotlight semantic caches are emptied on install, even under 50 MiB.\n"
        "The on-disk file index is not touched.\n"
        "The Apple Intelligence profile is opened at the end. macOS makes you\n"
        "approve that one in System Settings."
    )
    if agent_loaded(SITE_THAW, uid):
        print(
            "This Mac already has the site shutdown thaw. quiet-mac adds its own\n"
            "60s fixer beside it. Both are safe to run; the site one is enough if\n"
            "you only wanted the thaw."
        )
    failed = ensure_plocate() != 0
    python = agent_python()
    enforce_plist_path, thaw_plist_path, enforce_changed, thaw_changed = (
        prepare_user_files(python)
    )
    print(f"thaw: {ensure_agent(LABEL_THAW, thaw_plist_path, thaw_changed)}")
    user = _current_user()
    root_rc = 0
    if root_kit_current(user):
        print("root helper: already installed")
    else:
        print(
            "root helper: a dialog will ask to install it. Click Allow.\n"
            "Touch ID works. Enter and Esc do not decide."
        )
        root = subprocess.run(
            [
                *_sudo_prefix(fresh=True),
                python,
                str(Path(__file__).resolve()),
                "--install-root",
                "--user",
                user,
            ],
            text=True,
            check=False,
        )
        root_rc = root.returncode
        if root_rc != 0:
            print(
                "root install did not finish. The user half stays installed.",
                file=sys.stderr,
            )
            failed = True
    # B5: system-domain flags. sudo -n works after the sudoers file is in place.
    if HELPER.is_file():
        flag_rc, flag_out = run_root_helper(revert=False)
        if flag_out:
            print(flag_out)
        if flag_rc != 0:
            print(f"system flags: {flag_out or 'root helper failed'}", file=sys.stderr)
            failed = True
    else:
        failed = True
    when = dt.datetime.now()
    commands = command_lines()
    lock_path = (
        home_dir() / "Library/Application Support/neofinder-stub-export/nightly.lock"
    )
    indexing_blocked = indexing_enabled() and not skip_indexing_off(
        home_dir(), when, lock_held(lock_path), commands
    )
    if indexing_blocked and not indexing_off():
        print("Spotlight indexing is still enabled", file=sys.stderr)
        failed = True
    print(
        f"enforce: {ensure_agent(LABEL_ENFORCE, enforce_plist_path, enforce_changed)}"
    )
    # B2: empty the semantic caches on every install, even under the cap.
    # A second install deletes nothing when the directories are already empty.
    cmd_empty_stores(only_over=None, quiet_ok=True)
    if failed:
        print(SUDO_NAG, file=sys.stderr)
        maybe_notify_sudo()
    profile_rc = ensure_intelligence_profile()
    if profile_rc != 0:
        print(PROFILE_NAG, file=sys.stderr)
        maybe_notify_profile()
        failed = True
    if failed:
        print("install: finished with errors. just doctor lists them.", file=sys.stderr)
        return 1
    print(
        f"install: quiet-mac {VERSION}. A second run changes nothing already applied."
    )
    return 0


def cmd_upgrade() -> int:
    installed = installed_version()
    relation = version_relation(installed)
    if relation == "newer":
        print(
            f"installed {installed} is newer than this checkout ({VERSION}). "
            "Refusing to downgrade."
        )
        return 1
    if relation == "older":
        print(f"upgrading {installed} -> {VERSION}")
    elif relation == "missing":
        print(f"nothing installed; installing {VERSION}")
    else:
        print(f"quiet-mac {VERSION} is current; install will only repair drift")
    return cmd_install()


def cmd_system_flags() -> int:
    """Set the system-domain disable flags. This is the step that needs root."""
    if not HELPER.is_file():
        print(SUDO_NAG)
        maybe_notify_sudo()
        return 1
    rc, out = run_root_helper(False)
    if rc != 0:
        print(out or "sudo -n failed; asking with a dialog")
        asked = subprocess.run([*_sudo_prefix(), str(HELPER)], text=True, check=False)
        rc = asked.returncode
        if asked.stdout:
            print(asked.stdout.strip())
        if asked.stderr:
            print(asked.stderr.strip(), file=sys.stderr)
    elif out:
        print(out)
    clear_probe_cache()
    missing = [
        job.label
        for job in load_policy()
        if job.domain == "system" and not is_disabled("system", job.label)
    ]
    if missing or rc != 0:
        print(f"system flags still unset: {len(missing)}")
        for label in missing:
            print(f"  {label}")
        print(SUDO_NAG)
        maybe_notify_sudo()
        return 1
    count = sum(1 for job in load_policy() if job.domain == "system")
    print(f"system flags: set ({count} labels)")
    return 0


def cmd_doctor(notify: bool = True) -> int:
    print(f"quiet-mac {VERSION}")
    findings = policy_findings(console_uid()) + infra_findings()
    print(render_findings(findings))
    if notify:
        if any(item.code == "sudo" and item.level == "error" for item in findings):
            maybe_notify_sudo()
        if any(item.code == "profile" and item.level == "error" for item in findings):
            maybe_notify_profile()
    return 1 if any(item.level == "error" for item in findings) else 0


def cmd_recovery() -> int:
    print(recovery_text(silicon_kind(platform.machine())))
    return 0


def cmd_profile() -> int:
    """Print the System Settings steps and open the profile. install waits."""
    path = profile_mobileconfig_path()
    if not path.is_file():
        print(f"profile file missing: {path}", file=sys.stderr)
        return 1
    print(profile_install_steps(profiles_settings_location(macos_version())))
    if os.environ.get("QUIET_MAC_HOME"):
        return 0
    _run(["open", str(path)])
    _run(["open", PROFILE_SETTINGS_URL])
    return 0


def cmd_snapshot() -> int:
    """Record status and doctor. Does not change the Mac, and does not notify."""
    directory = state_dir() / "snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = directory / f"{stamp}.txt"
    import io

    buf = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    previous = os.environ.get("QUIET_MAC_NO_NOTIFY")
    os.environ["QUIET_MAC_NO_NOTIFY"] = "1"
    sys.stdout = buf
    sys.stderr = buf
    try:
        cmd_status()
        buf.write("\n# doctor\n")
        cmd_doctor(notify=False)
    finally:
        sys.stdout = old_out
        sys.stderr = old_err
        if previous is None:
            os.environ.pop("QUIET_MAC_NO_NOTIFY", None)
        else:
            os.environ["QUIET_MAC_NO_NOTIFY"] = previous
    path.write_text(buf.getvalue(), encoding="utf-8")
    print(path)
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
            *_sudo_prefix(fresh=True),
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


def pause_site_apple_daemons() -> str:
    """Stop the site watchdog re-freezing Apple daemons on its next pass.

    The file is machine-local, under ~/.config, not this repo. A later
    site deploy can write enabled = true again.
    """
    path = Path.home() / ".config/djbclark/watchdogd.d/apple-daemons.toml"
    if not path.is_file():
        return "no site apple-daemons rule"
    text = path.read_text(encoding="utf-8")
    new, note = disable_toml_service(text, "apple-daemons")
    if note == "already":
        return f"site apple-daemons already disabled ({path})"
    path.write_text(new, encoding="utf-8")
    return (
        f"site apple-daemons disabled ({path}). "
        "watchdogd reads that on its next pass. A later site deploy can turn it back on."
    )


def continue_stopped_user() -> int:
    """SIGCONT every stopped process of this user. Does not terminate them."""
    try:
        result = _run(
            ["ps", "-axo", "pid=,stat=,comm=", "-U", str(os.getuid())], timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"ps failed: {exc}", file=sys.stderr)
        return 0
    continued = 0
    for pid, _proc_stat, comm in stopped_from_ps(result.stdout):
        if pid == os.getpid():
            continue
        if _signal(pid, signal.SIGCONT):
            print(f"continued pid {pid} {comm}")
            continued += 1
    return continued


def factory_as_root() -> int:
    """Enable system flags, turn Spotlight indexing on, remove our profile."""
    if os.geteuid() != 0:
        print("quiet-mac: --factory-root must run as root", file=sys.stderr)
        return 1
    for job in load_policy():
        if job.domain != "system":
            continue
        _run(["launchctl", "enable", f"system/{job.label}"])
        print(f"enable system/{job.label}")
    indexing = subprocess.run(
        ["/usr/bin/mdutil", "-a", "-i", "on"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    detail = (indexing.stdout or indexing.stderr).strip()
    if detail:
        print(detail)
    if indexing.returncode != 0:
        print("Spotlight indexing could not be turned on", file=sys.stderr)
        return indexing.returncode or 1
    print("Spotlight indexing: on")
    removed = subprocess.run(
        [
            "profiles",
            "remove",
            "-type",
            "configuration",
            "-identifier",
            PROFILE_ID,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    blob = (removed.stdout or "") + (removed.stderr or "")
    if removed.returncode == 0:
        print(f"profile: removed {PROFILE_ID}")
    else:
        print(
            "profile: not removed by the command"
            + (f" ({blob.strip()})" if blob.strip() else "")
        )
        location = profiles_settings_location(macos_version())
        print(
            "If it is still installed, delete it in System Settings → "
            f"{location}. The payload id is {PROFILE_ID}."
        )
    return 0


def cmd_factory() -> int:
    """Restore Apple's shipping daemon and Spotlight behavior.

    plocate, NeoFinder, and Homebrew stay installed. Emptied semantic
    caches are left for Apple to rebuild.
    """
    uid = console_uid()
    if uid is None or uid != os.getuid():
        print(
            "factory: log in at the console and run this as that user",
            file=sys.stderr,
        )
        return 1
    print(
        "factory restores Apple's shipping daemons and Spotlight indexing.\n"
        "plocate, NeoFinder, and Homebrew stay installed.\n"
        "Emptied CoreSpotlight caches are not put back; Apple rebuilds them.\n"
        "The site shutdown thaw stays, so a leftover stopped process cannot\n"
        "stall the next reboot."
    )
    print(pause_site_apple_daemons())
    bootout_agent(LABEL_ENFORCE)
    _enable_user(uid)
    continued = continue_stopped_user()
    print(f"continued {continued} stopped process(es)")
    print(
        "factory: a dialog will ask to enable the system daemons, turn\n"
        "Spotlight indexing on, and remove the Apple Intelligence profile.\n"
        "Click Allow. Touch ID works. Enter and Esc do not decide."
    )
    root = subprocess.run(
        [
            *_sudo_prefix(),
            agent_python(),
            str(Path(__file__).resolve()),
            "--factory-root",
        ],
        text=True,
        check=False,
    )
    bootout_agent(LABEL_THAW)
    remove_root_files()
    print(
        "factory: quiet-mac agents removed. Disable flags were enabled.\n"
        "File name search is still: plocate -i NAME"
    )
    return 0 if root.returncode == 0 else root.returncode


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
        (pid, proc_stat, comm)
        for pid, proc_stat, comm in stopped_from_ps(result.stdout)
        if pid != os.getpid()
    ]
    for pid, proc_stat, comm in rows:
        _signal(pid, signal.SIGCONT)
        _signal(pid, signal.SIGTERM)
        log_line("thaw.log", f"CONT+TERM {pid} {comm} (was {proc_stat})")
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
    if len(argv) >= 2 and argv[1] == "--factory-root":
        return factory_as_root()
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
    if cmd == "upgrade":
        return cmd_upgrade()
    if cmd == "doctor":
        return cmd_doctor()
    if cmd == "system-flags":
        return cmd_system_flags()
    if cmd == "recovery":
        return cmd_recovery()
    if cmd == "profile":
        return cmd_profile()
    if cmd == "snapshot":
        return cmd_snapshot()
    if cmd == "revert":
        return cmd_revert()
    if cmd == "factory":
        return cmd_factory()
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
