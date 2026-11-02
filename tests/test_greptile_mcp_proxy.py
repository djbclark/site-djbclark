"""greptile-mcp-proxy: allowlist, key hygiene, header rules, SSE/session passthrough, timeouts.

Hermetic: a fake Greptile upstream and the proxy both bind OS-assigned loopback ports (port 0) and a fake
`sudo-secretspec` script supplies a fake key. No network, no real secret.
"""

from __future__ import annotations

import http.client
import http.server
import importlib.machinery
import importlib.util
import json
import socketserver
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parent.parent / "bin" / "greptile-mcp-proxy"
KEY = "grp_FAKEKEY_0123456789abcdef"
ALLOWED = {
    "get_me", "list_pull_requests", "get_merge_request", "list_merge_request_comments",
    "list_code_reviews", "get_code_review", "trigger_code_review", "search_greptile_comments",
}
EXTRA = {f"extra_tool_{i}" for i in range(13)}  # 21 upstream tools in all


@pytest.fixture()
def gp():
    loader = importlib.machinery.SourceFileLoader("greptile_mcp_proxy_under_test", str(BIN))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


class Upstream:
    """Fake Greptile. `mode` picks the reply shape; every request it receives is recorded."""

    def __init__(self):
        self.received: list[dict] = []
        self.mode = "json"
        up = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def _handle(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                body = json.loads(raw) if raw else None
                up.received.append({"method": self.command, "headers": dict(self.headers.items()), "body": body, "path": self.path})
                if up.mode == "401":
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", f'Bearer realm="x", error_description="bad {KEY}"')
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": f"bad key {KEY}"}).encode())
                    return
                if up.mode == "hang":
                    time.sleep(5)
                    return
                msg = body if isinstance(body, dict) else {}
                method, rid = msg.get("method"), msg.get("id")
                hdr = {}
                if method == "initialize":
                    hdr["Mcp-Session-Id"] = "sess-123"
                    result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}}
                elif method == "tools/list":
                    result = {"tools": [{"name": n, "description": "d"} for n in sorted(ALLOWED | EXTRA)]}
                elif method == "tools/call":
                    text = f"leaked {KEY}" if up.mode == "leak" else "ok"
                    result = {"content": [{"type": "text", "text": text}], "echo_session": self.headers.get("Mcp-Session-Id")}
                else:
                    self.send_response(202)
                    self.end_headers()
                    return
                reply = {"jsonrpc": "2.0", "id": rid, "result": result}
                if up.mode == "sse":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    for k, v in hdr.items():
                        self.send_header(k, v)
                    self.end_headers()
                    self.wfile.write(b'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress","params":{"progress":1}}\n\n')
                    self.wfile.flush()
                    time.sleep(0.2)
                    self.wfile.write(b"event: message\ndata: " + json.dumps(reply).encode() + b"\n\n")
                    return
                data = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                for k, v in hdr.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_POST = do_DELETE = do_GET = _handle

        class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True

        self.srv = S(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def calls(self, method: str) -> list[dict]:
        return [r for r in self.received if isinstance(r["body"], dict) and r["body"].get("method") == method]


def fake_secretspec(tmp_path: Path, rc: int = 0) -> str:
    p = tmp_path / f"sudo-secretspec-{rc}"
    p.write_text(f"#!/bin/sh\n[ \"$1\" = get ] && [ \"$2\" = GREPTILE_API_KEY ] || exit 9\n[ {rc} -eq 0 ] && echo '{KEY}'\nexit {rc}\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(p)


@pytest.fixture()
def rig(gp, tmp_path):
    up = Upstream()
    servers = []

    def make(secretspec_rc=0, read_timeout=5.0, total_timeout=20.0):
        keys = gp.KeyState(lambda: gp.load_key(fake_secretspec(tmp_path, secretspec_rc)), retry_s=0.0)
        keys.get()
        proxy = gp.Proxy(("127.0.0.1", 0), f"http://127.0.0.1:{up.port}/mcp", keys, 2.0, read_timeout, total_timeout)
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        servers.append(proxy)
        return proxy.server_address[1]

    yield up, make
    for s in servers:
        s.shutdown()
        s.server_close()
    up.srv.shutdown()
    up.srv.server_close()


def post(port, body, headers=None, raw=None, path="/mcp"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    data = raw if raw is not None else json.dumps(body).encode()
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    h.update(headers or {})
    c.request("POST", path, body=data, headers=h)
    r = c.getresponse()
    out = (r.status, dict(r.getheaders()), r.read())
    c.close()
    return out


def rpc(method, params=None, rid=1):
    m = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        m["params"] = params
    return m


def test_tools_list_is_filtered_to_the_allowlist_json_and_sse(rig):
    up, make = rig
    port = make()
    for mode in ("json", "sse"):
        up.mode = mode
        st, hd, body = post(port, rpc("tools/list"))
        assert st == 200
        if mode == "sse":
            assert hd["Content-Type"].startswith("text/event-stream")
            datas = [json.loads(ln[6:]) for ln in body.decode().splitlines() if ln.startswith("data: ")]
            reply = next(d for d in datas if "result" in d)
        else:
            reply = json.loads(body)
        assert {t["name"] for t in reply["result"]["tools"]} == ALLOWED


def test_non_allowlisted_call_is_refused_locally_and_never_forwarded(rig):
    up, make = rig
    port = make()
    for name in ("extra_tool_3", "Get_Me", "get_me ", "", None, 7):
        st, _, body = post(port, rpc("tools/call", {"name": name, "arguments": {}}, rid=42))
        err = json.loads(body)
        assert st == 200 and err["id"] == 42 and err["error"]["code"] == -32602, name
    # a batch carrying one disallowed call is refused whole, including its allowed members
    st, _, body = post(port, [rpc("tools/call", {"name": "get_me"}, 1), rpc("tools/call", {"name": "extra_tool_1"}, 2)])
    out = {e["id"]: e for e in json.loads(body)}
    assert set(out) == {1, 2} and all("error" in e for e in out.values())
    assert up.received == []


def test_duplicate_key_smuggling_is_a_parse_error_not_a_forward(rig):
    up, make = rig
    port = make()
    raw = b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_me","name":"extra_tool_1"}}'
    st, _, body = post(port, None, raw=raw)
    assert st == 400 and json.loads(body)["error"]["code"] == -32700
    st, _, _ = post(port, None, raw=b"{not json")
    assert st == 400 and up.received == []


def test_allowed_call_is_forwarded_with_only_the_proxys_bearer(rig):
    up, make = rig
    port = make()
    st, _, body = post(port, rpc("tools/call", {"name": "get_me", "arguments": {}}),
                       headers={"Authorization": "Bearer CLIENT-SUPPLIED", "Cookie": "a=b", "X-Api-Key": "CLIENT-SUPPLIED"})
    assert st == 200 and json.loads(body)["result"]["content"][0]["text"] == "ok"
    (r,) = up.received
    h = {k.lower(): v for k, v in r["headers"].items()}
    assert h["authorization"] == f"Bearer {KEY}"
    assert "cookie" not in h and "x-api-key" not in h and "CLIENT-SUPPLIED" not in json.dumps(r["headers"])
    assert r["body"]["params"]["name"] == "get_me"


def test_key_never_appears_in_logs_responses_or_errors(rig, capsys):
    up, make = rig
    port = make()
    seen = []

    up.mode = "leak"  # the upstream itself echoes the key back
    seen.append(post(port, rpc("tools/call", {"name": "get_me"})))
    up.mode = "401"  # upstream auth failure must not surface the key, WWW-Authenticate or an OAuth hint
    st, hd, body = post(port, rpc("tools/list"))
    seen.append((st, hd, body))
    assert st == 502 and "www-authenticate" not in {k.lower() for k in hd}
    seen.append(post(port, rpc("tools/call", {"name": "extra_tool_1"})))
    seen.append(post(port, None, raw=b"{not json"))
    up.mode = "json"
    broken = make(secretspec_rc=3)  # key unreadable: a clean 503, no key, no secretspec output
    st, hd, body = post(broken, rpc("tools/list"))
    assert st == 503 and json.loads(body)["error"]["code"] == -32000
    seen.append((st, hd, body))
    assert up.calls("tools/call")[0]["body"]["params"]["name"] == "get_me"
    for st, hd, body in seen:
        assert KEY.encode() not in body and KEY not in json.dumps(hd)
    assert b"[redacted]" in seen[0][2]
    err = capsys.readouterr().err
    assert err.strip() and KEY not in err
    assert "tools/call get_me 200" in err and "tools/call extra_tool_1 REFUSED 200" in err
    assert "{" not in err  # no bodies


def test_sse_response_streams_event_by_event(rig):
    up, make = rig
    port = make()
    up.mode = "sse"
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    c.request("POST", "/mcp", body=json.dumps(rpc("tools/call", {"name": "get_code_review"})).encode(),
              headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    r = c.getresponse()
    assert r.status == 200 and r.getheader("Content-Type").startswith("text/event-stream")
    t0 = time.monotonic()
    first = r.readline()  # "event: message", then the first data line, before the second event exists upstream
    assert first == b"event: message\n" and b"notifications/progress" in r.readline()
    assert time.monotonic() - t0 < 0.15
    rest = r.read().decode()
    assert '"result"' in rest and rest.endswith("\n\n")
    c.close()


def test_session_and_protocol_headers_pass_both_ways(rig):
    up, make = rig
    port = make()
    st, hd, _ = post(port, rpc("initialize", {"protocolVersion": "2025-06-18"}))
    assert hd["Mcp-Session-Id"] == "sess-123"
    st, _, body = post(port, rpc("tools/call", {"name": "get_me"}), headers={"Mcp-Session-Id": "sess-123", "MCP-Protocol-Version": "2025-06-18"})
    assert json.loads(body)["result"]["echo_session"] == "sess-123"
    h = {k.lower(): v for k, v in up.calls("tools/call")[0]["headers"].items()}
    assert h["mcp-session-id"] == "sess-123" and h["mcp-protocol-version"] == "2025-06-18"
    # notifications get the upstream's bodiless 202
    st, _, body = post(port, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert st == 202 and body == b""


def test_upstream_timeout_is_an_error_not_a_hang(rig):
    up, make = rig
    port = make(read_timeout=0.5, total_timeout=3.0)
    up.mode = "hang"
    t0 = time.monotonic()
    st, _, body = post(port, rpc("tools/call", {"name": "get_me"}, rid=9))
    assert st == 504 and json.loads(body)["id"] == 9 and json.loads(body)["error"]["code"] == -32000
    assert time.monotonic() - t0 < 3.0


def test_only_the_mcp_path_post_and_loopback_hosts_are_served(rig, gp):
    up, make = rig
    port = make()
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", "/mcp")
    r = c.getresponse()
    assert r.status == 405 and r.getheader("Allow") == "POST, DELETE"
    c.close()
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("DELETE", "/mcp")  # no session: nothing to terminate
    assert c.getresponse().status == 405
    assert post(port, rpc("tools/list"), path="/other")[0] == 404
    assert post(port, rpc("tools/list"), headers={"Host": "evil.example"})[0] == 403  # DNS rebinding
    assert post(port, rpc("tools/list"), headers={"Origin": "https://evil.example"})[0] == 403
    assert up.received == []
    with pytest.raises(SystemExit):  # the bearer key must never be sent over plain http off-box
        gp.Proxy(("127.0.0.1", 0), "http://example.com/mcp", gp.KeyState(lambda: None), 1, 1, 1)
    with pytest.raises(Exception):
        gp.parse_listen("0.0.0.0:18808")


def test_register_edits_each_client_once_with_backup_and_keeps_other_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    loader = importlib.machinery.SourceFileLoader("greptile_mcp_register_under_test", str(BIN.with_name("greptile-mcp-register")))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    reg = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = reg
    loader.exec_module(reg)
    files = {
        ".cursor/mcp.json": {"mcpServers": {"firecrawl": {"url": "http://127.0.0.1:18804/mcp"}}},
        ".config/opencode/opencode.json": {"mcp": {"firecrawl": {"type": "remote"}}, "provider": {"x": 1}},
        ".gemini/config/mcp_config.json": {"mcpServers": {"firecrawl": {"disabled": False}}},
    }
    for rel, doc in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(json.dumps(doc))
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex/config.toml").write_text('[mcp_servers.firecrawl]\nurl = "http://127.0.0.1:18804/mcp"\n\n[mcp_servers.b.http_headers]\nx = "1"\n')
    names = ["cursor", "codex", "opencode", "agy"]
    assert [reg.TARGETS[n](True) for n in names] == ["would register"] * 4  # --check writes nothing
    assert not list(tmp_path.rglob("*.bak-2026-11-01-greptile"))
    assert [reg.TARGETS[n](False) for n in names] == ["registered"] * 4
    assert [reg.TARGETS[n](False) for n in names] == ["already registered"] * 4
    assert len(list(tmp_path.rglob("*.bak-2026-11-01-greptile"))) == 4
    for rel in files:
        doc = json.loads((tmp_path / rel).read_text())
        servers = doc.get("mcpServers") or doc["mcp"]
        assert "firecrawl" in servers and "http://127.0.0.1:18808/mcp" in json.dumps(servers["greptile"])
    assert json.loads((tmp_path / ".config/opencode/opencode.json").read_text())["provider"] == {"x": 1}
    import tomllib

    t = tomllib.loads((tmp_path / ".codex/config.toml").read_text())["mcp_servers"]
    assert t["greptile"]["url"] == "http://127.0.0.1:18808/mcp" and t["b"]["http_headers"] == {"x": "1"} and "firecrawl" in t
    assert "Authorization" not in json.dumps(files) and not any("Bearer" in p.read_text() for p in tmp_path.rglob("*.json"))
