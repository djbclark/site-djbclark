#!/usr/bin/env python3
"""Tests for bin/s1_cycle.py: the scheduled S1 ingest cycle.

The three adapters are replaced by stub scripts in a temp bin dir, so no store
is touched; each stub records that it ran and behaves as its STUB_<NAME>
environment variable says (ok, fail, sleep, maintenance).
"""
from __future__ import annotations

import fcntl
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CYCLE = REPO / "bin" / "s1_cycle.py"

STUB = textwrap.dedent(
    """\
    import json, os, sys, time
    from pathlib import Path
    name = Path(__file__).stem
    stub_dir = Path(os.environ["STUB_DIR"])
    (stub_dir / (name + ".ran")).write_text(" ".join(sys.argv[1:]))
    mode = os.environ.get("STUB_" + name.upper(), "ok")
    if mode == "fail":
        print("first stderr line", file=sys.stderr)
        print("boom: adapter failed", file=sys.stderr)
        sys.exit(3)
    if mode == "sleep":
        (stub_dir / (name + ".pid")).write_text(str(os.getpid()))
        time.sleep(60)
    if mode == "maintenance":
        (Path(os.environ["DATA_DIR"]) / "maintenance.lock").write_text("pid=1 purpose=test")
    print("  indexed 10/20")
    print(json.dumps({"dry_run": False, "files": 2, "created": 5, "note": "x"}, indent=2))
    """
)

NAMES = (
    "s1_claude", "s1_hermes", "s1_codex", "s1_acprun", "s1_copilot", "s1_grok",
    "s1_opencode", "s1_zcode", "s1_search",
)


def dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


class CycleTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.bin = root / "bin"
        self.data = root / "data"
        self.stubs = root / "stubs"
        for d in (self.bin, self.data, self.stubs):
            d.mkdir()
        for name in NAMES:
            (self.bin / f"{name}.py").write_text(STUB)
        self.env = dict(os.environ, STUB_DIR=str(self.stubs), DATA_DIR=str(self.data))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def argv(self, *extra: str) -> list[str]:
        return [sys.executable, "-I", str(CYCLE), *extra, "--data-dir", str(self.data),
                "--bin-dir", str(self.bin), "--db", "/nonexistent/s1.sqlite3"]

    def run_cycle(self, *extra: str, **stub_modes: str) -> subprocess.CompletedProcess[str]:
        env = dict(self.env, **{f"STUB_{k.upper()}": v for k, v in stub_modes.items()})
        return subprocess.run(self.argv(*extra), env=env, capture_output=True, text=True,
                              timeout=60)

    def ran(self, name: str) -> bool:
        return (self.stubs / f"{name}.ran").exists()

    def log(self) -> str:
        return (self.data / "cycle.log").read_text()


