"""Receipt and target safety contracts for fleet-watch's native Paseo sender."""
import importlib.util
import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("fleet_watch_paseo", Path(__file__).resolve().parents[1] / "bin/fleet_watch_paseo.py")
SENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SENDER)
AID = "5e55a100-0000-0000-0000-000000000000"


class NativeSend(unittest.TestCase):
    def setUp(self):
        self.info = {"Id": AID, "Archived": False, "PendingPermissions": [], "Status": "idle"}
        self.rows = [{"id": AID, "shortId": "5e55a1"}]

    def invoke(self, status="sent", target="5e55a1"):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            if argv[1] == "ls":
                obj = self.rows
            elif argv[1] == "agent":
                obj = self.info
            else:
                self.assertEqual(argv[1:3], ["send", AID])
                self.assertIn("--json", argv)
                self.assertIn("--no-wait", argv)
                self.assertEqual(argv[argv.index("--behavior") + 1], "steer")
                self.assertEqual(Path(argv[argv.index("--prompt-file") + 1]).read_text(), "[fleet-watch] a notice")
                self.assertEqual(os.environ.get("PASEO_AGENT_ID"), "source-id")
                obj = {"status": status}
            return subprocess.CompletedProcess(argv, 0, json.dumps(obj), "")

        with patch.dict(os.environ, {"PASEO_AGENT_ID": "source-id"}), patch.object(SENDER.subprocess, "run", side_effect=run):
            result = SENDER.send(target, "a notice")
        return result, calls

    def test_prefix_and_uuid_require_successful_receipts(self):
        for target in ("5e55a1", AID):
            for status in ("sent", "completed"):
                with self.subTest(target=target, status=status):
                    self.assertEqual(self.invoke(status, target)[0], 0)

    def test_exit_zero_is_not_delivery(self):
        for status in ("queued", "accepted", "timeout", "permission", "error", None, ""):
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, "not delivered"):
                self.invoke(status)

    def test_inspect_failures_never_send(self):
        for key, value in (("Id", "wrong"), ("Archived", True), ("PendingPermissions", [{}]),
                           ("PendingPermissions", None), ("Status", "starting"), ("Status", None)):
            with self.subTest(key=key, value=value):
                original = dict(self.info)
                self.info[key] = value
                with self.assertRaises(ValueError):
                    self.invoke()
                self.info = original

    def test_running_target_requires_steer_support(self):
        self.info.update(Status="running", Provider="unknown")
        with self.assertRaisesRegex(ValueError, "safely steer"):
            self.invoke()
        self.info["Capabilities"] = {"steerActiveTurn": True}
        self.assertEqual(self.invoke()[0], 0)
        self.info.update(Provider="claude", Capabilities={"steerActiveTurn": False})
        with self.assertRaises(ValueError):
            self.invoke()

    def test_ambiguous_prefix_never_sends(self):
        self.rows.append({"id": "other", "shortId": "5e55a2"})
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.invoke(target="5e55")

    def test_transport_failure_and_invalid_json_fail_closed(self):
        for result in (subprocess.CompletedProcess([], 1, '{"status":"sent"}', ""),
                       subprocess.CompletedProcess([], 0, "invalid json", "")):
            with self.subTest(result=result), patch.object(SENDER.subprocess, "run", return_value=result):
                with self.assertRaises(ValueError):
                    SENDER.send(AID, "notice")
