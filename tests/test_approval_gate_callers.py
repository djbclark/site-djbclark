"""Unit tests for site callers wired onto sudo-ask (bin/tired, neofinder-spotlight-batch.sh)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TIRED = ROOT / "bin" / "tired"
NEOFINDER_BATCH = ROOT / "macos" / "neofinder" / "neofinder-spotlight-batch.sh"
HELPER = ROOT / "roles" / "sudo_ask_grant" / "files" / "sudo-ask-granted"

_loader = importlib.machinery.SourceFileLoader("sudo_ask_granted_for_callers", str(HELPER))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
assert _spec
helper = importlib.util.module_from_spec(_spec)
_loader.exec_module(helper)


def _extract_tired_functions() -> str:
    """Return bin/tired without its trailing `main "$@"` invocation so tests can call functions directly."""
    lines = TIRED.read_text(encoding="utf-8").splitlines()
    assert lines[-1].strip() == 'main "$@"'
    return "\n".join(lines[:-1]) + "\n"


def _write_exec(path: pathlib.Path, content: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class TiredSudoAskTests(unittest.TestCase):
    def test_tired_bash_syntax(self) -> None:
        r = subprocess.run(["bash", "-n", str(TIRED)], capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_run_privileged_prefers_sudo_ask_for_single_and_multiline_pmset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            log = base / "calls.log"
            fake_sa = _write_exec(
                base / "fake-sudo-ask",
                f'#!/bin/bash\nprintf "%s\\0" "$@" >> "{log}"\nprintf "\\n---\\n" >> "{log}"\n',
            )
            script = (
                _extract_tired_functions()
                + 'run_privileged "/usr/bin/pmset -a hibernatemode 25"\n'
                + 'run_privileged "$(awake_cmds)"\n'
                + 'run_privileged "$(normal_defaults_cmds)"\n'
            )
            env = {"PATH": "/usr/bin:/bin", "HOME": str(base), "SUDO_ASK_BIN": str(fake_sa)}
            r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)

            records = [rec for rec in log.read_bytes().split(b"\n---\n") if rec]
            self.assertEqual(len(records), 3)

            argv_hib = [a.decode() for a in records[0].split(b"\0") if a]
            argv_awake = [a.decode() for a in records[1].split(b"\0") if a]
            argv_normal = [a.decode() for a in records[2].split(b"\0") if a]

            self.assertEqual(argv_hib, ["/usr/bin/pmset", "-a", "hibernatemode", "25"])
            self.assertEqual(argv_awake[:2], ["/bin/sh", "-c"])
            self.assertIn("/usr/bin/pmset -a disablesleep 1", argv_awake[2])
            self.assertEqual(argv_normal[:2], ["/bin/sh", "-c"])
            self.assertIn("/usr/bin/pmset -a disablesleep 0", argv_normal[2])

            # Verify every command emitted by tired passes the real sudo-ask-granted window policy!
            if sys.platform == "darwin":
                old_uid, old_epoch = helper.INVOKER_UID, helper.GRANTED_EPOCH
                try:
                    helper.INVOKER_UID = os.getuid()
                    helper.GRANTED_EPOCH = None
                    for label, argv in (("hibernate", argv_hib), ("awake", argv_awake), ("normal", argv_normal)):
                        with self.subTest(cmd=label):
                            why = helper.evaluate(argv, "/tmp", helper.EXEC_PATH)
                            self.assertIsNone(why, f"{label} was rejected by sudo-ask-granted: {why}")
                finally:
                    helper.INVOKER_UID, helper.GRANTED_EPOCH = old_uid, old_epoch

    def test_find_sudo_ask_prefers_home_local_bin_and_falls_back_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            home_sa = _write_exec(base / ".local" / "bin" / "sudo-ask", "#!/bin/bash\nexit 0\n")
            script = _extract_tired_functions() + "find_sudo_ask\n"
            env = {"PATH": "/usr/bin:/bin", "HOME": str(base)}
            r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), str(home_sa))

            # Explicit empty SUDO_ASK_BIN disables sudo-ask and falls back to sudo.
            log = base / "sudo.log"
            fake_bin = base / "bin"
            _write_exec(
                fake_bin / "sudo",
                f'#!/bin/bash\nif [ "$1" = "-n" ] && [ "$2" = "true" ]; then exit 0; fi\n'
                f'echo "SUDO $*" >> "{log}"\nexit 0\n',
            )
            script_fb = _extract_tired_functions() + 'run_privileged "/usr/bin/pmset -a hibernatemode 3"\n'
            env_fb = {"PATH": f"{fake_bin}:/usr/bin:/bin", "HOME": str(base), "SUDO_ASK_BIN": ""}
            r_fb = subprocess.run(["bash", "-c", script_fb], env=env_fb, capture_output=True, text=True, check=False)
            self.assertEqual(r_fb.returncode, 0, r_fb.stderr)
            self.assertIn("SUDO /bin/bash ", log.read_text(encoding="utf-8"))


class NeofinderSpotlightBatchTests(unittest.TestCase):
    def test_script_bash_syntax(self) -> None:
        r = subprocess.run(["bash", "-n", str(NEOFINDER_BATCH)], capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_defaults_to_sudo_ask_when_installed_and_falls_back_to_sudo(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("re-exec path only runs when non-root")
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            # 1. Prefer ~/.local/bin/sudo-ask
            home_sa = _write_exec(base / ".local" / "bin" / "sudo-ask", '#!/bin/bash\necho "HOME_SA:$*"\n')
            env = {"PATH": "/usr/bin:/bin", "HOME": str(base)}
            r1 = subprocess.run([str(NEOFINDER_BATCH)], env=env, capture_output=True, text=True, check=False)
            self.assertEqual(r1.returncode, 0, r1.stderr)
            self.assertIn(f"re-execing under {home_sa}", r1.stdout)
            self.assertIn("HOME_SA:", r1.stdout)

            # 2. Fall back to `command -v sudo-ask` on PATH when ~/.local/bin/sudo-ask is absent
            home_sa.unlink()
            path_bin = base / "pathbin"
            path_sa = _write_exec(path_bin / "sudo-ask", '#!/bin/bash\necho "PATH_SA:$*"\n')
            env2 = {"PATH": f"{path_bin}:/usr/bin:/bin", "HOME": str(base)}
            r2 = subprocess.run([str(NEOFINDER_BATCH)], env=env2, capture_output=True, text=True, check=False)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertIn(f"re-execing under {path_sa}", r2.stdout)
            self.assertIn("PATH_SA:", r2.stdout)

            # 3. Fall back to plain `sudo` when sudo-ask is absent everywhere
            path_sa.unlink()
            _write_exec(path_bin / "sudo", '#!/bin/bash\necho "PLAIN_SUDO:$*"\n')
            env3 = {"PATH": f"{path_bin}:/usr/bin:/bin", "HOME": str(base)}
            r3 = subprocess.run([str(NEOFINDER_BATCH)], env=env3, capture_output=True, text=True, check=False)
            self.assertEqual(r3.returncode, 0, r3.stderr)
            self.assertIn("re-execing under sudo", r3.stdout)
            self.assertIn("PLAIN_SUDO:", r3.stdout)

            # 4. Explicit --sudo overrides default
            custom = _write_exec(base / "custom-sudo", '#!/bin/bash\necho "CUSTOM:$*"\n')
            r4 = subprocess.run(
                [str(NEOFINDER_BATCH), "--sudo", str(custom)],
                env=env3,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(r4.returncode, 0, r4.stderr)
            self.assertIn(f"re-execing under {custom}", r4.stdout)
            self.assertIn("CUSTOM:", r4.stdout)


if __name__ == "__main__":
    unittest.main()
