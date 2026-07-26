#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Serialize coordinated ops release cut and deploy work.

Two layers:

1. **Exclusive flock** (`ops-release.lock`) — held for the duration of one
   mutating command (deploy, check-with-side-effects, claim write). Same
   fcntl semantics as ``bin/brew_flock.py`` (macOS has no util-linux flock).

2. **Claim file** (`ops-release.claim.json`) — multi-step reservation so two
   agents do not cut/deploy different versions at the same time. Survives
   across several shell commands. Stale if the holder PID is dead or the
   claim is older than ``--stale-after`` (default 2h).

Usage examples:

  bin/ops_release_lock.py claim status
  bin/ops_release_lock.py claim begin 1.0.2 --operation cut
  bin/ops_release_lock.py hold -- just ops-release-deploy 1.0.2
  bin/ops_release_lock.py claim end

  # deploy_ops_release.py acquires the flock automatically for check/deploy.

Exit codes:
  0   success
  75  lock or claim busy (EX_TEMPFAIL)
  124 timed out waiting for flock
  2   usage error
  other child exit status / 127 if command not found
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EX_TEMPFAIL = 75
EX_TIMEOUT = 124
CLAIM_SCHEMA = 1
DEFAULT_STALE_AFTER = 2 * 60 * 60  # 2 hours
VALID_OPERATIONS = frozenset({"cut", "deploy", "hold"})


def default_state_dir() -> Path:
    if env := os.environ.get("SITE_OPS_RELEASE_STATE"):
        return Path(env).expanduser()
    if xdg_state := os.environ.get("XDG_STATE_HOME"):
        return Path(xdg_state) / "site-djbclark"
    return Path.home() / ".local" / "state" / "site-djbclark"


def lock_path(state_dir: Path | None = None) -> Path:
    if env := os.environ.get("SITE_OPS_RELEASE_LOCK"):
        return Path(env).expanduser()
    return (state_dir or default_state_dir()) / "ops-release.lock"


def claim_path(state_dir: Path | None = None) -> Path:
    if env := os.environ.get("SITE_OPS_RELEASE_CLAIM"):
        return Path(env).expanduser()
    return (state_dir or default_state_dir()) / "ops-release.claim.json"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass(frozen=True)
class Claim:
    version: str
    operation: str
    pid: int
    hostname: str
    holder: str
    started_at: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CLAIM_SCHEMA,
            "version": self.version,
            "operation": self.operation,
            "pid": self.pid,
            "hostname": self.hostname,
            "holder": self.holder,
            "started_at": self.started_at,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Claim:
        return cls(
            version=str(data["version"]),
            operation=str(data["operation"]),
            pid=int(data["pid"]),
            hostname=str(data.get("hostname") or ""),
            holder=str(data.get("holder") or ""),
            started_at=str(data["started_at"]),
            note=str(data.get("note") or ""),
        )


def read_claim(path: Path) -> Claim | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != CLAIM_SCHEMA:
        return None
    try:
        return Claim.from_dict(data)
    except (KeyError, TypeError, ValueError):
        return None


