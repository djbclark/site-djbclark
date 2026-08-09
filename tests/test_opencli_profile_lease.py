import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "opencli_profile_lease.py"
SPEC = importlib.util.spec_from_file_location("opencli_profile_lease", SCRIPT)
lease = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(lease)


class ProfileLeaseTests(unittest.TestCase):
    def test_same_profile_reports_owner_metadata_when_busy(self) -> None:
        with tempfile.TemporaryDirectory() as state:
            with lease.ProfileLease("brave-bluehost", "topic-bluehost", "bluehost", 1, state_dir=state):
                with self.assertRaises(lease.LeaseBusy) as ctx:
                    with lease.ProfileLease("brave-bluehost", "topic-gemini", "gemini", 0, state_dir=state):
                        pass
            self.assertEqual(ctx.exception.owner["owner"], "topic-bluehost")
            self.assertEqual(ctx.exception.owner["purpose"], "bluehost")
            self.assertEqual(ctx.exception.owner["profile"], "brave-bluehost")

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


if __name__ == "__main__":
    unittest.main()
