"""Transport, active-scope, deadline-budget, fail-closed, and CLI-fallback contracts for phantom_watch."""
import ast
import base64
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
FLEET_WATCH = REPO_ROOT / "bin/fleet-watch"
AID_RUN_1 = "11111111-2222-3333-4444-555555555555"
AID_RUN_2 = "66666666-7777-8888-9999-aaaaaaaaaaaa"
AID_IDLE = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
WS_MAGIC_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

CLEAN_TRANSPORT_ENV = {
    "ADE_PASEO_URL": "",
    "ADE_PASEO_TRANSPORT": "",
    "FLEET_WATCH_PASEO": "",
    "PASEO_CLI": "",
    "PASEO_HOME": "",
    "FLEET_WATCH_PHANTOM_PASEO_DIR": "",
}


def _load_phantom_namespace(
    state_dir,
    home_dir,
    *,
    mode="manual",
    now=1_800_000_000.0,
    paseo_bin="paseo",
    paseo_dir=None,
    cmd_timeout=30.0,
    deadline_offset=120.0,
):
    """Load all function definitions from phantom_watch's embedded Python block without executing top-level main()."""
    script = FLEET_WATCH.read_text(encoding="utf-8")
    embedded = script.split("<<'PY' || true", 1)[1].split("\nPY\n", 1)[0]
    tree = ast.parse(embedded)
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    resolved_paseo_dir = Path(paseo_dir) if paseo_dir is not None else Path(home_dir) / ".paseo"
    messages = []
    logs = []
    namespace = {
        "datetime": datetime,
        "fcntl": fcntl,
        "importlib": importlib,
        "json": json,
        "os": os,
        "re": re,
        "sqlite3": sqlite3,
        "subprocess": subprocess,
        "sys": sys,
        "tempfile": tempfile,
        "time": time,
        "Path": Path,
        "mode": mode,
        "root": Path(state_dir),
        "home": Path(home_dir),
        "dry": mode == "dry",
        "quiet": mode == "check",
        "state_file": Path(state_dir) / "phantom.json",
        "PASEO": paseo_bin,
        "HERMES_PING": "/nonexistent/hermes-ping",
        "hermes": "/nonexistent/hermes",
        "target": "telegram:test",
        "relay": str(REPO_ROOT / "bin/fleet_watch_paseo.py"),
        "LEAD": "7c58015b",
        "SILENT": 900.0,
        "GAP": 270.0,
        "DEADLINE": time.monotonic() + deadline_offset,
        "CMD_TIMEOUT": cmd_timeout,
        "NOW": now,
        "PASEO_DIR": resolved_paseo_dir,
        "OC_DB": str(Path(state_dir) / "opencode.db"),
        "OC_SERVICE": str(Path(state_dir) / "service.json"),
        "MAX_TRIES": 3,
        "REFUSAL": (b"reported running but no active run was cancelled", b"cancellation was not acknowledged"),
        "UUID": re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
        "STEERED": ("claude",),
        "SOURCE": re.compile(r'source-agent-id=\\?"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\\?"'),
        "OC": {},
        "REFUSED": {},
        "_said": messages,
        "_logged": logs,
    }
    exec(compile(ast.Module(body=definitions, type_ignores=[]), "phantom_watch", "exec"), namespace)
    namespace["say"] = messages.append
    namespace["log"] = logs.append
    return namespace


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


