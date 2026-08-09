#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Local physical OpenCLI Browser Bridge profile lease.

The lease is intentionally process-scoped: callers hold an advisory flock while
using one canonical OpenCLI profile, and the kernel releases it if the caller
crashes. Metadata is diagnostic only and never includes command arguments,
prompts, responses, cookies, or credentials.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_LOCK_TIMEOUT = 10.0
MAX_METADATA_TEXT = 160


class LeaseBusy(Exception):
    def __init__(self, profile: str, owner: dict[str, Any], timeout: float) -> None:
        self.profile = profile
        self.owner = owner
        self.timeout = timeout
        owner_text = json.dumps(owner, sort_keys=True) if owner else "unknown owner"
        super().__init__(f"OpenCLI profile {profile!r} busy after {timeout:g}s ({owner_text})")


def _state_dir(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    xdg_state = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
    return Path(xdg_state) / "site-djbclark" / "opencli-profile-leases"


def _safe_profile(profile: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in profile)
    if not safe:
        raise ValueError("profile must contain at least one safe filename character")
    return safe[:MAX_METADATA_TEXT]


def _safe_metadata_text(value: str, field: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError(f"{field} must not be empty")
    return cleaned[:MAX_METADATA_TEXT]


def _lease_path(profile: str, state_dir: str | None) -> Path:
    return _state_dir(state_dir) / "profiles" / f"{_safe_profile(profile)}.lock"


def _read_metadata(fd: int) -> dict[str, Any]:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 8192).decode("utf-8", errors="replace").strip()
        value = json.loads(raw) if raw else {}
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


class ProfileLease:
    """Exclusive process-scoped lease for one physical OpenCLI profile."""

    def __init__(
        self,
        profile: str,
        owner: str,
        purpose: str,
        timeout: float,
        *,
        state_dir: str | None = None,
    ) -> None:
        self.profile = _safe_metadata_text(profile, "profile")
        self.owner = _safe_metadata_text(owner, "owner")
        self.purpose = _safe_metadata_text(purpose, "purpose")
        self.timeout = max(0.0, timeout)
        self.path = _lease_path(self.profile, state_dir)
        self._fd: int | None = None

    def __enter__(self) -> "ProfileLease":
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    os.close(fd)
                    raise
                if time.monotonic() >= deadline:
                    owner = _read_metadata(fd)
                    os.close(fd)
                    raise LeaseBusy(self.profile, owner, self.timeout) from exc
                time.sleep(0.05)
        metadata = {
            "profile": self.profile,
            "owner": self.owner,
            "purpose": self.purpose,
            "pid": os.getpid(),
            "acquired_at": time.time(),
        }
        try:
            os.ftruncate(fd, 0)
            os.write(fd, json.dumps(metadata, sort_keys=True).encode("utf-8"))
            os.fsync(fd)
            os.fchmod(fd, 0o600)
        except OSError:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            raise
        self._fd = fd
        return self

    def __exit__(self, *exc_info: object) -> bool:
        if self._fd is not None:
            try:
                os.ftruncate(self._fd, 0)
                os.fsync(self._fd)
            except OSError:
                pass
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
            self._fd = None
        return False


def profile_status(profile: str, *, state_dir: str | None = None) -> dict[str, Any]:
    path = _lease_path(profile, state_dir)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            return {"profile": profile, "busy": True, "owner": _read_metadata(fd)}
        return {"profile": profile, "busy": False, "owner": None}
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("status",):
        p = sub.add_parser(command)
        p.add_argument("--profile", required=True)
        p.add_argument("--state-dir")
    p_run = sub.add_parser("run", help="run one command while holding the profile lease")
    p_run.add_argument("--profile", required=True)
    p_run.add_argument("--owner", required=True)
    p_run.add_argument("--purpose", required=True)
    p_run.add_argument("--lock-timeout", type=float, default=DEFAULT_LOCK_TIMEOUT)
    p_run.add_argument("--state-dir")
    p_run.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "status":
            print(json.dumps(profile_status(args.profile, state_dir=args.state_dir), sort_keys=True))
            return 0
        command = list(args.command)
        if command and command[0] == "--":
            command.pop(0)
        if not command:
            raise ValueError("run requires a command after --")
        completed_returncode = 0
        with ProfileLease(
            args.profile,
            args.owner,
            args.purpose,
            args.lock_timeout,
            state_dir=args.state_dir,
        ):
            completed_returncode = subprocess.run(command, check=False, shell=False).returncode
        return completed_returncode
    except LeaseBusy as exc:
        print(json.dumps({"ok": False, "error_type": "lock_busy", "profile": exc.profile, "owner": exc.owner}), file=sys.stderr)
        return 16
    except (OSError, ValueError) as exc:
        print(f"opencli_profile_lease: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
