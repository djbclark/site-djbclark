#!/usr/bin/env python3
"""Tests for fleet-watch's Hetzner restock watcher (`fleet-watch hetzner`).

Runs the real script with HOME pointed at a temp dir. The Hetzner API is a local HTTP server that
serves the recorded response shape (tests/fixtures/hetzner_server_types.json) and records every
request; sudo-secretspec and hermes-ping are stubs. No real token, no network, nothing is sent.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FLEET_WATCH = Path(os.environ.get("FLEET_WATCH_SCRIPT", REPO / "bin" / "fleet-watch"))
FIXTURE = REPO / "tests" / "fixtures" / "hetzner_server_types.json"
TOKEN = "fake-token-0123456789abcdef"

# The boundary's `run --reason R -- cmd...`: the child gets every declared secret, not just one.
SECRETSPEC_STUB = f"""#!/bin/bash
echo "$*" >> "$HOME/secretspec.calls"
[ "$1" = run ] || exit 2
shift 3   # run --reason R
[ "$1" = -- ] && shift
HETZNER_CLOUD_TOKEN={TOKEN} OTHER_DECLARED_SECRET=decoy-secret exec "$@"
"""

PING_STUB = """#!/bin/bash
rc=$(cat "$HOME/ping_rc" 2>/dev/null || echo 0)
[ "$rc" = 0 ] && echo "$*" >> "$HOME/pings"
exit "$rc"
"""


class Api:
    """Serves self.body at any GET path; records (method, path, authorization) of every request."""

    def __init__(self) -> None:
        self.body: dict = json.loads(FIXTURE.read_text())
        self.status = 200
        self.requests: list[tuple[str, str, str | None]] = []
        api = self

        class H(BaseHTTPRequestHandler):
            def _serve(self) -> None:
                api.requests.append((self.command, self.path, self.headers.get("Authorization")))
                if self.command != "GET":
                    self.send_response(405)
                    self.end_headers()
                    return
                data = json.dumps(api.body).encode()
                self.send_response(api.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _serve

            def log_message(self, *args) -> None:
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1/server_types?per_page=50"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def set(self, typ: str, loc: str, available: bool) -> None:
        for st in self.body["server_types"]:
            if st["name"] == typ:
                for entry in st["locations"]:
                    if entry["name"] == loc:
                        entry["available"] = available

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class HetznerWatch(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.home = root / "home"
        self.bin = root / "bin"
        (self.home / ".local" / "bin").mkdir(parents=True)
        self.bin.mkdir()
        for path, text in ((self.home / ".local" / "bin" / "hermes-ping", PING_STUB),
                           (self.bin / "sudo-secretspec", SECRETSPEC_STUB)):
            path.write_text(text)
            path.chmod(0o755)
        self.state_dir = self.home / ".local" / "state" / "fleet-watch"
        self.api = Api()
        self.addCleanup(self.api.close)
        self.addCleanup(self._tmp.cleanup)

    def run_watch(self, *args: str, url: str | None = None) -> subprocess.CompletedProcess:
        env = {
            "HOME": str(self.home), "PATH": f"{self.bin}:{os.environ['PATH']}",
            "FLEET_WATCH_SECRETSPEC": str(self.bin / "sudo-secretspec"),
            "FLEET_WATCH_HETZNER_URL": url or self.api.url, "FLEET_WATCH_TO": "telegram:1:2",
        }
        return subprocess.run([str(FLEET_WATCH), "hetzner", *args], env=env, capture_output=True,
                              text=True, timeout=120)

    def pings(self) -> list[str]:
        f = self.home / "pings"
        return f.read_text().splitlines() if f.exists() else []

    def state(self) -> dict:
        return json.loads((self.state_dir / "hetzner-restock.json").read_text())

    def test_first_run_seeds_state_and_stays_silent_when_nothing_is_available(self) -> None:
        r = self.run_watch()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.pings(), [])
        self.assertEqual(self.state()["avail"], {
            "cx33@fsn1": False, "cx33@nbg1": False, "cx43@fsn1": False, "cx43@nbg1": False})

    def test_first_run_pings_only_for_pairs_already_available(self) -> None:
        self.api.set("cx33", "nbg1", True)
        self.assertEqual(self.run_watch().returncode, 0)
        self.assertEqual(len(self.pings()), 1)
        self.assertIn("cx33 now available in nbg1 (rescale vps-primary: needs power-off; ask djbclark)",
                      self.pings()[0])

    def test_pings_on_change_only_and_once_per_change(self) -> None:
        self.run_watch()
        self.assertEqual(self.pings(), [])
        self.api.set("cx43", "fsn1", True)
        self.run_watch()
        self.run_watch()  # same state again: silent
        self.assertEqual(len(self.pings()), 1)
        self.assertIn("cx43 now available in fsn1", self.pings()[0])
        self.api.set("cx43", "fsn1", False)
        self.run_watch()
        self.run_watch()
        self.assertEqual(len(self.pings()), 2)
        self.assertIn("cx43 back to unavailable in fsn1", self.pings()[1])
        self.assertIs(self.state()["avail"]["cx43@fsn1"], False)

    def test_unwatched_types_and_locations_are_ignored(self) -> None:
        self.run_watch()
        self.api.set("cx23", "fsn1", False)  # cx23 is not watched
        self.api.set("cx33", "hel1", True)  # hel1 is not watched
        self.run_watch()
        self.assertEqual(self.pings(), [])

    def test_failed_ping_is_retried_on_the_next_run(self) -> None:
        self.run_watch()
        self.api.set("cx33", "fsn1", True)
        (self.home / "ping_rc").write_text("1")
        self.assertNotEqual(self.run_watch().returncode, 0)
        self.assertIs(self.state()["avail"]["cx33@fsn1"], False)  # not recorded as announced
        (self.home / "ping_rc").write_text("0")
        self.assertEqual(self.run_watch().returncode, 0)
        self.assertEqual(len(self.pings()), 1)
        self.assertIs(self.state()["avail"]["cx33@fsn1"], True)

    def test_api_failure_pings_nothing_and_keeps_state(self) -> None:
        self.run_watch()
        before = self.state()
        self.api.status = 401
        r = self.run_watch()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.pings(), [])
        self.assertEqual(self.state(), before)

    def test_response_without_watched_pairs_is_an_error_not_a_change(self) -> None:
        self.run_watch()
        before = self.state()
        self.api.body = {"server_types": [], "meta": {}}
        self.assertNotEqual(self.run_watch().returncode, 0)
        self.assertEqual(self.pings(), [])
        self.assertEqual(self.state(), before)

    def test_only_get_requests_with_bearer_token_and_token_never_stored(self) -> None:
        self.api.set("cx33", "nbg1", True)
        self.run_watch()
        self.run_watch("--dry-run")
        self.assertTrue(self.api.requests)
        for method, path, auth in self.api.requests:
            self.assertEqual(method, "GET")
            self.assertTrue(path.startswith("/v1/server_types?per_page=50"), path)
            self.assertEqual(auth, f"Bearer {TOKEN}")
        calls = (self.home / "secretspec.calls").read_text()
        self.assertIn('run --reason hetzner restock watch --', calls)
        self.assertNotIn(TOKEN, calls)
        for f in self.home.rglob("*"):
            if f.is_file() and f.name != "secretspec.calls":
                text = f.read_text(errors="replace")
                self.assertNotIn(TOKEN, text, f)
                self.assertNotIn("decoy-secret", text, f)

    def test_redirect_is_refused_so_the_token_cannot_follow_it(self) -> None:
        sink = Api()
        self.addCleanup(sink.close)

        class R(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(302)
                self.send_header("Location", sink.url)
                self.end_headers()

            def log_message(self, *args) -> None:
                pass

        httpd = HTTPServer(("127.0.0.1", 0), R)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        r = self.run_watch(url=f"http://127.0.0.1:{httpd.server_port}/v1/server_types?per_page=50")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(sink.requests, [])

    def test_follows_pagination_with_get(self) -> None:
        pages = {}
        full = copy.deepcopy(self.api.body)
        first = {"server_types": full["server_types"][:1],
                 "meta": {"pagination": {"page": 1, "next_page": 2}}}
        rest = {"server_types": full["server_types"][1:],
                "meta": {"pagination": {"page": 2, "next_page": None}}}
        pages[1], pages[2] = first, rest
        api = self.api

        class P(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                api.requests.append((self.command, self.path, self.headers.get("Authorization")))
                data = json.dumps(pages[2 if "page=2" in self.path else 1]).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args) -> None:
                pass

        httpd = HTTPServer(("127.0.0.1", 0), P)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        r = self.run_watch(url=f"http://127.0.0.1:{httpd.server_port}/v1/server_types?per_page=50")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.state()["avail"]), 4)
        self.assertEqual([m for m, _, _ in api.requests], ["GET", "GET"])

    def test_fixture_dry_run_prints_the_ping_and_touches_nothing(self) -> None:
        data = json.loads(FIXTURE.read_text())
        for st in data["server_types"]:
            if st["name"] == "cx43":
                st["locations"][1]["available"] = True  # nbg1
        fx = Path(self._tmp.name) / "fx.json"
        fx.write_text(json.dumps(data))
        r = self.run_watch("--fixture", str(fx), url="http://127.0.0.1:9/unused")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would ping: cx43 now available in nbg1 (rescale vps-primary: needs power-off; "
                      "ask djbclark)", r.stdout)
        self.assertEqual(self.pings(), [])
        self.assertFalse((self.state_dir / "hetzner-restock.json").exists())
        self.assertFalse((self.home / "secretspec.calls").exists())

    def test_recorded_fixture_matches_the_verified_shape(self) -> None:
        r = self.run_watch("--fixture", str(FIXTURE))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hetzner: cx33@fsn1=no cx33@nbg1=no cx43@fsn1=no cx43@nbg1=no", r.stdout)
        self.assertNotIn("would ping", r.stdout)


if __name__ == "__main__":
    unittest.main()
