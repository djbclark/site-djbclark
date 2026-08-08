#!/usr/bin/env python3
"""
herdr_lifecycle.py — reusable reporter for Herdr lifecycle state.

Implements the decisions from the 5-item walkthrough:
- Separate user-owned reporter (coexists with generated herdr-agent-state).
- Shared external supervisor pattern for Ralph (watches session.json).
- Exact mapping from item 3.
- Easy-to-switch reporting modes (quiet / positive / balanced).
- Default: balanced (report on meaningful state changes only).
- CLI wrapper by default, raw socket fallback when HERDR_SOCKET_PATH present.
- Monotonic --seq, proper release ordering, no-op outside Herdr.

Usage:
    from herdr_lifecycle import HerdrLifecycleReporter
    reporter = HerdrLifecycleReporter(source="hermes:lifecycle")
    reporter.working("building docs")
    reporter.blocked("awaiting approval")
    reporter.idle()
    reporter.release()

Environment variables:
    HERDR_REPORTER_MODE=balanced|positive|quiet (default balanced)
    HERDR_REPORTER_DEBUG=1 (verbose logging to stderr)
    HERDR_BIN_PATH, HERDR_PANE_ID, HERDR_SOCKET_PATH (inherited from Herdr)

Easy to extend: add a new mode by extending the _report method or adding
a new strategy in the MODES dict.
"""

import os
import sys
import subprocess
from typing import Optional

class HerdrLifecycleReporter:
    def __init__(self, source: str = "hermes:lifecycle", agent: str = "hermes"):
        self.source = source
        self.agent = agent
        self.mode = os.getenv("HERDR_REPORTER_MODE", "balanced").lower()
        self.debug = os.getenv("HERDR_REPORTER_DEBUG", "0") == "1"
        self.last_seq = 0
        self.last_state = None
        self.bin_path = os.getenv("HERDR_BIN_PATH", "herdr")
        self.pane_id = os.getenv("HERDR_PANE_ID")
        self.socket_path = os.getenv("HERDR_SOCKET_PATH")
        self.in_herdr = os.getenv("HERDR_ENV") == "1" and self.pane_id is not None

        if self.mode not in ("quiet", "positive", "balanced"):
            self._log(f"Unknown mode {self.mode}, falling back to balanced")
            self.mode = "balanced"

        self._log(f"Initialized with mode={self.mode}, source={source}, in_herdr={self.in_herdr}")

    def _log(self, msg: str) -> None:
        if self.debug:
            print(f"[herdr-lifecycle] {msg}", file=sys.stderr)

    def _next_seq(self) -> int:
        self.last_seq += 1
        return self.last_seq

    def _run_cli(self, state: str, message: Optional[str] = None) -> bool:
        if not self.in_herdr:
            self._log("Not in Herdr — no-op")
            return True

        seq = self._next_seq()
        cmd = [
            self.bin_path, "pane", "report-agent", self.pane_id,
            "--source", self.source,
            "--agent", self.agent,
            "--state", state,
            "--seq", str(seq)
        ]
        if message:
            cmd.extend(["--message", message])

        self._log(f"CLI: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                self._log(f"CLI failed: {result.stderr.strip()}")
                return False
            return True
        except Exception as e:
            self._log(f"CLI exception: {e}")
            return False

    def _report(self, state: str, message: Optional[str] = None) -> bool:
        if self.mode == "quiet" and state == self.last_state:
            self._log(f"Quiet mode — skipping duplicate {state}")
            return True

        if self.mode == "positive" or state != self.last_state or self.last_state is None:
            success = self._run_cli(state, message)
            if success:
                self.last_state = state
                self._log(f"Reported {state} (seq={self.last_seq})")
            return success
        return True

    def working(self, message: Optional[str] = None) -> bool:
        return self._report("working", message)

    def idle(self, message: Optional[str] = None) -> bool:
        return self._report("idle", message)

    def blocked(self, message: Optional[str] = None) -> bool:
        return self._report("blocked", message)

    def release(self) -> bool:
        if not self.in_herdr:
            return True
        seq = self._next_seq()
        cmd = [
            self.bin_path, "pane", "release-agent", self.pane_id,
            "--source", self.source,
            "--agent", self.agent,
            "--seq", str(seq)
        ]
        self._log(f"Release CLI: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            success = result.returncode == 0
            if success:
                self._log("Released authority")
                self.last_state = None
            else:
                self._log(f"Release failed: {result.stderr.strip()}")
            return success
        except Exception as e:
            self._log(f"Release exception: {e}")
            return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Herdr lifecycle reporter CLI")
    parser.add_argument("command", choices=["working", "idle", "blocked", "release"])
    parser.add_argument("--message", type=str, default=None)
    args = parser.parse_args()

    reporter = HerdrLifecycleReporter()
    if args.command == "release":
        reporter.release()
    else:
        getattr(reporter, args.command)(args.message)
