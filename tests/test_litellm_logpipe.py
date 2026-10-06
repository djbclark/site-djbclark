"""C1: bin/litellm_logpipe.py must never leave its child running after it dies.

Every test runs the real wrapper around a dummy child (a few lines of Python
that report their pid and sleep), never a live service. The child also spawns a
grandchild, to show that signals reach the whole process group.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "litellm_logpipe.py"
KILL_AFTER = 2.0

CHILD = r"""
import os, signal, subprocess, sys, time
if sys.argv[1] == "ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
grand = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
print(time.strftime("%Y-%m-%d %H:%M:%S"), "DUMMY", os.getpid(), grand.pid, flush=True)
while True:
    time.sleep(1)
"""


def alive(pid: int) -> bool:
    """True while `pid` exists and is not a zombie."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    out = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return bool(out) and not out.startswith("Z")


def wait_until(cond, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


class LogpipeSupervisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "out.log"
        self.extra: list[int] = []

    def tearDown(self) -> None:
        for pid in self.extra:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.tmp.cleanup()

    def start(self, mode: str) -> tuple[subprocess.Popen, int, int]:
        wrapper = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPT),
                "--out",
                str(self.log),
                "--kill-after",
                str(KILL_AFTER),
                "--",
                sys.executable,
                "-c",
                CHILD,
                mode,
            ],
            stdin=subprocess.DEVNULL,
        )
        found: list[re.Match] = []

        def ready() -> bool:
            if self.log.exists():
                m = re.search(r"DUMMY (\d+) (\d+)", self.log.read_text())
                if m:
                    found.append(m)
                    return True
            return False

        self.assertTrue(wait_until(ready, 15), "dummy child never reported its pid")
        child, grand = int(found[0].group(1)), int(found[0].group(2))
        self.extra += [child, grand, wrapper.pid]
        self.assertEqual(os.getpgid(child), child, "child is not its own group leader")
        self.assertEqual(os.getpgid(grand), child, "grandchild left the child's group")
        time.sleep(0.5)  # let the reaper register its kqueue filters
        return wrapper, child, grand

    def test_sigterm_to_wrapper_stops_child_and_grandchild(self) -> None:
        wrapper, child, grand = self.start("normal")
        t0 = time.time()
        wrapper.send_signal(signal.SIGTERM)
        wrapper.wait(timeout=KILL_AFTER + 10)
        self.assertTrue(wait_until(lambda: not alive(child), 5))
        self.assertTrue(wait_until(lambda: not alive(grand), 5))
        print(
            f"\n  SIGTERM wrapper: child+grandchild gone, wrapper exited "
            f"{wrapper.returncode} after {time.time() - t0:.1f}s"
        )

    def test_sigkill_to_wrapper_reaper_kills_child_group(self) -> None:
        wrapper, child, grand = self.start("normal")
        t0 = time.time()
        wrapper.send_signal(signal.SIGKILL)
        wrapper.wait(timeout=5)
        self.assertTrue(
            wait_until(lambda: not alive(child), KILL_AFTER + 8),
            "child survived a SIGKILLed wrapper (orphan)",
        )
        self.assertTrue(wait_until(lambda: not alive(grand), 5))
        print(
            f"\n  SIGKILL wrapper: reaper killed the group after {time.time() - t0:.1f}s"
        )

    def test_child_ignoring_sigterm_is_killed_after_kill_after(self) -> None:
        wrapper, child, grand = self.start("ignore-term")
        t0 = time.time()
        wrapper.send_signal(signal.SIGTERM)
        wrapper.wait(timeout=KILL_AFTER + 10)
        elapsed = time.time() - t0
        self.assertFalse(alive(child))
        self.assertGreaterEqual(
            elapsed, KILL_AFTER - 0.3, "SIGKILL came before --kill-after"
        )
        self.assertLess(elapsed, KILL_AFTER + 5)
        self.assertTrue(wait_until(lambda: not alive(grand), 5))
        print(
            f"\n  SIGTERM-ignoring child: SIGKILLed, wrapper exited after {elapsed:.1f}s"
        )

    def test_sigkill_wrapper_with_child_ignoring_sigterm(self) -> None:
        wrapper, child, grand = self.start("ignore-term")
        t0 = time.time()
        wrapper.send_signal(signal.SIGKILL)
        wrapper.wait(timeout=5)
        self.assertTrue(
            wait_until(lambda: not alive(child), KILL_AFTER + 8),
            "reaper did not escalate to SIGKILL",
        )
        self.assertTrue(wait_until(lambda: not alive(grand), 5))
        print(
            f"\n  SIGKILL wrapper + SIGTERM-ignoring child: gone after {time.time() - t0:.1f}s"
        )

    def test_reaper_exits_when_child_exits_on_its_own(self) -> None:
        wrapper, child, grand = self.start("normal")
        os.kill(grand, signal.SIGKILL)
        os.kill(child, signal.SIGKILL)
        wrapper.wait(timeout=KILL_AFTER + 10)

        def no_reaper() -> bool:
            out = subprocess.run(
                ["pgrep", "-f", f"reap {wrapper.pid} {child} "],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            return not out.strip()

        self.assertTrue(wait_until(no_reaper, 5), "reaper outlived the child")


if __name__ == "__main__":
    unittest.main()
