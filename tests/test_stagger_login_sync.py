#!/usr/bin/env python3
"""Unit tests for bin/stagger-login-sync pure helpers."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "stagger-login-sync"
# bin/stagger-login-sync has no .py suffix; SourceFileLoader still loads it.
_LOADER = importlib.machinery.SourceFileLoader("stagger_login_sync", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(_LOADER.name, _LOADER)
assert SPEC and SPEC.loader
sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync
SPEC.loader.exec_module(sync)


SAMPLE_LOG = """
2026-11-10 02:25:49.317 E  tccd[425:2a7f6a] Failed to get code reference from: TCCDProcess: identifier=com.binaryfruit.DriveDxLoginItemHelper, pid=1, auid=501, euid=501, binary_path=/Applications/DriveDx.app/Contents/Library/LoginItems/DriveDxLoginItemHelper.app/Contents/MacOS/DriveDxLoginItemHelper. -67065
2026-11-10 02:26:00.000 E  tccd[425:2a7f6a] Failed to get code reference from: TCCDProcess: identifier=com.contextsformac.Contexts, pid=2, auid=501, euid=501, binary_path=/Applications/Contexts.app/Contents/MacOS/Contexts -67065
2026-11-10 02:26:01.000 E  tccd[425:2a7f6a] Failed to get code reference from: TCCDProcess: identifier=com.contextsformac.Contexts, pid=3, auid=501, euid=501, binary_path=/Applications/Contexts.app/Contents/MacOS/Contexts -67065
2026-11-10 02:26:02.000 E  tccd[425:2a7f6a] Failed to get code reference from: TCCDProcess: identifier=com.talonvoice.Talon, pid=4, auid=501, euid=501, binary_path=/Applications/Talon.app/Contents/MacOS/Talon -67065
"""


class OuterAppTests(unittest.TestCase):
    def test_embedded_login_item_is_skipped(self) -> None:
        self.assertIsNone(
            sync.outer_app_from_binary(
                "/Applications/DriveDx.app/Contents/Library/LoginItems/"
                "DriveDxLoginItemHelper.app/Contents/MacOS/DriveDxLoginItemHelper."
            )
        )

    def test_top_level_app_resolved(self) -> None:
        self.assertEqual(
            sync.outer_app_from_binary("/Applications/Contexts.app/Contents/MacOS/Contexts"),
            Path("/Applications/Contexts.app"),
        )


class ParseRefusalsTests(unittest.TestCase):
    def test_counts_skip_embedded(self) -> None:
        counts = sync.parse_refusals(SAMPLE_LOG)
        self.assertEqual(counts[Path("/Applications/Contexts.app")], 2)
        self.assertEqual(counts[Path("/Applications/Talon.app")], 1)
        self.assertNotIn(Path("/Applications/DriveDx.app"), counts)


class CullDiscoverTests(unittest.TestCase):
    def test_keeps_existing_even_without_refusals_and_adds_login_item(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sticky = root / "Warden.app"
            sticky.mkdir()
            new = root / "Contexts.app"
            new.mkdir()
            gone = root / "Gone.app"
            existing = [
                sync.Entry("app", (str(sticky),), 165),
                sync.Entry("app", (str(gone),), 170),
                sync.Entry(
                    "launchd",
                    ("gui/501/com.example", str(root / "missing.plist")),
                    150,
                ),
            ]
            # Create a real plist so launchd keep works in a second case.
            plist = root / "ok.plist"
            plist.write_text("{}", encoding="utf-8")
            existing.append(
                sync.Entry("launchd", ("gui/501/com.ok", str(plist)), 150)
            )

            refusals = {new: 5, Path("/Applications/Talon.app"): 50}
            items = {"Contexts": new, "Other": None}
            kept, culled, added, notes = sync.cull_and_discover(
                existing,
                refusals,
                items,
                apps_roots=(str(root) + "/",),
            )
            self.assertEqual({Path(e.parts[0]) for e in kept if e.kind == "app"}, {sticky, new})
            self.assertIn(gone, culled)
            self.assertIn(root / "missing.plist", culled)
            self.assertEqual(added, [new])
            self.assertTrue(any("Talon" in n or "SMAppService" in n for n in notes))


class ScheduleTests(unittest.TestCase):
    def test_bartender_last_and_launchd_keeps_delay(self) -> None:
        entries = [
            sync.Entry("launchd", ("gui/501/a", "/tmp/a.plist"), 150),
            sync.Entry("app", ("/Applications/Zebra.app",), 200),
            sync.Entry("app", ("/Applications/Bartender 7.app",), 300),
            sync.Entry("app", ("/Applications/Alpha.app",), 180),
        ]
        placed = sync.schedule(entries, base=150, gap=12)
        delays = [d for d, _ in placed]
        self.assertEqual(delays[0], 150)
        apps = [(d, Path(e.parts[0]).name) for d, e in placed if e.kind == "app"]
        self.assertEqual(apps[-1][1], "Bartender 7.app")
        self.assertLess(apps[0][0], apps[-1][0])


class ParseConfTests(unittest.TestCase):
    def test_parse_skips_comments(self) -> None:
        text = (
            "# comment\n"
            "150\tlaunchd\tgui/501/x\t/Library/LaunchAgents/x.plist\n"
            "165\tapp\t/Applications/Warden.app\n"
        )
        entries = sync.parse_conf(text)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].kind, "launchd")
        self.assertEqual(entries[1].parts[0], "/Applications/Warden.app")


if __name__ == "__main__":
    unittest.main()
