#!/usr/bin/env python3
"""
ralph_herdr_supervisor.py — watches Ralph's .ralph-tui/session.json and reports lifecycle state to Herdr using the shared helper.

Uses the exact mapping from the 5-item walkthrough.
Runs as a long-lived supervisor (can be launched in a Herdr pane).
Defaults to balanced mode but respects HERDR_REPORTER_MODE.

Usage:
    ralph_herdr_supervisor.py [session_dir]

Default session_dir: ~/.ralph-tui or current directory's .ralph-tui
"""

import json
import time
import sys
from pathlib import Path
from typing import Optional, Dict, Any

# Import the shared helper from the same bin directory
sys.path.insert(0, str(Path(__file__).parent))
from herdr_lifecycle import HerdrLifecycleReporter

class RalphHerdrSupervisor:
    def __init__(self, session_dir: Optional[Path] = None):
        self.session_dir = Path(session_dir) if session_dir else Path.home() / ".ralph-tui"
        self.session_file = self.session_dir / "session.json"
        self.reporter = HerdrLifecycleReporter(source="hermes:ralph", agent="ralph")
        self.last_state = None
        self.last_mtime = 0
        self.running = True
        self._log("Supervisor initialized, watching " + str(self.session_file))

    def _log(self, msg: str) -> None:
        if self.reporter.debug:
            print(f"[ralph-herdr-supervisor] {msg}", file=sys.stderr)

    def _read_session(self) -> Optional[Dict[str, Any]]:
        if not self.session_file.exists():
            return None
        try:
            with open(self.session_file) as f:
                return json.load(f)
        except Exception as e:
            self._log(f"Failed to read session file: {e}")
            return None

    def _map_state(self, session: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Map Ralph's structured state to Herdr states (exact mapping from item 3)."""
        status = session.get("status", "").lower()
        iteration = session.get("current_iteration")
        task = session.get("current_task")
        paused = session.get("paused", False)
        completed = session.get("completed", False)
        error = session.get("error")

        message = None
        if error:
            message = f"Error: {error.get('message', 'unknown')}"
            return "blocked", message
        if completed:
            return "idle", "Task completed"
        if paused:
            return "idle", "Paused"
        if iteration or task or status in ("running", "active", "working"):
            return "working", f"Iteration {iteration or 0}"
        if status in ("idle", "ready"):
            return "idle", None

        # Default to working for any active session
        return "working", "Ralph active"

    def run(self, poll_interval: float = 2.0) -> None:
        """Main polling loop."""
        self._log(f"Starting poll loop (interval={poll_interval}s)")
        while self.running:
            try:
                mtime = self.session_file.stat().st_mtime if self.session_file.exists() else 0
                if mtime != self.last_mtime:
                    session = self._read_session()
                    if session:
                        state, message = self._map_state(session)
                        if state != self.last_state or self.reporter.mode == "positive":
                            if state == "working":
                                self.reporter.working(message)
                            elif state == "idle":
                                self.reporter.idle(message)
                            elif state == "blocked":
                                self.reporter.blocked(message)
                            self.last_state = state
                    self.last_mtime = mtime
            except Exception as e:
                self._log(f"Poll error: {e}")

            time.sleep(poll_interval)

        self.reporter.release()
        self._log("Supervisor stopped")

    def stop(self) -> None:
        self.running = False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-dir", type=Path, default=None, help="Ralph session directory")
    parser.add_argument("--poll", type=float, default=2.0, help="Poll interval in seconds")
    args = parser.parse_args()

    supervisor = RalphHerdrSupervisor(args.session_dir)
    try:
        supervisor.run(args.poll)
    except KeyboardInterrupt:
        supervisor.stop()
        print("Supervisor stopped by user.")
    except Exception as e:
        print(f"Supervisor crashed: {e}")
        supervisor.stop()
