"""roles/sudo_ask_grant: the root helper's policy and grant-file checks, the sudo-ask client's
window path, and the setup script's read-only modes.

Nothing here touches the live privileged boundary. The helper is loaded in-process and its hard-coded
paths are patched to a temp directory (the installed file has no hook for that: no env var, no
argument). The client runs as a PATCHED COPY whose sudo, osascript, helper and hermes-ping are
absolute-path fakes (never rely on PATH order: the shell startup reorders it). The setup script runs
only --print and --check, plus the --live guard's refusals and a temp-dir fake.
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
            "INVOKER_UID": os.getuid() or 501,   # the user whose writable paths prompt
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
                     ["timeout", "5", "ls"], ["sudo", "-n", "ls"], ["find", "-L", ".", "-name", "a"],
                     ["dseditgroup", "-o", "read", "admin"], ["crontab", "-l"]):
            with self.subTest(argv=argv):
                self.assertAllowed(argv)

    def test_unknown_program(self) -> None:
        self.assertDenied(["no-such-program-xyz"])
        self.assertDenied(["./nothing-here"])

    # ---- ruling 1: code the invoking user can change prompts, even inside a window

    def test_agent_writable_scripts_and_programs_prompt(self) -> None:
        f = self.work / "a"
        f.write_text("print(1)\n")
        copy = self.work / "g"
        copy.write_text(HELPER.read_text())
        copy.chmod(0o755)
        mine = self.work / "echo"
        mine.write_bytes(pathlib.Path("/bin/echo").read_bytes())
        mine.chmod(0o755)
        for argv in (["python3", str(f)], ["sh", str(f)], ["bash", str(f)], ["perl", str(f)], [str(mine), "hi"],
                     ["python3", "-IS", str(copy), "grant", "24h"],       # MED-3: a copy of the helper in ~/g
                     ["python3", str(copy), "grant", "24h"], ["env", "python3", str(f)],
                     ["nice", "sh", str(f)], ["sh", "-c", "python3 " + str(f)],
                     ["python3", "/dev/stdin"], ["python3", "-"], ["python3", "-m", "http.server"],
                     ["python3", "-mhttp.server"], ["python3", "-Im", "pdb"], ["perl", "-M/tmp/x", str(f)],
                     ["sh", "/dev/stdin"], ["bash", "/dev/fd/0"]):
            with self.subTest(argv=argv):
                self.assertDenied(argv)

    def test_root_owned_scripts_and_system_tools_run(self) -> None:
        rc = pathlib.Path("/etc/rc.common")
        if not rc.is_file():
            self.skipTest("no /etc/rc.common here")
        self.assertAllowed(["sh", str(rc)])      # control: the script check is not just refusing everything
        self.assertAllowed(["ls", "/usr/bin"])
        self.assertAllowed(["perl", "-MPOSIX", str(rc)])

    def test_unknown_invoker_prompts_for_everything(self) -> None:
        for uid in (None, 0):
            with self.subTest(uid=uid), mock.patch.object(mod, "INVOKER_UID", uid):
                self.assertDenied(["ls"])
                self.assertDenied(["echo", "hi"])

    def test_agent_writable_places(self) -> None:
        for p in ("/tmp/x", "/private/tmp/x/y", "/var/folders/zz/T/x", "/private/var/tmp/x", "/TMP/X", str(self.work)):
            with self.subTest(p=p):
                self.assertTrue(mod.agent_writable(p))
        self.assertFalse(mod.agent_writable("/usr/bin/true"))
        self.assertFalse(mod.agent_writable("/bin/ls"))

    def test_agent_writable_group_and_world_bits(self) -> None:
        def fake_stat(path):
            if path == "/srv/shared":
                return os.stat_result((0o40775, 1, 1, 1, 0, 20, 0, 0, 0, 0))
            if path == "/srv/open":
                return os.stat_result((0o40777, 1, 1, 1, 0, 0, 0, 0, 0, 0))
            if path == "/srv/mine":
                return os.stat_result((0o40755, 1, 1, 1, mod.INVOKER_UID, 0, 0, 0, 0, 0))
            return os.stat_result((0o40755, 1, 1, 1, 0, 0, 0, 0, 0, 0))
        with mock.patch.object(mod.os, "stat", fake_stat), mock.patch.object(mod, "_user_groups", return_value={20, 501}):
            self.assertTrue(mod.agent_writable("/srv/shared/tool"))
            self.assertTrue(mod.agent_writable("/srv/open/tool"))
            self.assertTrue(mod.agent_writable("/srv/mine/tool"))
            self.assertFalse(mod.agent_writable("/srv/other/tool"))
        with mock.patch.object(mod.os, "stat", fake_stat), mock.patch.object(mod, "_user_groups", return_value={501}):
            self.assertFalse(mod.agent_writable("/srv/shared/tool"))   # group-writable, but not the user's group
        with mock.patch.object(mod.os, "stat", fake_stat), mock.patch.object(mod, "_user_groups", return_value=None):
            self.assertTrue(mod.agent_writable("/srv/other/tool"))     # cannot tell: prompt

    def test_make_and_git_read_code_from_the_working_directory(self) -> None:
        self.assertDenied(["make"], cwd=self.work)
        self.assertDenied(["git", "status"], cwd=self.work)
        self.assertAllowed(["git", "--version"], cwd="/usr")

    # ---- adversary round 1, LOW findings

    def test_a_link_named_like_a_read_only_tool_is_judged_by_its_target(self) -> None:
        link = self.work / "cat"
        os.symlink("/bin/cp", link)
        with mock.patch.object(mod, "agent_writable", return_value=False):   # isolate LOW-1 from ruling 1
            self.assertDenied([str(link), str(self.work / "a"), "/etc/sudoers.d/x"])
            self.assertDenied([str(link), "x"], cwd="/private/etc/pam.d")
            self.assertAllowed(["/bin/cat", "/etc/sudoers.d"])

    def test_hash_and_dollar_in_shell_text_prompt(self) -> None:
        for text in ("echo a#b", "echo hi # visudo", "echo $HOME", "ls $X", "cat /etc/$Y", "echo ${x}", "echo $1"):
            with self.subTest(text=text):
                self.assertDenied(["sh", "-c", text])

    def test_find_f_and_follow_links(self) -> None:
        self.assertDenied(["find", "-f", "/etc/sudoers.d", "-delete"])
        self.assertDenied(["find", "-f", "/etc", "-exec", "rm", "{}", ";"])
        self.assertDenied(["find", "-L", str(self.work), "-delete"])
        self.assertDenied(["find", "-H", str(self.work), "-exec", "ls", "{}", ";"])

    def test_root_owned_files_with_other_hard_links_prompt(self) -> None:
        def lstat(nlink):
            return lambda p: os.stat_result((0o100644, 1, 1, nlink, 0, 0, 0, 0, 0, 0))
        with mock.patch.object(mod.os, "lstat", lstat(2)):
            self.assertDenied(["touch", "anything"])
        with mock.patch.object(mod.os, "lstat", lstat(1)):
            self.assertAllowed(["touch", "anything"])

    def test_every_dseditgroup_operation_is_checked(self) -> None:
        self.assertDenied(["dseditgroup", "-o", "read", "-o", "edit", "-a", "x", "-t", "user", "admin"])
        self.assertDenied(["dseditgroup", "-o", "edit", "-o", "read", "-a", "x", "admin"])
        self.assertAllowed(["dseditgroup", "-o", "checkmember", "-m", "x", "admin"])

    def test_persistence_paths_are_protected(self) -> None:
        for p in ("/Library/LaunchDaemons/x.plist", "/Library/LaunchAgents/x.plist", "/Library/StartupItems/x",
                  "/etc/periodic/daily/999.x", "/etc/paths", "/etc/paths.d/x", "/etc/zshenv", "/etc/zprofile",
                  "/etc/zshrc", "/etc/profile", "/etc/bashrc", "/var/root/.zshrc", "/var/root", "/etc/ssh/sshd_config",
                  "/usr/lib/cron/tabs/root", "/var/at/tabs/root", "/etc/ld.so.conf",
                  "/Library/Security/SecurityAgentPlugins/x"):
            for prog in (["touch"], ["tee"], ["cp", str(self.work / "x")], ["chmod", "777"]):
                with self.subTest(path=p, prog=prog[0]):
                    self.assertDenied(prog + [p])
        self.assertAllowed(["ls", "/etc/paths.d"])
        self.assertAllowed(["touch", str(self.work / "pathsfoo")])

    def test_launchctl_and_crontab_that_run_things(self) -> None:
        for argv in (["launchctl", "bootstrap", "system", "/x.plist"], ["launchctl", "load", "-w", "/x.plist"],
                     ["launchctl", "enable", "system/x"], ["launchctl", "submit", "-l", "x", "--", "/bin/sh"],
                     ["launchctl", "kickstart", "system/x"], ["launchctl", "asuser", "501", "/bin/sh"],
                     ["crontab", "-u", "root", "/x"], ["crontab", "/x"], ["crontab", "-e"], ["crontab", "-r"]):
            with self.subTest(argv=argv):
                self.assertDenied(argv)
        self.assertAllowed(["launchctl", "list"])
        self.assertAllowed(["launchctl", "print", "system"])


class ModeTests(GrantBase):
    """main() with the boundary patched: no root needed, execve captured."""

    def run_main(self, *args, env=None, fresh=None, installed=True):
        """fresh: a refusal text for the fresh-authentication proof (None: proven). installed: run as the installed
        helper path (False: as some other copy)."""
        calls = []
        real = os.path.realpath(str(HELPER)) if installed else "/usr/local/libexec/sudo-ask-granted"
        with mock.patch.object(mod, "need_root"), \
                mock.patch.object(mod, "INSTALLED_PATH", real), \
                mock.patch.object(mod, "fresh_auth_problem", return_value=fresh), \
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
        self.assertEqual(env["PATH"], mod.EXEC_PATH)   # the caller's PATH and HOME never reach the root program
        self.assertEqual(env["HOME"], "/var/root")
        self.assertEqual(env["PWD"], str(self.work))

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

    def test_grant_refused_without_proof_of_fresh_authentication(self) -> None:
        rc, _ = self.run_main("grant", "30m", fresh="sudo was not run with -k")
        self.assertEqual(rc, mod.EX_REFUSED)
        self.assertFalse((self.dir / "grant").exists())
        self.assertIn("GRANT-REFUSED(sudo was not run with -k)", self.log_text())

    def test_grant_refused_from_a_copy_of_the_helper(self) -> None:   # MED-3
        rc, _ = self.run_main("grant", "24h", installed=False)
        self.assertEqual(rc, mod.EX_REFUSED)
        self.assertFalse((self.dir / "grant").exists())

    def test_grant_uses_the_real_ancestor_check_by_default(self) -> None:
        self.put(expires_in=-1, granted_ago=100)   # not a window; just a file to compare against
        chain = {100: (50, "/usr/bin/sudo", "sudo -k /usr/local/libexec/sudo-ask-granted grant 1h"), 50: (1, "zsh", "zsh")}
        with mock.patch.object(mod, "need_root"), mock.patch.object(mod, "proc_info", lambda pid: chain.get(pid)), \
                mock.patch.object(mod.os, "getppid", return_value=100), \
                mock.patch.object(mod, "INSTALLED_PATH", os.path.realpath(str(HELPER))), \
                mock.patch.dict(mod.os.environ, {"SUDO_UID": "501"}), mock.patch("os.getcwd", return_value=str(self.work)):
            self.assertEqual(mod.main(["h", "grant", "1h"]), 0)
            chain[100] = (50, "/usr/bin/sudo", "sudo -n /usr/local/libexec/sudo-ask-granted grant 1h")
            with self.assertRaises(SystemExit) as cm:
                mod.main(["h", "grant", "1h"])
            self.assertEqual(cm.exception.code, mod.EX_REFUSED)

    def test_revoke_needs_no_authentication_but_takes_no_arguments(self) -> None:   # ruling 3
        self.put()
        self.assertEqual(self.run_main("revoke", "x")[0], mod.EX_USAGE)
        self.assertEqual(self.run_main("revoke", "--", "x")[0], mod.EX_USAGE)
        self.assertTrue(mod.read_grant(int(time.time()))[0], "a refused revoke must not revoke")
        rc, _ = self.run_main("revoke", fresh="no proof of anything")   # no fresh-auth check on this path
        self.assertEqual(rc, 0)
        self.assertFalse(mod.read_grant(int(time.time()))[0])

    def test_exec_refuses_a_program_that_changes_between_check_and_run(self) -> None:   # LOW-6
        self.put()
        real_resolve = mod.resolve
        def flipping(name, cwd, path):
            if "GRANTED-EXEC" in self.log_text() and name == "echo":
                return "/bin/ls"
            return real_resolve(name, cwd, path)
        with mock.patch.object(mod, "resolve", flipping):
            rc, calls = self.run_main("exec", "--", "echo", "hi")
        self.assertEqual((rc, calls), (mod.EX_DENIED, []))
        self.assertIn("changed during the check", self.log_text())

    def test_exec_prompts_for_agent_writable_programs(self) -> None:   # ruling 1 at exec time
        self.put()
        script = self.work / "a.py"
        script.write_text("print(1)\n")
        rc, calls = self.run_main("exec", "--", "python3", str(script))
        self.assertEqual((rc, calls), (mod.EX_DENIED, []))
        self.assertIn("DENYLISTED", self.log_text())

    def test_log_is_private_capped_and_rotates(self) -> None:   # LOW-9
        mod.log("EVENT", "x" * 10000)
        st = os.stat(mod.LOG_FILE)
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o600)
        line = self.log_text()
        self.assertLess(len(line), mod.CMD_LOG_MAX + 400)
        self.assertIn("[10000 chars]", line)
        os.chmod(mod.LOG_FILE, 0o644)
        mod.log("AGAIN")
        self.assertEqual(stat.S_IMODE(os.stat(mod.LOG_FILE).st_mode), 0o600)   # tightened on every write
        with mock.patch.object(mod, "LOG_MAX_BYTES", 10):
            mod.log("AFTER-ROTATE")
        self.assertTrue(pathlib.Path(mod.LOG_FILE + ".1").exists())
        self.assertEqual(len(self.log_text().splitlines()), 1)

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


class FreshAuthTests(unittest.TestCase):
    """MED-1: grant proves fresh authentication by the nearest sudo above it carrying -k."""

    @staticmethod
    def chain(*rows):
        table = {100 + i: (101 + i if i + 1 < len(rows) else 1, comm, args) for i, (comm, args) in enumerate(rows)}
        return lambda pid: table.get(pid)

    def problem(self, *rows):
        return mod.fresh_auth_problem(info=self.chain(*rows), start=100)

    def test_sudo_with_k_proves_it(self) -> None:
        for args in ("sudo -k /h grant 1h", "sudo -nk /h grant 1h", "sudo --reset-timestamp /h grant 1h",
                     "sudo -u root -k /h grant 1h", "sudo -k -n /h grant 1h"):
            with self.subTest(args=args):
                self.assertIsNone(self.problem(("/usr/bin/sudo", args), ("-zsh", "-zsh")))

    def test_sudo_without_k_does_not(self) -> None:
        for args in ("sudo -n /h grant 1h", "sudo /h grant 1h", "sudo -ukate /h grant 1h", "sudo -u root /h grant 1h",
                     "sudo /h grant 1h -k", "sudo -- /h grant -k"):
            with self.subTest(args=args):
                self.assertIn("-k", self.problem(("/usr/bin/sudo", args), ("-zsh", "-zsh")) or "")

    def test_no_sudo_above_does_not(self) -> None:
        self.assertIn("no sudo", self.problem(("python3", "python3 x"), ("-zsh", "-zsh")))
        self.assertIn("no sudo", mod.fresh_auth_problem(info=lambda pid: None, start=100))

    def test_nearest_sudo_decides(self) -> None:
        # an outer `sudo -k` must not vouch for an inner plain `sudo -n`: the inner is the one that ran us
        self.assertIsNotNone(self.problem(("/usr/bin/sudo", "sudo -n /h grant 1h"), ("/bin/sh", "sh -c x"),
                                          ("/usr/bin/sudo", "sudo -k sh -c x"), ("-zsh", "-zsh")))

    def test_a_sudo_named_program_elsewhere_is_not_sudo(self) -> None:
        self.assertIsNotNone(self.problem(("/tmp/sudo", "sudo -k /h grant 1h"), ("-zsh", "-zsh")))

    def test_deep_chain_is_bounded(self) -> None:
        rows = [("sh", "sh")] * 20
        self.assertIsNotNone(self.problem(*rows, ("/usr/bin/sudo", "sudo -k x")))


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
        self.assertNotRegex(line, r"\bgrant\b|NOPASSWD: ALL")
        # ruling 3: revoke needs no password, with an EMPTY argument list ("" matches no arguments, never a wildcard)
        self.assertIn('/usr/local/libexec/sudo-ask-granted revoke ""', line)
        self.assertNotRegex(line, r"revoke( \*|\s*,|\s*$)")
        self.assertIn("Defaults!/usr/local/libexec/sudo-ask-granted env_reset, timestamp_timeout=0", p.stdout)

    def test_root_steps_use_system_tools_only(self) -> None:   # MED-2
        src = SETUP.read_text()
        code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
        self.assertIn("export PATH=/usr/bin:/bin:/usr/sbin:/sbin", code)
        self.assertNotIn("/opt/homebrew", code)
        self.assertNotRegex(code, r"(?m)(^|[;&|(])\s*sudo ")                  # no PATH-resolved sudo call
        self.assertIn('run_root() { "$fake" "$@"; }', code)              # root steps go through one absolute path
        self.assertNotIn('sudo -n "$BIN" revoke', code)                  # no live revoke probe
        self.assertIn('-l "$BIN" revoke extra', code)
        self.assertIn("a sudo ticket is cached", code)                   # MED-1: verify warns

    def test_check_is_read_only_and_reports(self) -> None:
        p = self.run_setup("--check", "--diff")
        self.assertIn(p.returncode, (0, 3), p.stderr)
        self.assertIn("/usr/local/libexec/sudo-ask-granted", p.stdout)

    def test_unknown_flag(self) -> None:
        self.assertEqual(self.run_setup("--bogus").returncode, 64)

    # The --live guard. Every case below puts a FAKE sudo-ask (it only logs its arguments) first on a PATH set
    # inside the subprocess env, so even a broken guard could not reach the real one. PATH has no real sudo-ask.
    def guarded(self, *args, fake_dir=None, with_fake=True):
        log = pathlib.Path(tempfile.mkdtemp(prefix="sag-guard-log-")) / "calls"
        self.addCleanup(lambda: __import__("shutil").rmtree(log.parent, ignore_errors=True))
        path = PATH
        if with_fake:
            d = pathlib.Path(fake_dir or tempfile.mkdtemp(prefix="sag-guard-fake-"))
            self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
            fake = d / "sudo-ask"
            fake.write_text('#!/bin/bash\necho "$*" >> "$FAKE_LOG"\n')
            fake.chmod(0o755)
            path = "%s:%s" % (d, PATH)
        env = {"PATH": path, "HOME": str(log.parent), "FAKE_LOG": str(log), "TMPDIR": "/tmp"}
        p = subprocess.run([str(SETUP), *args], capture_output=True, text=True, env=env, check=False)
        return p, (log.read_text() if log.exists() else "")

    def test_live_guard_refuses_without_a_temp_fake_or_live(self) -> None:
        outside = tempfile.mkdtemp(prefix="sag-guard-out-", dir=str(ROOT / "tests"))  # a real, non-temp location
        if any(os.path.realpath(outside).startswith(os.path.realpath(t) + "/") for t in ("/tmp", "/var/folders")):
            self.skipTest("the repo itself lives in a temp dir")
        for args, kw in (((), {"with_fake": False}), (("--rollback",), {"with_fake": False}),
                         ((), {"fake_dir": outside}), (("--rollback",), {"fake_dir": outside}),
                         (("--verify",), {}), (("--verify",), {"fake_dir": outside})):
            with self.subTest(args=args, **{k: bool(v) for k, v in kw.items()}):
                p, calls = self.guarded(*args, **kw)
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertIn("refusing to run", p.stderr)
                self.assertEqual(calls, "")
        __import__("shutil").rmtree(outside, ignore_errors=True)

    def test_temp_fake_runs_install_and_rollback_without_verify(self) -> None:
        p, calls = self.guarded()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("skipped --verify", p.stdout)
        self.assertEqual(len(calls.splitlines()), 1)
        self.assertIn("visudo -cf", calls)
        # MED-2 / LOW-10b: the root body pins PATH, replaces the helper by rename, re-checks the whole sudoers set
        # and removes the drop-in again if that fails
        self.assertIn("PATH=/usr/bin:/bin:/usr/sbin:/sbin;set -e", calls)
        self.assertIn("install -S -o root -g wheel -m 755", calls)
        self.assertIn("visudo -c>/dev/null||{ rm -f $S;exit 1;}", calls)
        self.assertLess(len(calls.splitlines()[0]), 700 + 200)   # the dialog text is capped at 700 by the script
        p, calls = self.guarded("--rollback")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("rm -f /etc/sudoers.d/sudo-ask-grant", calls)
        self.assertIn("PATH=/usr/bin:/bin:/usr/sbin:/sbin; rm -f", calls)
        self.assertIn("rm -rf /var/db/sudo-ask", calls)

    def test_verify_never_runs_without_live(self) -> None:
        p, _ = self.guarded("--verify", with_fake=False)
        self.assertEqual(p.returncode, 2)

    def test_read_only_modes_need_no_guard(self) -> None:
        for args in (("--print",), ("--check",)):
            p, calls = self.guarded(*args, with_fake=False)
            self.assertIn(p.returncode, (0, 3), p.stderr)
            self.assertEqual(calls, "")

    def test_justfile_recipes_pass_live(self) -> None:
        jf = (ROOT / "justfile").read_text()
        for mode in ("", " --verify", " --rollback"):
            self.assertIn("sudo-ask-grant-setup.sh%s --live\n" % mode, jf)

    def test_script_syntax(self) -> None:
        for f in (SETUP, CLIENT):
            self.assertEqual(subprocess.run(["bash", "-n", str(f)], check=False).returncode, 0)


class ClientTests(unittest.TestCase):
    """bin/sudo-ask as a patched copy driven by fakes (absolute paths, one state dir)."""

    FAKE_SUDO = """#!/bin/bash
