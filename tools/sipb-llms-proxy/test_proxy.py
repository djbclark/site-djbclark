#!/usr/bin/env python3
"""Acceptance tests for the hardened sipb-llms-proxy.

Stdlib only. No network except 127.0.0.1. Uses a local fake upstream (a stdlib
http.server thread) and the proxy itself on a high port. Never touches the real
SIPB server.
"""
import http.client
import http.server
import importlib.util
import json
import os
import socketserver
import tempfile
import threading
import time
import unittest
from importlib.machinery import SourceFileLoader

PROXY_DEV = os.path.dirname(os.path.abspath(__file__))
PROXY_PATH = os.path.join(PROXY_DEV, "sipb-llms-proxy")

PROXY_PORT = 18891
UPSTREAM_PORT = 18890

TMP = tempfile.mkdtemp(prefix="sipb-proxy-test-")


class UpstreamState:
    def __init__(self):
        self.lock = threading.Lock()
        self.requests = []
        self.handler = None  # callable(method, path, body, headers) -> (status, ctype, bytes)
        self.active = 0
        self.max_active = 0

    def reset(self):
        with self.lock:
            self.requests = []
            self.handler = None
            self.active = 0
            self.max_active = 0


STATE = UpstreamState()


class UpstreamHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _handle(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        st = STATE
        with st.lock:
            st.requests.append({
                "method": self.command,
                "path": self.path,
                "headers": {k: v for k, v in self.headers.items()},
                "body": body,
            })
            st.active += 1
            st.max_active = max(st.max_active, st.active)
        try:
            status, ctype, out = st.handler(self.command, self.path, body, dict(self.headers.items()))
        finally:
            with st.lock:
                st.active -= 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()


# --- start fake upstream, then import the proxy with env pointing at it -----

class _ReuseTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


_upstream = _ReuseTCPServer(("127.0.0.1", UPSTREAM_PORT), UpstreamHandler)
_upstream.daemon_threads = True
threading.Thread(target=_upstream.serve_forever, daemon=True).start()

os.environ["SIPB_UPSTREAM"] = "http://127.0.0.1:%d" % UPSTREAM_PORT
os.environ["SIPB_MAX_CONCURRENCY"] = "1"
os.environ["SIPB_RETRIES"] = "2"
os.environ["SIPB_QUEUE_TIMEOUT"] = "900"
os.environ["SIPB_LOG"] = os.path.join(TMP, "requests.jsonl")
os.environ["SIPB_RULES_FILE"] = os.path.join(TMP, "rules.md")

_loader = SourceFileLoader("sipb_llms_proxy", PROXY_PATH)
_spec = importlib.util.spec_from_loader("sipb_llms_proxy", _loader)
proxy = importlib.util.module_from_spec(_spec)
_loader.exec_module(proxy)

_proxy = proxy.Server(("127.0.0.1", PROXY_PORT), proxy.Handler)
_proxy.daemon_threads = True
threading.Thread(target=_proxy.serve_forever, daemon=True).start()


def http_request(method, path, body=b"", headers=None, timeout=30):
    conn = http.client.HTTPConnection("127.0.0.1", PROXY_PORT, timeout=timeout)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        status = resp.status
        rheaders = {k.lower(): v for k, v in resp.getheaders()}
        data = resp.read()
        return status, rheaders, data
    finally:
        conn.close()


def post_json(payload, headers=None):
    return http_request("POST", "/api/chat/completions", json.dumps(payload).encode(), headers)


def json_ok(status, data):
    return status, json.loads(data.decode())


def sse_event(line):
    line = line.strip()
    if not line.startswith(b"data:"):
        return None
    payload = line[5:].strip()
    if payload == b"[DONE]":
        return None
    try:
        return json.loads(payload)
    except Exception:
        return None


class ProxyTests(unittest.TestCase):
    def setUp(self):
        STATE.reset()
        proxy.LOG_PATH = os.path.join(TMP, self._testMethodName + ".jsonl")
        if os.path.exists(proxy.LOG_PATH):
            os.remove(proxy.LOG_PATH)
        proxy.RULES_FILE = os.path.join(TMP, self._testMethodName + ".rules.md")
        if os.path.exists(proxy.RULES_FILE):
            os.remove(proxy.RULES_FILE)

    def wait_for(self, cond, timeout=5.0, interval=0.02):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cond():
                return True
            time.sleep(interval)
        return cond()

    def read_log_lines(self):
        try:
            with open(proxy.LOG_PATH) as f:
                return [json.loads(l) for l in f if l.strip()]
        except (OSError, ValueError):
            return []

    # --- 1. finish_reason fix still works --------------------------------

    def test_finish_reason_fix_stream(self):
        def handler(method, path, body, headers):
            sse = (
                b'data: {"id":"1","choices":[{"delta":{"role":"assistant"}}]}\n\n'
                b'data: {"id":"1","choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
                b'"type":"function","function":{"name":"foo","arguments":"{}"}}]}}]}\n\n'
                b'data: {"id":"1","choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                b'data: [DONE]\n\n'
            )
            return 200, "text/event-stream", sse

        STATE.handler = handler
        status, headers, data = post_json({"model": "m", "stream": True, "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(status, 200)
        finish_events = [sse_event(l) for l in data.split(b"\n")]
        finish_events = [e for e in finish_events if e is not None and any(
            (c or {}).get("finish_reason") for c in (e.get("choices") or []))]
        self.assertTrue(finish_events)
        self.assertEqual(finish_events[-1]["choices"][0]["finish_reason"], "tool_calls")

    def test_finish_reason_fix_json(self):
        resp_json = {
            "id": "1",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "foo", "arguments": "{}"}}],
                },
                "finish_reason": "stop",
            }],
        }

        def handler(method, path, body, headers):
            return 200, "application/json", json.dumps(resp_json).encode()

        STATE.handler = handler
        status, headers, data = post_json({"model": "m", "stream": False, "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(status, 200)
        got = json.loads(data.decode())
        self.assertEqual(got["choices"][0]["finish_reason"], "tool_calls")

    # --- 2. rules injection ----------------------------------------------

    def test_rules_injected_once(self):
        rules = "RULE_MARKER_1: be nice."
        with open(proxy.RULES_FILE, "w") as f:
            f.write(rules + "\n")

        seen = {}

        def handler(method, path, body, headers):
            seen["body"] = body
            return 200, "application/json", json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}).encode()

        STATE.handler = handler
        post_json({"model": "m", "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]})
        sent = json.loads(seen["body"].decode())
        self.assertEqual(sent["messages"][0]["role"], "system")
        self.assertTrue(sent["messages"][0]["content"].startswith(rules + "\n\n"))
        # exactly one prepend: the marker appears exactly once
        self.assertEqual(sent["messages"][0]["content"].count("RULE_MARKER_1"), 1)

    def test_rules_skipped_with_header(self):
        rules = "RULE_MARKER_2"
        with open(proxy.RULES_FILE, "w") as f:
            f.write(rules + "\n")

        seen = {}

        def handler(method, path, body, headers):
            seen["body"] = body
            return 200, "application/json", json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}).encode()

        STATE.handler = handler
        post_json({"model": "m", "messages": [{"role": "system", "content": "sys"}]}, headers={"X-Sipb-Rules": "off"})
        sent = json.loads(seen["body"].decode())
        self.assertEqual(sent["messages"][0]["content"], "sys")

    def test_rules_idempotent(self):
        rules = "RULE_MARKER_3"
        with open(proxy.RULES_FILE, "w") as f:
            f.write(rules + "\n")

        seen = {}

        def handler(method, path, body, headers):
            seen["body"] = body
            return 200, "application/json", json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}).encode()

        STATE.handler = handler
        # already present -> must not be duplicated
        post_json({"model": "m", "messages": [{"role": "system", "content": rules + "\n\nsys"}]})
        sent = json.loads(seen["body"].decode())
        self.assertEqual(sent["messages"][0]["content"].count("RULE_MARKER_3"), 1)
        self.assertTrue(sent["messages"][0]["content"].endswith("sys"))

    def test_rules_insert_when_no_system(self):
        rules = "RULE_MARKER_4"
        with open(proxy.RULES_FILE, "w") as f:
            f.write(rules + "\n")

        seen = {}

        def handler(method, path, body, headers):
            seen["body"] = body
            return 200, "application/json", json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}).encode()

        STATE.handler = handler
        post_json({"model": "m", "messages": [{"role": "user", "content": "hi"}]})
        sent = json.loads(seen["body"].decode())
        self.assertEqual(sent["messages"][0]["role"], "system")
        self.assertIn("RULE_MARKER_4", sent["messages"][0]["content"])

    # --- 3. concurrency ----------------------------------------------------

    def test_concurrency_serializes(self):
        def handler(method, path, body, headers):
            time.sleep(0.4)
            return 200, "application/json", json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}).encode()

        STATE.handler = handler
        results = []

        def worker():
            status, headers, data = post_json({"model": "m_serial", "messages": [{"role": "user", "content": "hi"}]})
            results.append(status)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.assertEqual(results, [200, 200])
        # The proxy must serialize same-model requests: fake upstream never saw
        # two requests at once.
        self.assertEqual(STATE.max_active, 1)

    # --- 4. retry -----------------------------------------------------------

    def test_retry_503_then_200(self):
        calls = {"n": 0}

        def handler(method, path, body, headers):
            calls["n"] += 1
            if calls["n"] == 1:
                return 503, "application/json", b'{"error": "overloaded"}'
            return 200, "application/json", json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}).encode()

        STATE.handler = handler
        status, headers, data = post_json({"model": "m_retry", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(status, 200)
        self.assertEqual(calls["n"], 2)
        # log should report retries == 1 (wait for the async log write)
        self.assertTrue(self.wait_for(lambda: any(
            l.get("event") != "retry" for l in self.read_log_lines())))
        req_lines = [l for l in self.read_log_lines() if l.get("event") != "retry"]
        self.assertEqual(req_lines[-1]["retries"], 1)

    def test_retry_empty_stream(self):
        calls = {"n": 0}

        def handler(method, path, body, headers):
            calls["n"] += 1
            if calls["n"] == 1:
                return 200, "text/event-stream", b""
            sse = (
                b'data: {"id":"1","choices":[{"delta":{"content":"hello"}}]}\n\n'
                b'data: {"id":"1","choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                b'data: [DONE]\n\n'
            )
            return 200, "text/event-stream", sse

        STATE.handler = handler
        status, headers, data = post_json({"model": "m_empty", "stream": True, "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(status, 200)
        self.assertEqual(calls["n"], 2)
        self.assertIn(b'"content":"hello"', data)

    def test_400_not_retried(self):
        calls = {"n": 0}

        def handler(method, path, body, headers):
            calls["n"] += 1
            return 400, "application/json", b'{"error": "bad request"}'

        STATE.handler = handler
        status, headers, data = post_json({"model": "m_400", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(status, 400)
        self.assertEqual(calls["n"], 1)

    # --- 5. latency log -----------------------------------------------------

    def test_log_no_key_no_content(self):
        secret = "Bearer sk-SUPERSECRET123"
        prompt_text = "TOP_SECRET_PROMPT_CONTENT_XYZ"

        def handler(method, path, body, headers):
            return 200, "application/json", json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}).encode()

        STATE.handler = handler
        status, headers, data = post_json(
            {"model": "m_log", "messages": [{"role": "user", "content": prompt_text}]},
            headers={"Authorization": secret},
        )
        self.assertEqual(status, 200)
        self.assertTrue(self.wait_for(lambda: bool(self.read_log_lines())))
        raw = "\n".join(json.dumps(l) for l in self.read_log_lines())
        self.assertNotIn("sk-SUPERSECRET123", raw)
        self.assertNotIn("TOP_SECRET_PROMPT_CONTENT_XYZ", raw)
        # and every line is valid JSON with the expected fields
        for rec in self.read_log_lines():
            if rec.get("event") == "retry":
                continue
            for key in ("ts", "model", "stream", "n_messages", "prompt_chars", "retries"):
                self.assertIn(key, rec)

    # --- 6. pass-through GET ------------------------------------------------

    def test_models_pass_through(self):
        models = {"object": "list", "data": [{"id": "gpt-4o"}]}

        def handler(method, path, body, headers):
            return 200, "application/json", json.dumps(models).encode()

        STATE.handler = handler
        status, headers, data = http_request("GET", "/api/models")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data.decode()), models)

    # --- 7. text-form tool calls -> native tool_calls -----------------------

    def _stream_text(self, text, finish="stop"):
        chunks = text if isinstance(text, list) else [text]
        body = b""
        for c in chunks:
            body += b"data: " + json.dumps({"choices": [{"delta": {"content": c}}]}).encode() + b"\n\n"
        body += b"data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": finish}]}).encode() + b"\n\ndata: [DONE]\n\n"
        return 200, "text/event-stream", body

    def _collect_toolcalls(self, data):
        calls = []
        finish = None
        for line in data.split(b"\n"):
            ev = sse_event(line)
            if ev is None:
                continue
            for ch in ev.get("choices") or []:
                for tc in (ch.get("delta") or {}).get("tool_calls") or []:
                    calls.append(tc)
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
        return calls, finish

    def test_normalize_stream_invoke(self):
        text = '<tool_calls>\n<invoke name="bash">\n<parameter name="command">ls -la</parameter>\n</invoke>\n</tool_calls>'
        STATE.handler = lambda *a: self._stream_text(text)
        status, headers, data = post_json({"model": "m", "stream": True, "messages": []})
        self.assertEqual(status, 200)
        calls, finish = self._collect_toolcalls(data)
        self.assertEqual(finish, "tool_calls")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "bash")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"command": "ls -la"})
        self.assertNotIn(b"<invoke", data)  # the pseudo-syntax is replaced, not leaked

    def test_normalize_stream_function(self):
        text = '<function=ls>\n<parameter=path>\n/tmp\n</parameter>\n</function>\n</tool_call>'
        STATE.handler = lambda *a: self._stream_text(text)
        status, headers, data = post_json({"model": "m", "stream": True, "messages": []})
        calls, finish = self._collect_toolcalls(data)
        self.assertEqual(finish, "tool_calls")
        self.assertEqual(calls[0]["function"]["name"], "ls")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"path": "/tmp"})

    def test_normalize_stream_view(self):
        text = ["I'll read it.\n", "<view><location>/etc/hosts</location></view>"]
        STATE.handler = lambda *a: self._stream_text(text)
        status, headers, data = post_json({"model": "m", "stream": True, "messages": []})
        calls, finish = self._collect_toolcalls(data)
        self.assertEqual(finish, "tool_calls")
        self.assertEqual(calls[0]["function"]["name"], "view")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"file_path": "/etc/hosts"})
        self.assertIn(b"I'll read it.", data)  # prose before the marker still streams

    def test_normalize_json(self):
        body = {"choices": [{"message": {"role": "assistant",
                "content": '<function=ls><parameter=path>/tmp</parameter></function>'},
                "finish_reason": "stop"}]}

        def handler(method, path, body_, headers):
            return 200, "application/json", json.dumps(body).encode()

        STATE.handler = handler
        status, headers, data = post_json({"model": "m", "stream": False, "messages": []})
        got = json.loads(data.decode())
        ch = got["choices"][0]
        self.assertEqual(ch["finish_reason"], "tool_calls")
        self.assertEqual(ch["message"]["tool_calls"][0]["function"]["name"], "ls")
        self.assertEqual(ch["message"]["content"], "")

    def test_normalize_leaves_plain_text(self):
        def handler(method, path, body, headers):
            return 200, "application/json", json.dumps({"choices": [
                {"message": {"content": "The answer is 42."}, "finish_reason": "stop"}]}).encode()

        STATE.handler = handler
        status, headers, data = post_json({"model": "m", "stream": False, "messages": []})
        got = json.loads(data.decode())
        self.assertNotIn("tool_calls", got["choices"][0]["message"])
        self.assertEqual(got["choices"][0]["finish_reason"], "stop")

    def test_normalize_leaves_code_fence(self):
        text = "Here is the command:\n\n```bash\ntouch /tmp/x && echo hi > /tmp/x\n```"
        STATE.handler = lambda *a: self._stream_text(text)
        status, headers, data = post_json({"model": "m", "stream": True, "messages": []})
        calls, finish = self._collect_toolcalls(data)
        self.assertFalse(calls)  # a bare fence is illustrative: not executed
        self.assertEqual(finish, "stop")
        self.assertIn(b"touch /tmp/x", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
