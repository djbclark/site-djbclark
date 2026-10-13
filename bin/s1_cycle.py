#!/usr/bin/env python3
"""One scheduled S1 ingest cycle: Claude scan, Hermes sink, search index.

The adapters are one-shot, checkpoint-resuming commands; until 2026-10-12
nothing ever scheduled them, and the store sat seven weeks stale (last event
2026-08-24) without anyone noticing. launchd now runs this every 15 minutes
(`com.<site_ns>.s1-ingest`, roles/site_agents, `site_agents_s1_ingest_enabled`),
and `fleet-watch` pages when a producer's newest event gets old.

Steps, in order, each in its own process group with its exit status checked:

    claude-scan    s1_claude.py scan --quiet
    hermes-sink    s1_hermes.py sink
    search-index   s1_search.py index

No step depends on another succeeding (the index covers whatever is in the
store), so a failed step never skips the later ones; the cycle exits 1 if any
failed. Each step appends one line with its counts (the numbers in its closing
JSON) to `cycle.log` in the data directory, which is capped at 1 MiB with one
rotated generation (`cycle.log.1`).

Lock protocol (everything that writes the store honours it):

    ingest.lock       A flock(2) on this file is held for the whole cycle; the
                      file holds the owner's "pid=<pid> started=<epoch>". The
                      kernel drops the lock when the process dies, so a crash
                      cannot wedge it; a leftover file whose pid is gone is a
                      stale lock and is simply taken over (logged as such). A
                      cycle that finds the lock held logs "skipped: locked"
                      and exits 0: launchd never overlaps the job, so the
                      other holder is a hand run or `wait-idle`.
    maintenance.lock  Present = hands off. A cycle that finds it (before
                      taking ingest.lock, after taking it, or between steps)
                      logs "skipped: maintenance" and exits 0 without touching
                      the store. Migrations and CAS packing create it (write
                      your pid and purpose into it), then run
                      `s1_cycle.py wait-idle` to wait out a cycle already
                      running, do their work, and remove it.

Wedge guard: the cycle has a 50-minute budget (--deadline). When it runs out,
the running step's process group (the cycle's own children only, never a
pattern match) gets SIGTERM, then SIGKILL 10 s later, the remaining steps are
skipped, and the cycle exits 124. SIGTERM to the cycle (launchd bootout) is
forwarded to the running step the same way.

Usage:
    s1_cycle.py [run] [--deadline SECONDS]
    s1_cycle.py wait-idle [--timeout SECONDS]   # exit 0 once no cycle runs
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path.home() / ".local" / "share" / "s1-evidence"
BIN_DIR = Path(__file__).resolve().parent
DEADLINE_S = 50 * 60
KILL_GRACE_S = 10
LOG_CAP_BYTES = 1 << 20
EXIT_FAILED = 1
EXIT_DEADLINE = 124

STEPS: list[tuple[str, str, list[str]]] = [
    ("claude-scan", "s1_claude.py", ["scan", "--quiet"]),
    ("hermes-sink", "s1_hermes.py", ["sink"]),
    ("codex-scan", "s1_codex.py", ["scan", "--quiet"]),
    ("acprun-scan", "s1_acprun.py", ["scan", "--quiet"]),
    ("copilot-scan", "s1_copilot.py", ["scan", "--quiet"]),
    ("grok-scan", "s1_grok.py", ["scan", "--quiet"]),
    ("opencode-sink", "s1_opencode.py", ["sink"]),
    ("zcode-sink", "s1_zcode.py", ["sink"]),
    ("cursor-scan", "s1_cursor_cli.py", ["scan"]),
    ("agy-scan", "s1_agy.py", ["scan"]),
    ("crush-scan", "s1_crush.py", ["scan"]),
    ("cline-scan", "s1_cline.py", ["scan"]),
    ("qwen-scan", "s1_qwen.py", ["scan"]),
    ("cursor-ide-scan", "s1_cursor_ide.py", ["scan"]),
    ("cursor-transcripts-scan", "s1_cursor_transcripts.py", ["scan"]),
    ("search-index", "s1_search.py", ["index"]),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class CycleLog:
    def __init__(self, path: Path):
        self.path = path

    def line(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.path.stat().st_size > LOG_CAP_BYTES:
                self.path.replace(self.path.with_name(self.path.name + ".1"))
        except FileNotFoundError:
            pass
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(f"{now_iso()} pid={os.getpid()} {text}\n")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno == errno.EPERM
    return True


def read_owner(path: Path) -> dict[str, int]:
    """Parse "pid=<n> started=<epoch>" from a lock file; {} when unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    owner = {}
    for field in text.split():
        key, _, value = field.partition("=")
        if value.isdigit():
            owner[key] = int(value)
    return owner


