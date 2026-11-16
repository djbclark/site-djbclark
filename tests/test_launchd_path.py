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
import re
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
        self.assertEqual(APPLIER.read_text().splitlines()[0], "#!/bin/sh -p")
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

    def test_rejects_control_characters_in_any_entry(self) -> None:
        # The old `printf | grep -Eq` check passed an entry when ANY line of it
        # matched, so a newline smuggled arbitrary text (even `..`) past it.
        bad = [
            f"/ok\nevil:{BASE}",
            f"/ok\n../x:{BASE}",
            f"/ok\n/usr/bin\n:{BASE}",
            f"/ok\r:{BASE}",
            f"/ok\tx:{BASE}",
            f"{BASE}:/opt/x\n",
            f"/opt/x\n{BASE}",
        ]
        for value in bad:
            with self.subTest(value=value):
                p = self.run_applier("--check", value)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertIn("control character", p.stderr)
                self.assertEqual(p.stdout, "")

    def test_rejects_non_ascii_whatever_the_callers_locale(self) -> None:
        # sudo keeps LANG/LC_*: without the script's own LC_ALL=C, bracket ranges
        # in a UTF-8 locale admit accented and fullwidth letters (homoglyph dirs).
        env = {**os.environ, "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}
        for value in (f"/a\u00e9:{BASE}", f"/a\uff21:{BASE}", f"/usr/b\u0456n:{BASE}"):
            with self.subTest(value=value):
                p = subprocess.run(
                    [str(APPLIER), "--config-file", str(self.config), "--check", value],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=env,
                )
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertIn("absolute path of", p.stderr)

    def test_rejects_double_and_trailing_slashes(self) -> None:
        for value in (f"{BASE}:/usr/bin/", f"//usr/bin:{BASE}", f"/usr//bin:{BASE}", f"//:{BASE}"):
            with self.subTest(value=value):
                p = self.run_applier("--check", value)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertIn("no // and no trailing /", p.stderr)

    def test_imported_shell_functions_cannot_replace_tools(self) -> None:
        # `sh -p`: a BASH_FUNC_id%% in the environment must not override /usr/bin/id.
        env = {**os.environ, "BASH_FUNC_id%%": "() { echo 0; }"}
        p = subprocess.run(
            [str(APPLIER), "--config-file", str(self.config), "--check", BASE],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertEqual((p.returncode, p.stdout.strip()), (0, "would-change"), p.stderr)

    def test_a_clean_path_still_passes(self) -> None:
        p = self.run_applier("--check", f"/:/opt/homebrew/bin:/a_b/c-d.e+f@g:{BASE}")
        self.assertEqual((p.returncode, p.stdout.strip()), (0, "would-change"), p.stderr)

    def test_stored_value_compare_is_exact(self) -> None:
        want = f"/opt/homebrew/bin:{BASE}"
        self.config.write_bytes(plistlib.dumps({"PathEnvironmentVariable": want + ":"}))
        p = self.run_applier("--check", want)
        self.assertEqual(p.stdout.strip(), "would-change")

    def test_caller_path_cannot_substitute_tools(self) -> None:
        # The applier runs as root through NOPASSWD sudo: a PATH-resolved tool
        # in the caller's (or brew's) directory must never be picked up.
        # A fake `id` that claims uid 0 would make --config-file be refused.
        with tempfile.TemporaryDirectory() as d:
            fake = pathlib.Path(d) / "id"
            fake.write_text("#!/bin/sh\necho 0\n")
            fake.chmod(0o755)
            env = {**os.environ, "PATH": f"{d}:{os.environ.get('PATH', '')}"}
            p = subprocess.run(
                [str(APPLIER), "--config-file", str(self.config), "--check", BASE],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
        self.assertEqual((p.returncode, p.stdout.strip()), (0, "would-change"), p.stderr)

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


class RootScriptPathTests(unittest.TestCase):
    """The applier runs through NOPASSWD sudo: no user-owned brew tools (2026-10-15)."""

    def test_applier_uses_only_system_tools(self) -> None:
        text = APPLIER.read_text(encoding="utf-8")
        code = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertNotIn("/opt/homebrew", code)
        lines = [ln for ln in code.splitlines() if ln.strip()]
        self.assertEqual(lines[0], "PATH=/usr/bin:/bin:/usr/sbin:/sbin")
        self.assertEqual(lines[1:4], ["export PATH", "LC_ALL=C", "export LC_ALL"])
        self.assertEqual(sum("PATH=" in ln for ln in lines), 1, "PATH set twice")
        self.assertIsNone(
            re.search(
                r"\bg(awk|date|sed|grep|tail|head|mktemp|stat|find|xargs|sort|cut|tr|wc|readlink|realpath|timeout|ls|touch|chmod|chown|ln|cp|mv|rm|base64)\b",
                code,
            ),
            "a g* tool in a root-run script",
        )
        self.assertNotIn("grep", code, "validation must be whole-string `case`, not a line matcher")


class SyncTests(unittest.TestCase):
    def test_dedupe_keeps_first_occurrence_and_drops_relative(self) -> None:
        self.assertEqual(
            sync.dedupe("/a/bin:/b/:.:/a/bin:relative:/b:/usr/bin::/bin"),
            "/a/bin:/b:/usr/bin:/bin",
        )

    def test_dedupe_output_always_passes_the_applier_slash_rules(self) -> None:
        self.assertEqual(sync.dedupe("/opt//bin:/opt/bin/:/a///b//:/"), "/opt/bin:/a/b:/")

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
