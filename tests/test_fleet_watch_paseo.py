"""Receipt and target safety contracts for fleet-watch's native Paseo sender."""
import importlib.util
import json
import os
import subprocess
import unittest
import tempfile
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
                self.assertEqual(Path(argv[argv.index("--prompt-file") + 1]).read_text(), "[fleet-watch] a notice\n\nPlease reply: ack source-id")
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


class PendingSend(unittest.TestCase):
    def test_timeout_and_accepted_are_never_replayed(self):
        for outcome in (subprocess.TimeoutExpired(["paseo", "send"], 60),
                        {"status": "queued"}, {"status": "accepted"}):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                receipt = str(Path(directory) / "receipt.json")
                info = {"Id": AID, "Archived": False, "PendingPermissions": [], "Status": "idle"}
                replies = [[{"id": AID, "shortId": "5e55a1"}], info, outcome]
                with patch.object(SENDER, "call", side_effect=replies) as call:
                    with self.assertRaises(SENDER.PendingDelivery):
                        SENDER.send(AID, "notice", receipt_file=receipt)
                    self.assertEqual(call.call_count, 3)
                self.assertIn(json.loads(Path(receipt).read_text())["status"], ("sending", "accepted"))
                with patch.object(SENDER, "call") as call:
                    with self.assertRaises(SENDER.PendingDelivery):
                        SENDER.send(AID, "notice", receipt_file=receipt)
                    call.assert_not_called()

    def test_phantom_pending_retains_write_ahead_state(self):
        # Execute the actual embedded monitor's send/attempt functions, without
        # opening its databases or contacting a running daemon.
        import ast
        script = (Path(__file__).resolve().parents[1] / "bin/fleet-watch").read_text()
        embedded = script.split("<<'PY' || true", 1)[1].split("\nPY\n", 1)[0]
        tree = ast.parse(embedded)
        definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ("send_relay", "attempt")]
        import time
        namespace = dict(subprocess=subprocess, sys=__import__("sys"), relay="helper.py", clean=lambda s, n: s,
                         DEADLINE=time.monotonic() + 300, time=time, log=lambda s: None,
                         persist=lambda state: True)
        exec(compile(ast.Module(body=definitions, type_ignores=[]), "phantom", "exec"), namespace)
        for outcome in (subprocess.CompletedProcess([], 5, "", "queued"),
                        subprocess.TimeoutExpired(["python", "helper"], 90)):
            with self.subTest(outcome=outcome), patch.object(subprocess, "run", side_effect=[outcome]):
                note = {"relay": False}
                namespace["attempt"]({}, note, "relay", lambda limit: namespace["send_relay"](AID, "notice", limit), "test")
                self.assertEqual(note["relay"], "sending")
                self.assertNotIn("relay_fails", note)


class NativeDispatch(unittest.TestCase):
    def test_dispatch_invokes_paseo_run(self):
        with tempfile.TemporaryDirectory() as td:
            brief = Path(td) / "brief.md"
            brief.write_text("Review PR #123")
            workdir = Path(td) / "work"
            workdir.mkdir()

            calls = []

            def run_mock(argv, **kwargs):
                calls.append(argv)
                if argv[1:3] == ["workspace", "ls"]:
                    return subprocess.CompletedProcess(argv, 0, json.dumps([{"id": "ws-test", "cwd": str(workdir)}]), "")
                elif argv[1] == "run":
                    return subprocess.CompletedProcess(argv, 0, json.dumps({"agentId": "test-agent-id"}), "")
                return subprocess.CompletedProcess(argv, 0, "{}", "")

            with patch.dict(os.environ, {"PASEO_AGENT_ID": "lead-456"}), \
                 patch.object(SENDER, "check_headroom"), \
                 patch.object(SENDER.subprocess, "run", side_effect=run_mock):
                rc = SENDER.dispatch(
                    name="worker-1",
                    brief=str(brief),
                    cwd=str(workdir),
                    provider="claude/sonnet",
                    mode="bypassPermissions",
                    kind="judgment",
                    task="upstream-pr",
                    min_headroom=0,
                )
                self.assertEqual(rc, 0)

            self.assertEqual(len(calls), 2)
            run_cmd = calls[1]
            self.assertEqual(run_cmd[1], "run")
            self.assertIn("--provider", run_cmd)
            self.assertEqual(run_cmd[run_cmd.index("--provider") + 1], "claude/sonnet")
            self.assertIn("--mode", run_cmd)
            self.assertEqual(run_cmd[run_cmd.index("--mode") + 1], "bypassPermissions")
            self.assertIn("--title", run_cmd)
            self.assertEqual(run_cmd[run_cmd.index("--title") + 1], "worker-1")
            self.assertIn("--no-wait", run_cmd)
            self.assertIn("--json", run_cmd)
            self.assertIn("--workspace", run_cmd)
            self.assertEqual(run_cmd[run_cmd.index("--workspace") + 1], "ws-test")
            self.assertIn("ade.kind=judgment", run_cmd)
            self.assertIn("ade.name=worker-1", run_cmd)
            self.assertIn("ade.task=upstream-pr", run_cmd)
            self.assertIn("ade.lead=lead-456", run_cmd)
            self.assertIn("ade.via=fleet-watch", run_cmd)
            self.assertEqual(run_cmd[-1], "Review PR #123")

    def test_dispatch_missing_brief_raises(self):
        with self.assertRaises(ValueError):
            SENDER.dispatch(name="w", brief="/nonexistent/brief.md", min_headroom=0)

    def test_dispatch_failure_raises(self):
        with tempfile.TemporaryDirectory() as td:
            brief = Path(td) / "brief.md"
            brief.write_text("brief")
            fail_proc = subprocess.CompletedProcess(["paseo", "run"], 1, "", "unknown error")
            with patch.object(SENDER, "check_headroom"), \
                 patch.object(SENDER, "resolve_workspace", return_value="ws-1"), \
                 patch.object(SENDER.subprocess, "run", return_value=fail_proc):
                with self.assertRaises(ValueError):
                    SENDER.dispatch(name="w", brief=str(brief), min_headroom=0)

    def test_check_headroom_raises_when_insufficient(self):
        aiuse_data = {"available": [
            {"provider": "claude", "pool_family": "default", "usable_now": True, "headroom_percent": 5.0}
        ]}
        proc = subprocess.CompletedProcess(["aiuse"], 0, json.dumps(aiuse_data), "")
        with patch.object(SENDER.shutil, "which", return_value="/bin/aiuse"), \
             patch("pathlib.Path.exists", return_value=True), \
             patch.object(SENDER.subprocess, "run", return_value=proc):
            with self.assertRaises(SENDER.QuotaUnavailable):
                SENDER.check_headroom(min_headroom=10.0)


class AgentCounting(unittest.TestCase):
    def test_count_running_agents(self):
        rows = [
            {"id": "a1", "status": "running"},
            {"id": "a2", "status": "idle"},
            {"id": "a3", "status": "running"},
            {"id": "a4", "status": "archived"},
        ]
        with patch.object(SENDER, "call", return_value=rows):
            self.assertEqual(SENDER.count_running_agents(), 2)

    def test_count_running_agents_handles_dict_envelope(self):
        data = {"agents": [{"id": "a1", "status": "running"}]}
        with patch.object(SENDER, "call", return_value=data):
            self.assertEqual(SENDER.count_running_agents(), 1)

    def test_count_running_agents_failure_returns_zero(self):
        with patch.object(SENDER, "call", side_effect=OSError("CLI not found")):
            self.assertEqual(SENDER.count_running_agents(), 0)