def _iso_utc(ts):
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class PhantomWatchTransport(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000.0
        self.recent_iso = _iso_utc(self.now - 60)
        self.listing = [
            {"id": AID_RUN_1, "shortId": AID_RUN_1[:7], "name": "worker-1", "provider": "claude/sonnet", "status": "running"},
            {"id": AID_IDLE, "shortId": AID_IDLE[:7], "name": "idle-1", "provider": "codex", "status": "idle"},
        ]
        self.inspect_1 = {
            "Id": AID_RUN_1,
            "Name": "worker-1",
            "Provider": "claude",
            "Status": "running",
            "Archived": False,
            "UpdatedAt": self.recent_iso,
            "PendingPermissions": [],
        }

    def test_daemon_transport_preserves_active_scope_with_zero_subprocess_spawns(self):
        client = MagicMock()
        client.target = types.SimpleNamespace(mcp_only=False)
        client.list_agents.return_value = self.listing
        client.inspect_agent.return_value = self.inspect_1
        client_cls = MagicMock(return_value=client)
        fake_pc = _make_fake_paseo_client_module(client_cls)

        with tempfile.TemporaryDirectory() as tmp:
            ns = _load_phantom_namespace(tmp, tmp, mode="manual", now=self.now)
            with patch.dict(os.environ, CLEAN_TRANSPORT_ENV), \
                    patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                    patch.object(subprocess, "run") as run_mock:
                ns["main"]()
                run_mock.assert_not_called()

        client_cls.assert_called_once()
        self.assertEqual(client_cls.call_args.kwargs["paseo_home"], Path(tmp) / ".paseo")
        client.list_agents.assert_called_once_with(
            include_background=False,
            include_archived=False,
            active_only=True,
            cli_rows=True,
        )
        client.inspect_agent.assert_called_once_with(AID_RUN_1, cli_shape=True)
        self.assertTrue(any("ok:" in line for line in ns["_said"]))
        self.assertIn("phantom: checked 1 running agent(s)", ns["_said"])

    def test_mcp_only_url_fails_closed_for_active_scope(self):
        client = MagicMock()
        client.target = types.SimpleNamespace(mcp_only=True)
        client_cls = MagicMock(return_value=client)
        fake_pc = _make_fake_paseo_client_module(client_cls)

        with tempfile.TemporaryDirectory() as tmp:
            ns = _load_phantom_namespace(tmp, tmp, mode="manual", now=self.now)
            env = dict(CLEAN_TRANSPORT_ENV, ADE_PASEO_URL="http://127.0.0.1:7263/mcp/agents")
            with patch.dict(os.environ, env), \
                    patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                    patch.object(subprocess, "run") as run_mock:
                with self.assertRaisesRegex(RuntimeError, "MCP-only"):
                    ns["main"]()
                client.list_agents.assert_not_called()
                run_mock.assert_not_called()

    def test_daemon_list_error_fails_closed_without_cli_fallback(self):
        client = MagicMock()
        client.target = types.SimpleNamespace(mcp_only=False)
        client_cls = MagicMock(return_value=client)
        fake_pc = _make_fake_paseo_client_module(client_cls)
        client.list_agents.side_effect = fake_pc.DaemonError("daemon down")

        with tempfile.TemporaryDirectory() as tmp:
            ns = _load_phantom_namespace(tmp, tmp, mode="manual", now=self.now)
            with patch.dict(os.environ, CLEAN_TRANSPORT_ENV), \
                    patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                    patch.object(subprocess, "run") as run_mock:
                with self.assertRaisesRegex(RuntimeError, "paseo daemon ls failed"):
                    ns["main"]()
                run_mock.assert_not_called()

    def test_daemon_init_error_fails_closed_without_cli_fallback(self):
        client_cls = MagicMock()
        fake_pc = _make_fake_paseo_client_module(client_cls)
        client_cls.side_effect = fake_pc.DaemonError("bad daemon URL")

        with tempfile.TemporaryDirectory() as tmp:
            ns = _load_phantom_namespace(tmp, tmp, mode="manual", now=self.now)
            with patch.dict(os.environ, CLEAN_TRANSPORT_ENV), \
                    patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                    patch.object(subprocess, "run") as run_mock:
                with self.assertRaisesRegex(RuntimeError, "paseo daemon unavailable"):
                    ns["main"]()
                run_mock.assert_not_called()

    def test_daemon_inspect_error_fails_closed_per_agent_and_continues(self):
        listing = [
            {"id": AID_RUN_1, "shortId": AID_RUN_1[:7], "name": "worker-1", "provider": "claude", "status": "running"},
            {"id": AID_RUN_2, "shortId": AID_RUN_2[:7], "name": "worker-2", "provider": "codex", "status": "running"},
        ]
        inspect_2 = {
            "Id": AID_RUN_2,
            "Name": "worker-2",
            "Provider": "codex",
            "Status": "running",
            "Archived": False,
            "UpdatedAt": self.recent_iso,
            "PendingPermissions": [],
        }
        client = MagicMock()
        client.target = types.SimpleNamespace(mcp_only=False)
        client_cls = MagicMock(return_value=client)
        fake_pc = _make_fake_paseo_client_module(client_cls)
        client.list_agents.return_value = listing
        client.inspect_agent.side_effect = [fake_pc.DaemonError("inspect timeout"), inspect_2]

        with tempfile.TemporaryDirectory() as tmp:
            ns = _load_phantom_namespace(tmp, tmp, mode="manual", now=self.now)
            with patch.dict(os.environ, CLEAN_TRANSPORT_ENV), \
                    patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                    patch.object(subprocess, "run") as run_mock:
                ns["main"]()
                run_mock.assert_not_called()

        self.assertTrue(any("no verdict:" in line and AID_RUN_1[:8] in line for line in ns["_logged"]))
        self.assertTrue(any("worker-2" in line and "ok:" in line for line in ns["_said"]))
        self.assertIn("phantom: checked 2 running agent(s)", ns["_said"])

    def test_cli_overrides_use_subprocess_and_skip_daemon_client(self):
        for env_key, env_val, paseo_bin in (
            ("FLEET_WATCH_PASEO", "/custom/paseo", "/custom/paseo"),
            ("ADE_PASEO_TRANSPORT", "cli", "paseo"),
        ):
            with self.subTest(env_key=env_key), tempfile.TemporaryDirectory() as tmp:
                client_cls = MagicMock()
                fake_pc = _make_fake_paseo_client_module(client_cls)
                calls = []

                def fake_run(argv, recorded=calls, **kwargs):
                    recorded.append(argv)
                    if argv[1] == "ls":
                        return subprocess.CompletedProcess(argv, 0, json.dumps(self.listing), "")
                    if argv[1] == "inspect":
                        return subprocess.CompletedProcess(argv, 0, json.dumps(self.inspect_1), "")
                    raise AssertionError(f"unexpected argv: {argv}")

                ns = _load_phantom_namespace(tmp, tmp, mode="manual", now=self.now, paseo_bin=paseo_bin)
                env = dict(CLEAN_TRANSPORT_ENV, **{env_key: env_val})
                with patch.dict(os.environ, env), \
                        patch.dict(sys.modules, {"ade_paseo_client": fake_pc}), \
                        patch.object(subprocess, "run", side_effect=fake_run):
                    ns["main"]()

                client_cls.assert_not_called()
                self.assertEqual(calls, [[paseo_bin, "ls", "--json"], [paseo_bin, "inspect", AID_RUN_1, "--json"]])

    def test_present_broken_ade_paseo_client_fails_closed_unless_cli_explicit(self):
        saved = sys.modules.pop("ade_paseo_client", None)
        try:
            for broken_src in ("def broken(:\n", "raise RuntimeError('module boom')\n"):
                with tempfile.TemporaryDirectory() as tmp:
                    ade_bin = Path(tmp) / "src/djbclark-ade/bin"
                    ade_bin.mkdir(parents=True)
                    (ade_bin / "ade_paseo_client.py").write_text(broken_src, encoding="utf-8")

                    for label, extra_env in (
                        ("default_daemon", {}),
                        ("forced_daemon", {"ADE_PASEO_TRANSPORT": "daemon"}),
                        ("forced_url", {"ADE_PASEO_URL": "unix:///tmp/nonexistent.sock"}),
                    ):
                        with self.subTest(src=broken_src.strip(), mode=label):
                            sys.modules.pop("ade_paseo_client", None)
                            ns = _load_phantom_namespace(tmp, tmp, mode="manual", now=self.now)
                            env = dict(CLEAN_TRANSPORT_ENV, **extra_env)
                            with patch.dict(os.environ, env), patch.object(subprocess, "run") as run_mock:
                                with self.assertRaisesRegex(RuntimeError, "failed to load ade_paseo_client"):
                                    ns["main"]()
                                run_mock.assert_not_called()

                    for label, extra_env, expected_bin in (
                        ("explicit_cli", {"ADE_PASEO_TRANSPORT": "cli"}, "paseo"),
                        ("custom_cli_bin", {"FLEET_WATCH_PASEO": "/custom/paseo"}, "/custom/paseo"),
                    ):
                        with self.subTest(src=broken_src.strip(), escape=label):
                            sys.modules.pop("ade_paseo_client", None)
                            calls = []

                            def fake_run(argv, recorded=calls, **kwargs):
                                recorded.append(argv)
                                if argv[1] == "ls":
                                    return subprocess.CompletedProcess(argv, 0, json.dumps(self.listing), "")
                                return subprocess.CompletedProcess(argv, 0, json.dumps(self.inspect_1), "")

                            ns = _load_phantom_namespace(tmp, tmp, mode="manual", now=self.now, paseo_bin=expected_bin)
                            env = dict(CLEAN_TRANSPORT_ENV, **extra_env)
                            with patch.dict(os.environ, env), patch.object(subprocess, "run", side_effect=fake_run):
                                ns["main"]()
                            self.assertEqual(calls, [[expected_bin, "ls", "--json"], [expected_bin, "inspect", AID_RUN_1, "--json"]])
        finally:
            sys.modules.pop("ade_paseo_client", None)
            if saved is not None:
                sys.modules["ade_paseo_client"] = saved

    def test_absent_ade_paseo_client_under_forced_daemon_fails_closed(self):
        saved = sys.modules.pop("ade_paseo_client", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                for extra_env in ({"ADE_PASEO_TRANSPORT": "daemon"}, {"ADE_PASEO_URL": "http://127.0.0.1:7263"}):
                    with self.subTest(extra_env=extra_env):
                        ns = _load_phantom_namespace(tmp, tmp, mode="manual", now=self.now)
                        env = dict(CLEAN_TRANSPORT_ENV, **extra_env)
                        with patch.dict(os.environ, env), patch.object(subprocess, "run") as run_mock:
                            with self.assertRaisesRegex(RuntimeError, "ade_paseo_client unavailable"):
                                ns["main"]()
                            run_mock.assert_not_called()
        finally:
            if saved is not None:
                sys.modules["ade_paseo_client"] = saved

    def test_missing_ade_paseo_client_falls_back_to_cli(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            if argv[1] == "ls":
                return subprocess.CompletedProcess(argv, 0, json.dumps(self.listing), "")
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.inspect_1), "")

        with tempfile.TemporaryDirectory() as tmp:
            ns = _load_phantom_namespace(tmp, tmp, mode="manual", now=self.now)
            with patch.dict(os.environ, CLEAN_TRANSPORT_ENV), \
                    patch.dict(sys.modules, {"ade_paseo_client": None}), \
                    patch.object(subprocess, "run", side_effect=fake_run):
                ns["main"]()

        self.assertEqual(calls, [["paseo", "ls", "--json"], ["paseo", "inspect", AID_RUN_1, "--json"]])

    def test_missing_home_ade_paseo_client_file_falls_back_to_cli(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            if argv[1] == "ls":
                return subprocess.CompletedProcess(argv, 0, json.dumps(self.listing), "")
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.inspect_1), "")

        saved = sys.modules.pop("ade_paseo_client", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                ns = _load_phantom_namespace(tmp, tmp, mode="manual", now=self.now)
                with patch.dict(os.environ, CLEAN_TRANSPORT_ENV), \
                        patch.object(subprocess, "run", side_effect=fake_run):
                    ns["main"]()
        finally:
            if saved is not None:
                sys.modules["ade_paseo_client"] = saved

        self.assertEqual(calls, [["paseo", "ls", "--json"], ["paseo", "inspect", AID_RUN_1, "--json"]])

    def test_paseo_dir_honors_paseo_home_and_expands_tilde(self):
        script = FLEET_WATCH.read_text(encoding="utf-8")
        embedded = script.split("<<'PY' || true", 1)[1].split("\nPY\n", 1)[0]
        header_lines = []
        for line in embedded.splitlines():
            if line.startswith("def "):
                break
            header_lines.append(line)
        header_src = "\n".join(header_lines)

        with tempfile.TemporaryDirectory() as fake_home:
            cases = [
                ("default", {}, Path(fake_home) / ".paseo"),
                ("paseo_home_tilde", {"PASEO_HOME": "~/custom-paseo"}, Path(fake_home) / "custom-paseo"),
                ("phantom_dir_tilde_beats_paseo_home", {"PASEO_HOME": "~/other", "FLEET_WATCH_PHANTOM_PASEO_DIR": "~/phantom-paseo"}, Path(fake_home) / "phantom-paseo"),
            ]
            for label, extra_env, expected in cases:
                with self.subTest(label=label):
                    env = dict(CLEAN_TRANSPORT_ENV, HOME=fake_home, **extra_env)
                    ns = {}
                    with patch.dict(os.environ, env), \
                            patch.object(sys, "argv", ["phantom", "dry", fake_home, "/bin/h", "t", "/bin/r"]):
                        exec(compile(header_src, "phantom_header", "exec"), ns)
                    self.assertEqual(ns["PASEO_DIR"], expected)


def _ws_recv_frame(conn):
    def recv_exact(n):
        buf = bytearray()
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise EOFError("socket closed")
            buf.extend(chunk)
        return bytes(buf)

    b1, b2 = recv_exact(2)
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", recv_exact(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(8))[0]
    mask = recv_exact(4) if masked else b""
    payload = recv_exact(length) if length else b""
    if masked:
        payload = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
    return opcode, payload


def _ws_send_json(conn, obj):
    payload = json.dumps(obj).encode("utf-8")
    header = bytearray([0x81])
    if len(payload) < 126:
        header.append(len(payload))
    elif len(payload) < 65_536:
        header.append(126)
        header.extend(struct.pack("!H", len(payload)))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", len(payload)))
    conn.sendall(bytes(header) + payload)


class _UnixMockPaseoDaemon:
    """Minimal AF_UNIX server handling /ws (multi-page fetch_agents + fetch_agent) and POST /mcp/agents."""

    def __init__(
        self,
        sock_path,
        pages,
        agents_by_id,
        *,
        mcp_status=200,
        page_delay_s=0.0,
        mcp_delay_s=0.0,
        ws_agent_delay_s=0.0,
    ):
        self.sock_path = sock_path
        self.pages = pages
        self.agents_by_id = agents_by_id
        self.mcp_status = mcp_status
        self.page_delay_s = page_delay_s
        self.mcp_delay_s = mcp_delay_s
        self.ws_agent_delay_s = ws_agent_delay_s
        self.ws_calls = 0
        self.mcp_calls = 0
        self.fetch_agent_ws_calls = 0
        self.fetch_agents_requests = []
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(sock_path)
        self._sock.listen(16)
        self._sock.settimeout(0.1)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._handle(conn)
            except (EOFError, OSError):
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _handle(self, conn):
        conn.settimeout(5.0)
        raw = bytearray()
        while b"\r\n\r\n" not in raw:
            chunk = conn.recv(4096)
            if not chunk:
                return
            raw.extend(chunk)
        sep = raw.index(b"\r\n\r\n")
        head = raw[:sep].decode("iso-8859-1")
        body = bytes(raw[sep + 4:])
        lines = head.split("\r\n")
        method, path, _ = lines[0].split(" ", 2)
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        if method == "GET" and path == "/ws":
            self.ws_calls += 1
            key = headers["sec-websocket-key"]
            accept = base64.b64encode(hashlib.sha1((key + WS_MAGIC_GUID).encode("ascii")).digest()).decode("ascii")
            conn.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode("ascii")
            )
            _ws_recv_frame(conn)  # hello
            _ws_send_json(conn, {"type": "session", "message": {"type": "status", "payload": {"status": "server_info"}}})
            while not self._stop.is_set():
                opcode, payload = _ws_recv_frame(conn)
                if opcode == 0x8:
                    return
                if opcode != 0x1:
                    continue
                req = json.loads(payload.decode("utf-8"))
                inner = req.get("message") or {}
                mtype = inner.get("type")
                if mtype == "fetch_agents_request":
                    self.fetch_agents_requests.append(inner)
                    cursor = (inner.get("page") or {}).get("cursor")
                    idx = int(cursor) if cursor is not None else 0
                    if self.page_delay_s > 0:
                        time.sleep(self.page_delay_s)
                    entries = [{"agent": snap} for snap in self.pages[idx]]
                    next_cursor = str(idx + 1) if idx + 1 < len(self.pages) else None
                    page_info = {"nextCursor": next_cursor} if next_cursor is not None else {}
                    _ws_send_json(
                        conn,
                        {
                            "type": "session",
                            "message": {
                                "type": "fetch_agents_response",
                                "payload": {
                                    "requestId": inner.get("requestId"),
                                    "entries": entries,
                                    "pageInfo": page_info,
                                },
                            },
                        },
                    )
                elif mtype == "fetch_agent_request":
                    self.fetch_agent_ws_calls += 1
                    if self.ws_agent_delay_s > 0:
                        time.sleep(self.ws_agent_delay_s)
                    snap = self.agents_by_id.get(inner.get("agentId"))
                    _ws_send_json(
                        conn,
                        {
                            "type": "session",
                            "message": {
                                "type": "fetch_agent_response",
                                "payload": {
                                    "requestId": inner.get("requestId"),
                                    "agent": snap,
                                },
                            },
                        },
                    )
            return

        if method == "POST" and path == "/mcp/agents":
            self.mcp_calls += 1
            clen = int(headers.get("content-length", "0"))
            while len(body) < clen:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                body += chunk
            if self.mcp_delay_s > 0:
                time.sleep(self.mcp_delay_s)
            if self.mcp_status != 200:
                resp_bytes = b'{"error":"unauthorized"}'
                conn.sendall(
                    (
                        f"HTTP/1.1 {self.mcp_status} Unauthorized\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(resp_bytes)}\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode("ascii")
                    + resp_bytes
                )
                return
            rpc = json.loads(body.decode("utf-8"))
            agent_id = (rpc.get("params") or {}).get("arguments", {}).get("agentId")
            resp_obj = {
                "jsonrpc": "2.0",
                "id": rpc["id"],
                "result": {"structuredContent": {"snapshot": self.agents_by_id.get(agent_id)}},
            }
            resp_bytes = json.dumps(resp_obj).encode("utf-8")
            conn.sendall(
                (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(resp_bytes)}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("ascii")
                + resp_bytes
            )

    def close(self):
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)
        if os.path.exists(self.sock_path):
            os.unlink(self.sock_path)


