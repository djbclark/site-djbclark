from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_SCRIPT = ROOT / "bin" / "ops_release_lock.py"
DEPLOY_SCRIPT = ROOT / "bin" / "deploy_ops_release.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class OpsReleaseLockTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.state = Path(self._tmpdir.name)
        self.lock = self.state / "ops-release.lock"
        self.claim = self.state / "ops-release.claim.json"
        self.env = {
            **os.environ,
            "SITE_OPS_RELEASE_LOCK": str(self.lock),
            "SITE_OPS_RELEASE_CLAIM": str(self.claim),
            "SITE_OPS_RELEASE_STATE": str(self.state),
        }

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def run_lock(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(LOCK_SCRIPT), *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_claim_begin_end_status(self) -> None:
        begin = self.run_lock(
            "claim", "begin", "1.0.2", "--operation", "cut", "--holder", "test"
        )
        self.assertEqual(begin.returncode, 0, begin.stderr)
        status = self.run_lock("claim", "status")
        self.assertEqual(status.returncode, 0)
        self.assertIn("version=1.0.2", status.stdout)
        data = json.loads(self.claim.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], "1.0.2")
        self.assertEqual(data["operation"], "cut")
        end = self.run_lock("claim", "end", "--version", "1.0.2")
        self.assertEqual(end.returncode, 0, end.stderr)
        status2 = self.run_lock("claim", "status")
        self.assertIn("claim: none", status2.stdout)

    def test_second_begin_blocked_while_live(self) -> None:
        first = self.run_lock("claim", "begin", "1.0.1", "--operation", "deploy")
        self.assertEqual(first.returncode, 0, first.stderr)
        # Same process is the holder; begin different version should still block
        # because claim is live for 1.0.1.
        second = self.run_lock("claim", "begin", "1.0.2", "--operation", "cut")
        self.assertEqual(second.returncode, 75, second.stderr + second.stdout)
        force = self.run_lock(
            "claim", "begin", "1.0.2", "--operation", "cut", "--force"
        )
        self.assertEqual(force.returncode, 0, force.stderr)
        self.run_lock("claim", "end", "--version", "1.0.2", "--force")

    def test_hold_runs_command(self) -> None:
        result = self.run_lock("hold", "--", "python3", "-c", "print('ok')")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    def test_deploy_refuses_foreign_claim(self) -> None:
        deploy = load("deploy_ops_release_for_claim", DEPLOY_SCRIPT)
        self.claim.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "version": "1.0.1",
                    "operation": "cut",
                    "pid": os.getpid(),
                    "hostname": "test",
                    "holder": "test",
                    "started_at": "2099-01-01T00:00:00Z",
                    "note": "",
                }
            ),
            encoding="utf-8",
        )
        os.environ["SITE_OPS_RELEASE_CLAIM"] = str(self.claim)
        try:
            with self.assertRaises(deploy.ReleaseError) as ctx:
                deploy.assert_claim_allows("1.0.2", require_claim=False)
            self.assertIn("1.0.1", str(ctx.exception))
        finally:
            os.environ.pop("SITE_OPS_RELEASE_CLAIM", None)


if __name__ == "__main__":
    unittest.main()
