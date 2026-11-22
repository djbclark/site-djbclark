"""roles/sudo_ask_grant: the root helper's policy and grant-file checks, the sudo-ask client's
window path, and the setup script's read-only modes.

Nothing here touches the live privileged boundary. The helper is loaded in-process and its hard-coded
paths are patched to a temp directory (the installed file has no hook for that: no env var, no
argument). The client runs as a PATCHED COPY whose sudo, osascript, helper and hermes-ping are
absolute-path fakes (never rely on PATH order: the shell startup reorders it). The setup script runs
only --print and --check.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import pathlib
import re
import stat
import subprocess
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
HELPER = ROOT / "roles" / "sudo_ask_grant" / "files" / "sudo-ask-granted"
SETUP = ROOT / "roles" / "sudo_ask_grant" / "files" / "sudo-ask-grant-setup.sh"
CLIENT = ROOT / "bin" / "sudo-ask"
PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

_loader = importlib.machinery.SourceFileLoader("sudo_ask_granted", str(HELPER))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
assert _spec
mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(mod)


class GrantBase(unittest.TestCase):
    """A temp 'boundary': grant dir, grant file and log under a temp prefix."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name) / "state"
        self.dir.mkdir(mode=0o755)
        os.chmod(self.dir, 0o755)
        self.work = pathlib.Path(self.tmp.name) / "work"
        self.work.mkdir()
        patches = {
            "GRANT_DIR": str(self.dir),
            "GRANT_FILE": str(self.dir / "grant"),
            "LOG_FILE": str(pathlib.Path(self.tmp.name) / "grant.log"),
            "OWNER_UID": os.getuid(),
        }
        for k, v in patches.items():
            p = mock.patch.object(mod, k, v)
            p.start()
            self.addCleanup(p.stop)
        self.now = int(time.time())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def put(self, expires_in=3600, granted_ago=0, dur=None, mode=0o644, **over):
        gra = self.now - granted_ago
        exp = self.now + expires_in
        d = {"expires_utc": mod.iso(exp), "granted_utc": mod.iso(gra),
             "granted_by_uid": 501, "duration_s": dur if dur is not None else exp - gra,
             "nonce": "ab" * 16}
        d.update(over)
        f = self.dir / "grant"
        f.write_text(json.dumps(d))
        os.chmod(f, mode)

    def read(self):
        return mod.read_grant(self.now)


