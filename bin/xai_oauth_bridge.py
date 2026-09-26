#!/usr/bin/env python3
"""Loopback bridge: SuperGrok OAuth subscription -> OpenAI-compatible endpoint.

LiteLLM can only send a static API key, but the operator's Grok access is an
xAI OAuth grant (SuperGrok subscription, device-code login) whose access token
expires and whose refresh token ROTATES on every refresh. Hermes already owns
that grant in ~/.hermes/auth.json. Two independent refreshers of one rotating
grant would invalidate each other, so this bridge does not keep its own copy:
on every request it calls Hermes's own resolver, which refreshes under Hermes's
auth-store lock and writes the rotated grant back. Hermes and this bridge
therefore share one grant safely.

Must run under the Hermes venv python with the Hermes checkout importable:

    ~/.hermes/hermes-agent/venv/bin/python bin/xai_oauth_bridge.py

LiteLLM routes the `grok-sub` model here (see roles/litellm). Loopback-only,
no auth: never bind anything but 127.0.0.1.
"""

from __future__ import annotations

import argparse
import http.client
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERMES_AGENT_DIR = os.path.expanduser(
    os.environ.get("HERMES_AGENT_DIR", "~/.hermes/hermes-agent")
)
sys.path.insert(0, HERMES_AGENT_DIR)

from hermes_cli.auth import resolve_xai_oauth_runtime_credentials  # noqa: E402

# Hop-by-hop and length headers are recomputed by us / http.client.
_DROP_REQ = {"host", "authorization", "content-length", "connection",
             "accept-encoding", "transfer-encoding"}
_DROP_RESP = {"connection", "transfer-encoding", "content-length",
              "content-encoding", "keep-alive"}
_TIMEOUT = float(os.environ.get("XAI_BRIDGE_TIMEOUT", "660"))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _proxy(self) -> None:
        if not self.path.startswith("/v1/"):
            self.send_error(404, "only /v1/* is bridged")
            return
        try:
            creds = resolve_xai_oauth_runtime_credentials()
        except Exception as exc:  # surface auth failure to LiteLLM as 502
            self._plain(502, f"xai-oauth credential error: {type(exc).__name__}: {exc}")
            return
        base = urllib.parse.urlsplit(creds["base_url"])  # https://api.x.ai/v1
        upstream_path = base.path.rstrip("/") + self.path[len("/v1"):]

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in _DROP_REQ}
        headers["Authorization"] = f"Bearer {creds['api_key']}"
        headers["Accept-Encoding"] = "identity"

        conn = http.client.HTTPSConnection(base.netloc, timeout=_TIMEOUT)
        try:
            conn.request(self.command, upstream_path, body=body, headers=headers)
            resp = conn.getresponse()
            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                if k.lower() not in _DROP_RESP:
                    self.send_header(k, v)
            # Stream through (SSE included) with chunked framing.
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                chunk = resp.read1(65536)
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
        except Exception as exc:
            try:
                self._plain(502, f"xai upstream error: {type(exc).__name__}: {exc}")
            except Exception:
                pass
        finally:
            conn.close()
            self.close_connection = True

    def _plain(self, status: int, msg: str) -> None:
        data = msg.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    do_GET = do_POST = _proxy

    def log_message(self, format: str, *args) -> None:  # noqa: A002 — base-class name; one line per request
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), format % args))


def main() -> None:
    ap = argparse.ArgumentParser(description="Loopback SuperGrok OAuth bridge for LiteLLM")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=14011)
    args = ap.parse_args()
    if args.host not in ("127.0.0.1", "::1", "localhost"):
        sys.exit("refusing non-loopback bind: this bridge has no auth")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
