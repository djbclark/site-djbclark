#!/usr/bin/env python3
"""Tests for fleet-watch's S1 evidence freshness check (`fleet-watch s1`).

Runs the real script with HOME pointed at a temp dir, a stub hermes-ping that
records each notice, and a temp S1 store; "now" is pinned with
FLEET_WATCH_S1_NOW. Nothing is sent and the live store is never opened.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))

import s1_evidence as s1  # noqa: E402

FLEET_WATCH = REPO / "bin" / "fleet-watch"
NOW = 1_800_000_000  # 2027-01-15T08:00:00Z
HOUR = 3600


def iso(epoch: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FleetWatchS1(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.home = root / "home"
        (self.home / ".local" / "bin").mkdir(parents=True)
        self.pings = self.home / "pings"
        self.ping_rc = self.home / "ping_rc"
        ping = self.home / ".local" / "bin" / "hermes-ping"
        ping.write_text(
            "#!/bin/bash\n"
            'rc=$(cat "$HOME/ping_rc" 2>/dev/null || echo 0)\n'
            '[ "$rc" = 0 ] && echo "$*" >> "$HOME/pings"\n'
            'exit "$rc"\n'
        )
        ping.chmod(0o755)
        self.state = self.home / ".local" / "state" / "fleet-watch"
        self.db = root / "candidates.sqlite3"
        self.store = s1.EvidenceStore(self.db, root / "cas")
        self.seq = 0

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def event(self, producer: str, epoch: int) -> None:
        self.seq += 1
        self.store.put_event(producer=producer, source_uri="file:///x",
                             source_locator=str(self.seq), raw=str(self.seq).encode(),
                             ts_utc=iso(epoch))

    def watch(self, now: int = NOW, mode: str = "1", **env: str) -> str:
        full = dict(os.environ, HOME=str(self.home), FLEET_WATCH_S1=mode,
                    FLEET_WATCH_S1_DB=str(self.db), FLEET_WATCH_S1_NOW=str(now))
        full.update(env)
        result = subprocess.run(["bash", str(FLEET_WATCH), "s1"], env=full,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def sent(self) -> list[str]:
        return self.pings.read_text().splitlines() if self.pings.exists() else []

    def test_fresh_store_sends_nothing(self) -> None:
        self.event("claude-code", NOW - HOUR)
        self.event("hermes", NOW - 60)
        self.assertEqual(self.watch(), "s1=ok claude-code=1h0m hermes=1m")
        self.assertEqual(self.sent(), [])

    def test_stale_producer_pings_once_per_incident(self) -> None:
        self.event("claude-code", NOW - 7 * HOUR)
        self.event("hermes", NOW - HOUR)
        self.assertTrue(self.watch().startswith("s1=stale:claude-code "))
        self.assertEqual(self.sent(), ["s1-evidence: claude-code stale 7h0m"])
        self.assertTrue((self.state / "s1-stale-claude-code").exists())
        # Still stale on the next runs: no repeat.
        self.watch(now=NOW + 300)
        self.watch(now=NOW + 600)
        self.assertEqual(len(self.sent()), 1)

    def test_recovery_pings_once_and_clears_the_incident(self) -> None:
        self.event("claude-code", NOW - 7 * HOUR)
        self.event("hermes", NOW - HOUR)
        self.watch()
        self.event("claude-code", NOW - 120)
        self.assertEqual(self.watch(), "s1=ok claude-code=2m hermes=1h0m")
        self.assertEqual(self.sent()[1:], ["s1-evidence: claude-code fresh again (newest event 2m old)"])
        self.assertFalse((self.state / "s1-stale-claude-code").exists())
        self.watch(now=NOW + 60)
        self.assertEqual(len(self.sent()), 2)
        # A second incident pings again.
        self.watch(now=NOW + 7 * HOUR)
        self.assertEqual(self.sent()[2:], ["s1-evidence: claude-code stale 7h2m",
                                           "s1-evidence: hermes stale 8h0m"])

    def test_hindsight_is_never_checked(self) -> None:
        self.event("hindsight", NOW - 60 * 24 * HOUR)
        self.event("claude-code", NOW - 60)
        out = self.watch(FLEET_WATCH_S1_PRODUCERS="hindsight claude-code")
        self.assertEqual(out, "s1=ok claude-code=1m")
        self.assertEqual(self.sent(), [])

    def test_producer_without_events_is_stale(self) -> None:
        self.event("claude-code", NOW - 60)
        self.assertEqual(self.watch(), "s1=stale:hermes claude-code=1m hermes=never")
        self.assertEqual(self.sent(), ["s1-evidence: hermes stale (no events)"])

    def test_threshold_is_configurable(self) -> None:
        self.event("claude-code", NOW - 2 * HOUR)
        self.event("hermes", NOW - 60)
        self.assertEqual(self.watch(FLEET_WATCH_S1_MAX_AGE="3600"),
                         "s1=stale:claude-code claude-code=2h0m hermes=1m")

    def test_failed_ping_is_retried_next_run(self) -> None:
        self.event("claude-code", NOW - 7 * HOUR)
        self.event("hermes", NOW - 60)
        self.ping_rc.write_text("1")
        self.watch()
        self.assertFalse((self.state / "s1-stale-claude-code").exists())
        self.ping_rc.write_text("0")
        self.watch()
        self.assertEqual(self.sent(), ["s1-evidence: claude-code stale 7h0m"])

    def test_unreadable_store_changes_nothing(self) -> None:
        self.event("claude-code", NOW - 7 * HOUR)
        out = self.watch(FLEET_WATCH_S1_DB=str(self.home / "missing.sqlite3"))
        self.assertEqual(out, "s1=unknown")
        self.assertEqual(self.sent(), [])

    def test_auto_mode_follows_the_ingest_plist(self) -> None:
        self.event("claude-code", NOW - 7 * HOUR)
        self.event("hermes", NOW - 60)
        self.assertTrue(self.watch(mode="auto").startswith("s1=off"))
        self.assertEqual(self.sent(), [])
        agents = self.home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        (agents / "com.djbclark.s1-ingest.plist").write_text("<plist/>")
        self.assertTrue(self.watch(mode="auto").startswith("s1=stale:claude-code"))
        self.assertEqual(len(self.sent()), 1)

    def test_age_matches_s1_evidence_stats_format(self) -> None:
        # Oldest first, so each new event becomes the newest.
        for age in (49 * 86400 + 3 * HOUR, 86400, 7 * HOUR + 125, 3600, 3599, 60, 59, 5):
            self.event("claude-code", NOW - age)
            self.event("hermes", NOW - age)
            out = self.watch(mode="1", FLEET_WATCH_S1_MAX_AGE=str(10**9))
            self.assertIn(f"hermes={s1.format_age(age)}", out)


if __name__ == "__main__":
    unittest.main()