class DurationTests(unittest.TestCase):
    def test_accepted(self) -> None:
        for text, secs in {"30m": 1800, "2h": 7200, "8h": 28800, "24h": 86400, "1d": 86400,
                           "60s": 60, "1440m": 86400, "008h": 28800}.items():
            with self.subTest(text=text):
                self.assertEqual(mod.parse_duration(text), secs)

    def test_refused(self) -> None:
        for text in ["25h", "1441m", "2d", "0m", "59s", "8", "h", "-1h", "8H", "1.5h", "", "8h ",
                     "8 h", "999999d", "0x10m", "1h30m", "∞"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                mod.parse_duration(text)


class GrantFileTests(GrantBase):
    def test_valid_window_is_open(self) -> None:
        self.put()
        ok, why, d = self.read()
        self.assertTrue(ok, why)
        self.assertEqual(d["remaining_s"], 3600)

    def test_missing_is_closed(self) -> None:
        ok, why, _ = self.read()
        self.assertFalse(ok)
        self.assertIn("no window", why)

    def test_expired_is_closed(self) -> None:
        self.put(expires_in=-5, granted_ago=3605)
        ok, why, _ = self.read()
        self.assertFalse(ok)
        self.assertIn("expired", why)

    def test_future_dated_grant_is_closed(self) -> None:
        self.put(expires_in=86400 + 3600, granted_ago=-3600)  # granted an hour from now
        self.assertFalse(self.read()[0])
        # only the future stamp is wrong: 60 s long, expires within 24 h, granted an hour from now
        self.put(expires_in=3660, granted_ago=-3600, dur=60)
        ok, why, _ = self.read()
        self.assertFalse(ok)
        self.assertIn("future", why)

    def test_expiry_more_than_24h_out_is_closed(self) -> None:
        # granted just inside the clock slack, 24h long: expires > 24h from now
        self.put(expires_in=86400 + 100, granted_ago=-100)
        ok, why, _ = self.read()
        self.assertFalse(ok)
        self.assertIn("24h", why)

    def test_impossible_duration_is_closed(self) -> None:
        self.put(expires_in=90000, granted_ago=0)  # 25 h
        self.assertFalse(self.read()[0])
        self.put(dur=7200, expires_in=3600)  # duration does not match the stamps
        self.assertFalse(self.read()[0])

    def test_wrong_owner_is_closed(self) -> None:
        self.put()
        with mock.patch.object(mod, "OWNER_UID", os.getuid() + 1):
            self.assertFalse(self.read()[0])

    def test_group_or_world_writable_file_is_closed(self) -> None:
        for m in (0o664, 0o646, 0o666):
            with self.subTest(mode=oct(m)):
                self.put(mode=m)
                self.assertFalse(self.read()[0])

    def test_writable_dir_is_closed(self) -> None:
        self.put()
        os.chmod(self.dir, 0o775)
        ok, why, _ = self.read()
        self.assertFalse(ok)
        self.assertIn("dir", why)

    def test_symlinked_grant_is_closed(self) -> None:
        self.put()
        real = self.dir / "real"
        (self.dir / "grant").rename(real)
        os.symlink(real, self.dir / "grant")
        self.assertFalse(self.read()[0])

    def test_damaged_files_are_closed(self) -> None:
        for body in ["", "not json", "[]", '{"expires_utc": 5}', "x" * 5000]:
            with self.subTest(body=body[:10]):
                f = self.dir / "grant"
                f.write_text(body)
                os.chmod(f, 0o644)
                self.assertFalse(self.read()[0])

    def test_write_grant_round_trips(self) -> None:
        d = mod.write_grant(1800, self.now, 501)
        f = self.dir / "grant"
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o644)
        ok, why, data = self.read()
        self.assertTrue(ok, why)
        self.assertEqual(data["duration_s"], 1800)
        self.assertEqual(data["granted_by_uid"], 501)
        self.assertEqual(d["expires_utc"], data["expires_utc"])
        self.assertEqual(list(self.dir.glob(".grant.*")), [])


