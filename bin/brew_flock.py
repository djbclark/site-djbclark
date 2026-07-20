#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Serialize brew-touching commands with an exclusive advisory lock (Phase F4).

macOS does not ship util-linux flock(1). This wrapper uses fcntl.flock on a
lock file (same semantics). Default lock path:

  /tmp/site-djbclark-brew.lock

Override with SITE_BREW_LOCK.

Usage:
  bin/brew_flock.py -- brew install just
  bin/brew_flock.py --timeout 30 -- just goose-apply
  bin/brew_flock.py --nonblock -- true   # exit 75 if lock held

Exit codes:
  0   child succeeded
  75  lock not acquired under --nonblock (EX_TEMPFAIL)
  124 timed out waiting for lock (--timeout)
  other  child exit status, or 127 if child not found
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_LOCK = "/tmp/site-djbclark-brew.lock"
EX_TEMPFAIL = 75
EX_TIMEOUT = 124


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--lock-file",
        default=os.environ.get("SITE_BREW_LOCK", DEFAULT_LOCK),
        help=f"lock file path (default: $SITE_BREW_LOCK or {DEFAULT_LOCK})",
    )
    p.add_argument(
        "--nonblock",
        action="store_true",
        help="fail immediately with exit 75 if lock is held",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="seconds to wait for the lock (exclusive with --nonblock)",
    )
    p.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="command to run under the lock (use -- before command)",
    )
    return p.parse_args()


def acquire(lock_fd: int, *, nonblock: bool, timeout: float | None) -> None:
    if nonblock:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                print(
                    f"brew_flock: lock held ({os.environ.get('SITE_BREW_LOCK', DEFAULT_LOCK)}); "
                    "another brew operation is in progress",
                    file=sys.stderr,
                )
                raise SystemExit(EX_TEMPFAIL) from exc
            raise
        return

    if timeout is None:
        # Blocking wait; print once so operators know why we stalled.
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            print(
                "brew_flock: waiting for exclusive lock "
                f"({os.environ.get('SITE_BREW_LOCK', DEFAULT_LOCK)})…",
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
                print(
                    f"brew_flock: timed out after {timeout}s waiting for lock",
                    file=sys.stderr,
                )
                raise SystemExit(EX_TIMEOUT) from exc
            time.sleep(0.1)


def main() -> int:
    args = parse_args()
    cmd = list(args.command)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("brew_flock: missing command (usage: brew_flock.py -- <cmd>…)", file=sys.stderr)
        return 2
    if args.nonblock and args.timeout is not None:
        print("brew_flock: --nonblock and --timeout are mutually exclusive", file=sys.stderr)
        return 2

    lock_path = Path(args.lock_file).expanduser()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Open for read/write; create if missing. Keep fd open for the child lifetime.
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        acquire(lock_fd, nonblock=args.nonblock, timeout=args.timeout)
        # Record holder for debugging (best-effort).
        try:
            os.ftruncate(lock_fd, 0)
            os.lseek(lock_fd, 0, os.SEEK_SET)
            os.write(
                lock_fd,
                f"pid={os.getpid()} cmd={' '.join(cmd)}\n".encode(),
            )
        except OSError:
            pass
        try:
            proc = subprocess.run(cmd, check=False)
        except FileNotFoundError:
            print(f"brew_flock: command not found: {cmd[0]}", file=sys.stderr)
            return 127
        return int(proc.returncode)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