def write_claim(path: Path, claim: Claim) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = json.dumps(claim.to_dict(), indent=2, sort_keys=True) + "\n"
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(payload, encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def clear_claim(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def claim_is_stale(claim: Claim, *, stale_after: float) -> tuple[bool, str]:
    """Age-based staleness only.

    Claims outlive the short-lived ``claim begin`` CLI process, so a dead
    holder PID is normal and must not free the reservation. Crashed agents
    clear with ``claim end --force`` or wait until ``stale_after``.
    """
    try:
        age = (utc_now() - parse_iso(claim.started_at)).total_seconds()
    except ValueError:
        return True, "claim started_at is unparseable"
    if age > stale_after:
        return True, f"claim age {int(age)}s exceeds stale-after {int(stale_after)}s"
    return False, ""


def format_claim(claim: Claim) -> str:
    return (
        f"version={claim.version} operation={claim.operation} "
        f"pid={claim.pid} host={claim.hostname or '-'} "
        f"holder={claim.holder or '-'} started={claim.started_at}"
        + (f" note={claim.note!r}" if claim.note else "")
    )


class LockError(RuntimeError):
    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def acquire_flock(
    lock_fd: int,
    path: Path,
    *,
    nonblock: bool,
    timeout: float | None,
) -> None:
    if nonblock:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise LockError(
                    f"ops-release lock held ({path}); another release/deploy is in progress",
                    EX_TEMPFAIL,
                ) from exc
            raise
        return

    if timeout is None:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            print(
                f"ops_release_lock: waiting for exclusive lock ({path})…",
                file=sys.stderr,
            )
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            return

    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            if time.monotonic() >= deadline:
                raise LockError(
                    f"timed out after {timeout}s waiting for ops-release lock",
                    EX_TIMEOUT,
                ) from exc
            time.sleep(0.1)


def open_lock(path: Path) -> int:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags, 0o600)


def record_holder(lock_fd: int, text: str) -> None:
    try:
        os.ftruncate(lock_fd, 0)
        os.lseek(lock_fd, 0, os.SEEK_SET)
        os.write(lock_fd, (text + "\n").encode())
    except OSError:
        pass


def with_flock(
    *,
    nonblock: bool = False,
    timeout: float | None = None,
    state_dir: Path | None = None,
    holder_note: str = "",
):
    """Context manager alternative via generator used by command handlers."""

    class _Guard:
        def __init__(self) -> None:
            self.path = lock_path(state_dir)
            self.fd = -1

        def __enter__(self) -> Path:
            self.fd = open_lock(self.path)
            try:
                acquire_flock(
                    self.fd, self.path, nonblock=nonblock, timeout=timeout
                )
            except Exception:
                os.close(self.fd)
                self.fd = -1
                raise
            record_holder(
                self.fd,
                f"pid={os.getpid()} host={socket.gethostname()} {holder_note}".strip(),
            )
            return self.path

        def __exit__(self, *exc: object) -> None:
            if self.fd >= 0:
                try:
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                os.close(self.fd)
                self.fd = -1

    return _Guard()


def cmd_hold(args: argparse.Namespace) -> int:
    cmd = list(args.command)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("ops_release_lock: hold requires a command after --", file=sys.stderr)
        return 2
    try:
        with with_flock(
            nonblock=args.nonblock,
            timeout=args.timeout,
            holder_note=f"cmd={' '.join(cmd)}",
        ):
            try:
                proc = subprocess.run(cmd, check=False)
            except FileNotFoundError:
                print(f"ops_release_lock: command not found: {cmd[0]}", file=sys.stderr)
                return 127
            return int(proc.returncode)
    except LockError as exc:
        print(f"ops_release_lock: {exc}", file=sys.stderr)
        return exc.code


def cmd_claim_status(args: argparse.Namespace) -> int:
    path = claim_path()
    claim = read_claim(path)
    if claim is None:
        print("claim: none")
        return 0
    stale, reason = claim_is_stale(claim, stale_after=args.stale_after)
    print(f"claim: {format_claim(claim)}")
    print(f"path: {path}")
    if stale:
        print(f"stale: yes ({reason})")
        return 0
    print("stale: no")
    return 0


def cmd_claim_begin(args: argparse.Namespace) -> int:
    version = args.version.removeprefix("ops-v")
    operation = args.operation
    if operation not in VALID_OPERATIONS:
        print(
            f"ops_release_lock: invalid operation {operation!r}; "
            f"expected one of {', '.join(sorted(VALID_OPERATIONS))}",
            file=sys.stderr,
        )
        return 2
    cpath = claim_path()
    try:
        with with_flock(nonblock=args.nonblock, timeout=args.timeout, holder_note="claim begin"):
            existing = read_claim(cpath)
            if existing is not None:
                stale, reason = claim_is_stale(existing, stale_after=args.stale_after)
                same = (
                    existing.version == version
                    and existing.operation == operation
                    and existing.pid == os.getpid()
                )
                if same:
                    print(f"claim: refreshed {format_claim(existing)}")
                    return 0
                if not stale and not args.force:
                    print(
                        f"ops_release_lock: active claim blocks begin: {format_claim(existing)}",
                        file=sys.stderr,
                    )
                    print(
                        "ops_release_lock: wait for claim end, or --force if the holder is abandoned",
                        file=sys.stderr,
                    )
                    return EX_TEMPFAIL
                if stale:
                    print(
                        f"ops_release_lock: replacing stale claim ({reason}): {format_claim(existing)}",
                        file=sys.stderr,
                    )
                elif args.force:
                    print(
                        f"ops_release_lock: --force replacing claim: {format_claim(existing)}",
                        file=sys.stderr,
                    )
            claim = Claim(
                version=version,
                operation=operation,
                pid=os.getpid(),
                hostname=socket.gethostname(),
                holder=args.holder or os.environ.get("USER", "") or str(os.getuid()),
                started_at=iso_now(),
                note=args.note or "",
            )
            write_claim(cpath, claim)
            print(f"claim: began {format_claim(claim)}")
            return 0
    except LockError as exc:
        print(f"ops_release_lock: {exc}", file=sys.stderr)
        return exc.code


def cmd_claim_end(args: argparse.Namespace) -> int:
    cpath = claim_path()
    try:
        with with_flock(nonblock=args.nonblock, timeout=args.timeout, holder_note="claim end"):
            existing = read_claim(cpath)
            if existing is None:
                print("claim: none (already clear)")
                return 0
            if args.version and existing.version != args.version.removeprefix("ops-v"):
                print(
                    f"ops_release_lock: claim version {existing.version} != {args.version}",
                    file=sys.stderr,
                )
                return EX_TEMPFAIL
            foreign_live = (
                existing.pid != os.getpid() and pid_alive(existing.pid)
            )
            if foreign_live and not args.force:
                # Cooperative end: matching --version is enough (deploy handoff).
                if not args.version:
                    print(
                        f"ops_release_lock: claim owned by live pid {existing.pid}; "
                        "pass --version matching the claim, or --force",
                        file=sys.stderr,
                    )
                    return EX_TEMPFAIL
            clear_claim(cpath)
            print(f"claim: ended {format_claim(existing)}")
            return 0
    except LockError as exc:
        print(f"ops_release_lock: {exc}", file=sys.stderr)
        return exc.code


def cmd_claim_wait(args: argparse.Namespace) -> int:
    deadline = None if args.timeout is None else time.monotonic() + args.timeout
    cpath = claim_path()
    while True:
        claim = read_claim(cpath)
        if claim is None:
            print("claim: none")
            return 0
        stale, reason = claim_is_stale(claim, stale_after=args.stale_after)
        if stale:
            print(f"claim: stale ({reason}); clearing")
            try:
                with with_flock(timeout=5.0, holder_note="claim wait stale clear"):
                    current = read_claim(cpath)
                    if current is not None:
                        still_stale, _ = claim_is_stale(
                            current, stale_after=args.stale_after
                        )
                        if still_stale:
                            clear_claim(cpath)
                print("claim: none")
                return 0
            except LockError as exc:
                print(f"ops_release_lock: {exc}", file=sys.stderr)
                return exc.code
        if args.version and claim.version != args.version.removeprefix("ops-v"):
            # Wait until no conflicting claim, or only matching version remains cleared
            pass
        elif args.version is None or claim.version == args.version.removeprefix("ops-v"):
            # Waiting for this claim to end
            pass
        if deadline is not None and time.monotonic() >= deadline:
            print(
                f"ops_release_lock: timed out waiting for claim to clear "
                f"({format_claim(claim)})",
                file=sys.stderr,
            )
            return EX_TIMEOUT
        print(
            f"ops_release_lock: waiting for claim to end ({format_claim(claim)})…",
            file=sys.stderr,
        )
        time.sleep(args.poll)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stale-after",
        type=float,
        default=DEFAULT_STALE_AFTER,
        help="seconds after which a claim with a live PID is still considered stale "
        f"(default {DEFAULT_STALE_AFTER})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    hold = sub.add_parser("hold", help="run a command under the exclusive flock")
    hold.add_argument("--nonblock", action="store_true")
    hold.add_argument("--timeout", type=float, default=None)
    hold.add_argument("command", nargs=argparse.REMAINDER)
    hold.set_defaults(func=cmd_hold)

    claim = sub.add_parser("claim", help="multi-step release reservation")
    claim_sub = claim.add_subparsers(dest="claim_command", required=True)

    st = claim_sub.add_parser("status", help="show active claim")
    st.set_defaults(func=cmd_claim_status)

    begin = claim_sub.add_parser("begin", help="reserve a version for cut/deploy")
    begin.add_argument("version", help="MAJOR.MINOR.PATCH or ops-vMAJOR.MINOR.PATCH")
    begin.add_argument(
        "--operation",
        default="cut",
        choices=sorted(VALID_OPERATIONS),
        help="cut=tagging/publishing, deploy=fast-forwarding ~/ops, hold=generic",
    )
    begin.add_argument("--holder", default="", help="human/agent label")
    begin.add_argument("--note", default="")
    begin.add_argument("--force", action="store_true", help="replace a live claim")
    begin.add_argument("--nonblock", action="store_true")
    begin.add_argument("--timeout", type=float, default=30.0)
    begin.set_defaults(func=cmd_claim_begin)

    end = claim_sub.add_parser("end", help="clear the active claim")
    end.add_argument("--version", default="", help="require matching version")
    end.add_argument("--force", action="store_true")
    end.add_argument("--nonblock", action="store_true")
    end.add_argument("--timeout", type=float, default=30.0)
    end.set_defaults(func=cmd_claim_end)

    wait = claim_sub.add_parser("wait", help="block until claim is clear or stale")
    wait.add_argument("--version", default=None, help="only wait on this version")
    wait.add_argument("--timeout", type=float, default=None)
    wait.add_argument("--poll", type=float, default=2.0)
    wait.set_defaults(func=cmd_claim_wait)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Propagate stale-after onto nested claim handlers.
    if not hasattr(args, "stale_after"):
        args.stale_after = DEFAULT_STALE_AFTER
    return int(args.func(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGINT)
