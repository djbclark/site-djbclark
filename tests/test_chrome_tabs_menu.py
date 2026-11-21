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


def record(payload: bytes) -> bytes:
    return len(payload).to_bytes(2, "little") + payload


class TrimSession(unittest.TestCase):
    HEADER = b"SNSS" + (3).to_bytes(4, "little")

    def test_whole_file_is_unchanged(self):
        data = self.HEADER + record(b"\x06abc") + record(b"\x07defg")
        self.assertEqual(ctm.trim_to_last_record(data), data)

    def test_half_written_last_record_is_cut(self):
        whole = self.HEADER + record(b"\x06abc")
        for cut in range(1, 7):
            data = whole + record(b"\x07defgh")[:cut]
            self.assertEqual(ctm.trim_to_last_record(data), whole, cut)

    def test_non_snss_data_is_left_alone(self):
        self.assertEqual(ctm.trim_to_last_record(b"not a session"), b"not a session")


class RealUrl(unittest.TestCase):
    def test_web_urls_pass_through(self):
        self.assertEqual(
            ctm.real_url("https://a.example/p?url=https://b.example"),
            "https://a.example/p?url=https://b.example",
        )

    def test_great_suspender_unencoded_last_param(self):
        u = "chrome-extension://abc/suspended.html#ttl=T&pos=0&uri=https://a.example/x?y=1&z=2"
        self.assertEqual(ctm.real_url(u), "https://a.example/x?y=1&z=2")

    def test_park_page_encoded_param(self):
        u = "chrome-extension://abc/park.html?title=T&url=https%3A%2F%2Fa.example%2Fx%3Fy%3D1&favicon=f"
        self.assertEqual(ctm.real_url(u), "https://a.example/x?y=1")

    def test_extension_page_without_target_is_left_and_then_hidden(self):
        u = "chrome-extension://abc/options.html"
        self.assertEqual(ctm.real_url(u), u)
        self.assertEqual(ctm.split_openable([{"url": u, "title": "x"}]), ([], 1))

    def test_suspended_tab_becomes_openable(self):
        ok, hidden = ctm.split_openable(
            [
                {
                    "url": "chrome-extension://abc/suspended.html#uri=https://a.example/",
                    "title": "T",
                }
            ]
        )
        self.assertEqual((ok[0]["url"], hidden), ("https://a.example/", 0))


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
            session = Path(d, "Session_1")
            session.write_bytes(b"SNSS" + (3).to_bytes(4, "little"))
            fake.write_text(
                "#!/bin/sh\ncat <<'EOF'\n" + json.dumps(payload) + "\nEOF\n"
            )
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            self.assertEqual(
                ctm.dump_windows(str(fake), str(session)),
                [[{"url": "https://a.example", "title": "A"}]],
            )

    def test_failing_dump_raises(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d, "dump")
            session = Path(d, "Session_1")
            session.write_bytes(b"SNSS" + (3).to_bytes(4, "little"))
            fake.write_text("#!/bin/sh\necho boom >&2\nexit 3\n")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            with self.assertRaises(RuntimeError):
                ctm.dump_windows(str(fake), str(session))


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
