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
import re
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

# The boundary's `get NAME --reason R`: prints that one value on stdout. Asking for anything else
# would hand out the decoy, so a test sees it if the watcher ever requests another secret.
SECRETSPEC_STUB = f"""#!/bin/bash
echo "$*" >> "$HOME/secretspec.calls"
[ -e "$HOME/get_rc" ] && exit "$(cat "$HOME/get_rc")"
[ "$1" = get ] && [ "$3" = --reason ] || exit 2
case "$2" in
  HETZNER_CLOUD_TOKEN) echo {TOKEN} ;;
  *) echo decoy-secret ;;
esac
"""

PING_STUB = """#!/bin/bash
env >> "$HOME/ping.env"
rc=$(cat "$HOME/ping_rc" 2>/dev/null || echo 0)
[ "$rc" = 0 ] && echo "$*" >> "$HOME/pings"
exit "$rc"
"""


class Api:
    """Serves self.body at any GET path; records (method, path, authorization) of every request."""

    def __init__(self) -> None:
        self.body: dict = json.loads(FIXTURE.read_text())
        self.status = 200
        self.always_next = False  # every response claims one more page follows
        self.requests: list[tuple[str, str, str | None]] = []
        api = self

        class H(BaseHTTPRequestHandler):
            def _serve(self) -> None:
                api.requests.append((self.command, self.path, self.headers.get("Authorization")))
                if self.command != "GET":
                    self.send_response(405)
                    self.end_headers()
                    return
                body = api.body
                if api.always_next:
                    page = int((re.search(r"[?&]page=(\d+)", self.path) or [0, 1])[1])
                    body = {**body, "meta": {"pagination": {"page": page, "next_page": page + 1}}}
                data = json.dumps(body).encode()
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

    def run_watch(self, *args: str, url: str | None = None,
                  extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        env = {
            "HOME": str(self.home), "PATH": f"{self.bin}:{os.environ['PATH']}",
            "FLEET_WATCH_SECRETSPEC": str(self.bin / "sudo-secretspec"),
            "FLEET_WATCH_HETZNER_URL": url or self.api.url, "FLEET_WATCH_TO": "telegram:1:2",
            **(extra_env or {}),
        }
        return subprocess.run([str(FLEET_WATCH), "hetzner", *args], env=env, capture_output=True,
                              text=True, timeout=120)

    def assert_no_secret_anywhere(self, r: subprocess.CompletedProcess) -> None:
        """The token and the decoy appear in no stdout, stderr, log, state or recorded child environment."""
        texts = {"stdout": r.stdout, "stderr": r.stderr}
        texts.update({str(f): f.read_text(errors="replace") for f in self.home.rglob("*") if f.is_file()})
        for where, text in texts.items():
            self.assertNotIn(TOKEN, text, where)
            self.assertNotIn("decoy-secret", text, where)
        ping_env = self.home / "ping.env"
        if ping_env.exists():
            self.assertNotIn("HETZNER_CLOUD_TOKEN", ping_env.read_text())

    def gets(self) -> list[str]:
        f = self.home / "secretspec.calls"
        return f.read_text().splitlines() if f.exists() else []

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
        r = self.run_watch()
        self.assertNotEqual(r.returncode, 0)
        self.assert_no_secret_anywhere(r)
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
        self.assert_no_secret_anywhere(r)

    def test_response_without_watched_pairs_is_an_error_not_a_change(self) -> None:
        self.run_watch()
        before = self.state()
        self.api.body = {"server_types": [], "meta": {}}
        r = self.run_watch()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.pings(), [])
        self.assertEqual(self.state(), before)
        self.assert_no_secret_anywhere(r)

    def test_only_get_requests_with_bearer_token_and_token_never_leaves_the_fetch_process(self) -> None:
        self.api.set("cx33", "nbg1", True)
        r = self.run_watch()
        self.run_watch("--dry-run")
        self.assertTrue(self.api.requests)
        for method, path, auth in self.api.requests:
            self.assertEqual(method, "GET")
            self.assertTrue(path.startswith("/v1/server_types?per_page=50"), path)
            self.assertEqual(auth, f"Bearer {TOKEN}")
        # Exactly one secret is ever requested, by name; the notify child ran and saw no token.
        self.assertTrue(self.gets())
        for call in self.gets():
            self.assertEqual(call, "get HETZNER_CLOUD_TOKEN --reason hetzner restock watch")
        self.assertTrue((self.home / "ping.env").exists())
        self.assert_no_secret_anywhere(r)

    def test_url_that_is_not_the_real_api_or_loopback_gets_no_request_and_no_token(self) -> None:
        port = self.api.httpd.server_port
        for bad in (f"http://127.1:{port}/v1/server_types?per_page=50",  # loopback in disguise
                    f"http://example.invalid:{port}/v1/server_types?per_page=50",
                    f"https://127.0.0.1:{port}/v1/server_types?per_page=50",
                    f"http://api.hetzner.cloud/v1/server_types?per_page=50",
                    f"https://api.hetzner.cloud.evil.invalid/v1/server_types?per_page=50",
                    f"https://api.hetzner.cloud@127.1:{port}/v1/server_types?per_page=50",
                    f"http://127.0.0.1@127.1:{port}/v1/server_types?per_page=50",
                    f"ftp://127.0.0.1:{port}/v1/server_types?per_page=50"):
            with self.subTest(url=bad):
                r = self.run_watch(url=bad)
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(self.api.requests, [])
                self.assertEqual(self.gets(), [])  # the token was not even asked for
                self.assertIn("refusing URL", (self.state_dir / "fleet-watch.log").read_text())
                self.assert_no_secret_anywhere(r)

    def test_token_that_cannot_be_read_means_no_request(self) -> None:
        (self.home / "get_rc").write_text("1")
        r = self.run_watch()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.api.requests, [])
        self.assert_no_secret_anywhere(r)

    def test_watched_grid_is_taken_from_the_configuration(self) -> None:
        r = self.run_watch(extra_env={"FLEET_WATCH_HETZNER_TYPES": "cx33", "FLEET_WATCH_HETZNER_LOCATIONS": "hel1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(list(self.state()["avail"]), ["cx33@hel1"])

    def test_pagination_is_capped(self) -> None:
        self.api.always_next = True
        r = self.run_watch()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.api.requests), 5)
        self.assertTrue(all(m == "GET" for m, _, _ in self.api.requests))

    def test_overlapping_run_leaves_the_pass_to_the_one_holding_the_lock(self) -> None:
        self.state_dir.mkdir(parents=True)
        lock = self.state_dir / "hetzner-restock.run"
        lock.mkdir()
        holder = subprocess.Popen(["sleep", "30"])
        self.addCleanup(holder.kill)
        (lock / "pid").write_text(str(holder.pid))
        self.api.set("cx33", "nbg1", True)
        self.assertEqual(self.run_watch().returncode, 0)
        self.assertEqual(self.api.requests, [])
        self.assertEqual(self.pings(), [])
        holder.kill()
        holder.wait()
        self.assertEqual(self.run_watch().returncode, 0)  # stale lock is taken over
        self.assertEqual(len(self.pings()), 1)
        self.assertFalse(lock.exists())

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
        self.assert_no_secret_anywhere(r)

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
        self.assertEqual(self.gets(), [])

    def test_recorded_fixture_matches_the_verified_shape(self) -> None:
        r = self.run_watch("--fixture", str(FIXTURE))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hetzner: cx33@fsn1=no cx33@nbg1=no cx43@fsn1=no cx43@nbg1=no", r.stdout)
        self.assertNotIn("would ping", r.stdout)


if __name__ == "__main__":
    unittest.main()
