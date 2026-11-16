"""macos/quiet: policy decisions, store emptying, and drift against the site lists.

The live freezer on this machine is still bin/apple_daemon_ban.sh. quiet-mac
is the copy someone can install without the rest of ~/ops. These tests fail
when those lists diverge, and they never signal a real process.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import pathlib
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
QUIET = ROOT / "macos" / "quiet" / "quiet_mac.py"
POLICY = ROOT / "macos" / "quiet" / "daemons.tsv"
ROOT_SH = ROOT / "macos" / "quiet" / "quiet-mac-root.sh"
SIP = ROOT / "macos" / "sip-doit-with-sudo.sh"
BAN = ROOT / "bin" / "apple_daemon_ban.sh"
BAN_ROOT = ROOT / "roles" / "watchdogd" / "files" / "apple_daemon_ban_root.sh"

_spec = importlib.util.spec_from_file_location("quiet_mac", QUIET)
assert _spec and _spec.loader
qm = importlib.util.module_from_spec(_spec)
sys.modules["quiet_mac"] = qm
_spec.loader.exec_module(qm)


def _bash_array(text: str, name: str) -> set[str]:
    match = re.search(rf"^{name}=\((.*?)\n\)", text, re.DOTALL | re.MULTILINE)
    if not match:
        raise AssertionError(f"array {name} not found")
    return set(re.findall(r'"(com\.apple\.[^"]+)"', match.group(1)))


def _flag_only(text: str) -> set[str]:
    match = re.search(r'^FLAG_ONLY_DAEMONS="([^"]*)"', text, re.MULTILINE)
    if not match:
        raise AssertionError("FLAG_ONLY_DAEMONS not found")
    return set(match.group(1).split())


class PolicyTests(unittest.TestCase):
    def test_policy_loads_and_rejects_a_frozen_root_daemon(self) -> None:
        jobs = qm.load_policy(POLICY)
        self.assertGreaterEqual(len(jobs), 40)
        self.assertTrue(
            all(job.action != "freeze" or job.domain != "system" for job in jobs)
        )
        labels = {job.label for job in jobs}
        self.assertNotIn("com.apple.BiomeAgent", labels)
        flow = next(job for job in jobs if job.label == "com.apple.intelligenceflowd")
        self.assertEqual(flow.action, "flag")

    def test_bad_policy_rows_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "daemons.tsv"
            path.write_text(
                "freeze\tsystem\tcom.apple.cloudd\tno\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                qm.load_policy(path)
            path.write_text(
                "freeze\tgui\tcom.apple.suggestd\ta\nfreeze\tgui\tcom.apple.suggestd\tb\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                qm.load_policy(path)

    def test_lists_match_the_site_scripts(self) -> None:
        jobs = qm.load_policy(POLICY)
        by = lambda action, domain: {
            j.label for j in jobs if j.action == action and j.domain == domain
        }
        sip = SIP.read_text(encoding="utf-8")
        ban = BAN.read_text(encoding="utf-8")
        root = BAN_ROOT.read_text(encoding="utf-8")
        self.assertEqual(by("freeze", "gui"), _bash_array(ban, "FREEZE_LABELS"))
        self.assertEqual(by("freeze", "user"), _bash_array(ban, "USER_FREEZE_LABELS"))
        self.assertEqual(by("term", "gui"), _bash_array(ban, "TERM_LABELS"))
        self.assertEqual(by("term", "system"), _bash_array(root, "SYSTEM_LABELS"))
        gui = {j.label for j in jobs if j.domain == "gui"}
        user = {j.label for j in jobs if j.domain == "user"}
        system = {j.label for j in jobs if j.domain == "system"}
        self.assertEqual(gui, _bash_array(sip, "GUI_DAEMONS"))
        self.assertEqual(user, _bash_array(sip, "USER_DAEMONS"))
        self.assertEqual(system, _bash_array(sip, "SYSTEM_DAEMONS"))
        self.assertEqual({j.label for j in jobs if j.action == "flag"}, _flag_only(sip))
        stores = set(re.findall(r'"(Library/Metadata/CoreSpotlight/[^"]+)"', sip))
        self.assertEqual(set(qm.SEMANTIC_STORES), stores)


class RootHelperPathTests(unittest.TestCase):
    """The root helper runs through NOPASSWD sudo: no user-owned brew tools."""

    def test_root_helper_uses_only_system_tools(self) -> None:
        root = BAN_ROOT.read_text(encoding="utf-8")
        self.assertIn("\nPATH=/usr/bin:/bin:/usr/sbin:/sbin\n", root)
        code = "\n".join(
            line for line in root.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertNotIn("/opt/homebrew", code)
        lines = [ln for ln in code.splitlines() if ln.strip()]
        self.assertEqual(lines[0], "PATH=/usr/bin:/bin:/usr/sbin:/sbin")
        self.assertEqual(sum("PATH=" in ln for ln in lines), 1, "PATH set twice")
        self.assertIsNone(
            re.search(r"\bg(awk|date|sed|grep|tail|head|mktemp|stat|find|xargs|sort|cut|tr|wc|readlink|realpath|timeout|ls|touch|chmod|chown|ln|cp|mv|rm|base64)\b", code),
            "a g* tool in a root-run script",
        )


class DecisionTests(unittest.TestCase):
    def job(self, action: str, domain: str = "gui") -> qm.Job:
        return qm.Job(action, domain, "com.apple.example", "because")

    def live(self, **kwargs) -> qm.Live:
        base = {
            "disabled": True,
            "pid": None,
            "frozen": False,
            "age_s": None,
            "rss_kb": None,
        }
        base.update(kwargs)
        return qm.Live(**base)

    def test_freeze_stops_a_running_job_and_leaves_a_frozen_one(self) -> None:
        job = self.job("freeze")
        running = self.live(pid=4, age_s=10)
        self.assertEqual(
            [a.kind for a in qm.actions_for(job, running)],
            ["stop"],
        )
        frozen = self.live(pid=4, frozen=True, age_s=500)
        self.assertEqual(qm.actions_for(job, frozen), [])
        self.assertIsNone(qm.problem(job, frozen))
        self.assertTrue(qm.desired(job, frozen))

    def test_young_runner_is_not_a_check_failure(self) -> None:
        job = self.job("freeze")
        young = self.live(pid=4, age_s=30)
        self.assertIsNone(qm.problem(job, young))
        old = self.live(pid=4, age_s=121)
        self.assertIn("running unfrozen", qm.problem(job, old) or "")

    def test_term_does_not_kill_a_frozen_one_shot(self) -> None:
        job = self.job("term")
        frozen = self.live(pid=9, frozen=True, age_s=1000)
        self.assertEqual(qm.actions_for(job, frozen), [])

    def test_flag_only_is_never_signalled(self) -> None:
        job = self.job("flag")
        running = self.live(disabled=False, pid=3, age_s=9999)
        kinds = [a.kind for a in qm.actions_for(job, running)]
        self.assertEqual(kinds, ["disable"])
        self.assertIsNone(qm.problem(job, self.live(pid=3, age_s=9999)))

    def test_system_jobs_are_not_signalled_by_the_user_pass(self) -> None:
        job = self.job("term", "system")
        self.assertEqual(qm.actions_for(job, self.live(pid=2, age_s=5)), [])
        self.assertIsNone(qm.problem(job, self.live(pid=2, age_s=5)))
        self.assertIn(
            "running unfrozen", qm.problem(job, self.live(pid=2, age_s=500)) or ""
        )
        self.assertIn(
            "frozen root", qm.problem(job, self.live(pid=2, frozen=True)) or ""
        )

    def test_missing_flag_is_a_problem_even_when_stopped(self) -> None:
        job = self.job("freeze")
        live = self.live(disabled=False, pid=4, frozen=True)
        self.assertEqual(qm.problem(job, live), "flag not set: gui/com.apple.example")


class IndexAndStoreTests(unittest.TestCase):
    def test_nightly_window(self) -> None:
        self.assertFalse(qm.in_nightly_window(dt.datetime(2026, 1, 1, 0, 59)))
        self.assertTrue(qm.in_nightly_window(dt.datetime(2026, 1, 1, 1, 0)))
        self.assertTrue(qm.in_nightly_window(dt.datetime(2026, 1, 1, 5, 45)))
        self.assertFalse(qm.in_nightly_window(dt.datetime(2026, 1, 1, 5, 46)))

    def test_indexing_guard_is_only_for_a_neofinder_machine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            when = dt.datetime(2026, 1, 1, 2, 0)
            self.assertFalse(qm.skip_indexing_off(home, when, False, []))
            (home / "nfbatch.sparseimage").write_text("x", encoding="utf-8")
            self.assertTrue(qm.skip_indexing_off(home, when, False, []))
            self.assertFalse(
                qm.skip_indexing_off(home, dt.datetime(2026, 1, 1, 12, 0), False, [])
            )

    def test_empty_store_removes_children_and_keeps_symlink_targets(self) -> None:
        if not str(pathlib.Path.home()).startswith("/Users/"):
            self.skipTest("home is not under /Users")
        with tempfile.TemporaryDirectory(dir=pathlib.Path.home()) as tmp:
            home = pathlib.Path(tmp)
            rel = qm.SEMANTIC_STORES[0]
            store = home / rel
            store.mkdir(parents=True)
            (store / "embed").write_bytes(b"x" * 10)
            nested = store / "sub"
            nested.mkdir()
            (nested / "j").write_bytes(b"yy")
            outside = home / "outside"
            outside.write_text("keep", encoding="utf-8")
            (store / "link").symlink_to(outside)
            self.assertEqual(qm.empty_store(home, rel, only_over=100), 0)
            self.assertTrue((store / "embed").exists())
            removed = qm.empty_store(home, rel, only_over=0)
            self.assertGreaterEqual(removed, 3)
            self.assertEqual(outside.read_text(encoding="utf-8"), "keep")
            self.assertEqual(list(store.iterdir()), [])

    def test_empty_store_refuses_a_symlinked_directory(self) -> None:
        if not str(pathlib.Path.home()).startswith("/Users/"):
            self.skipTest("home is not under /Users")
        with tempfile.TemporaryDirectory(dir=pathlib.Path.home()) as tmp:
            home = pathlib.Path(tmp)
            real = home / "real-store"
            real.mkdir()
            (real / "secret").write_text("no", encoding="utf-8")
            link_parent = home / "Library/Metadata/CoreSpotlight"
            link_parent.mkdir(parents=True)
            (link_parent / "DocumentProcessing").symlink_to(real)
            with self.assertRaises(ValueError):
                qm.empty_store(home, qm.SEMANTIC_STORES[0], only_over=0)
            self.assertEqual((real / "secret").read_text(encoding="utf-8"), "no")


class RenderTests(unittest.TestCase):
    def test_sudoers_is_four_exact_commands(self) -> None:
        text = qm.sudoers_text("ada")
        self.assertIn(
            "ada ALL=(root) NOPASSWD: /usr/local/libexec/quiet-mac/quiet-mac-root\n",
            text,
        )
        self.assertIn("quiet-mac-root-revert", text)
        self.assertIn("/usr/bin/mdutil -a -i off\n", text)
        self.assertIn("/usr/bin/profiles list\n", text)
        self.assertEqual(text.count("NOPASSWD:"), 4)
        self.assertNotIn("ALL=(ALL)", text)
        with self.assertRaises(ValueError):
            qm.sudoers_text("ada bad")
        self.assertFalse(qm.sudoers_is_current(None, False, "ada"))
        self.assertTrue(qm.sudoers_is_current(None, True, "ada"))
        self.assertTrue(qm.sudoers_is_current(text, False, "ada"))
        self.assertFalse(qm.sudoers_is_current("other\n", True, "ada"))

    def test_plists_thaw_is_persistent_and_enforce_is_a_minute(self) -> None:
        home = pathlib.Path("/Users/ada")
        logs = home / "Library/Logs/quiet-mac"
        enforce = qm.enforce_plist(
            "/opt/homebrew/bin/python3", "/opt/quiet_mac.py", home, logs
        )
        thaw = qm.thaw_plist(
            "/opt/homebrew/bin/python3", "/opt/quiet_mac.py", home, logs
        )
        self.assertEqual(enforce["StartInterval"], 60)
        self.assertNotIn("KeepAlive", enforce)
        self.assertTrue(thaw["KeepAlive"])
        self.assertEqual(thaw["ProgramArguments"][-1], "thaw-wait")
        self.assertEqual(enforce["ProgramArguments"][-1], "enforce")

    def test_prepare_user_files_writes_under_the_override_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            env = os.environ.get("QUIET_MAC_HOME")
            os.environ["QUIET_MAC_HOME"] = str(home)
            try:
                enforce, thaw, _enforce_changed, _thaw_changed = qm.prepare_user_files(
                    "/opt/homebrew/bin/python3"
                )
                again = qm.prepare_user_files("/opt/homebrew/bin/python3")
            finally:
                if env is None:
                    os.environ.pop("QUIET_MAC_HOME", None)
                else:
                    os.environ["QUIET_MAC_HOME"] = env
            self.assertTrue(enforce.exists())
            loaded = plistlib.loads(thaw.read_bytes())
            self.assertEqual(loaded["Label"], qm.LABEL_THAW)
            self.assertTrue((home / ".local/libexec/quiet-mac/daemons.tsv").is_file())
            version = home / ".local/libexec/quiet-mac/VERSION"
            self.assertEqual(version.read_text(encoding="utf-8").strip(), qm.VERSION)
            self.assertFalse(again[2])
            self.assertFalse(again[3])


class RootHelperTests(unittest.TestCase):
    def test_root_helper_disables_only_system_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            log = work / "launchctl.log"
            fake_bin = work / "bin"
            fake_bin.mkdir()
            launcher = fake_bin / "launchctl"
            launcher.write_text(
                textwrap.dedent(
                    f"""\
                    #!/bin/bash
                    printf '%s\\n' "$*" >> {log}
                    exit 0
                    """
                ),
                encoding="utf-8",
            )
            launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
            policy = work / "daemons.tsv"
            policy.write_text(
                "freeze\tgui\tcom.apple.suggestd\tuser job\n"
                "term\tsystem\tcom.apple.cloudd\tsystem job\n"
                "flag\tsystem\tcom.apple.modelmanagerd\tflag only\n",
                encoding="utf-8",
            )
            helper = work / "quiet-mac-root"
            helper.write_bytes(ROOT_SH.read_bytes())
            helper.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
            env["QUIET_MAC_POLICY"] = str(policy)
            result = subprocess.run(
                [str(helper)],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            recorded = log.read_text(encoding="utf-8")
            self.assertIn("disable system/com.apple.cloudd", recorded)
            self.assertIn("disable system/com.apple.modelmanagerd", recorded)
            self.assertNotIn("suggestd", recorded)
            refused = subprocess.run(
                [str(helper), "please"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(refused.returncode, 2)

    def test_stopped_ps_rows(self) -> None:
        text = "  10 S+ /bin/sleep\n  11 T /usr/libexec/suggestd\n  12 R+ other\n"
        self.assertEqual(qm.stopped_from_ps(text), [(11, "T", "/usr/libexec/suggestd")])

    def test_etime(self) -> None:
        self.assertEqual(qm._etime_seconds("01:02:03"), 3723)
        self.assertEqual(qm._etime_seconds("2-00:00:01"), 2 * 86400 + 1)
        self.assertEqual(qm._etime_seconds("45"), 45)


class VersionAndGuideTests(unittest.TestCase):
    def test_version_relation(self) -> None:
        self.assertEqual(qm.version_relation(None), "missing")
        self.assertEqual(qm.version_relation("1.0.0", "1.0.0"), "same")
        self.assertEqual(qm.version_relation("0.9.0", "1.0.0"), "older")
        self.assertEqual(qm.version_relation("2.0.0", "1.0.0"), "newer")
        self.assertEqual(qm.version_relation("nope"), "invalid")

    def test_upgrade_refuses_a_downgrade_without_installing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            lib = home / ".local/libexec/quiet-mac"
            lib.mkdir(parents=True)
            (lib / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            previous = os.environ.get("QUIET_MAC_HOME")
            os.environ["QUIET_MAC_HOME"] = str(home)
            os.environ["QUIET_MAC_NO_NOTIFY"] = "1"
            try:
                self.assertEqual(qm.cmd_upgrade(), 1)
            finally:
                if previous is None:
                    os.environ.pop("QUIET_MAC_HOME", None)
                else:
                    os.environ["QUIET_MAC_HOME"] = previous
                os.environ.pop("QUIET_MAC_NO_NOTIFY", None)

    def test_silicon_and_recovery_text(self) -> None:
        self.assertEqual(qm.silicon_kind("arm64"), "apple")
        self.assertEqual(qm.silicon_kind("x86_64"), "intel")
        apple = qm.recovery_text("apple")
        intel = qm.recovery_text("intel")
        self.assertIn("does not boot into Recovery", apple)
        self.assertIn("next login", apple)
        self.assertIn("com.quiet-mac.enforce", apple)
        self.assertIn("power button", apple)
        self.assertIn("Command-R", intel)
        self.assertIn("does not boot into Recovery", intel)
        self.assertIn("next login", intel)
        self.assertNotIn("power button", intel)

    def test_plocate_plan_keeps_an_existing_nightly(self) -> None:
        self.assertEqual(
            qm.plocate_plan(True, "gui/1/com.djbclark.plocate-updatedb", True), "keep"
        )
        self.assertEqual(qm.plocate_plan(True, None, True), "start-nightly")
        self.assertEqual(qm.plocate_plan(False, None, True), "install-and-start")
        self.assertEqual(
            qm.plocate_plan(False, "gui/1/sh.brew.plocate", True), "install-only"
        )
        self.assertEqual(qm.plocate_plan(False, None, False), "need-brew")

    def test_sudo_nag_is_printed_once(self) -> None:
        findings = [
            qm.Finding("error", "sudo", "flag not set: system/com.apple.cloudd"),
            qm.Finding("error", "sudo", "flag not set: system/com.apple.spindump"),
            qm.Finding("warning", "version", "not installed"),
        ]
        text = qm.render_findings(findings)
        self.assertEqual(text.count("NAG:"), 1)
        self.assertIn("just install", text)
        self.assertIn("just system-flags", text)

    def test_usage_tracking_agent_is_flag_only(self) -> None:
        jobs = {(job.domain, job.label): job for job in qm.load_policy()}
        job = jobs[("gui", "com.apple.UsageTrackingAgent")]
        self.assertEqual(job.action, "flag")

    def test_readme_names_every_daemon_and_the_new_commands(self) -> None:
        readme = (ROOT / "macos" / "README.md").read_text(encoding="utf-8")
        for job in qm.load_policy():
            self.assertIn(job.label, readme, job.label)
        for word in (
            "just doctor",
            "just upgrade",
            "just factory",
            "plocate -i",
            "NeoFinder",
            "corner-rescue",
            "stagger-login",
            "net-watch",
            "Device Management",
            "1.1.0",
        ):
            self.assertIn(word, readme)

    def test_profile_steps_follow_the_os(self) -> None:
        self.assertEqual(
            qm.profiles_settings_location("14.6"), "Privacy & Security → Profiles"
        )
        self.assertEqual(
            qm.profiles_settings_location("15.0"), "General → Device Management"
        )
        self.assertEqual(
            qm.profiles_settings_location("27.2"), "General → Device Management"
        )
        self.assertEqual(
            qm.profiles_settings_location("12.7"), "System Preferences → Profiles"
        )
        steps = qm.profile_install_steps("General → Device Management")
        self.assertIn("No Apple Intelligence (djbclark)", steps)
        self.assertIn("8 minutes", steps)
        self.assertIn("Enter and Esc do not install it", steps)
        self.assertIn("1. System Settings opens", steps)

    def test_profile_install_is_skipped_under_the_test_home(self) -> None:
        previous = os.environ.get("QUIET_MAC_HOME")
        os.environ["QUIET_MAC_HOME"] = "/tmp/quiet-mac-test-home"
        try:
            self.assertEqual(qm.ensure_intelligence_profile(), 0)
        finally:
            if previous is None:
                os.environ.pop("QUIET_MAC_HOME", None)
            else:
                os.environ["QUIET_MAC_HOME"] = previous

    def test_disable_toml_service_is_idempotent(self) -> None:
        text = 'name = "apple-daemons"\ninterval_s = 60\n'
        once, note = qm.disable_toml_service(text, "apple-daemons")
        self.assertEqual(note, "inserted")
        self.assertIn("enabled = false\n", once)
        twice, note_again = qm.disable_toml_service(once, "apple-daemons")
        self.assertEqual(note_again, "already")
        self.assertEqual(twice, once)
        flipped, note_true = qm.disable_toml_service(
            "enabled = true\n", "apple-daemons"
        )
        self.assertEqual(note_true, "disabled")
        self.assertNotIn("enabled = true", flipped)


if __name__ == "__main__":
    unittest.main()