class IngestLock:
    """flock(2) on ingest.lock, with the owner's pid written inside."""

    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None
        self.stale_owner: dict[str, int] = {}

    def try_acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        # The lock is ours; whatever pid the file still names is a dead run's.
        previous = read_owner(self.path)
        if previous.get("pid") and previous["pid"] != os.getpid():
            self.stale_owner = previous
        os.ftruncate(fd, 0)
        os.write(fd, f"pid={os.getpid()} started={int(time.time())}\n".encode())
        self.fd = fd
        return True

    def release(self) -> None:
        if self.fd is None:
            return
        # Empty the file before unlocking so nobody reads our pid as live.
        os.ftruncate(self.fd, 0)
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)
        self.fd = None


def last_json(text: str) -> dict[str, Any]:
    """The closing JSON object an adapter prints after any progress lines."""
    lines = text.splitlines()
    for start in range(len(lines) - 1, -1, -1):
        if lines[start].startswith("{"):
            try:
                value = json.loads("\n".join(lines[start:]))
            except ValueError:
                continue
            return value if isinstance(value, dict) else {}
    return {}


def counts(result: dict[str, Any]) -> str:
    return " ".join(
        f"{k}={v}" for k, v in result.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    )


def tail(path: Path, n: int = 20) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


class Cycle:
    def __init__(self, args: argparse.Namespace):
        self.data_dir = Path(args.data_dir).expanduser()
        self.bin_dir = Path(args.bin_dir).expanduser()
        self.python = args.python
        self.store_args: list[str] = []
        if args.db:
            self.store_args += ["--db", args.db]
        if args.cas:
            self.store_args += ["--cas", args.cas]
        self.deadline = time.monotonic() + args.deadline
        self.budget = args.deadline
        self.log = CycleLog(self.data_dir / "cycle.log")
        self.maintenance = self.data_dir / "maintenance.lock"
        self.lock = IngestLock(self.data_dir / "ingest.lock")
        self.child: subprocess.Popen[bytes] | None = None
        self.terminated = False

    # -- process control --------------------------------------------------

    def _signal_child(self, signum: int) -> None:
        """Signal the running step's process group: our own child only."""
        if self.child is not None:
            try:
                os.killpg(self.child.pid, signum)
            except ProcessLookupError:
                pass

    def _on_term(self, signum: int, _frame: Any) -> None:
        # Only flag and forward here; the step loop escalates to SIGKILL. Waiting
        # on the child inside a signal handler can deadlock on Popen's lock.
        self.terminated = True
        self._signal_child(signal.SIGTERM)

    def _wait(self, child: subprocess.Popen[bytes]) -> tuple[int, bool]:
        """Poll the step to completion under the wedge guard; (rc, timed_out)."""
        timed_out, term_at = False, None
        while True:
            rc = child.poll()
            if rc is not None:
                return rc, timed_out
            now = time.monotonic()
            if now >= self.deadline and not timed_out:
                timed_out = True
                self._signal_child(signal.SIGTERM)
            if term_at is None and (timed_out or self.terminated):
                term_at = now
            if term_at is not None and now - term_at > KILL_GRACE_S:
                self._signal_child(signal.SIGKILL)
            time.sleep(0.2)

    def run_step(self, name: str, script: str, argv: list[str], workdir: Path) -> str:
        """Run one step; returns ok | failed | deadline."""
        out_path, err_path = workdir / f"{name}.out", workdir / f"{name}.err"
        cmd = [self.python, "-I", str(self.bin_dir / script), *self.store_args, *argv]
        started = time.monotonic()
        with out_path.open("wb") as out, err_path.open("wb") as err:
            try:
                self.child = subprocess.Popen(cmd, stdout=out, stderr=err,
                                              stdin=subprocess.DEVNULL, start_new_session=True)
            except OSError as exc:
                self.log.line(f"step={name} status=failed rc=127 error={exc.__class__.__name__}")
                return "failed"
            try:
                rc, timed_out = self._wait(self.child)
            finally:
                self.child = None
        fields = [f"step={name}", "", f"rc={rc}", f"secs={time.monotonic() - started:.1f}"]
        result = counts(last_json(out_path.read_text(encoding="utf-8", errors="replace")))
        if result:
            fields.append(result)
        if timed_out:
            fields[1] = "status=killed"
            self.log.line(" ".join(fields + [f"reason=deadline-{self.budget}s"]))
            return "deadline"
        if rc != 0 or self.terminated:
            fields[1] = "status=failed"
            err_tail = tail(err_path)
            fields.append(f"error={json.dumps(err_tail[-1][:200] if err_tail else '')}")
            self.log.line(" ".join(fields))
            for line in err_tail:
                print(f"{name}: {line}", file=sys.stderr)
            return "failed"
        fields[1] = "status=ok"
        self.log.line(" ".join(fields))
        return "ok"

    # -- the cycle --------------------------------------------------------

    def run(self) -> int:
        if self.maintenance.exists():
            self.log.line("skipped: maintenance")
            return 0
        if not self.lock.try_acquire():
            owner = read_owner(self.lock.path)
            self.log.line(f"skipped: locked by pid={owner.get('pid', '?')}")
            return 0
        signal.signal(signal.SIGTERM, self._on_term)
        try:
            if self.lock.stale_owner:
                self.log.line(f"recovered stale lock from pid={self.lock.stale_owner.get('pid')}"
                              f" alive={pid_alive(self.lock.stale_owner['pid'])}")
            # Re-check now that the lock is ours: a maintainer may have created
            # maintenance.lock between the first check and the flock.
            if self.maintenance.exists():
                self.log.line("skipped: maintenance")
                return 0
            return self._steps()
        finally:
            self.lock.release()

    def _steps(self) -> int:
        started = time.monotonic()
        self.log.line("cycle start")
        statuses: dict[str, str] = {}
        with tempfile.TemporaryDirectory(prefix="s1-cycle-") as tmp:
            for name, script, argv in STEPS:
                if self.terminated:
                    statuses[name] = "skipped"
                    self.log.line(f"step={name} status=skipped reason=terminated")
                    continue
                if "deadline" in statuses.values():
                    statuses[name] = "skipped"
                    self.log.line(f"step={name} status=skipped reason=deadline")
                    continue
                if self.maintenance.exists():
                    self.log.line(f"skipped: maintenance (before step={name})")
                    return EXIT_FAILED if "failed" in statuses.values() else 0
                statuses[name] = self.run_step(name, script, argv, Path(tmp))
        failed = [n for n, s in statuses.items() if s in ("failed", "deadline")]
        secs = f"{time.monotonic() - started:.1f}"
        if "deadline" in statuses.values():
            self.log.line(f"cycle end status=deadline secs={secs} failed={','.join(failed)}")
            return EXIT_DEADLINE
        if failed or self.terminated:
            self.log.line(f"cycle end status=failed secs={secs} failed={','.join(failed) or '-'}")
            return EXIT_FAILED
        self.log.line(f"cycle end status=ok secs={secs}")
        return 0


