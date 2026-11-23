"""bin/approval-gate: the one place that decides whether the sudo-ask window covers a gate.

The gate loads the root helper's plain functions from HELPER_PATH. Here HELPER_PATH is the repo's copy of the
helper, the trusted uid is this user, and the helper's hard-coded grant paths are patched to a temp boundary.
Nothing touches /var/db, /etc, /usr/local or sudo; `ask` is tested with absolute-path fakes (SUDO, SUDO_ASK).
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import stat
import subprocess
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
GATE = ROOT / "bin" / "approval-gate"
HELPER = ROOT / "roles" / "sudo_ask_grant" / "files" / "sudo-ask-granted"
REGISTRY = ROOT / "config" / "approval-gates.toml"

_loader = importlib.machinery.SourceFileLoader("approval_gate", str(GATE))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
assert _spec
gate = importlib.util.module_from_spec(_spec)
_loader.exec_module(gate)


class GateBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = pathlib.Path(self.tmp.name)
        self.dir = base / "state"
        self.dir.mkdir(mode=0o755)
        os.chmod(self.dir, 0o755)
        gate._helper = None
        self.addCleanup(setattr, gate, "_helper", None)
        for k, v in (("HELPER_PATH", str(HELPER)), ("TRUSTED_UID", os.getuid()), ("LOG", str(base / "gatelog"))):
            p = mock.patch.object(gate, k, v)
            p.start()
            self.addCleanup(p.stop)
        h = gate.load_helper()
        assert h is not None
        for k, v in (("GRANT_DIR", str(self.dir)), ("GRANT_FILE", str(self.dir / "grant")),
                     ("LOG_FILE", str(base / "grant.log")), ("OWNER_UID", os.getuid())):
            p = mock.patch.object(h, k, v)
            p.start()
            self.addCleanup(p.stop)
        self.h = h
        self.now = int(time.time())

    def open_window(self, secs=3600, dur=None, mode=0o644):
        gra, exp = self.now, self.now + secs
        d = {"expires_utc": self.h.iso(exp), "granted_utc": self.h.iso(gra), "granted_by_uid": 501,
             "duration_s": dur if dur is not None else secs, "nonce": "ab" * 16}
        f = self.dir / "grant"
        f.write_text(json.dumps(d))
        os.chmod(f, mode)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = gate.main(["approval-gate", *argv])
        return rc, out.getvalue(), err.getvalue()


class RegistryTests(unittest.TestCase):
    EXPECTED_WINDOW_OK = {
        "sudo-ask",
        "bgrun-approve-local",
        "bgrun-ticket",
        "load-watch-ci-local",
        "tired-pmset",
        "neofinder-spotlight-batch",
        "neofinder-just-sudo",
        "sip-doit-with-sudo",
        "quiet-mac-ops",
    }
    EXPECTED_ALWAYS_PROMPT = {
        "denylist-sudoers-pam",
        "denylist-grant-helper",
        "denylist-secretspec-broker",
        "denylist-tcc-keychain",
        "denylist-disk-erase",
        "denylist-csrutil-nvram",
        "denylist-accounts",
        "ade-merge-ready-approve-post",
        "quiet-mac-install-root",
        "mac-dns-setup",
        "launchd-path-setup",
        "container-route-setup",
        "tart-route-setup",
        "mds-xpc-clients-setup",
        "neofinder-index-setup",
        "sudo-secretspec-admin",
        "sudo-secretspec-backup",
        "op-sync-grok",
        "ade-install-keys-collect",
        "gui-hog-dialog",
        "quiet-mac-mobileconfig",
        "ade-auto-permit-prompts",
        "sudo-askpass-osascript",
    }

    def test_seed_registry_is_well_formed(self) -> None:
        raw_entries = gate.parse_registry(REGISTRY.read_text())["gate"]
        g = gate.gates()
        self.assertTrue(g)
        self.assertEqual(len(raw_entries), len(g), "duplicate gate name in registry")
        for name, e in g.items():
            self.assertEqual(set(e), {"name", "owner", "policy", "max_ttl"}, name)
            self.assertIn(e["policy"], ("window-ok", "always-prompt"), name)
            self.assertIsInstance(e["max_ttl"], int, name)
            self.assertNotIsInstance(e["max_ttl"], bool, name)
            self.assertGreaterEqual(e["max_ttl"], 0, name)
            owner = e["owner"]
            if ":" in owner:
                repo, rel = owner.split(":", 1)
                self.assertIn(repo, ("djbclark-ade", "sudo-secretspec"), name)
                self.assertTrue(rel and not rel.startswith("/") and ".." not in pathlib.PurePosixPath(rel).parts, owner)
            else:
                self.assertTrue((ROOT / owner).exists(), "owner file of %s is missing: %s" % (name, owner))
        window_ok = {n for n, e in g.items() if e["policy"] == "window-ok"}
        always_prompt = {n for n, e in g.items() if e["policy"] == "always-prompt"}
        self.assertEqual(window_ok, self.EXPECTED_WINDOW_OK)
        self.assertEqual(always_prompt, self.EXPECTED_ALWAYS_PROMPT)
        denies = [n for n in always_prompt if n.startswith("denylist-")]
        self.assertGreaterEqual(len(denies), 5)

    def test_fallback_parser_agrees_with_tomllib(self) -> None:
        try:
            import tomllib
        except ImportError:
            self.skipTest("no tomllib in this Python (< 3.11)")
        text = REGISTRY.read_text()
        self.assertEqual(gate.parse_registry(text), tomllib.loads(text))
        with self.assertRaises(ValueError):
            gate.parse_registry("name = 'x'\n")
        with self.assertRaises(ValueError):
            gate.parse_registry('[[gate]]\nname = "a" "b"\n')

    def test_registry_loads_without_tomllib(self) -> None:
        want = gate.gates()
        with mock.patch.object(gate, "tomllib", None):
            self.assertEqual(gate.gates(), want)

    def test_unreadable_registry_means_nothing_is_covered(self) -> None:
        with mock.patch.object(gate, "REGISTRY", "/nonexistent/gates.toml"):
            self.assertEqual(gate.gates(), {})


class DecideTests(GateBase):
    def test_open_window_covers_a_window_ok_gate(self) -> None:
        self.open_window(1800)
        ok, why, info = gate.decide("sudo-ask", now=self.now)
        self.assertTrue(ok, why)
        self.assertEqual(info["ttl"], 1800)
        self.assertEqual(info["expires_epoch"], self.now + 1800)

    def test_closed_window_prompts(self) -> None:
        ok, why, _ = gate.decide("sudo-ask", now=self.now)
        self.assertFalse(ok)
        self.assertIn("no", why.lower())

    def test_expired_window_prompts(self) -> None:
        self.open_window(60)
        ok, _, _ = gate.decide("sudo-ask", now=self.now + 61)
        self.assertFalse(ok)

    def test_damaged_grant_prompts(self) -> None:
        self.open_window(3600, mode=0o666)
        self.assertFalse(gate.decide("sudo-ask", now=self.now)[0])
        self.open_window(3600, dur=7200)  # duration does not match the expiry
        self.assertFalse(gate.decide("sudo-ask", now=self.now)[0])

    def test_unknown_gate_prompts(self) -> None:
        self.open_window()
        ok, why, _ = gate.decide("no-such-gate", now=self.now)
        self.assertFalse(ok)
        self.assertIn("unknown gate", why)

    def test_always_prompt_gates_are_never_covered(self) -> None:
        self.open_window()
        for name, e in gate.gates().items():
            if e["policy"] == "always-prompt":
                with self.subTest(name):
                    self.assertFalse(gate.decide(name, now=self.now)[0])

    def test_ttl_is_capped_by_gate_and_caller(self) -> None:
        self.open_window(7200)
        self.assertEqual(gate.decide("bgrun-approve-local", now=self.now)[2]["ttl"], 3600)  # registry max_ttl
        self.assertEqual(gate.decide("bgrun-ticket", max_ttl=900, now=self.now)[2]["ttl"], 900)  # caller cap
        self.assertEqual(gate.decide("bgrun-ticket", max_ttl=99999, now=self.now)[2]["ttl"], 7200)  # window ends first
        self.assertEqual(gate.decide("bgrun-approve-local", max_ttl=300, now=self.now)[2]["ttl"], 300)

    def test_a_program_written_after_the_grant_prompts_through_the_gate(self) -> None:   # MED-2 B1, gate side
        self.open_window()
        script = pathlib.Path(self.tmp.name) / "made-in-the-window.py"
        script.write_text("print(1)\n")
        os.utime(script, (self.now + 5, self.now + 5))
        with mock.patch.object(self.h, "agent_writable", return_value=False):
            ok, why, _ = gate.decide("sudo-ask", cmd=["python3", str(script)], now=self.now)
        self.assertFalse(ok)
        self.assertIn("changed after the window was granted", why)
        self.assertEqual(self.h.GRANTED_EPOCH, self.now)

    def test_denylisted_command_prompts(self) -> None:
        self.open_window()
        self.assertFalse(gate.decide("sudo-ask", cmd=["visudo"], now=self.now)[0])
        self.assertFalse(gate.decide("sudo-ask", cmd=["sh", "-c", "echo $(visudo"], now=self.now)[0])
        self.assertTrue(gate.decide("sudo-ask", cmd=["/usr/bin/true"], now=self.now)[0])

    def repoint(self):
        """A freshly loaded helper module (the gate forgot it) gets the same temp boundary, so only the trust check can close the window."""
        gate._helper = None
        h = gate.load_helper()
        if h is None:
            return None
        for k, v in (("GRANT_DIR", str(self.dir)), ("GRANT_FILE", str(self.dir / "grant")),
                     ("LOG_FILE", str(pathlib.Path(self.tmp.name) / "grant.log")), ("OWNER_UID", os.getuid())):
            setattr(h, k, v)
        return h

    def test_missing_or_untrusted_helper_means_no_window(self) -> None:
        self.open_window()
        self.assertTrue(self.repoint())
        self.assertTrue(gate.decide("sudo-ask", now=self.now)[0])  # control: the same setup is open when trusted
        with mock.patch.object(gate, "HELPER_PATH", "/nonexistent/helper"):
            self.assertIsNone(self.repoint())
            self.assertFalse(gate.decide("sudo-ask", now=self.now)[0])
        with mock.patch.object(gate, "TRUSTED_UID", os.getuid() + 1):  # owned by someone else
            self.assertIsNone(self.repoint())
            self.assertFalse(gate.decide("sudo-ask", now=self.now)[0])
        copy = pathlib.Path(self.tmp.name) / "helper-copy"
        copy.write_text(HELPER.read_text())
        copy.chmod(0o775)  # group-writable
        with mock.patch.object(gate, "HELPER_PATH", str(copy)):
            self.assertIsNone(self.repoint())
            self.assertFalse(gate.decide("sudo-ask", now=self.now)[0])


class CliTests(GateBase):
    """main() with the real clock (the helper reads time.time itself through gate.window)."""

    def test_status_open_and_closed(self) -> None:
        rc, out, _ = self.run_main("status")
        self.assertEqual(rc, 1)
        self.assertIn("open=0", out)
        self.open_window(3600)
        rc, out, _ = self.run_main("status")
        self.assertEqual(rc, 0)
        kv = dict(ln.split("=", 1) for ln in out.splitlines())
        self.assertEqual(kv["open"], "1")
        self.assertIn(int(kv["remaining_s"]), range(3590, 3601))
        self.assertEqual(int(kv["expires_epoch"]), self.now + 3600)
        self.assertRegex(kv["expires_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_check_exit_codes_and_output(self) -> None:
        rc, out, err = self.run_main("check", "--gate", "sudo-ask")
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("prompt", err)
        self.open_window(3600)
        rc, out, _ = self.run_main("check", "--gate", "bgrun-ticket", "--max-ttl", "600")
        self.assertEqual(rc, 0)
        kv = dict(ln.split("=", 1) for ln in out.splitlines())
        self.assertEqual(int(kv["ttl"]), 600)
        self.assertEqual(int(kv["expires_epoch"]), self.now + 3600)  # the window's, not the capped ttl
        self.assertEqual(self.run_main("check", "--gate", "denylist-sudoers-pam")[0], 1)
        self.assertEqual(self.run_main("check", "--gate", "sudo-ask", "--", "visudo")[0], 1)
        self.assertEqual(self.run_main("check", "--gate", "sudo-ask", "--", "/usr/bin/true")[0], 0)

    def test_check_every_registered_gate_honours_its_policy_in_an_open_window(self) -> None:
        self.open_window(3600)
        for name, entry in gate.gates().items():
            with self.subTest(gate=name, policy=entry["policy"]):
                if entry["policy"] == "window-ok":
                    rc, out, err = self.run_main("check", "--gate", name, "--", "/usr/bin/true")
                    self.assertEqual(rc, 0, err)
                    self.assertIn("ttl=", out)
                    rc_deny, _, _ = self.run_main("check", "--gate", name, "--", "visudo")
                    self.assertEqual(rc_deny, 1)
                else:
                    rc_plain, out_plain, err_plain = self.run_main("check", "--gate", name)
                    self.assertEqual((rc_plain, out_plain), (1, ""))
                    self.assertIn("always prompts", err_plain)
                    rc_cmd, out_cmd, _ = self.run_main("check", "--gate", name, "--", "/usr/bin/true")
                    self.assertEqual((rc_cmd, out_cmd), (1, ""))

    def test_usage_errors_exit_2(self) -> None:
        for argv in ((), ("bogus",), ("status", "--gate", "x"), ("check",), ("check", "--gate"),
                     ("check", "--gate", "sudo-ask", "--max-ttl", "0"), ("check", "--gate", "sudo-ask", "--max-ttl", "x"),
                     ("check", "--gate", "sudo-ask", "extra"), ("check", "--gate", "sudo-ask", "--"),
                     ("ask", "--gate", "sudo-ask", "--", "true"), ("ask", "--gate", "sudo-ask", "--reason", "r"),
                     ("ask", "--reason", "r", "--", "true")):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_main(*argv)[0], 2)

    def ask(self, window: bool):
        """Run `ask` with os.execv captured: -> the execv call (path, argv)."""
        if window:
            self.open_window()
        calls = []

        def fake_exec(path, argv):
            calls.append((path, argv))
            raise SystemExit(0)

        with mock.patch.object(gate.os, "execv", fake_exec), mock.patch.object(gate, "SUDO", "/fake/sudo"), \
                mock.patch.object(gate, "SUDO_ASK", "/fake/sudo-ask"):
            with self.assertRaises(SystemExit):
                self.run_main("ask", "--gate", "sudo-ask", "--reason", "why not", "--", "/usr/bin/true", "a b")
        self.assertEqual(len(calls), 1)
        return calls[0]

    def test_ask_in_a_window_goes_through_the_helper_without_sudo_ask(self) -> None:
        path, argv = self.ask(True)
        self.assertEqual(path, "/fake/sudo")
        self.assertEqual(argv, ["/fake/sudo", "-n", str(HELPER), "exec", "--", "/usr/bin/true", "a b"])
        self.assertIn("WINDOW", pathlib.Path(gate.LOG).read_text())

    def test_ask_without_a_window_goes_to_the_normal_dialog(self) -> None:
        path, argv = self.ask(False)
        self.assertEqual((path, argv), ("/fake/sudo-ask", ["/fake/sudo-ask", "/usr/bin/true", "a b"]))
        self.assertIn("PROMPT(", pathlib.Path(gate.LOG).read_text())

    def test_log_is_private_to_the_command_text_it_was_given(self) -> None:
        self.ask(False)
        self.assertNotIn("\n\n", pathlib.Path(gate.LOG).read_text())


class SourceTests(unittest.TestCase):
    def test_executable_and_not_a_second_implementation(self) -> None:
        self.assertTrue(GATE.stat().st_mode & stat.S_IXUSR)
        src = GATE.read_text()
        for name in ("def read_grant", "def parse_duration", "PROTECTED"):  # the policy stays in the helper
            self.assertNotIn(name, src)
        self.assertIn("read_grant", src)
        self.assertIn("evaluate", src)

    def test_real_process_reports_no_window_when_no_helper_is_installed(self) -> None:
        # Real script, real HELPER_PATH: on a machine without the install the answer is "prompt" (exit 1).
        if os.path.exists("/usr/local/libexec/sudo-ask-granted"):
            self.skipTest("a helper is installed here")
        env = {"PATH": "/usr/bin:/bin", "HOME": tempfile.gettempdir()}
        p = subprocess.run([str(GATE), "check", "--gate", "sudo-ask"], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(p.returncode, 1, p.stderr)


if __name__ == "__main__":
    unittest.main()
