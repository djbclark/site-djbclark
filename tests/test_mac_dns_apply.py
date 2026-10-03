"""roles/mac_dns/files/mac-dns-apply: input validation and check mode.

Runs the real script unprivileged. Nothing here writes: invalid inputs must
exit 2 before any side effect, and --check is read-only by contract.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "roles" / "mac_dns" / "files" / "mac-dns-apply"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCRIPT), *args], capture_output=True, text=True, check=False)


@unittest.skipUnless(sys.platform == "darwin", "networksetup/resolver are macOS-only")
class MacDnsApplyTests(unittest.TestCase):
    def test_script_is_posix_sh_and_executable(self) -> None:
        self.assertEqual(SCRIPT.read_text().splitlines()[0], "#!/bin/sh")
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        self.assertEqual(subprocess.run(["sh", "-n", str(SCRIPT)], check=False).returncode, 0)

    def test_rejects_bad_domain(self) -> None:
        for bad in ("Bad Domain", "../../etc/passwd", "-x.ts.net", "ts.net.", "singlelabel", "a..b"):
            with self.subTest(bad=bad):
                p = run("--check", "resolver", bad, "1.2.3.4")
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertIn("invalid domain", p.stderr)

    def test_rejects_bad_nameserver(self) -> None:
        for bad in ("1.2.3.4;rm -rf /", "example.com", "1.2.3", "100.100.100.100 extra", "::g"):
            with self.subTest(bad=bad):
                p = run("--check", "resolver", "example.ts.net", bad)
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertIn("invalid nameserver", p.stderr)

    def test_accepts_ipv4_and_ipv6(self) -> None:
        p = run("--check", "resolver", "example.ts.net", "100.100.100.100", "fd7a:115c:a1e0::53")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(p.stdout.strip(), {"unchanged", "would-change"})

    def test_rejects_unknown_network_service(self) -> None:
        p = run("--check", "searchdomains", "Not A Service", "example.com")
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn("unknown network service", p.stderr)

    def test_resolver_remove_of_absent_file_is_unchanged(self) -> None:
        p = run("--check", "resolver-remove", "definitely-absent.example.net")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), "unchanged")

    def test_refuses_to_write_without_root(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("running as root")
        p = run("resolver", "definitely-absent.example.net", "1.2.3.4")
        self.assertEqual(p.returncode, 1)
        self.assertIn("must run as root", p.stderr)

    def test_usage_errors(self) -> None:
        self.assertEqual(run().returncode, 2)
        self.assertEqual(run("bogus").returncode, 2)
        self.assertEqual(run("resolver", "example.ts.net").returncode, 2)


if __name__ == "__main__":
    unittest.main()