class PolicyTests(GrantBase):
    def check(self, argv, cwd=None):
        return mod.evaluate(argv, str(cwd or self.work), PATH)

    def assertDenied(self, argv, cwd=None):
        self.assertIsNotNone(self.check(argv, cwd), "should be refused: %r" % (argv,))

    def assertAllowed(self, argv, cwd=None):
        self.assertIsNone(self.check(argv, cwd), "should run: %r" % (argv,))

    def test_listed_programs(self) -> None:
        for argv in (["visudo"], ["visudo", "-c"], ["csrutil", "status"], ["nvram", "-p"],
                     ["tccutil", "reset", "All"], ["fdesetup", "status"], ["systemsetup", "-getdate"]):
            with self.subTest(argv=argv):
                self.assertDenied(argv)

    def test_diskutil(self) -> None:
        for v in ("eraseDisk", "eraseVolume", "erase", "eraseDisk", "secureErase", "zeroDisk",
                  "partitionDisk", "reformat"):
            with self.subTest(verb=v):
                self.assertDenied(["diskutil", v, "x", "disk9"])
        self.assertDenied(["diskutil", "apfs", "deleteVolume", "disk3s1"])
        self.assertDenied(["diskutil"])
        self.assertAllowed(["diskutil", "list"])
        self.assertAllowed(["diskutil", "apfs", "list"])

    def test_rm_class(self) -> None:
        for argv in (["rm", "-rf", "/"], ["rm", "-fr", "/usr"], ["rm", "-r", "/Users"],
                     ["rm", "-Rf", "/private/etc"], ["rm", "-rf", "--no-preserve-root", "/tmp/x"],
                     ["rm", "-rf", "/System"], ["chmod", "-R", "777", "/"], ["chown", "-R", "x", "/Users"]):
            with self.subTest(argv=argv):
                self.assertDenied(argv)
        victim = self.work / "junk"
        victim.mkdir()
        self.assertAllowed(["rm", "-rf", str(victim)])

    def test_protected_paths(self) -> None:
        for p in ("/etc/sudoers", "/etc/sudoers.d/x", "/private/etc/sudoers.d", "/etc/pam.d/sudo",
                  "/ETC/Sudoers.D/x", "/etc/../etc/sudoers", "/var/db/sudo-ask/grant",
                  "/usr/local/libexec/sudo-ask-granted", "/usr/local/libexec/sudo-secretspec",
                  "/usr/local/libexec/anything", "/var/log/sudo-ask-grant.log",
                  "/Library/Application Support/com.apple.TCC/TCC.db",
                  "/Users/someone/Library/Application Support/com.apple.TCC/TCC.db",
                  "/Users/someone/Library/Keychains/login.keychain-db", "/var/db/dslocal/nodes/Default"):
            for prog in (["touch"], ["chmod", "777"], ["cp", str(self.work / "x")], ["rm"], ["tee"]):
                with self.subTest(path=p, prog=prog[0]):
                    self.assertDenied(prog + [p])

    def test_protected_paths_match_case_insensitively(self) -> None:
        # APFS is case-insensitive by default; these carry none of the tripwire words
        for p in ("/PRIVATE/ETC/SUDO.CONF", "/Usr/Local/LibExec/helper", "/USR/LIB/PAM/x"):
            with self.subTest(path=p):
                self.assertDenied(["touch", p])

    def test_ancestors_of_protected_paths(self) -> None:
        for p in ("/etc", "/usr/local", "/var/db", "/"):
            with self.subTest(path=p):
                self.assertDenied(["chmod", "-R", "777", p])
        self.assertAllowed(["ls", "-la", "/usr/local"])

    def test_reading_protected_paths_is_allowed(self) -> None:
        self.assertAllowed(["ls", "/etc/sudoers.d"])
        self.assertAllowed(["cat", "/etc/pam.d/sudo"])
        self.assertAllowed(["grep", "x", "/etc/sudoers"])

    def test_relative_path_in_protected_cwd(self) -> None:
        self.assertDenied(["touch", "sudoers.d/x"], cwd="/private/etc")
        self.assertDenied(["touch", "x"], cwd="/private/etc/pam.d")

    def test_symlink_to_listed_program(self) -> None:
        link = self.work / "harmless"
        os.symlink("/usr/sbin/visudo", link)
        self.assertDenied([str(link)])
        link2 = self.work / "target"
        os.symlink("/etc/sudoers.d", link2)
        self.assertDenied(["touch", str(link2 / "x")])

    def test_user_and_keychain_changes(self) -> None:
        self.assertDenied(["dscl", ".", "-create", "/Users/x"])
        self.assertDenied(["dscl", ".", "-append", "/Groups/admin", "GroupMembership", "x"])
        self.assertDenied(["dscl", "."])
        self.assertAllowed(["dscl", ".", "-read", "/Users/root", "UniqueID"])
        self.assertDenied(["dseditgroup", "-o", "edit", "-a", "x", "-t", "user", "admin"])
        self.assertDenied(["sysadminctl", "-addUser", "x"])
        self.assertDenied(["security", "delete-keychain", "x"])
        self.assertDenied(["security", "set-keychain-password"])
        self.assertAllowed(["security", "find-identity"])

    def test_date_and_dd(self) -> None:
        self.assertDenied(["date", "112212002026"])
        self.assertAllowed(["date", "+%s"])
        self.assertDenied(["dd", "if=/dev/zero", "of=/dev/disk3"])

    def test_wrappers_are_unwrapped(self) -> None:
        for argv in (["env", "visudo"], ["env", "-i", "A=1", "visudo"], ["nice", "-n", "5", "visudo"],
                     ["nohup", "visudo"], ["time", "visudo"], ["timeout", "5", "visudo"],
                     ["sudo", "-u", "root", "visudo"], ["env", "nice", "env", "visudo"],
                     ["env", "-S", "visudo -c"], ["command", "visudo"],
                     ["sh", "-c", "visudo"], ["bash", "-c", "rm -rf /etc/sudoers.d"],
                     ["bash", "-lc", "echo hi; visudo"], ["sh", "-c", "echo hi && csrutil disable"],
                     ["sh", "-c", "ls | tee /etc/sudoers.d/x"], ["sh", "-c", "echo x > /etc/sudoers.d/y"],
                     ["sh", "-c", "echo x >> /etc/pam.d/sudo"],
                     ["sh", "-c", "sh -c 'visudo'"], ["env", "sh", "-c", "bash -c 'visudo'"],
                     ["find", "/etc", "-delete"], ["find", "/tmp", "-exec", "visudo", "{}", ";"],
                     ["find", "/", "-name", "x", "-exec", "rm", "{}", "+"],
                     ["find", ".", "-fprint", "/etc/sudoers.d/x"]):
            with self.subTest(argv=argv):
                self.assertDenied(argv)

    def test_unparseable_wrappers_fall_back_to_the_prompt(self) -> None:
        for text in ("echo $(visudo)", "echo `visudo`", "rm -rf /etc/sudo*", "ls {a,b}", "cd /etc && rm x",
                     "eval visudo", "for i in 1; do visudo; done", "echo hi\nvisudo", "(visudo)",
                     "x=1; $x", "PATH=/tmp/x ls", "cat <<EOF\nx\nEOF", "echo ~/x", "source /tmp/x",
                     "echo 'unterminated", "echo x >", "sudo -s"):
            with self.subTest(text=text):
                self.assertDenied(["sh", "-c", text])
        self.assertDenied(["sh"])
        self.assertDenied(["bash", "-s"])
        self.assertDenied(["env", "-S", "echo ${HOME}"])
        self.assertDenied(["env", "-S", "echo 'x"])
        self.assertDenied(["xargs", "rm"])
        self.assertDenied(["find", ".", "-exec", "rm", "{}"])  # no terminator
        self.assertDenied(["env", "PATH=/tmp/x", "ls"])
        self.assertDenied(["env", "-P", "/tmp", "ls"])

    def test_inline_interpreters_prompt(self) -> None:
        for argv in (["python3", "-c", "print(1)"], ["perl", "-e", "1"], ["ruby", "-e", "1"],
                     ["osascript", "-e", "beep"], ["python3"]):
            with self.subTest(argv=argv):
                self.assertDenied(argv)

    def test_ordinary_commands_run(self) -> None:
        f = self.work / "a"
        f.write_text("x")
        for argv in (["ls", "-la", str(self.work)], ["echo", "hi"], ["touch", str(self.work / "b")],
                     ["cp", str(f), str(self.work / "c")], ["env", "FOO=1", "echo", "hi"],
                     ["sh", "-c", "echo hi; ls -l"], ["sh", "-c", "echo hi > " + str(self.work / "out")],
                     ["bash", "-lc", "cat " + str(f) + " | wc -l"], ["find", ".", "-name", "a"],
                     ["find", str(self.work), "-name", "a", "-exec", "cat", "{}", ";"],
                     ["xargs", "-n1", "echo"], ["launchctl", "list"], ["nice", "-n", "5", "ls"],
                     ["env", "-S", "echo hi"], ["mkdir", "-p", str(self.work / "d" / "e")],
                     ["python3", str(f)], ["timeout", "5", "ls"], ["sudo", "-n", "ls"]):
            with self.subTest(argv=argv):
                self.assertAllowed(argv)

    def test_unknown_program(self) -> None:
        self.assertDenied(["no-such-program-xyz"])
        self.assertDenied(["./nothing-here"])