echo "sudo $*" >> "$FAKE_STATE/calls"
[ "$1" = -n ] && [ -f "$FAKE_STATE/n_needs_auth" ] && exit 1   # a sudoers line that needs authentication
[ "$1" = -k ] && shift
[ $# -eq 0 ] && exit 0
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
    # The fake approval-gate: status/check/ask driven by files in FAKE_STATE (open_until, check_rc, exec_rc).
    FAKE_GATE = """#!/bin/bash
echo "gate $*" >> "$FAKE_STATE/calls"
case $1 in
  status)
    if [ -f "$FAKE_STATE/open_until" ]; then
      e=$(cat "$FAKE_STATE/open_until")
      echo open=1; echo reason=window open; echo expires_epoch=$e
      echo expires_utc=$(TZ=UTC gdate -d @$e +%Y-%m-%dT%H:%M:%SZ); echo remaining_s=$((e - $(gdate +%s)))
      exit 0
    fi
    echo open=0; echo reason="no window is open"; exit 1 ;;
  check)
    [ -f "$FAKE_STATE/open_until" ] || exit 1
    [ "$(cat "$FAKE_STATE/check_rc" 2>/dev/null || echo 0)" = 0 ] || exit 1
    exit 0 ;;
  ask) while [ "$1" != -- ]; do shift; done; shift
       echo "ran: $*" >> "$FAKE_STATE/calls"; exit "$(cat "$FAKE_STATE/exec_rc" 2>/dev/null || echo 0)" ;;
esac
exit 0
"""
    FAKE_HELPER = """#!/bin/bash
echo "helper $*" >> "$FAKE_STATE/calls"
case $1 in
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
                           ("hermes-ping", cls.FAKE_PING), ("sudo-ask-granted", cls.FAKE_HELPER),
                           ("approval-gate", cls.FAKE_GATE)):
            f = base / name
            f.write_text(body)
            f.chmod(0o755)
            cls.fakes[name] = f
        src = CLIENT.read_text()
        for old, new in (("HELPER=/usr/local/libexec/sudo-ask-granted\n", "HELPER=%s\n" % cls.fakes["sudo-ask-granted"]),
                         ("SUDO=/usr/bin/sudo\n", "SUDO=%s\n" % cls.fakes["sudo"]),
                         ("OSASCRIPT=/usr/bin/osascript\n", "OSASCRIPT=%s\n" % cls.fakes["osascript"]),
                         ("PING=hermes-ping\n", "PING=%s\n" % cls.fakes["hermes-ping"]),
                         ('GATE=$(dirname "$(/usr/bin/readlink -f "${BASH_SOURCE[0]}")")/approval-gate\n',
                          "GATE=%s\n" % cls.fakes["approval-gate"])):
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
        self.assertIn("sudo -k echo hi there", self.calls())   # MED-1: -k, so no machine-wide ticket is left behind
        self.assertNotIn("sudo echo hi there", self.calls())
        self.assertIn("ALLOWED", self.log())
        self.assertNotIn("GRANTED-WINDOW", self.log())

    def test_helper_absent_normal_path(self) -> None:
        p = self.run_client("echo", "x", helper=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.dialogs()), 1)

    def test_gate_absent_normal_path(self) -> None:
        self.open_window()
        client = self.state / "sudo-ask"
        client.write_text(self.client.read_text().replace(str(self.fakes["approval-gate"]), "/nonexistent/gate"))
        client.chmod(0o755)
        env = {"PATH": PATH, "HOME": str(self.state), "XDG_STATE_HOME": str(self.state / "xdg"),
               "FAKE_STATE": str(self.state), "SUDO_ASK_MAX_WAIT": "1"}
        p = subprocess.run([str(client), "echo", "x"], capture_output=True, text=True, env=env, cwd=str(self.state), check=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.dialogs()), 1)
        self.assertNotIn("GRANTED-WINDOW", self.log())

    def test_deny_still_denies(self) -> None:
        (self.state / "answer").write_text("Deny|false")
        p = self.run_client("echo", "x")
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("sudo -k echo x", self.calls())

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

    def test_k_probe_in_a_window_has_no_dialog_and_no_fresh_auth(self) -> None:
        self.open_window()
        for args in (("-k", "/usr/bin/printf", "x y"), ("-k", "-k", "/usr/bin/printf", "x y")):
            with self.subTest(args=args):
                (self.state / "calls").unlink(missing_ok=True)
                p = self.run_client(*args)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(self.dialogs(), [])
                calls = self.calls()
                self.assertIn("gate check --gate sudo-ask -- /usr/bin/printf x y", calls)
                self.assertIn("gate ask --gate sudo-ask --reason sudo-ask -- /usr/bin/printf x y", calls)
                self.assertIn("ran: /usr/bin/printf x y", calls)
                self.assertFalse([c for c in calls if c.startswith("sudo")], "no sudo, so no -k and no fresh auth")
                self.assertIn("GRANTED-WINDOW", self.log())

    def test_k_probe_without_a_window_is_the_normal_dialog_with_k_kept(self) -> None:
        p = self.run_client("-k", "/usr/bin/printf", "x")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.dialogs()), 1)
        self.assertIn("sudo -k /usr/bin/printf x", self.calls())
        self.assertNotIn("GRANTED-WINDOW", self.log())

    def test_k_probe_denied_by_the_gate_inside_a_window_prompts(self) -> None:
        self.open_window()
        (self.state / "check_rc").write_text("1")
        self.run_client("-k", "visudo")
        self.assertEqual(len(self.dialogs()), 1)
        self.assertIn("sudo -k visudo", self.calls())
        self.assertFalse([c for c in self.calls() if c.startswith("ran:")])

    def test_k_alone_or_before_another_option_never_takes_the_window_path(self) -> None:
        self.open_window()
        for args in (("-k",), ("-k", "-n", "true"), ("-k", "FOO=1", "true")):
            with self.subTest(args=args):
                (self.state / "calls").unlink(missing_ok=True)
                self.run_client(*args)
                self.assertEqual(len(self.dialogs()), 1)
                self.assertFalse([c for c in self.calls() if c.startswith("ran:")])
                self.assertFalse([c for c in self.calls() if c.startswith("gate check")])

    def test_window_is_decided_by_the_gate_not_reimplemented(self) -> None:
        src = CLIENT.read_text()
        for name in ("status --check", "read_grant", "exec --"):
            self.assertNotIn(name, src)

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
        grant_call = next(c for c in calls if c.startswith("sudo ") and "grant" in c)
        self.assertTrue(grant_call.startswith("sudo -k "), grant_call)   # the helper proves fresh auth by this -k
        self.assertLess(calls.index("sudo -k"), calls.index(grant_call))
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
        self.assertIn("sudo -n %s revoke" % self.fakes["sudo-ask-granted"], self.calls())   # ruling 3: no auth needed
        self.assertNotIn("sudo -k", self.calls())
        self.assertEqual(self.dialogs(), [])
        self.assertFalse((self.state / "open_until").exists())
        self.assertTrue(any(c.startswith("ping: sudo-ask: approval window revoked") for c in self.calls()))
        self.assertIn("WINDOW-REVOKE", self.log())

    def test_revoke_falls_back_to_authentication_on_an_older_install(self) -> None:
        self.open_window()
        (self.state / "n_needs_auth").write_text("")
        p = self.run_client("--revoke")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("sudo -k %s revoke" % self.fakes["sudo-ask-granted"], self.calls())
        self.assertFalse((self.state / "open_until").exists())

    def test_the_helper_by_hand_gets_a_warning_in_the_dialog(self) -> None:   # LOW-10a
        helper = str(self.fakes["sudo-ask-granted"])
        link = self.state / "innocent"
        os.symlink(helper, link)
        for prog in (helper, str(link)):
            with self.subTest(prog=prog):
                (self.state / "calls").unlink(missing_ok=True)
                (self.state / "open_until").unlink(missing_ok=True)   # the fake helper's grant opened a window
                self.run_client(prog, "grant", "24h")
                self.assertTrue(any("APPROVAL-WINDOW HELPER" in c for c in self.dialogs()), self.dialogs())
        (self.state / "calls").unlink(missing_ok=True)
        self.run_client("echo", "x")
        self.assertFalse(any("APPROVAL-WINDOW HELPER" in c for c in self.dialogs()))

    def test_every_sudo_the_client_runs_is_k(self) -> None:   # MED-1: never feeds the machine-wide ticket
        self.run_client("echo", "x")
        self.run_client("-k", "echo", "y")
        self.run_client("--grant", "1h")
        self.run_client("--revoke")
        for c in self.calls():
            if c.startswith("sudo "):
                self.assertTrue(c.startswith(("sudo -k", "sudo -n %s revoke" % self.fakes["sudo-ask-granted"])), c)

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