def _snapshot(aid, title, provider, now):
    return {
        "id": aid,
        "title": title,
        "provider": provider,
        "model": "sonnet",
        "status": "running",
        "cwd": "/tmp",
        "createdAt": _iso_utc(now - 300),
        "updatedAt": _iso_utc(now - 60),
        "archivedAt": None,
        "background": False,
        "pendingPermissions": [],
        "labels": {},
    }


class PhantomWatchUnixEndToEnd(unittest.TestCase):
    def _require_real_client(self):
        real_client = Path.home() / "src/djbclark-ade/bin/ade_paseo_client.py"
        if not real_client.is_file():
            self.skipTest("~/src/djbclark-ade/bin/ade_paseo_client.py not present")
        return real_client

    def test_fleet_watch_phantom_multipage_active_scope_and_zero_cli_spawns(self):
        real_client = self._require_real_client()
        now = 1_800_000_000.0
        s1 = _snapshot(AID_RUN_1, "unix-page-1", "claude", now)
        s2 = _snapshot(AID_RUN_2, "unix-page-2", "codex", now)

        with tempfile.TemporaryDirectory(prefix="fw-", dir="/tmp") as short_tmp:
            sock_path = os.path.join(short_tmp, "p.sock")
            fake_home = Path(short_tmp) / "home"
            ade_bin = fake_home / "src/djbclark-ade/bin"
            ade_bin.mkdir(parents=True)
            (ade_bin / "ade_paseo_client.py").symlink_to(real_client)

            daemon = _UnixMockPaseoDaemon(sock_path, [[s1], [s2]], {AID_RUN_1: s1, AID_RUN_2: s2})
            try:
                env = dict(os.environ)
                env["HOME"] = str(fake_home)
                env["ADE_PASEO_URL"] = f"unix://{sock_path}"
                env["FLEET_WATCH_PASEO"] = "/nonexistent/paseo-must-not-run"
                env["FLEET_WATCH_PHANTOM_NOW"] = str(now)
                env.pop("ADE_PASEO_TRANSPORT", None)
                proc = subprocess.run(
                    ["bash", str(FLEET_WATCH), "phantom", "--dry-run"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env,
                )
            finally:
                daemon.close()

        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(daemon.ws_calls, 1)
        self.assertEqual(len(daemon.fetch_agents_requests), 2)
        for req in daemon.fetch_agents_requests:
            self.assertEqual(req.get("scope"), "active")
            self.assertNotIn("filter", req)
        self.assertEqual(daemon.mcp_calls, 2)
        self.assertIn("phantom: unix-page-1 11111111 (claude) ok:", proc.stdout)
        self.assertIn("phantom: unix-page-2 66666666 (codex) ok:", proc.stdout)
        self.assertIn("phantom: checked 2 running agent(s)", proc.stdout)

    def test_mcp_401_to_ws_fallback_with_local_credential(self):
        real_client = self._require_real_client()
        now = 1_800_000_000.0
        s1 = _snapshot(AID_RUN_1, "mcp-401-agent", "claude", now)

        with tempfile.TemporaryDirectory(prefix="fw-", dir="/tmp") as short_tmp:
            sock_path = os.path.join(short_tmp, "p.sock")
            fake_home = Path(short_tmp) / "home"
            ade_bin = fake_home / "src/djbclark-ade/bin"
            ade_bin.mkdir(parents=True)
            (ade_bin / "ade_paseo_client.py").symlink_to(real_client)
            paseo_home = fake_home / ".paseo"
            paseo_home.mkdir(parents=True)
            (paseo_home / "local-credential").write_text("secret-local-token\n", encoding="utf-8")

            daemon = _UnixMockPaseoDaemon(sock_path, [[s1]], {AID_RUN_1: s1}, mcp_status=401)
            try:
                env = dict(os.environ)
                env["HOME"] = str(fake_home)
                env["ADE_PASEO_URL"] = f"unix://{sock_path}"
                env["FLEET_WATCH_PASEO"] = "/nonexistent/paseo-must-not-run"
                env["FLEET_WATCH_PHANTOM_NOW"] = str(now)
                env.pop("ADE_PASEO_TRANSPORT", None)
                proc = subprocess.run(
                    ["bash", str(FLEET_WATCH), "phantom", "--dry-run"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env,
                )
            finally:
                daemon.close()

        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(daemon.mcp_calls, 1)
        self.assertEqual(daemon.fetch_agent_ws_calls, 1)
        self.assertIn("phantom: mcp-401-agent 11111111 (claude) ok:", proc.stdout)

    def test_single_wall_clock_budget_enforced_across_multipage_ws_list(self):
        real_client = self._require_real_client()
        now = 1_800_000_000.0
        s1 = _snapshot(AID_RUN_1, "slow-p1", "claude", now)
        s2 = _snapshot(AID_RUN_2, "slow-p2", "codex", now)
        s3 = _snapshot(AID_IDLE, "slow-p3", "claude", now)

        with tempfile.TemporaryDirectory(prefix="fw-", dir="/tmp") as short_tmp:
            sock_path = os.path.join(short_tmp, "p.sock")
            fake_home = Path(short_tmp) / "home"
            ade_bin = fake_home / "src/djbclark-ade/bin"
            ade_bin.mkdir(parents=True)
            (ade_bin / "ade_paseo_client.py").symlink_to(real_client)

            # 3 pages * 0.20s = 0.60s total, exceeding the 0.30s per-command budget.
            # Without a single shared deadline, each page would reset the 0.30s clock and succeed.
            daemon = _UnixMockPaseoDaemon(
                sock_path,
                [[s1], [s2], [s3]],
                {AID_RUN_1: s1, AID_RUN_2: s2, AID_IDLE: s3},
                page_delay_s=0.20,
            )
            try:
                env = dict(os.environ)
                env["HOME"] = str(fake_home)
                env["ADE_PASEO_URL"] = f"unix://{sock_path}"
                env["FLEET_WATCH_PASEO"] = "/nonexistent/paseo-must-not-run"
                env["FLEET_WATCH_PHANTOM_NOW"] = str(now)
                env["FLEET_WATCH_PHANTOM_CMD_TIMEOUT"] = "0.30"
                env.pop("ADE_PASEO_TRANSPORT", None)
                t0 = time.monotonic()
                proc = subprocess.run(
                    ["bash", str(FLEET_WATCH), "phantom", "--dry-run"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env,
                )
                elapsed = time.monotonic() - t0
            finally:
                daemon.close()

        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("phantom: unavailable: paseo daemon ls failed:", proc.stdout)
        self.assertLess(len(daemon.fetch_agents_requests), 3)
        self.assertLess(elapsed, 1.5)

    def test_single_wall_clock_budget_enforced_across_mcp_401_to_ws_fallback(self):
        real_client = self._require_real_client()
        now = 1_800_000_000.0
        s1 = _snapshot(AID_RUN_1, "slow-fallback", "claude", now)

        with tempfile.TemporaryDirectory(prefix="fw-", dir="/tmp") as short_tmp:
            sock_path = os.path.join(short_tmp, "p.sock")
            fake_home = Path(short_tmp) / "home"
            ade_bin = fake_home / "src/djbclark-ade/bin"
            ade_bin.mkdir(parents=True)
            (ade_bin / "ade_paseo_client.py").symlink_to(real_client)
            paseo_home = fake_home / ".paseo"
            paseo_home.mkdir(parents=True)
            (paseo_home / "local-credential").write_text("secret-local-token\n", encoding="utf-8")

            # MCP 401 takes 0.20s + WS fetch_agent takes 0.20s = 0.40s > 0.28s single budget.
            # Without a shared deadline, MCP (0.20 < 0.28) and WS (0.20 < 0.28) would both succeed.
            daemon = _UnixMockPaseoDaemon(
                sock_path,
                [[s1]],
                {AID_RUN_1: s1},
                mcp_status=401,
                mcp_delay_s=0.20,
                ws_agent_delay_s=0.20,
            )
            try:
                env = dict(os.environ)
                env["HOME"] = str(fake_home)
                env["ADE_PASEO_URL"] = f"unix://{sock_path}"
                env["FLEET_WATCH_PASEO"] = "/nonexistent/paseo-must-not-run"
                env["FLEET_WATCH_PHANTOM_NOW"] = str(now)
                env["FLEET_WATCH_PHANTOM_CMD_TIMEOUT"] = "0.28"
                env.pop("ADE_PASEO_TRANSPORT", None)
                proc = subprocess.run(
                    ["bash", str(FLEET_WATCH), "phantom", "--dry-run"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env,
                )
            finally:
                daemon.close()

        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(daemon.mcp_calls, 1)
        self.assertIn("phantom: 11111111 no verdict: paseo daemon inspect failed:", proc.stdout)


if __name__ == "__main__":
    unittest.main()