class ModeTests(GrantBase):
    """main() with the boundary patched: no root needed, execve captured."""

    def run_main(self, *args, env=None):
        calls = []
        with mock.patch.object(mod, "need_root"), \
                mock.patch.object(mod.os, "execve", lambda *a: calls.append(a)), \
                mock.patch.dict(mod.os.environ, {"PATH": PATH, "SUDO_UID": "501", **(env or {})}), \
                mock.patch("os.getcwd", return_value=str(self.work)):
            try:
                rc = mod.main(["h", *args])
            except SystemExit as e:
                rc = e.code
        return rc, calls

    def log_text(self):
        p = pathlib.Path(mod.LOG_FILE)
        return p.read_text() if p.exists() else ""

    def test_exec_with_open_window_runs_the_resolved_program(self) -> None:
        self.put()
        rc, calls = self.run_main("exec", "--", "echo", "hi")
        self.assertEqual(len(calls), 1)
        target, argv, env = calls[0]
        self.assertEqual(os.path.basename(target), "echo")
        self.assertEqual(argv, ["echo", "hi"])
        self.assertEqual(env["PWD"], str(self.work))
        self.assertIn("GRANTED-EXEC", self.log_text())

    def test_exec_environment_is_clean(self) -> None:
        self.put()
        _, calls = self.run_main("exec", "--", "echo", env={"BASH_ENV": "/x", "DYLD_INSERT_LIBRARIES": "/x",
                                                            "PYTHONPATH": "/x", "LANG": "C"})
        env = calls[0][2]
        for bad in ("BASH_ENV", "DYLD_INSERT_LIBRARIES", "PYTHONPATH"):
            self.assertNotIn(bad, env)
        self.assertEqual(env["LANG"], "C")

    def test_exec_refused_without_window(self) -> None:
        rc, calls = self.run_main("exec", "--", "echo", "hi")
        self.assertEqual(rc, mod.EX_REFUSED)
        self.assertEqual(calls, [])
        self.assertIn("REFUSED", self.log_text())

    def test_exec_refused_when_expired(self) -> None:
        self.put(expires_in=-1, granted_ago=3601)
        rc, calls = self.run_main("exec", "--", "echo")
        self.assertEqual((rc, calls), (mod.EX_REFUSED, []))

    def test_exec_rechecks_the_denylist(self) -> None:
        self.put()
        rc, calls = self.run_main("exec", "--", "visudo")
        self.assertEqual((rc, calls), (mod.EX_DENIED, []))
        self.assertIn("DENYLISTED", self.log_text())

    def test_exec_needs_the_audit_log(self) -> None:
        self.put()
        with mock.patch.object(mod, "LOG_FILE", str(self.dir / "no" / "such" / "log")):
            rc, calls = self.run_main("exec", "--", "echo")
        self.assertEqual((rc, calls), (mod.EX_NOEXEC, []))

    def test_exec_usage(self) -> None:
        self.put()
        for args in (("exec",), ("exec", "echo", "hi"), ("exec", "--"), ("exec grant", "--", "x"), ("bogus",), ()):
            with self.subTest(args=args):
                rc, calls = self.run_main(*args)
                self.assertEqual((rc, calls), (mod.EX_USAGE, []))

    def test_grant_writes_and_revoke_removes(self) -> None:
        rc, _ = self.run_main("grant", "30m")
        self.assertEqual(rc, 0)
        ok, why, d = mod.read_grant(int(time.time()))
        self.assertTrue(ok, why)
        self.assertEqual(d["duration_s"], 1800)
        self.assertEqual(d["granted_by_uid"], 501)
        rc, _ = self.run_main("revoke")
        self.assertEqual(rc, 0)
        self.assertFalse(mod.read_grant(int(time.time()))[0])
        self.assertIn("GRANT(30m", self.log_text())
        self.assertIn("REVOKE", self.log_text())

    def test_grant_refuses_bad_durations(self) -> None:
        for d in ("25h", "0m", "junk", "8", ""):
            with self.subTest(d=d):
                rc, _ = self.run_main("grant", d)
                self.assertEqual(rc, mod.EX_USAGE)
                self.assertFalse((self.dir / "grant").exists())
        self.assertEqual(self.run_main("grant")[0], mod.EX_USAGE)

    def test_status_output(self) -> None:
        import io, contextlib
        for opened, want in ((False, 1), (True, 0)):
            if opened:
                self.put()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc, _ = self.run_main("status")
            self.assertEqual(rc, want)
            self.assertIn("open=%d" % opened, buf.getvalue())
        self.assertIn("expires_epoch=", buf.getvalue())
        self.assertRegex(buf.getvalue(), r"expires_utc=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")

    def test_status_check(self) -> None:
        self.assertEqual(self.run_main("status", "--check", "--", "echo")[0], 1)
        self.put()
        self.assertEqual(self.run_main("status", "--check", "--", "echo")[0], 0)
        self.assertEqual(self.run_main("status", "--check", "--", "visudo")[0], mod.EX_DENIED)


