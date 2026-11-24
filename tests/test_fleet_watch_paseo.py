"""Receipt, transport, and target safety contracts for fleet-watch's native Paseo sender."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location("fleet_watch_paseo", Path(__file__).resolve().parents[1] / "bin/fleet_watch_paseo.py")
SENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SENDER)
AID = "5e55a100-0000-0000-0000-000000000000"
CLEAN_TRANSPORT_ENV = {
    "ADE_PASEO_URL": "",
    "ADE_PASEO_TRANSPORT": "",
    "FLEET_WATCH_PASEO": "",
    "PASEO_CLI": "",
}


def _make_fake_paseo_client_module(client_cls):
    class FakeDaemonError(Exception):
        pass

    class FakeAgentNotFoundError(FakeDaemonError, LookupError):
        pass

    def transport_mode(cli_override=None, env=None, *, cli_env_vars=()):
        e = os.environ if env is None else env
        if (e.get("ADE_PASEO_URL") or "").strip():
            return "daemon"
        explicit = (e.get("ADE_PASEO_TRANSPORT") or "").strip().lower()
        if explicit in ("daemon", "http", "ws"):
            return "daemon"
        if explicit == "cli":
            return "cli"
        if cli_override and str(cli_override).strip() and str(cli_override).strip() != "paseo":
            return "cli"
        for key in cli_env_vars:
            val = (e.get(key) or "").strip()
            if val and val != "paseo":
                return "cli"
        return "daemon"

    mod = types.SimpleNamespace(
        DaemonError=FakeDaemonError,
        AgentNotFoundError=FakeAgentNotFoundError,
        PaseoClient=client_cls,
        transport_mode=transport_mode,
    )
    return mod


class NativeSend(unittest.TestCase):
    def setUp(self):
        self.info = {"Id": AID, "Archived": False, "PendingPermissions": [], "Status": "idle"}
        self.rows = [{"id": AID, "shortId": "5e55a1"}]

    def invoke(self, status="sent", target="5e55a1", extra_env=None):
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

        env = dict(CLEAN_TRANSPORT_ENV, PASEO_AGENT_ID="source-id", ADE_PASEO_TRANSPORT="cli")
        if extra_env:
            env.update(extra_env)
        with patch.dict(os.environ, env), patch.object(SENDER.subprocess, "run", side_effect=run):
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
        env = dict(CLEAN_TRANSPORT_ENV, ADE_PASEO_TRANSPORT="cli")
        for result in (subprocess.CompletedProcess([], 1, '{"status":"sent"}', ""),
                       subprocess.CompletedProcess([], 0, "invalid json", "")):
            with self.subTest(result=result), patch.dict(os.environ, env), patch.object(SENDER.subprocess, "run", return_value=result):
                with self.assertRaises(ValueError):
                    SENDER.send(AID, "notice")


class DaemonTransportSend(unittest.TestCase):
    def setUp(self):
        self.info = {"Id": AID, "Archived": False, "PendingPermissions": [], "Status": "idle"}
        self.rows = [{"id": AID, "shortId": "5e55a1"}]

    def test_uuid_target_uses_direct_inspect_with_zero_cli_reads(self):
        client = MagicMock()
        client.inspect_agent.return_value = self.info
        client_cls = MagicMock(return_value=client)
        fake_pc = _make_fake_paseo_client_module(client_cls)
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "sent"}), "")

        with patch.dict(os.environ, CLEAN_TRANSPORT_ENV), \
                patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                patch.object(SENDER.subprocess, "run", side_effect=run):
            rc = SENDER.send(AID, "daemon notice")

        self.assertEqual(rc, 0)
        client_cls.assert_called_once_with(timeout=20)
        client.list_agents.assert_not_called()
        client.inspect_agent.assert_called_once_with(AID, cli_shape=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:3], ["paseo", "send", AID])

    def test_short_id_prefix_uses_daemon_list_and_inspect_with_zero_cli_reads(self):
        client = MagicMock()
        client.list_agents.return_value = self.rows
        client.inspect_agent.return_value = self.info
        client_cls = MagicMock(return_value=client)
        fake_pc = _make_fake_paseo_client_module(client_cls)
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "completed"}), "")

        with patch.dict(os.environ, CLEAN_TRANSPORT_ENV), \
                patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                patch.object(SENDER.subprocess, "run", side_effect=run):
            rc = SENDER.send("5e55a1", "daemon prefix notice")

        self.assertEqual(rc, 0)
        client.list_agents.assert_called_once_with(include_background=True, include_archived=True, cli_rows=True)
        client.inspect_agent.assert_called_once_with(AID, cli_shape=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:3], ["paseo", "send", AID])

    def test_daemon_errors_fail_closed_without_cli_fallback(self):
        client = MagicMock()
        client_cls = MagicMock(return_value=client)
        fake_pc = _make_fake_paseo_client_module(client_cls)

        scenarios = [
            ("init", AID, lambda: setattr(client_cls, "side_effect", fake_pc.DaemonError("unreachable"))),
            ("uuid_inspect", AID, lambda: setattr(client.inspect_agent, "side_effect", fake_pc.DaemonError("ws down"))),
            ("uuid_not_found", AID, lambda: setattr(client.inspect_agent, "side_effect", fake_pc.AgentNotFoundError("missing"))),
            ("prefix_list", "5e55a1", lambda: setattr(client.list_agents, "side_effect", fake_pc.DaemonError("list failed"))),
            ("prefix_inspect", "5e55a1", lambda: (
                setattr(client.list_agents, "return_value", self.rows),
                setattr(client.inspect_agent, "side_effect", fake_pc.DaemonError("inspect failed")),
            )),
        ]
        for label, target, configure in scenarios:
            with self.subTest(label=label):
                client.reset_mock(side_effect=True, return_value=True)
                client_cls.reset_mock(side_effect=True, return_value=True)
                client_cls.return_value = client
                configure()
                with patch.dict(os.environ, CLEAN_TRANSPORT_ENV), \
                        patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                        patch.object(SENDER.subprocess, "run") as run_mock:
                    with self.assertRaises(ValueError):
                        SENDER.send(target, "notice")
                    run_mock.assert_not_called()

    def test_cli_overrides_bypass_daemon_client(self):
        for env_key, env_val, expected_bin in (
            ("FLEET_WATCH_PASEO", "/custom/paseo", "/custom/paseo"),
            ("PASEO_CLI", "/other/paseo", "/other/paseo"),
            ("ADE_PASEO_TRANSPORT", "cli", "paseo"),
        ):
            with self.subTest(env_key=env_key):
                client_cls = MagicMock()
                fake_pc = _make_fake_paseo_client_module(client_cls)
                calls = []

                def run(argv, **kwargs):
                    calls.append(argv)
                    if argv[1] == "ls":
                        return subprocess.CompletedProcess(argv, 0, json.dumps(self.rows), "")
                    if argv[1] == "agent":
                        return subprocess.CompletedProcess(argv, 0, json.dumps(self.info), "")
                    return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "sent"}), "")

                env = dict(CLEAN_TRANSPORT_ENV, **{env_key: env_val})
                with patch.dict(os.environ, env), \
                        patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                        patch.object(SENDER.subprocess, "run", side_effect=run):
                    rc = SENDER.send(AID, "notice")

                self.assertEqual(rc, 0)
                client_cls.assert_not_called()
                self.assertEqual([c[0] for c in calls], [expected_bin, expected_bin, expected_bin])
                self.assertEqual([c[1] for c in calls], ["ls", "agent", "send"])

    def test_missing_ade_paseo_client_falls_back_to_cli(self):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            if argv[1] == "ls":
                return subprocess.CompletedProcess(argv, 0, json.dumps(self.rows), "")
            if argv[1] == "agent":
                return subprocess.CompletedProcess(argv, 0, json.dumps(self.info), "")
            return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "sent"}), "")

        with patch.dict(os.environ, CLEAN_TRANSPORT_ENV), \
                patch.dict(sys.modules, {"ade_paseo_client": None}), \
                patch.object(SENDER.subprocess, "run", side_effect=run):
            rc = SENDER.send(AID, "notice")

        self.assertEqual(rc, 0)
        self.assertEqual([c[1] for c in calls], ["ls", "agent", "send"])

    def test_missing_home_ade_paseo_client_file_falls_back_to_cli(self):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            if argv[1] == "ls":
                return subprocess.CompletedProcess(argv, 0, json.dumps(self.rows), "")
            if argv[1] == "agent":
                return subprocess.CompletedProcess(argv, 0, json.dumps(self.info), "")
            return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "sent"}), "")

        saved = sys.modules.pop("ade_paseo_client", None)
        try:
            with tempfile.TemporaryDirectory() as empty_home:
                env = dict(CLEAN_TRANSPORT_ENV, HOME=empty_home)
                with patch.dict(os.environ, env), \
                        patch.object(SENDER.subprocess, "run", side_effect=run):
                    rc = SENDER.send(AID, "notice")
        finally:
            if saved is not None:
                sys.modules["ade_paseo_client"] = saved

        self.assertEqual(rc, 0)
        self.assertEqual([c[1] for c in calls], ["ls", "agent", "send"])


class PendingSend(unittest.TestCase):
    def test_timeout_and_accepted_are_never_replayed(self):
        env = dict(CLEAN_TRANSPORT_ENV, ADE_PASEO_TRANSPORT="cli")
        for outcome in (subprocess.TimeoutExpired(["paseo", "send"], 60),
                        {"status": "queued"}, {"status": "accepted"}):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                receipt = str(Path(directory) / "receipt.json")
                info = {"Id": AID, "Archived": False, "PendingPermissions": [], "Status": "idle"}
                replies = [[{"id": AID, "shortId": "5e55a1"}], info, outcome]
                with patch.dict(os.environ, env), patch.object(SENDER, "call", side_effect=replies) as call:
                    with self.assertRaises(SENDER.PendingDelivery):
                        SENDER.send(AID, "notice", receipt_file=receipt)
                    self.assertEqual(call.call_count, 3)
                self.assertIn(json.loads(Path(receipt).read_text())["status"], ("sending", "accepted"))
                with patch.dict(os.environ, env), patch.object(SENDER, "call") as call:
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
