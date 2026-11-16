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


ALLOW = pathlib.Path(__file__).resolve().parent / "_mac_dns_allow.txt"
ALLOW_CONTENT = "nameserver 100.100.100.100\nnameserver fd7a:115c:a1e0::53\nresolver example.ts.net\nsearch example.ts.net\n"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    ALLOW.write_text(ALLOW_CONTENT)
    return subprocess.run([str(SCRIPT), "--allow-file", str(ALLOW), *args], capture_output=True, text=True, check=False)


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

    def test_rejects_anything_not_in_allow_list(self) -> None:
        p = run("--check", "resolver", "evil.ts.net", "100.100.100.100")
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn("not in", p.stderr)
        p = run("--check", "resolver", "example.ts.net", "1.2.3.4")
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn("nameserver '1.2.3.4' is not in", p.stderr)
        p = run("--check", "searchdomains", "Wi-Fi", "evil.example.com")
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn("search 'evil.example.com' is not in", p.stderr)

    def test_missing_allow_list_is_fatal(self) -> None:
        p = subprocess.run([str(SCRIPT), "--allow-file", "/nonexistent/allow", "--check", "resolver", "example.ts.net", "100.100.100.100"],
                           capture_output=True, text=True, check=False)
        self.assertEqual(p.returncode, 2)
        self.assertIn("allow-list", p.stderr)

    def test_rejects_bad_nameserver(self) -> None:
        for bad in ("100.100.100.100;rm -rf /", "example.com", "1.2.3", "100.100.100.100 extra", "::g"):
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

    def test_dnsservers_validation(self) -> None:
        p = run("--check", "dnsservers", "Not A Service", "Empty")
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn("unknown network service", p.stderr)
        for bad in ("1.1.1.1", "100.100.100.100", "not-an-ip"):
            p = run("--check", "dnsservers", "Wi-Fi", bad)
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertIn("accepts only Empty", p.stderr)
        p = run("--check", "dnsservers", "Wi-Fi", "Empty")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(p.stdout.strip(), {"unchanged", "would-change"})

    def test_resolver_remove_of_absent_allowed_domain_is_unchanged(self) -> None:
        p = run("--check", "resolver-remove", "example.ts.net")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), "unchanged")

    def test_refuses_to_write_without_root(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("running as root")
        p = run("resolver", "example.ts.net", "100.100.100.100")
        self.assertEqual(p.returncode, 1)
        self.assertIn("must run as root", p.stderr)

    def test_allow_file_flag_rejected_as_root_is_documented(self) -> None:
        self.assertIn("--allow-file is honoured only when NOT running as root", SCRIPT.read_text())

    def test_render_allow_list(self) -> None:
        renderer = SCRIPT.parent / "render-allow-list.py"
        gv = pathlib.Path(__file__).resolve().parents[1] / "inventory" / "group_vars" / "all.yml"
        p = subprocess.run(["uv", "run", "--quiet", "--with", "pyyaml", "python3", str(renderer), str(gv)],
                           capture_output=True, text=True, check=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        lines = p.stdout.splitlines()
        self.assertIn("resolver greyhound-sidemirror.ts.net", lines)
        self.assertIn("nameserver 100.100.100.100", lines)
        self.assertEqual(lines, sorted(lines))

    def test_usage_errors(self) -> None:
        self.assertEqual(run().returncode, 2)
        self.assertEqual(run("bogus").returncode, 2)
        self.assertEqual(run("resolver", "example.ts.net").returncode, 2)
        self.assertEqual(run("dnsservers", "Wi-Fi").returncode, 2)

    def test_newline_embedded_args_cannot_bypass_the_allow_list(self) -> None:
        # Review B1 (2026-11-16): grep matches if ANY line matches, so each of
        # these used to print would-change. Now each must exit 2, no side effect.
        cases = {
            "B1a nameserver": ("resolver", "example.ts.net", "6.6.6.6\nnameserver 100.100.100.100"),
            "B1b domain traversal": ("resolver", "/../../../tmp/zz\nresolver example.ts.net\nexample.ts.net", "100.100.100.100"),
            "B1b remove": ("resolver-remove", "/../../../tmp/zz\nresolver example.ts.net\nexample.ts.net"),
            "B1c domain directive": ("resolver", "example.ts.net", "100.100.100.100\ndomain google.com"),
            "B1d search": ("searchdomains", "Wi-Fi", "evil.com\nsearch example.ts.net"),
            "B1d service": ("searchdomains", "Wi-Fi\nWi-Fi", "example.ts.net"),
            "CR": ("resolver", "example.ts.net", "100.100.100.100\r"),
            "tab": ("resolver", "example.ts.net\t", "100.100.100.100"),
            "leading dash service": ("searchdomains", "-setdnsservers", "example.ts.net"),
        }
        for name, args in cases.items():
            with self.subTest(name):
                p = run("--check", *args)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertNotIn("would-change", p.stdout)

    def test_path_is_pinned_to_system_dirs(self) -> None:
        # Review B2: root runs this via NOPASSWD sudo; a user-owned brew dir on
        # its PATH, or a g* tool, is a passwordless-root path.
        code = [ln for ln in SCRIPT.read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        self.assertEqual(code[0], "set -eu")
        self.assertEqual(code[1], "PATH=/usr/bin:/bin:/usr/sbin:/sbin")
        body = "\n".join(code)
        self.assertEqual(body.count("PATH="), 1)
        for brew in ("/opt/homebrew", "/usr/local/bin", "/usr/local/opt"):
            self.assertNotIn(brew, body)
        self.assertNotRegex(body, r"\bg(awk|date|sed|grep|tail|head|mktemp|stat|find|xargs|sort|cut|tr|wc|readlink|realpath|timeout|ls|touch|chmod|chown|ln|cp|mv|rm|base64)\b")

    @classmethod
    def tearDownClass(cls) -> None:
        ALLOW.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
