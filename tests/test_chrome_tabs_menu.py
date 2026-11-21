#!/usr/bin/env python3
"""Tests for bin/chrome-tabs-menu: the pure parts (session-file discovery from lsof output, tab
filtering, grouping, the fake-dump read) and the --install checksum gate. The pop-up menu itself
needs a display and a pointer, so it is checked by hand, not here."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_loader = SourceFileLoader("chrome_tabs_menu", str(ROOT / "bin" / "chrome-tabs-menu"))
_spec = spec_from_loader("chrome_tabs_menu", _loader)
assert _spec is not None
ctm = module_from_spec(_spec)
_loader.exec_module(ctm)


def tab(url: str, title: str = "t") -> dict[str, str]:
    return {"url": url, "title": title}


class ParseLsof(unittest.TestCase):
    def test_newest_session_per_profile_and_tabs_files_ignored(self):
        text = "p1\nf12\nn/x/Chrome/Default/Sessions/Session_100\nn/x/Chrome/Default/Sessions/Session_300\nn/x/Chrome/Default/Sessions/Tabs_999\nn/x/Chrome/Profile 2/Sessions/Session_5\nn/x/Chrome/Default/Cookies"
        self.assertEqual(
            ctm.parse_lsof(text),
            {
                "Default": "/x/Chrome/Default/Sessions/Session_300",
                "Profile 2": "/x/Chrome/Profile 2/Sessions/Session_5",
            },
        )

    def test_numeric_not_lexical_order(self):
        text = "n/c/Default/Sessions/Session_9\nn/c/Default/Sessions/Session_10"
        self.assertEqual(
            ctm.parse_lsof(text), {"Default": "/c/Default/Sessions/Session_10"}
        )


class Filtering(unittest.TestCase):
    def test_only_http_tabs_are_openable(self):
        tabs = [
            tab("https://a.example/x"),
            tab("http://b.example"),
            tab("chrome://settings"),
            tab("about:blank"),
            tab("chrome-extension://abc/p.html"),
            tab("file:///tmp/x"),
            tab("https://"),
        ]
        ok, hidden = ctm.split_openable(tabs)
        self.assertEqual(
            [t["url"] for t in ok], ["https://a.example/x", "http://b.example"]
        )
        self.assertEqual(hidden, 5)

    def test_grouping_keeps_order_and_threshold(self):
        tabs = [tab(f"https://big.example/{i}") for i in range(ctm.GROUP_MIN)]
        tabs.insert(1, tab("https://one.example/"))
        tabs.append(tab("https://two.example/"))
        entries = ctm.group_by_host(tabs)
        self.assertEqual([label for label, _ in entries], ["big.example", "", ""])
        self.assertEqual(len(entries[0][1]), ctm.GROUP_MIN)
        self.assertEqual(entries[1][1][0]["url"], "https://one.example/")

    def test_below_threshold_stays_flat(self):
        tabs = [tab(f"https://h.example/{i}") for i in range(ctm.GROUP_MIN - 1)]
        self.assertTrue(all(label == "" for label, _ in ctm.group_by_host(tabs)))


class FakeDump(unittest.TestCase):
    def test_deleted_tabs_and_windows_dropped(self):
        payload = {
            "windows": [
                {
                    "tabs": [
                        {"url": "https://a.example", "title": "A", "deleted": False},
                        {"url": "https://gone.example", "title": "G", "deleted": True},
                    ]
                },
                {"deleted": True, "tabs": [{"url": "https://w.example", "title": "W"}]},
            ]
        }
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d, "dump")
            fake.write_text(
                "#!/bin/sh\ncat <<'EOF'\n" + json.dumps(payload) + "\nEOF\n"
            )
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            self.assertEqual(
                ctm.dump_windows(str(fake), "/nonexistent/Session_1"),
                [[{"url": "https://a.example", "title": "A"}]],
            )

    def test_failing_dump_raises(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d, "dump")
            fake.write_text("#!/bin/sh\necho boom >&2\nexit 3\n")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            with self.assertRaises(RuntimeError):
                ctm.dump_windows(str(fake), "/nonexistent/Session_1")


class Install(unittest.TestCase):
    def test_sha_mismatch_installs_nothing(self):
        with (
            tempfile.TemporaryDirectory() as home,
            mock.patch.dict(os.environ, {"HOME": home}),
        ):
            resp = mock.MagicMock()
            resp.__enter__.return_value.read.return_value = b"not the binary"
            with (
                mock.patch.object(ctm.urllib.request, "urlopen", return_value=resp),
                self.assertRaises(SystemExit),
            ):
                ctm.install()
            self.assertFalse(Path(home, ".local/bin/chrome-session-dump").exists())


if __name__ == "__main__":
    unittest.main()
