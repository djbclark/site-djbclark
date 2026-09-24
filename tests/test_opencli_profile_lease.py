import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "opencli_profile_lease.py"
SPEC = importlib.util.spec_from_file_location("opencli_profile_lease", SCRIPT)
lease = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(lease)


ALIASES = {
    "version": 1,
    "aliases": {"hermes-gemini": "e93u2d9q", "gemini-alt": "e93u2d9q", "opencli-chrome": "hujux4wm"},
    "defaultContextId": "hujux4wm",
}


class _IsolatedProfilesFile(unittest.TestCase):
    """Point the alias map at a per-test path so the real ~/.opencli never leaks in."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profiles_file = Path(tmp.name) / "browser-profiles.json"
        env = patch.dict(os.environ, {lease.BROWSER_PROFILES_ENV: str(self.profiles_file)})
        env.start()
        self.addCleanup(env.stop)

    def write_profiles(self, content: object) -> None:
        text = content if isinstance(content, str) else json.dumps(content)
        self.profiles_file.write_text(text)


class ProfileLeaseTests(_IsolatedProfilesFile):
    def test_same_profile_reports_owner_metadata_when_busy(self) -> None:
        with tempfile.TemporaryDirectory() as state:
            with lease.ProfileLease("brave-bluehost", "topic-bluehost", "bluehost", 1, state_dir=state):
                with self.assertRaises(lease.LeaseBusy) as ctx:
                    with lease.ProfileLease("brave-bluehost", "topic-gemini", "gemini", 0, state_dir=state):
                        pass
            self.assertEqual(ctx.exception.owner["owner"], "topic-bluehost")
            self.assertEqual(ctx.exception.owner["purpose"], "bluehost")
            self.assertEqual(ctx.exception.owner["profile"], "brave-bluehost")

    def test_busy_reader_waits_for_holder_metadata_publication(self) -> None:
        with tempfile.TemporaryDirectory() as state:
            write_started = threading.Event()
            release_write = threading.Event()
            metadata_published = threading.Event()
            release_holder = threading.Event()
            holder_errors: list[BaseException] = []
            real_write = lease.os.write

            def delayed_write(fd: int, data: bytes) -> int:
                write_started.set()
                if not release_write.wait(1):
                    raise TimeoutError("test did not release metadata write")
                written = real_write(fd, data)
                metadata_published.set()
                return written

            def hold() -> None:
                try:
                    with lease.ProfileLease(
                        "brave-bluehost", "topic-bluehost", "bluehost", 1, state_dir=state
                    ):
                        if not metadata_published.wait(1) or not release_holder.wait(1):
                            raise TimeoutError("test did not release lease holder")
                except BaseException as exc:  # surfaced in the main test thread
                    holder_errors.append(exc)

            with patch.object(lease.os, "write", side_effect=delayed_write):
                thread = threading.Thread(target=hold)
                thread.start()
                self.assertTrue(write_started.wait(1))
                timer = threading.Timer(0.05, release_write.set)
                timer.start()
                try:
                    with self.assertRaises(lease.LeaseBusy) as ctx:
                        with lease.ProfileLease(
                            "brave-bluehost", "topic-gemini", "gemini", 0, state_dir=state
                        ):
                            pass
                finally:
                    release_write.set()
                    release_holder.set()
                    timer.cancel()
                    thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(holder_errors, [])
            self.assertEqual(ctx.exception.owner["owner"], "topic-bluehost")

    def test_distinct_profiles_do_not_contend(self) -> None:
        with tempfile.TemporaryDirectory() as state:
            with lease.ProfileLease("chrome-gemini", "topic-gemini", "gemini", 0, state_dir=state):
                with lease.ProfileLease("brave-bluehost", "topic-bluehost", "bluehost", 0, state_dir=state):
                    pass

    def test_metadata_never_contains_prompt_like_values(self) -> None:
        with tempfile.TemporaryDirectory() as state:
            with lease.ProfileLease("chrome-gemini", "topic-gemini", "gemini", 0, state_dir=state):
                metadata_path = Path(state) / "profiles" / "chrome-gemini.lock"
                metadata = json.loads(metadata_path.read_text())
                self.assertNotIn("prompt", json.dumps(metadata).lower())
                self.assertNotIn("response", json.dumps(metadata).lower())
                self.assertNotIn("token", json.dumps(metadata).lower())

    def test_release_allows_next_owner(self) -> None:
        with tempfile.TemporaryDirectory() as state:
            first = lease.ProfileLease("chrome-gemini", "topic-one", "gemini", 0, state_dir=state)
            first.__enter__()
            first.__exit__(None, None, None)
            with lease.ProfileLease("chrome-gemini", "topic-two", "gemini", 0, state_dir=state):
                pass

    def test_cli_run_blocks_second_process_for_same_profile(self) -> None:
        with tempfile.TemporaryDirectory() as state:
            holder = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "run",
                    "--profile",
                    "brave-bluehost",
                    "--owner",
                    "topic-bluehost",
                    "--purpose",
                    "bluehost",
                    "--state-dir",
                    state,
                    "--lock-timeout",
                    "0",
                    "--",
                    sys.executable,
                    "-c",
                    "import time; time.sleep(0.5)",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                time.sleep(0.1)
                contender = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "run",
                        "--profile",
                        "brave-bluehost",
                        "--owner",
                        "topic-gemini",
                        "--purpose",
                        "gemini",
                        "--state-dir",
                        state,
                        "--lock-timeout",
                        "0",
                        "--",
                        sys.executable,
                        "-c",
                        "raise SystemExit(0)",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(contender.returncode, 16)
                self.assertIn("lock_busy", contender.stderr)
                self.assertIn("topic-bluehost", contender.stderr)
            finally:
                holder.communicate(timeout=2)


class CanonicalProfileTests(_IsolatedProfilesFile):
    def test_alias_resolves_to_context_id(self) -> None:
        self.write_profiles(ALIASES)
        self.assertEqual(lease.canonical_profile("hermes-gemini"), "e93u2d9q")
        self.assertEqual(lease.canonical_profile("opencli-chrome"), "hujux4wm")

    def test_unknown_name_and_context_id_pass_through(self) -> None:
        self.write_profiles(ALIASES)
        self.assertEqual(lease.canonical_profile("e93u2d9q"), "e93u2d9q")
        self.assertEqual(lease.canonical_profile("brave-bluehost"), "brave-bluehost")

    def test_missing_file_falls_back_to_name(self) -> None:
        self.assertFalse(self.profiles_file.exists())
        self.assertEqual(lease.canonical_profile("hermes-gemini"), "hermes-gemini")

    def test_malformed_file_falls_back_to_name(self) -> None:
        for content in ("{not json", "[]", {"aliases": ["hermes-gemini"]}, {"aliases": {"hermes-gemini": 7}}):
            with self.subTest(content=content):
                self.write_profiles(content)
                self.assertEqual(lease.canonical_profile("hermes-gemini"), "hermes-gemini")

    def test_alias_and_context_id_contend_on_one_lock(self) -> None:
        self.write_profiles(ALIASES)
        with tempfile.TemporaryDirectory() as state:
            with lease.ProfileLease("hermes-gemini", "topic-a", "gemini", 1, state_dir=state):
                for contender in ("e93u2d9q", "gemini-alt"):
                    with self.subTest(contender=contender):
                        with self.assertRaises(lease.LeaseBusy) as ctx:
                            with lease.ProfileLease(contender, "topic-b", "gemini", 0, state_dir=state):
                                pass
                        self.assertEqual(ctx.exception.profile, "e93u2d9q")
                        self.assertEqual(ctx.exception.owner["owner"], "topic-a")
                        self.assertEqual(ctx.exception.owner["profile"], "e93u2d9q")
                        self.assertEqual(ctx.exception.owner["requested_profile"], "hermes-gemini")
                status = lease.profile_status("gemini-alt", state_dir=state)
                self.assertTrue(status["busy"])
                self.assertEqual(status["profile"], "e93u2d9q")
                self.assertEqual(status["requested_profile"], "gemini-alt")
            self.assertTrue((Path(state) / "profiles" / "e93u2d9q.lock").exists())
            self.assertFalse((Path(state) / "profiles" / "hermes-gemini.lock").exists())

    def test_distinct_canonical_profiles_do_not_contend(self) -> None:
        self.write_profiles(ALIASES)
        with tempfile.TemporaryDirectory() as state:
            with lease.ProfileLease("hermes-gemini", "topic-a", "gemini", 0, state_dir=state):
                with lease.ProfileLease("opencli-chrome", "topic-b", "chrome", 0, state_dir=state):
                    pass

    def test_cli_run_alias_blocks_context_id_across_processes(self) -> None:
        self.write_profiles(ALIASES)

        def cmd(profile: str, owner: str, child: str) -> list[str]:
            return [
                sys.executable, str(SCRIPT), "run",
                "--profile", profile, "--owner", owner, "--purpose", "gemini",
                "--state-dir", state, "--lock-timeout", "0",
                "--", sys.executable, "-c", child,
            ]

        with tempfile.TemporaryDirectory() as state:
            holder = subprocess.Popen(
                cmd("hermes-gemini", "topic-alias", "import time; time.sleep(0.5)"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                time.sleep(0.1)
                contender = subprocess.run(
                    cmd("e93u2d9q", "topic-id", "raise SystemExit(0)"),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(contender.returncode, 16)
                self.assertIn("lock_busy", contender.stderr)
                self.assertIn("topic-alias", contender.stderr)
            finally:
                holder.communicate(timeout=2)


if __name__ == "__main__":
    unittest.main()
