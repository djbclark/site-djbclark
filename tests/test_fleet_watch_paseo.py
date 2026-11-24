"""Receipt, transport, target-binding, credential-home, and safety contracts for fleet-watch's native Paseo sender."""
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
    "PASEO_HOST": "",
    "PASEO_HOME": "",
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

    return types.SimpleNamespace(
        DaemonError=FakeDaemonError,
        AgentNotFoundError=FakeAgentNotFoundError,
        PaseoClient=client_cls,
        transport_mode=transport_mode,
    )


def _tcp_target(host="127.0.0.1", port=7263, *, mcp_only=False):
    return types.SimpleNamespace(kind="tcp", host=host, port=port, socket_path="", mcp_only=mcp_only)


def _unix_target(socket_path, *, mcp_only=False):
    return types.SimpleNamespace(kind="unix", host="", port=0, socket_path=socket_path, mcp_only=mcp_only)


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
            with self.subTest(result=result), patch.dict(os.environ, env), \
                    patch.object(SENDER.subprocess, "run", return_value=result), \
                    self.assertRaises(ValueError):
                SENDER.send(AID, "notice")


class DaemonTransportSend(unittest.TestCase):
    def setUp(self):
        self.info = {"Id": AID, "Archived": False, "PendingPermissions": [], "Status": "idle"}
        self.rows = [{"id": AID, "shortId": "5e55a1"}]

    def _new_client(self, target=None):
        client = MagicMock()
        client.target = target if target is not None else _tcp_target()
        client.inspect_agent.return_value = self.info
        client.list_agents.return_value = self.rows
        return client

    def test_uuid_target_uses_direct_inspect_and_binds_send_host_with_zero_cli_reads(self):
        client = self._new_client(target=_tcp_target("127.0.0.1", 7263))
        client_cls = MagicMock(return_value=client)
        fake_pc = _make_fake_paseo_client_module(client_cls)
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "sent"}), "")

        with tempfile.TemporaryDirectory() as fake_home:
            env = dict(CLEAN_TRANSPORT_ENV, HOME=fake_home)
            with patch.dict(os.environ, env), \
                    patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                    patch.object(SENDER.subprocess, "run", side_effect=run):
                rc = SENDER.send(AID, "daemon notice")

        self.assertEqual(rc, 0)
        client_cls.assert_called_once_with(timeout=20)
        client.list_agents.assert_not_called()
        client.inspect_agent.assert_called_once_with(AID, cli_shape=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:5], ["paseo", "send", AID, "--host", "127.0.0.1:7263"])

    def test_short_id_prefix_uses_daemon_list_and_inspect_with_zero_cli_reads(self):
        client = self._new_client(target=_tcp_target("127.0.0.1", 7263))
        client_cls = MagicMock(return_value=client)
        fake_pc = _make_fake_paseo_client_module(client_cls)
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "completed"}), "")

        with tempfile.TemporaryDirectory() as fake_home:
            env = dict(CLEAN_TRANSPORT_ENV, HOME=fake_home)
            with patch.dict(os.environ, env), \
                    patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                    patch.object(SENDER.subprocess, "run", side_effect=run):
                rc = SENDER.send("5e55a1", "daemon prefix notice")

        self.assertEqual(rc, 0)
        client.list_agents.assert_called_once_with(include_background=True, include_archived=True, cli_rows=True)
        client.inspect_agent.assert_called_once_with(AID, cli_shape=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:5], ["paseo", "send", AID, "--host", "127.0.0.1:7263"])

    def test_live_pid_lock_overrides_stale_config_and_binds_both_inspect_and_send(self):
        client = self._new_client(target=_tcp_target("127.0.0.1", 9123))
        client_cls = MagicMock(return_value=client)
        fake_pc = _make_fake_paseo_client_module(client_cls)
        calls = []

        with tempfile.TemporaryDirectory() as paseo_home:
            Path(paseo_home, "config.json").write_text(json.dumps({"daemon": {"listen": "127.0.0.1:7263"}}), encoding="utf-8")
            Path(paseo_home, "paseo.pid").write_text(
                json.dumps({"pid": os.getpid(), "listen": "127.0.0.1:9123", "startedAt": "2026-11-24T00:00:00Z"}),
                encoding="utf-8",
            )
            token = "A" * 43
            Path(paseo_home, "local-credential").write_text(f"{token}\n", encoding="utf-8")

            def run(argv, **kwargs):
                calls.append((argv, dict(os.environ)))
                # Simulate Paseo CLI's readLocalCredentialForTarget(PASEO_HOME, --host)
                host_arg = argv[argv.index("--host") + 1]
                cur_home = os.environ.get("PASEO_HOME")
                self.assertEqual(cur_home, paseo_home)
                lock = json.loads(Path(cur_home, "paseo.pid").read_text(encoding="utf-8"))
                self.assertEqual(lock["listen"], host_arg)
                self.assertEqual(Path(cur_home, "local-credential").read_text(encoding="utf-8").strip(), token)
                return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "sent"}), "")

            env = dict(CLEAN_TRANSPORT_ENV, PASEO_HOME=paseo_home)
            with patch.dict(os.environ, env), \
                    patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                    patch.object(SENDER.subprocess, "run", side_effect=run):
                rc = SENDER.send(AID, "live-pid notice")

        self.assertEqual(rc, 0)
        client_cls.assert_called_once_with(timeout=20, url="http://127.0.0.1:9123")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][:5], ["paseo", "send", AID, "--host", "127.0.0.1:9123"])
        self.assertEqual(calls[0][1].get("PASEO_HOME"), paseo_home)

    def test_stale_not_ready_prior_boot_or_invalid_pid_lock_fails_closed_without_leaking_listen(self):
        cases = [
            ("stale_pid", json.dumps({"pid": 99_999_999, "listen": "127.0.0.1:9123"}), "stale"),
            ("prior_boot_started_at", json.dumps({"pid": os.getpid(), "startedAt": "2020-01-01T00:00:00Z", "listen": "127.0.0.1:9123"}), "predates current host boot"),
            ("not_ready_null_listen", json.dumps({"pid": os.getpid(), "listen": None}), "not published"),
            ("malformed_json", "{not-json", "malformed"),
            ("non_loopback_listen", json.dumps({"pid": os.getpid(), "listen": "10.0.0.5:7263"}), "not a valid local loopback or unix target"),
            ("secret_bearing_listen", json.dumps({"pid": os.getpid(), "listen": "http://user:SUPERSECRET@127.0.0.1:7263/?token=LEAKME"}), "not a valid local loopback or unix target"),
        ]
        for label, body, pattern in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as paseo_home:
                Path(paseo_home, "paseo.pid").write_text(body, encoding="utf-8")
                client_cls = MagicMock()
                fake_pc = _make_fake_paseo_client_module(client_cls)
                env = dict(CLEAN_TRANSPORT_ENV, PASEO_HOME=paseo_home)
                with patch.dict(os.environ, env), \
                        patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                        patch.object(SENDER.subprocess, "run") as run_mock:
                    with self.assertRaisesRegex(ValueError, pattern) as ctx:
                        SENDER.send(AID, "notice")
                    msg = str(ctx.exception)
                    self.assertNotIn("SUPERSECRET", msg)
                    self.assertNotIn("LEAKME", msg)
                    self.assertNotIn("10.0.0.5", msg)
                    client_cls.assert_not_called()
                    run_mock.assert_not_called()

    def test_symlinked_parent_unix_socket_preserves_lock_spelling_for_cli_credential_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_dir = Path(tmp) / "real-sock-dir"
            real_dir.mkdir()
            alias_dir = Path(tmp) / "alias-sock-dir"
            alias_dir.symlink_to(real_dir)
            alias_sock = f"{alias_dir}/p.sock"
            expected_spelling = f"unix://{alias_sock}"
            self.assertNotEqual(os.path.realpath(alias_sock), alias_sock)

            paseo_home = Path(tmp) / "paseo-home"
            paseo_home.mkdir()
            token = "C" * 43
            (paseo_home / "paseo.pid").write_text(
                json.dumps({"pid": os.getpid(), "listen": expected_spelling}),
                encoding="utf-8",
            )
            (paseo_home / "local-credential").write_text(f"{token}\n", encoding="utf-8")

            # Verify both PID-lock resolution and ADE_PASEO_URL keep the exact symlinked spelling.
            for mode_label, extra_env in (
                ("pid_lock_path", {"PASEO_HOME": str(paseo_home)}),
                ("ade_paseo_url_path", {"PASEO_HOME": str(paseo_home), "ADE_PASEO_URL": expected_spelling}),
            ):
                with self.subTest(mode=mode_label):
                    client = self._new_client(target=_unix_target(alias_sock))
                    client_cls = MagicMock(return_value=client)
                    fake_pc = _make_fake_paseo_client_module(client_cls)
                    seen_hosts = []

                    def run(argv, recorded=seen_hosts, home_dir=str(paseo_home), expected_tok=token, **kwargs):
                        host_arg = argv[argv.index("--host") + 1]
                        recorded.append(host_arg)
                        # Exact Paseo readLocalCredentialForTarget string equality (no realpath)
                        lock = json.loads(Path(home_dir, "paseo.pid").read_text(encoding="utf-8"))
                        self.assertEqual(host_arg, lock["listen"])
                        self.assertEqual(os.environ.get("PASEO_HOME"), home_dir)
                        self.assertEqual(Path(home_dir, "local-credential").read_text(encoding="utf-8").strip(), expected_tok)
                        return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "sent"}), "")

                    env = dict(CLEAN_TRANSPORT_ENV, **extra_env)
                    with patch.dict(os.environ, env), \
                            patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                            patch.object(SENDER.subprocess, "run", side_effect=run):
                        rc = SENDER.send(AID, "unix alias notice")
                    self.assertEqual(rc, 0)
                    self.assertEqual(seen_hosts, [expected_spelling])

    def test_bound_host_param_matches_or_fails_closed_when_live_endpoint_changed(self):
        with tempfile.TemporaryDirectory() as paseo_home:
            Path(paseo_home, "paseo.pid").write_text(
                json.dumps({"pid": os.getpid(), "listen": "127.0.0.1:9123"}),
                encoding="utf-8",
            )
            client = self._new_client(target=_tcp_target("127.0.0.1", 9123))
            client_cls = MagicMock(return_value=client)
            fake_pc = _make_fake_paseo_client_module(client_cls)

            def run(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "sent"}), "")

            env = dict(CLEAN_TRANSPORT_ENV, PASEO_HOME=paseo_home)
            with patch.dict(os.environ, env), \
                    patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                    patch.object(SENDER.subprocess, "run", side_effect=run):
                self.assertEqual(SENDER.send(AID, "notice", host="127.0.0.1:9123"), 0)

            # Simulate daemon restarting onto a different port between scan and relay -> fail closed.
            Path(paseo_home, "paseo.pid").write_text(
                json.dumps({"pid": os.getpid(), "listen": "127.0.0.1:9999"}),
                encoding="utf-8",
            )
            client_cls.reset_mock()
            with patch.dict(os.environ, env), \
                    patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                    patch.object(SENDER.subprocess, "run") as run_mock:
                with self.assertRaisesRegex(ValueError, "disagrees with live Paseo daemon endpoint"):
                    SENDER.send(AID, "notice", host="127.0.0.1:9123")
                client_cls.assert_not_called()
                run_mock.assert_not_called()

    def test_ade_paseo_url_binds_send_via_host_flag_and_retains_paseo_home_for_local_credential(self):
        cases = [
            ("tcp_with_custom_credential_home", _tcp_target("127.0.0.1", 9999), "http://127.0.0.1:9999", "127.0.0.1:9999"),
            ("ipv6", _tcp_target("::1", 9999), "http://[::1]:9999", "[::1]:9999"),
            ("unix", _unix_target("/tmp/alt-paseo.sock"), "unix:///tmp/alt-paseo.sock", "unix:///tmp/alt-paseo.sock"),
        ]
        for label, target_obj, ade_url, expected_host in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as custom_home:
                token = "B" * 43
                Path(custom_home, "paseo.pid").write_text(
                    json.dumps({"pid": os.getpid(), "listen": expected_host}),
                    encoding="utf-8",
                )
                Path(custom_home, "local-credential").write_text(f"{token}\n", encoding="utf-8")

                client = self._new_client(target=target_obj)
                client_cls = MagicMock(return_value=client)
                fake_pc = _make_fake_paseo_client_module(client_cls)
                seen = []

                def run(argv, recorded=seen, home_dir=custom_home, expected_tok=token, **kwargs):
                    self.assertNotIn("env", kwargs)
                    self.assertEqual(os.environ.get("PASEO_HOME"), home_dir)
                    host_arg = argv[argv.index("--host") + 1]
                    lock = json.loads(Path(home_dir, "paseo.pid").read_text(encoding="utf-8"))
                    self.assertEqual(lock["listen"], host_arg)
                    self.assertEqual(Path(home_dir, "local-credential").read_text(encoding="utf-8").strip(), expected_tok)
                    recorded.append(argv)
                    return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "sent"}), "")

                env = dict(CLEAN_TRANSPORT_ENV, ADE_PASEO_URL=ade_url, PASEO_HOME=custom_home)
                with patch.dict(os.environ, env), \
                        patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                        patch.object(SENDER.subprocess, "run", side_effect=run):
                    rc = SENDER.send(AID, "notice")

                self.assertEqual(rc, 0)
                self.assertEqual(len(seen), 1)
                self.assertEqual(seen[0][:5], ["paseo", "send", AID, "--host", expected_host])

    def test_matching_paseo_host_and_ade_paseo_url_succeeds_with_host_flag(self):
        client = self._new_client(target=_tcp_target("127.0.0.1", 9999))
        client_cls = MagicMock(return_value=client)
        fake_pc = _make_fake_paseo_client_module(client_cls)
        seen = []

        def run(argv, **kwargs):
            seen.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "sent"}), "")

        env = dict(CLEAN_TRANSPORT_ENV, ADE_PASEO_URL="http://127.0.0.1:9999", PASEO_HOST="127.0.0.1:9999")
        with patch.dict(os.environ, env), \
                patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                patch.object(SENDER.subprocess, "run", side_effect=run):
            rc = SENDER.send(AID, "notice")

        self.assertEqual(rc, 0)
        self.assertEqual(seen[0][:5], ["paseo", "send", AID, "--host", "127.0.0.1:9999"])

    def test_mcp_only_url_refuses_short_id_prefix_resolution(self):
        client = self._new_client(target=_tcp_target(mcp_only=True))
        client_cls = MagicMock(return_value=client)
        fake_pc = _make_fake_paseo_client_module(client_cls)
        env = dict(CLEAN_TRANSPORT_ENV, ADE_PASEO_URL="http://127.0.0.1:7263/mcp/agents")

        with patch.dict(os.environ, env), \
                patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                patch.object(SENDER.subprocess, "run") as run_mock:
            with self.assertRaisesRegex(ValueError, "MCP-only"):
                SENDER.send("5e55a1", "notice")
            client.list_agents.assert_not_called()
            run_mock.assert_not_called()

    def test_daemon_errors_fail_closed_without_cli_fallback(self):
        client = self._new_client()
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
        with tempfile.TemporaryDirectory() as fake_home:
            for label, target, configure in scenarios:
                with self.subTest(label=label):
                    client.reset_mock(side_effect=True, return_value=True)
                    client.target = _tcp_target()
                    client_cls.reset_mock(side_effect=True, return_value=True)
                    client_cls.return_value = client
                    configure()
                    env = dict(CLEAN_TRANSPORT_ENV, HOME=fake_home)
                    with patch.dict(os.environ, env), \
                            patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                            patch.object(SENDER.subprocess, "run") as run_mock:
                        with self.assertRaises(ValueError):
                            SENDER.send(target, "notice")
                        run_mock.assert_not_called()

    def test_paseo_host_without_forced_daemon_routes_wholly_through_cli(self):
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

        env = dict(CLEAN_TRANSPORT_ENV, PASEO_HOST="ssh://user@remote-host")
        with patch.dict(os.environ, env), \
                patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                patch.object(SENDER.subprocess, "run", side_effect=run):
            rc = SENDER.send(AID, "notice")

        self.assertEqual(rc, 0)
        client_cls.assert_not_called()
        self.assertEqual([c[1] for c in calls], ["ls", "agent", "send"])

    def test_paseo_home_and_paseo_host_conflict_fails_closed(self):
        client_cls = MagicMock()
        fake_pc = _make_fake_paseo_client_module(client_cls)
        env = dict(CLEAN_TRANSPORT_ENV, PASEO_HOME="/tmp/p1", PASEO_HOST="127.0.0.1:7263")

        with patch.dict(os.environ, env), \
                patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                patch.object(SENDER.subprocess, "run") as run_mock:
            with self.assertRaisesRegex(ValueError, "cannot both be set"):
                SENDER.send(AID, "notice")
            client_cls.assert_not_called()
            run_mock.assert_not_called()

    def test_split_paseo_host_and_forced_daemon_fails_closed(self):
        scenarios = [
            ("url_mismatch_port", _tcp_target("127.0.0.1", 9999), {"ADE_PASEO_URL": "http://127.0.0.1:9999", "PASEO_HOST": "127.0.0.1:8888"}),
            ("url_mismatch_host", _tcp_target("127.0.0.1", 9999), {"ADE_PASEO_URL": "http://127.0.0.1:9999", "PASEO_HOST": "localhost:9999"}),
            ("remote_host_forced_daemon", _tcp_target("127.0.0.1", 7263), {"ADE_PASEO_TRANSPORT": "daemon", "PASEO_HOST": "ssh://user@remote"}),
            ("unix_mismatch", _unix_target("/tmp/a.sock"), {"ADE_PASEO_URL": "unix:///tmp/a.sock", "PASEO_HOST": "unix:///tmp/b.sock"}),
        ]
        with tempfile.TemporaryDirectory() as fake_home:
            for label, target_obj, extra_env in scenarios:
                with self.subTest(label=label):
                    client = self._new_client(target=target_obj)
                    client_cls = MagicMock(return_value=client)
                    fake_pc = _make_fake_paseo_client_module(client_cls)
                    env = dict(CLEAN_TRANSPORT_ENV, HOME=fake_home, **extra_env)
                    with patch.dict(os.environ, env), \
                            patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                            patch.object(SENDER.subprocess, "run") as run_mock:
                        with self.assertRaisesRegex(ValueError, "disagrees with daemon target"):
                            SENDER.send(AID, "notice")
                        run_mock.assert_not_called()

    def test_cli_overrides_and_combined_precedence(self):
        cases = [
            ("fleet_watch_paseo", {"FLEET_WATCH_PASEO": "/custom/paseo"}, "/custom/paseo"),
            ("paseo_cli", {"PASEO_CLI": "/other/paseo"}, "/other/paseo"),
            ("transport_cli", {"ADE_PASEO_TRANSPORT": "cli"}, "paseo"),
            ("whitespace_fw_does_not_shadow_paseo_cli", {"FLEET_WATCH_PASEO": "   ", "PASEO_CLI": "/other/paseo"}, "/other/paseo"),
            ("literal_paseo_fw_does_not_shadow_paseo_cli", {"FLEET_WATCH_PASEO": "paseo", "PASEO_CLI": "/other/paseo"}, "/other/paseo"),
            ("custom_fw_beats_custom_paseo_cli", {"FLEET_WATCH_PASEO": "/fw/paseo", "PASEO_CLI": "/other/paseo"}, "/fw/paseo"),
        ]
        for label, extra_env, expected_bin in cases:
            with self.subTest(label=label):
                client_cls = MagicMock()
                fake_pc = _make_fake_paseo_client_module(client_cls)
                calls = []

                def run(argv, recorded=calls, **kwargs):
                    recorded.append(argv)
                    if argv[1] == "ls":
                        return subprocess.CompletedProcess(argv, 0, json.dumps(self.rows), "")
                    if argv[1] == "agent":
                        return subprocess.CompletedProcess(argv, 0, json.dumps(self.info), "")
                    return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "sent"}), "")

                env = dict(CLEAN_TRANSPORT_ENV, **extra_env)
                with patch.dict(os.environ, env), \
                        patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                        patch.object(SENDER.subprocess, "run", side_effect=run):
                    rc = SENDER.send(AID, "notice")

                self.assertEqual(rc, 0)
                client_cls.assert_not_called()
                self.assertEqual([c[0] for c in calls], [expected_bin, expected_bin, expected_bin])
                self.assertEqual([c[1] for c in calls], ["ls", "agent", "send"])

    def test_forced_daemon_overrides_custom_cli_for_reads_and_pins_send_host(self):
        with tempfile.TemporaryDirectory() as fake_home:
            for label, extra_env, expected_host in (
                ("ade_url_beats_custom_cli", {"ADE_PASEO_URL": "http://127.0.0.1:9999", "FLEET_WATCH_PASEO": "/custom/paseo"}, "127.0.0.1:9999"),
                ("ade_transport_daemon_beats_custom_cli", {"ADE_PASEO_TRANSPORT": "daemon", "FLEET_WATCH_PASEO": "/custom/paseo"}, "127.0.0.1:9999"),
            ):
                with self.subTest(label=label):
                    client = self._new_client(target=_tcp_target("127.0.0.1", 9999))
                    client_cls = MagicMock(return_value=client)
                    fake_pc = _make_fake_paseo_client_module(client_cls)
                    calls = []

                    def run(argv, recorded=calls, **kwargs):
                        recorded.append(argv)
                        return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "sent"}), "")

                    env = dict(CLEAN_TRANSPORT_ENV, HOME=fake_home, **extra_env)
                    with patch.dict(os.environ, env), \
                            patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                            patch.object(SENDER.subprocess, "run", side_effect=run):
                        rc = SENDER.send(AID, "notice")

                    self.assertEqual(rc, 0)
                    client.inspect_agent.assert_called_once_with(AID, cli_shape=True)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(calls[0][:5], ["/custom/paseo", "send", AID, "--host", expected_host])

    def test_present_broken_ade_paseo_client_fails_closed_unless_cli_explicit(self):
        saved = sys.modules.pop("ade_paseo_client", None)
        try:
            for broken_src in ("def broken(:\n", "raise RuntimeError('init boom')\n"):
                with tempfile.TemporaryDirectory() as fake_home:
                    ade_bin = Path(fake_home) / "src/djbclark-ade/bin"
                    ade_bin.mkdir(parents=True)
                    (ade_bin / "ade_paseo_client.py").write_text(broken_src, encoding="utf-8")

                    for label, extra_env in (
                        ("default_daemon", {}),
                        ("forced_daemon", {"ADE_PASEO_TRANSPORT": "daemon"}),
                        ("forced_url", {"ADE_PASEO_URL": "http://127.0.0.1:7263"}),
                    ):
                        with self.subTest(src=broken_src.strip(), mode=label):
                            sys.modules.pop("ade_paseo_client", None)
                            env = dict(CLEAN_TRANSPORT_ENV, HOME=fake_home, **extra_env)
                            with patch.dict(os.environ, env), \
                                    patch.object(SENDER.subprocess, "run") as run_mock:
                                with self.assertRaisesRegex(ValueError, "failed to load ade_paseo_client"):
                                    SENDER.send(AID, "notice")
                                run_mock.assert_not_called()

                    for label, extra_env in (
                        ("explicit_cli", {"ADE_PASEO_TRANSPORT": "cli"}),
                        ("custom_cli_bin", {"FLEET_WATCH_PASEO": "/custom/paseo"}),
                    ):
                        with self.subTest(src=broken_src.strip(), escape=label):
                            sys.modules.pop("ade_paseo_client", None)
                            calls = []

                            def run(argv, recorded=calls, **kwargs):
                                recorded.append(argv)
                                if argv[1] == "ls":
                                    return subprocess.CompletedProcess(argv, 0, json.dumps(self.rows), "")
                                if argv[1] == "agent":
                                    return subprocess.CompletedProcess(argv, 0, json.dumps(self.info), "")
                                return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "sent"}), "")

                            env = dict(CLEAN_TRANSPORT_ENV, HOME=fake_home, **extra_env)
                            with patch.dict(os.environ, env), \
                                    patch.object(SENDER.subprocess, "run", side_effect=run):
                                rc = SENDER.send(AID, "notice")
                            self.assertEqual(rc, 0)
                            self.assertEqual([c[1] for c in calls], ["ls", "agent", "send"])
        finally:
            sys.modules.pop("ade_paseo_client", None)
            if saved is not None:
                sys.modules["ade_paseo_client"] = saved

    def test_absent_ade_paseo_client_under_forced_daemon_fails_closed(self):
        saved = sys.modules.pop("ade_paseo_client", None)
        try:
            with tempfile.TemporaryDirectory() as empty_home:
                for extra_env in ({"ADE_PASEO_TRANSPORT": "daemon"}, {"ADE_PASEO_URL": "http://127.0.0.1:7263"}):
                    with self.subTest(extra_env=extra_env):
                        env = dict(CLEAN_TRANSPORT_ENV, HOME=empty_home, **extra_env)
                        with patch.dict(os.environ, env), patch.object(SENDER.subprocess, "run") as run_mock:
                            with self.assertRaisesRegex(ValueError, "ade_paseo_client unavailable"):
                                SENDER.send(AID, "notice")
                            run_mock.assert_not_called()
        finally:
            if saved is not None:
                sys.modules["ade_paseo_client"] = saved

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

    def test_want_daemon_transport_matches_real_ade_paseo_client_precedence(self):
        real_path = Path.home() / "src/djbclark-ade/bin/ade_paseo_client.py"
        if not real_path.is_file():
            self.skipTest("~/src/djbclark-ade/bin/ade_paseo_client.py not present")
        spec = importlib.util.spec_from_file_location("_real_ade_paseo_client_check", real_path)
        real_pc = importlib.util.module_from_spec(spec)
        sys.modules["_real_ade_paseo_client_check"] = real_pc
        spec.loader.exec_module(real_pc)
        try:
            matrix = [
                {},
                {"FLEET_WATCH_PASEO": "paseo"},
                {"FLEET_WATCH_PASEO": "   ", "PASEO_CLI": "/custom/paseo"},
                {"FLEET_WATCH_PASEO": "paseo", "PASEO_CLI": "/custom/paseo"},
                {"ADE_PASEO_TRANSPORT": "cli"},
                {"ADE_PASEO_TRANSPORT": "daemon", "FLEET_WATCH_PASEO": "/custom/paseo"},
                {"ADE_PASEO_URL": "http://127.0.0.1:7263", "ADE_PASEO_TRANSPORT": "cli"},
                {"ADE_PASEO_URL": "http://127.0.0.1:7263", "FLEET_WATCH_PASEO": "/custom/paseo"},
            ]
            for extra in matrix:
                with self.subTest(extra=extra):
                    env = dict(CLEAN_TRANSPORT_ENV, **extra)
                    want_daemon, _ = SENDER._want_daemon_transport(env)
                    real_mode = real_pc.transport_mode(env=env, cli_env_vars=("FLEET_WATCH_PASEO", "PASEO_CLI"))
                    self.assertEqual(want_daemon, real_mode == "daemon")
        finally:
            sys.modules.pop("_real_ade_paseo_client_check", None)


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
        namespace = {
            "subprocess": subprocess,
            "sys": sys,
            "relay": "helper.py",
            "clean": lambda s, n: s,
            "DEADLINE": time.monotonic() + 300,
            "time": time,
            "log": lambda s: None,
            "persist": lambda state: True,
        }
        exec(compile(ast.Module(body=definitions, type_ignores=[]), "phantom", "exec"), namespace)
        for outcome in (subprocess.CompletedProcess([], 5, "", "queued"),
                        subprocess.TimeoutExpired(["python", "helper"], 90)):
            with self.subTest(outcome=outcome), patch.object(subprocess, "run", side_effect=[outcome]):
                note = {"relay": False}
                namespace["attempt"]({}, note, "relay", lambda limit: namespace["send_relay"](AID, "notice", limit), "test")
                self.assertEqual(note["relay"], "sending")
                self.assertNotIn("relay_fails", note)