def wait_idle(args: argparse.Namespace) -> int:
    """Block until no cycle holds ingest.lock (then let go at once)."""
    lock = IngestLock(Path(args.data_dir).expanduser() / "ingest.lock")
    end = time.monotonic() + args.timeout
    while True:
        lock.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            if time.monotonic() >= end:
                owner = read_owner(lock.path)
                print(f"still locked by pid={owner.get('pid', '?')}", file=sys.stderr)
                return EXIT_FAILED
            time.sleep(1)
            continue
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One scheduled S1 ingest cycle")
    parser.add_argument("command", nargs="?", default="run", choices=("run", "wait-idle"))
    parser.add_argument("--data-dir", default=str(DATA_DIR),
                        help="lock files and cycle.log live here")
    parser.add_argument("--bin-dir", default=str(BIN_DIR), help="where the adapters are")
    parser.add_argument("--python", default=sys.executable, help="interpreter for the steps")
    parser.add_argument("--db", default=None, help="passed to every step")
    parser.add_argument("--cas", default=None, help="passed to every step")
    parser.add_argument("--deadline", type=int, default=DEADLINE_S,
                        help="wedge guard: seconds before the running step is killed")
    parser.add_argument("--timeout", type=int, default=DEADLINE_S + 60,
                        help="wait-idle: seconds to wait")
    args = parser.parse_args(argv)
    if args.command == "wait-idle":
        return wait_idle(args)
    return Cycle(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