class TestCycle(CycleTestCase):
    def test_all_steps_ok(self) -> None:
        result = self.run_cycle()
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log()
        for step in ("claude-scan", "hermes-sink", "codex-scan", "acprun-scan", "copilot-scan",
                     "grok-scan", "opencode-sink", "zcode-sink", "search-index"):
            self.assertRegex(log, rf"step={step} status=ok rc=0 secs=\S+ files=2 created=5\n")
        self.assertIn("cycle end status=ok", log)
        self.assertNotIn("dry_run", log)  # booleans are not counts
        # The store arguments reach every step, before its subcommand.
        self.assertEqual((self.stubs / "s1_claude.ran").read_text(),
                         "--db /nonexistent/s1.sqlite3 scan --quiet")
        self.assertEqual((self.stubs / "s1_hermes.ran").read_text(),
                         "--db /nonexistent/s1.sqlite3 sink")
        self.assertEqual((self.stubs / "s1_search.ran").read_text(),
                         "--db /nonexistent/s1.sqlite3 index")
        # The lock is released and no longer names a pid.
        self.assertEqual((self.data / "ingest.lock").read_text(), "")

    def test_failed_step_does_not_skip_later_steps(self) -> None:
        result = self.run_cycle(s1_hermes="fail")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.ran("s1_search"))
        log = self.log()
        self.assertIn('step=hermes-sink status=failed rc=3', log)
        self.assertIn('error="boom: adapter failed"', log)
        self.assertRegex(log, r"step=search-index status=ok")
        self.assertIn("cycle end status=failed", log)
        self.assertIn("failed=hermes-sink", log)
        self.assertIn("hermes-sink: boom: adapter failed", result.stderr)

    def test_first_step_failing_still_runs_the_rest(self) -> None:
        result = self.run_cycle(s1_claude="fail")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.ran("s1_hermes"))
        self.assertTrue(self.ran("s1_search"))

    def test_maintenance_lock_skips_without_running_anything(self) -> None:
        (self.data / "maintenance.lock").write_text("pid=1 purpose=migration")
        result = self.run_cycle()
        self.assertEqual(result.returncode, 0)
        self.assertFalse(any(self.ran(n) for n in NAMES))
        self.assertIn("skipped: maintenance", self.log())
        self.assertFalse((self.data / "ingest.lock").exists())

    def test_maintenance_lock_appearing_between_steps_stops_the_cycle(self) -> None:
        result = self.run_cycle(s1_claude="maintenance")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(self.ran("s1_claude"))
        self.assertFalse(self.ran("s1_hermes"))
        self.assertFalse(self.ran("s1_search"))
        self.assertIn("skipped: maintenance (before step=hermes-sink)", self.log())

    def test_held_lock_skips(self) -> None:
        lock = self.data / "ingest.lock"
        with lock.open("w") as fh:
            fh.write(f"pid={os.getpid()} started=1\n")
            fh.flush()
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_cycle()
        self.assertEqual(result.returncode, 0)
        self.assertFalse(any(self.ran(n) for n in NAMES))
        self.assertIn(f"skipped: locked by pid={os.getpid()}", self.log())

    def test_stale_lock_from_dead_process_is_taken_over(self) -> None:
        pid = dead_pid()
        (self.data / "ingest.lock").write_text(f"pid={pid} started=1\n")
        result = self.run_cycle()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(self.ran(n) for n in NAMES))
        self.assertIn(f"recovered stale lock from pid={pid} alive=False", self.log())

    def test_deadline_kills_own_child_and_skips_the_rest(self) -> None:
        started = time.monotonic()
        result = self.run_cycle("--deadline", "1", s1_claude="sleep")
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(result.returncode, 124)
        pid = int((self.stubs / "s1_claude.pid").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertFalse(self.ran("s1_hermes"))
        log = self.log()
        self.assertIn("step=claude-scan status=killed", log)
        self.assertIn("reason=deadline-1s", log)
        self.assertIn("step=hermes-sink status=skipped reason=deadline", log)
        self.assertIn("cycle end status=deadline", log)

    def test_sigterm_is_forwarded_to_the_running_step(self) -> None:
        env = dict(self.env, STUB_S1_CLAUDE="sleep")
        proc = subprocess.Popen(self.argv(), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        pid_file = self.stubs / "s1_claude.pid"
        deadline = time.monotonic() + 20
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        child = int(pid_file.read_text())
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=30), 1)
        proc.communicate()
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)
        self.assertFalse(self.ran("s1_hermes"))
        self.assertIn("step=hermes-sink status=skipped reason=terminated", self.log())

    def test_cycle_log_is_capped(self) -> None:
        (self.data / "cycle.log").write_text("x" * ((1 << 20) + 10) + "\n")
        self.assertEqual(self.run_cycle().returncode, 0)
        self.assertTrue((self.data / "cycle.log.1").exists())
        self.assertLess((self.data / "cycle.log").stat().st_size, 4096)


class TestWaitIdle(CycleTestCase):
    def test_wait_idle_times_out_while_held_and_returns_when_free(self) -> None:
        lock = self.data / "ingest.lock"
        with lock.open("w") as fh:
            fh.write("pid=4242 started=1\n")
            fh.flush()
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held = subprocess.run(self.argv("wait-idle", "--timeout", "1"),
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(held.returncode, 1)
        self.assertIn("still locked by pid=4242", held.stderr)
        free = subprocess.run(self.argv("wait-idle", "--timeout", "1"),
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(free.returncode, 0)


if __name__ == "__main__":
    unittest.main()