class HelperSourceTests(unittest.TestCase):
    def test_paths_are_hard_coded_and_not_overridable(self) -> None:
        src = HELPER.read_text()
        self.assertEqual(src.splitlines()[0], "#!/usr/bin/python3 -IS")
        for const in ('GRANT_DIR = "/var/db/sudo-ask"', 'LOG_FILE = "/var/log/sudo-ask-grant.log"',
                      "OWNER_UID = 0"):
            self.assertIn(const, src)
        used = set(re.findall(r"environ(?:\.get)?\(?\[?[\"'](\w+)", src))
        self.assertLessEqual(used, {"SUDO_UID", "PATH"}, "the helper must not read other env vars")
        self.assertNotIn("argparse", src)
        self.assertTrue(os.access(HELPER, os.X_OK))


class SetupScriptTests(unittest.TestCase):
    def run_setup(self, *args):
        return subprocess.run([str(SETUP), *args], capture_output=True, text=True, check=False)

    def test_print_shows_a_split_sudoers_rule(self) -> None:
        p = self.run_setup("--print")
        self.assertEqual(p.returncode, 0, p.stderr)
        rule = [ln for ln in p.stdout.splitlines() if "NOPASSWD" in ln and not ln.startswith("#")]
        self.assertEqual(len(rule), 1)
        line = rule[0]
        self.assertIn("/usr/local/libexec/sudo-ask-granted exec *", line)
        self.assertIn("sudo-ask-granted status", line)
        self.assertNotRegex(line, r"\b(grant|revoke)\b|NOPASSWD: ALL")
        self.assertIn("Defaults!/usr/local/libexec/sudo-ask-granted env_reset, timestamp_timeout=0", p.stdout)

    def test_check_is_read_only_and_reports(self) -> None:
        p = self.run_setup("--check", "--diff")
        self.assertIn(p.returncode, (0, 3), p.stderr)
        self.assertIn("/usr/local/libexec/sudo-ask-granted", p.stdout)

    def test_unknown_flag(self) -> None:
        self.assertEqual(self.run_setup("--bogus").returncode, 64)

    def test_script_syntax(self) -> None:
        for f in (SETUP, CLIENT):
            self.assertEqual(subprocess.run(["bash", "-n", str(f)], check=False).returncode, 0)


