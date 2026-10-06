"""roles/launchd_path: applier input validation and check mode, plus bin/launchd-path-sync.

Runs the real applier unprivileged against a temporary config plist. Nothing here
writes: invalid input must exit 2 before any side effect, and --check is read-only.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import pathlib
import plistlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
APPLIER = ROOT / "roles" / "launchd_path" / "files" / "launchd-path-apply"
SYNC = ROOT / "bin" / "launchd-path-sync"
BASE = "/usr/bin:/bin:/usr/sbin:/sbin"

_loader = importlib.machinery.SourceFileLoader("launchd_path_sync", str(SYNC))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
assert _spec
sync = importlib.util.module_from_spec(_spec)
_loader.exec_module(sync)


@unittest.skipUnless(sys.platform == "darwin", "launchctl/PlistBuddy are macOS-only")
class ApplierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.config = pathlib.Path(self.tmp.name) / "user.plist"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_applier(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(APPLIER), "--config-file", str(self.config), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_script_is_posix_sh_and_executable(self) -> None:
        self.assertEqual(APPLIER.read_text().splitlines()[0], "#!/bin/sh")
        self.assertTrue(os.access(APPLIER, os.X_OK))
        self.assertEqual(
            subprocess.run(["sh", "-n", str(APPLIER)], check=False).returncode, 0
        )

    def test_rejects_invalid_paths(self) -> None:
        bad = {
            "": "empty",
            f"{BASE}:": "empty entry",
            f"relative/bin:{BASE}": "absolute path",
            f"/tmp/x y:{BASE}": "absolute path",
            f"/usr/../tmp:{BASE}": "no . or ..",
            f"/opt/bin:/opt/bin:{BASE}": "duplicate",
            "/usr/bin:/bin:/usr/sbin": "must include /sbin",
            f"/usr/*:{BASE}": "absolute path",
        }
        for value, message in bad.items():
            with self.subTest(value=value):
                p = self.run_applier("--check", value)
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertIn(message, p.stderr)
                self.assertEqual(p.stdout, "")

    def test_check_reports_would_change_when_unset(self) -> None:
        p = self.run_applier("--check", f"/opt/homebrew/bin:{BASE}")
        self.assertEqual(
            (p.returncode, p.stdout.strip()), (0, "would-change"), p.stderr
        )

    def test_check_reports_unchanged_when_stored_value_matches(self) -> None:
        want = f"/opt/homebrew/bin:{BASE}"
        self.config.write_bytes(plistlib.dumps({"PathEnvironmentVariable": want}))
        p = self.run_applier("--check", want)
        self.assertEqual((p.returncode, p.stdout.strip()), (0, "unchanged"), p.stderr)
        p = self.run_applier("--check", f"/usr/local/bin:{BASE}")
        self.assertEqual(p.stdout.strip(), "would-change")

    def test_apply_without_root_refuses(self) -> None:
        if os.getuid() == 0:
            self.skipTest("running as root")
        p = self.run_applier(f"/opt/homebrew/bin:{BASE}")
        self.assertEqual(p.returncode, 1)
        self.assertIn("must run as root", p.stderr)


class SyncTests(unittest.TestCase):
    def test_dedupe_keeps_first_occurrence_and_drops_relative(self) -> None:
        self.assertEqual(
            sync.dedupe("/a/bin:/b/:.:/a/bin:relative:/b:/usr/bin::/bin"),
            "/a/bin:/b:/usr/bin:/bin",
        )

    @unittest.skipUnless(sys.platform == "darwin", "macOS login shell")
    def test_desired_path_passes_the_applier(self) -> None:
        want = sync.login_shell_path()
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run(
                [
                    str(APPLIER),
                    "--config-file",
                    str(pathlib.Path(d) / "user.plist"),
                    "--check",
                    want,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == "__main__":
    unittest.main()