class ClientTests(unittest.TestCase):
    """bin/sudo-ask as a patched copy driven by fakes (absolute paths, one state dir)."""

    FAKE_SUDO = """#!/bin/bash
echo "sudo $*" >> "$FAKE_STATE/calls"
[ "$1" = -k ] && exit 0
[ "$1" = -n ] && shift
exec "$@"
"""
    FAKE_OSA = """#!/bin/bash
echo "dialog: $*" >> "$FAKE_STATE/calls"
cat "$FAKE_STATE/answer" 2>/dev/null || echo "Allow|false"
"""
    FAKE_PING = """#!/bin/bash
echo "ping: $*" >> "$FAKE_STATE/calls"
"""
    FAKE_HELPER = """#!/bin/bash
echo "helper $*" >> "$FAKE_STATE/calls"
case $1 in
  status)
    if [ "$2" = --check ]; then
      [ -f "$FAKE_STATE/open_until" ] || exit 1
      exit "$(cat "$FAKE_STATE/check_rc" 2>/dev/null || echo 0)"
    fi
    if [ -f "$FAKE_STATE/open_until" ]; then
      e=$(cat "$FAKE_STATE/open_until")
      echo open=1; echo reason=window open; echo expires_epoch=$e
      echo expires_utc=$(TZ=UTC gdate -d @$e +%Y-%m-%dT%H:%M:%SZ); echo remaining_s=$((e - $(gdate +%s)))
      exit 0
    fi
    echo open=0; echo reason="no window is open"; exit 1 ;;
  exec) shift 2; echo "ran: $*" >> "$FAKE_STATE/calls"; exit "$(cat "$FAKE_STATE/exec_rc" 2>/dev/null || echo 0)" ;;
  grant) date +%s >/dev/null; echo $(( $(gdate +%s) + 28800 )) > "$FAKE_STATE/open_until" ;;
  revoke) rm -f "$FAKE_STATE/open_until" ;;
esac
exit 0
"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(cls.tmp.name)
        cls.fakes = {}
        for name, body in (("sudo", cls.FAKE_SUDO), ("osascript", cls.FAKE_OSA),
                           ("hermes-ping", cls.FAKE_PING), ("sudo-ask-granted", cls.FAKE_HELPER)):
            f = base / name
            f.write_text(body)
            f.chmod(0o755)
            cls.fakes[name] = f
        src = CLIENT.read_text()
        for old, new in (("HELPER=/usr/local/libexec/sudo-ask-granted\n", "HELPER=%s\n" % cls.fakes["sudo-ask-granted"]),
                         ("SUDO=/usr/bin/sudo\n", "SUDO=%s\n" % cls.fakes["sudo"]),
                         ("OSASCRIPT=/usr/bin/osascript\n", "OSASCRIPT=%s\n" % cls.fakes["osascript"]),
                         ("PING=hermes-ping\n", "PING=%s\n" % cls.fakes["hermes-ping"])):
            assert src.count(old) == 1, old
            src = src.replace(old, new)
        cls.client = base / "sudo-ask"
        cls.client.write_text(src)
        cls.client.chmod(0o755)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def setUp(self) -> None:
        self.state = pathlib.Path(tempfile.mkdtemp(prefix="sag-state-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.state, ignore_errors=True))

    def run_client(self, *args, helper=True):
        env = {"PATH": PATH, "HOME": str(self.state), "XDG_STATE_HOME": str(self.state / "xdg"),
               "FAKE_STATE": str(self.state), "SUDO_ASK_MAX_WAIT": "1", "LANG": "en_US.UTF-8"}
        client = self.client
        if not helper:  # same copy, helper path that does not exist
            client = self.state / "sudo-ask"
            client.write_text(self.client.read_text().replace(str(self.fakes["sudo-ask-granted"]), "/nonexistent/helper"))
            client.chmod(0o755)
        return subprocess.run([str(client), *args], capture_output=True, text=True, env=env,
                              cwd=str(self.state), check=False)

    def calls(self):
        f = self.state / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def log(self):
        f = self.state / "xdg" / "sudo-ask" / "log"
        return f.read_text() if f.exists() else ""

    def open_window(self, secs=3600):
        (self.state / "open_until").write_text(str(int(time.time()) + secs))

    def dialogs(self):
        return [c for c in self.calls() if c.startswith("dialog:")]

    def test_no_window_normal_path_unchanged(self) -> None:
        p = self.run_client("echo", "hi there")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.dialogs()), 1)
        self.assertIn("sudo echo hi there", self.calls())
        self.assertIn("ALLOWED", self.log())
        self.assertNotIn("GRANTED-WINDOW", self.log())

    def test_helper_absent_normal_path(self) -> None:
        p = self.run_client("echo", "x", helper=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.dialogs()), 1)

    def test_deny_still_denies(self) -> None:
        (self.state / "answer").write_text("Deny|false")
        p = self.run_client("echo", "x")
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("sudo echo x", self.calls())

    def test_open_window_runs_without_dialog(self) -> None:
        self.open_window()
        p = self.run_client("echo", "hi")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.dialogs(), [])
        self.assertIn("ran: echo hi", self.calls())
        self.assertIn("GRANTED-WINDOW", self.log())
        self.assertNotIn("sudo echo hi", self.calls())

    def test_window_exit_code_is_the_commands(self) -> None:
        self.open_window()
        (self.state / "exec_rc").write_text("7")
        self.assertEqual(self.run_client("false").returncode, 7)

    def test_denylisted_command_still_prompts_inside_a_window(self) -> None:
        self.open_window()
        (self.state / "check_rc").write_text("76")
        p = self.run_client("visudo")
        self.assertEqual(len(self.dialogs()), 1)
        self.assertNotIn("ran: visudo", self.calls())
        self.assertNotIn("GRANTED-WINDOW", self.log())

    def test_option_or_assignment_first_skips_the_window_path(self) -> None:
        self.open_window()
        for args in (("-n", "true"), ("FOO=1", "true")):
            with self.subTest(args=args):
                (self.state / "calls").unlink(missing_ok=True)
                self.run_client(*args)
                self.assertEqual(len(self.dialogs()), 1)
                self.assertFalse([c for c in self.calls() if c.startswith("ran:")])

    def test_status(self) -> None:
        p = self.run_client("--status")
        self.assertEqual(p.returncode, 1)
        self.assertIn("none", p.stdout)
        self.open_window(2 * 3600 + 120)
        p = self.run_client("--status")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertRegex(p.stdout, r"OPEN until \d{4}-\d\d-\d\d \d\d:\d\d (AM|PM) E[SD]T \(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ; 2h\d+m left\)")
        self.assertEqual(self.run_client("status").returncode, 0)  # bare word, no program named status
        self.assertEqual(self.run_client("--status", "x").returncode, 64)

    def test_grant_default_is_8h_with_dialog_note_and_ping(self) -> None:
        p = self.run_client("--grant")
        self.assertEqual(p.returncode, 0, p.stderr)
        calls = self.calls()
        self.assertIn("helper grant 8h", calls)
        self.assertTrue(any("OPENS AN APPROVAL WINDOW for 8h" in c for c in self.dialogs()))
        self.assertLess(calls.index("sudo -k"), calls.index(next(c for c in calls if c.startswith("sudo ") and "grant" in c)))
        self.assertTrue(any(c.startswith("ping: sudo-ask: approval window open until") for c in calls))
        self.assertIn("OPEN until", p.stdout)
        self.assertIn("WINDOW-GRANT(", self.log())

    def test_grant_with_duration_and_bare_word(self) -> None:
        for args, dur in (("--grant", "30m"), ("grant", "2h")):
            with self.subTest(args=args):
                (self.state / "calls").unlink(missing_ok=True)
                self.assertEqual(self.run_client(args, dur).returncode, 0)
                self.assertIn("helper grant " + dur, self.calls())

    def test_grant_junk_refused_before_any_dialog(self) -> None:
        for d in ("25h", "1441m", "0m", "59s", "abc", "8", "-1h", "1.5h", "999999d"):
            with self.subTest(d=d):
                (self.state / "calls").unlink(missing_ok=True)
                p = self.run_client("--grant", d)
                self.assertEqual(p.returncode, 64, p.stderr)
                self.assertEqual(self.calls(), [])
        self.assertEqual(self.run_client("--grant", "1h", "extra").returncode, 64)

    def test_grant_exactly_24h_ok(self) -> None:
        self.assertEqual(self.run_client("--grant", "24h").returncode, 0)
        self.assertIn("helper grant 24h", self.calls())

    def test_grant_denied_in_dialog_never_reaches_the_helper(self) -> None:
        (self.state / "answer").write_text("Deny|false")
        p = self.run_client("--grant", "1h")
        self.assertEqual(p.returncode, 1)
        self.assertFalse([c for c in self.calls() if c.startswith("helper grant")])

    def test_grant_without_helper(self) -> None:
        p = self.run_client("--grant", "1h", helper=False)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.dialogs(), [])

    def test_revoke(self) -> None:
        self.open_window()
        p = self.run_client("--revoke")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("helper revoke", self.calls())
        self.assertEqual(self.dialogs(), [])
        self.assertFalse((self.state / "open_until").exists())
        self.assertTrue(any(c.startswith("ping: sudo-ask: approval window revoked") for c in self.calls()))
        self.assertIn("WINDOW-REVOKE", self.log())

    def test_first_use_after_expiry_pings_once(self) -> None:
        marker = self.state / "xdg" / "sudo-ask" / "window-expires"
        marker.parent.mkdir(parents=True)
        marker.write_text(str(int(time.time()) - 60))
        self.run_client("echo", "x")
        self.assertEqual(len([c for c in self.calls() if "window expired" in c]), 1)
        self.assertFalse(marker.exists())
        self.run_client("echo", "y")
        self.assertEqual(len([c for c in self.calls() if "window expired" in c]), 1)
        self.assertIn("WINDOW-EXPIRED", self.log())

    def test_ping_failure_never_blocks(self) -> None:
        self.fakes["hermes-ping"].write_text("#!/bin/bash\nexit 9\n")
        try:
            self.assertEqual(self.run_client("--grant", "1h").returncode, 0)
        finally:
            self.fakes["hermes-ping"].write_text(self.FAKE_PING)

    def test_no_arguments(self) -> None:
        self.assertEqual(self.run_client().returncode, 64)


if __name__ == "__main__":
    unittest.main()
