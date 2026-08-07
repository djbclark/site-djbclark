from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "gemini_opencli_bridge.py"
SPEC = importlib.util.spec_from_file_location("gemini_opencli_bridge", SCRIPT)
assert SPEC and SPEC.loader
bridge = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bridge
SPEC.loader.exec_module(bridge)


def cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["opencli"], returncode=returncode, stdout=stdout, stderr=stderr)


class SequenceRunner:
    """Fake opencli runner: returns queued CompletedProcess results in order,
    recording every (args, timeout) call for assertions."""

    def __init__(self, results: list[subprocess.CompletedProcess]) -> None:
        self._results = list(results)
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, args: list[str], *, timeout: float) -> subprocess.CompletedProcess:
        self.calls.append((args, timeout))
        if not self._results:
            raise AssertionError("SequenceRunner exhausted")
        return self._results.pop(0)


class ClassifyFailureTests(unittest.TestCase):
    def test_daemon_unavailable_wins_over_other_patterns(self) -> None:
        # "quota" happens to appear in the same message as a daemon failure;
        # daemon must win so callers don't misdiagnose an offline bridge as
        # a login/quota problem.
        text = "Error: ECONNREFUSED talking to daemon (quota check skipped)"
        self.assertEqual(bridge.classify_failure(text), bridge.ErrorType.DAEMON_UNAVAILABLE)

    def test_login_required(self) -> None:
        self.assertEqual(
            bridge.classify_failure("Please sign in to continue"), bridge.ErrorType.LOGIN_REQUIRED
        )

    def test_quota_or_challenge(self) -> None:
        self.assertEqual(
            bridge.classify_failure("Too many requests, try later"),
            bridge.ErrorType.QUOTA_OR_CHALLENGE,
        )

    def test_unrecognized_failure_is_ui_mismatch(self) -> None:
        self.assertEqual(
            bridge.classify_failure("something completely unexpected exploded"),
            bridge.ErrorType.UI_MISMATCH,
        )


class ResolveOpencliBinTests(unittest.TestCase):
    def test_daemon_unavailable_when_binary_missing(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": "", "GEMINI_BRIDGE_OPENCLI_BIN": ""}, clear=False):
            del os.environ["GEMINI_BRIDGE_OPENCLI_BIN"]
            with mock.patch.object(bridge.os, "access", return_value=False):
                with self.assertRaises(bridge.BridgeError) as ctx:
                    bridge.resolve_opencli_bin()
            self.assertEqual(ctx.exception.error_type, bridge.ErrorType.DAEMON_UNAVAILABLE)

    def test_standard_homebrew_fallback_is_used(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": ""}, clear=False):
            with mock.patch.object(bridge.shutil, "which", return_value=None):
                with mock.patch.object(
                    bridge.os, "access", side_effect=lambda path, mode: path == "/opt/homebrew/bin/opencli"
                ):
                    self.assertEqual(bridge.resolve_opencli_bin(), "/opt/homebrew/bin/opencli")

    def test_override_env_var_used_verbatim(self) -> None:
        with mock.patch.dict(os.environ, {"GEMINI_BRIDGE_OPENCLI_BIN": "/opt/custom/opencli"}):
            self.assertEqual(bridge.resolve_opencli_bin(), "/opt/custom/opencli")


class StatusTests(unittest.TestCase):
    def test_status_ok(self) -> None:
        runner = SequenceRunner([cp(stdout=json.dumps({"Status": "ok", "Login": True, "Url": "https://gemini.google.com/app"}))])
        result = bridge.do_status("hermes-gemini", 10, runner=runner)
        self.assertTrue(result.ok)
        self.assertEqual(result.data["Login"], True)

    def test_status_login_required(self) -> None:
        runner = SequenceRunner([cp(stdout=json.dumps({"Status": "ok", "Login": False}))])
        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge.do_status("hermes-gemini", 10, runner=runner)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.LOGIN_REQUIRED)

    def test_status_login_required_string_variant(self) -> None:
        runner = SequenceRunner([cp(stdout=json.dumps({"Login": "logged out"}))])
        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge.do_status("hermes-gemini", 10, runner=runner)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.LOGIN_REQUIRED)

    def test_status_daemon_unavailable(self) -> None:
        runner = SequenceRunner([cp(returncode=1, stderr="Failed to start opencli daemon")])
        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge.do_status("hermes-gemini", 10, runner=runner)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.DAEMON_UNAVAILABLE)

    def test_status_quota_or_challenge(self) -> None:
        runner = SequenceRunner([cp(returncode=1, stderr="Unusual traffic detected, please solve the captcha")])
        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge.do_status("hermes-gemini", 10, runner=runner)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.QUOTA_OR_CHALLENGE)

    def test_status_malformed_json_is_ui_mismatch(self) -> None:
        runner = SequenceRunner([cp(stdout="not json at all")])
        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge.do_status("hermes-gemini", 10, runner=runner)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.UI_MISMATCH)

    def test_status_empty_output_is_ui_mismatch(self) -> None:
        runner = SequenceRunner([cp(stdout="")])
        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge.do_status("hermes-gemini", 10, runner=runner)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.UI_MISMATCH)


class ReadTests(unittest.TestCase):
    def test_read_ok(self) -> None:
        turns = [{"Role": "user", "Text": "hi"}, {"Role": "model", "Text": "hello"}]
        runner = SequenceRunner([cp(stdout=json.dumps(turns))])
        result = bridge.do_read("hermes-gemini", 10, runner=runner)
        self.assertTrue(result.ok)
        self.assertEqual(result.data["turn_count"], 2)

    def test_read_wrapped_object_shape(self) -> None:
        runner = SequenceRunner([cp(stdout=json.dumps({"turns": [{"Role": "model", "Text": "hi"}]}))])
        result = bridge.do_read("hermes-gemini", 10, runner=runner)
        self.assertEqual(result.data["turn_count"], 1)

    def test_read_unexpected_shape_is_ui_mismatch(self) -> None:
        runner = SequenceRunner([cp(stdout=json.dumps({"unexpected": True}))])
        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge.do_read("hermes-gemini", 10, runner=runner)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.UI_MISMATCH)


class AskTests(unittest.TestCase):
    def test_ask_accepts_genuinely_new_response(self) -> None:
        baseline = [{"Role": "user", "Text": "marker one"}, {"Role": "model", "Text": "old reply"}]
        after = baseline + [
            {"Role": "user", "Text": "marker two"},
            {"Role": "model", "Text": "new reply"},
        ]
        runner = SequenceRunner(
            [
                cp(stdout=json.dumps(baseline)),  # baseline read
                cp(stdout=json.dumps({"response": "new reply"})),  # ask
                cp(stdout=json.dumps(after)),  # post-ask read
            ]
        )
        result = bridge.do_ask(
            "hermes-gemini", "marker two", ask_timeout=30, read_timeout=10, runner=runner
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.data["response"], "new reply")
        self.assertEqual(result.data["turn_count"], 4)

    def test_ask_rejects_stale_response_when_no_new_turn(self) -> None:
        turns = [{"Role": "user", "Text": "marker"}, {"Role": "model", "Text": "old reply"}]
        runner = SequenceRunner(
            [
                cp(stdout=json.dumps(turns)),  # baseline read
                cp(stdout=json.dumps({"response": "old reply"})),  # ask (echoes stale text)
                *[cp(stdout=json.dumps(turns)) for _ in range(40)],  # unchanged post-ask reads
            ]
        )
        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge.do_ask("hermes-gemini", "marker", ask_timeout=30, read_timeout=10, runner=runner)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.STALE_RESPONSE)

    def test_ask_accepts_nonduplicate_response_when_opencli_read_does_not_persist(self) -> None:
        turns = [{"Role": "user", "Text": "marker"}, {"Role": "model", "Text": "old reply"}]
        runner = SequenceRunner(
            [
                cp(stdout=json.dumps(turns)),
                cp(stdout=json.dumps({"response": "new reply"})),
                *[cp(stdout=json.dumps(turns)) for _ in range(40)],
            ]
        )
        result = bridge.do_ask("hermes-gemini", "marker", ask_timeout=30, read_timeout=10, runner=runner)
        self.assertTrue(result.ok)
        self.assertEqual(result.data["ownership"], "ask_response_delta")
        self.assertEqual(result.data["response"], "new reply")

        baseline = [{"Role": "user", "Text": "marker"}]
        after = baseline + [{"Role": "user", "Text": "an echoed user turn, not a reply"}]
        runner = SequenceRunner(
            [
                cp(stdout=json.dumps(baseline)),
                cp(stdout=json.dumps({"response": "whatever"})),
                cp(stdout=json.dumps(after)),
            ]
        )
        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge.do_ask("hermes-gemini", "marker", ask_timeout=30, read_timeout=10, runner=runner)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.STALE_RESPONSE)

    def test_ask_first_conversation_turn_is_not_an_error(self) -> None:
        # A brand-new conversation reads back as a valid empty JSON list --
        # a normal successful read, not a BridgeError -- so a legitimate
        # first ask must not be blocked.
        after = [{"Role": "user", "Text": "marker"}, {"Role": "model", "Text": "first reply"}]
        runner = SequenceRunner(
            [
                cp(stdout=json.dumps([])),  # baseline read: empty conversation, success
                cp(stdout=json.dumps({"response": "first reply"})),  # ask
                cp(stdout=json.dumps(after)),  # post-ask read
            ]
        )
        result = bridge.do_ask(
            "hermes-gemini", "marker", ask_timeout=30, read_timeout=10, runner=runner
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.data["response"], "first reply")

    def test_ask_propagates_baseline_read_daemon_unavailable(self) -> None:
        # OpenCLI has no documented, specific "no active conversation"
        # signal distinct from a real failure -- any baseline-read error
        # (login required, quota/challenge, daemon down, timeout, malformed
        # output, ...) must propagate rather than being swallowed into an
        # assumed-empty baseline.
        runner = SequenceRunner([cp(returncode=1, stderr="ECONNREFUSED talking to daemon")])
        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge.do_ask("hermes-gemini", "marker", ask_timeout=30, read_timeout=10, runner=runner)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.DAEMON_UNAVAILABLE)
        self.assertEqual(len(runner.calls), 1)  # ask/post-read never attempted

    def test_ask_propagates_baseline_read_login_required_style_failure(self) -> None:
        runner = SequenceRunner([cp(returncode=1, stderr="Please sign in to continue")])
        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge.do_ask("hermes-gemini", "marker", ask_timeout=30, read_timeout=10, runner=runner)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.LOGIN_REQUIRED)
        self.assertEqual(len(runner.calls), 1)

    def test_ask_propagates_baseline_read_quota_or_challenge(self) -> None:
        runner = SequenceRunner([cp(returncode=1, stderr="Too many requests, try later")])
        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge.do_ask("hermes-gemini", "marker", ask_timeout=30, read_timeout=10, runner=runner)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.QUOTA_OR_CHALLENGE)
        self.assertEqual(len(runner.calls), 1)

    def test_ask_propagates_baseline_read_timeout(self) -> None:
        def timeout_runner(args: list[str], *, timeout: float) -> subprocess.CompletedProcess:
            raise bridge.BridgeError(bridge.ErrorType.TIMEOUT, "opencli gemini read timed out after 10s")

        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge.do_ask("hermes-gemini", "marker", ask_timeout=30, read_timeout=10, runner=timeout_runner)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.TIMEOUT)

    def test_ask_propagates_baseline_read_generic_ui_mismatch(self) -> None:
        # A ui_mismatch that does NOT match the narrow no-active-conversation
        # wording (malformed JSON, unexpected shape, unrecognized error text,
        # ...) must still propagate rather than being treated as "empty".
        runner = SequenceRunner([cp(stdout="not json at all")])
        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge.do_ask("hermes-gemini", "marker", ask_timeout=30, read_timeout=10, runner=runner)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.UI_MISMATCH)
        self.assertEqual(len(runner.calls), 1)

    def test_ask_tolerates_narrowly_identified_no_active_conversation_baseline(self) -> None:
        # The one and only tolerated baseline-read failure: opencli's own
        # explicit "no active conversation" wording, which is neither a
        # daemon/login/quota condition nor a malformed-output condition --
        # it's a legitimate "nothing to read yet" signal for a brand-new
        # session.
        after = [{"Role": "user", "Text": "marker"}, {"Role": "model", "Text": "first reply"}]
        runner = SequenceRunner(
            [
                cp(returncode=1, stderr="Error: no active conversation for this session"),
                cp(stdout=json.dumps({"response": "first reply"})),  # ask
                cp(stdout=json.dumps(after)),  # post-ask read
            ]
        )
        result = bridge.do_ask(
            "hermes-gemini", "marker", ask_timeout=30, read_timeout=10, runner=runner
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.data["response"], "first reply")

    def test_ask_malformed_response_json_is_ui_mismatch(self) -> None:
        runner = SequenceRunner(
            [
                cp(stdout=json.dumps([])),
                cp(stdout=json.dumps({"unexpected": "shape"})),
                cp(stdout=json.dumps([{"Role": "model", "Text": "x"}])),
            ]
        )
        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge.do_ask("hermes-gemini", "marker", ask_timeout=30, read_timeout=10, runner=runner)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.UI_MISMATCH)


class PromptArgumentSafetyTests(unittest.TestCase):
    def test_prompt_is_a_single_argv_element(self) -> None:
        dangerous = "; rm -rf / #`whoami`$(id)"
        args = bridge._build_gemini_args("hermes-gemini", ["gemini", "ask", dangerous])
        self.assertIn(dangerous, args)
        self.assertEqual(args.count(dangerous), 1)
        # No element got shell-tokenized/split.
        for element in args:
            self.assertNotIn("\n", element if isinstance(element, str) else "")

    def test_run_opencli_never_uses_shell(self) -> None:
        dangerous = "$(rm -rf /)"
        with mock.patch.object(bridge, "resolve_opencli_bin", return_value="/usr/bin/opencli"):
            with mock.patch("subprocess.run", return_value=cp(stdout="{}")) as run_mock:
                bridge.run_opencli(["gemini", "ask", dangerous], timeout=5)
        run_mock.assert_called_once()
        called_cmd = run_mock.call_args.args[0]
        self.assertIsInstance(called_cmd, list)
        self.assertIn(dangerous, called_cmd)
        self.assertFalse(run_mock.call_args.kwargs.get("shell", False))  # shell=True never passed

    def test_run_opencli_adds_homebrew_parent_to_child_path(self) -> None:
        with mock.patch.object(bridge, "resolve_opencli_bin", return_value="/opt/homebrew/bin/opencli"):
            with mock.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=False):
                with mock.patch("subprocess.run", return_value=cp(stdout="{}")) as run_mock:
                    bridge.run_opencli(["gemini", "status"], timeout=5)
        child_path = run_mock.call_args.kwargs["env"]["PATH"]
        self.assertEqual(child_path, "/opt/homebrew/bin:/usr/bin")

        with mock.patch.object(bridge, "resolve_opencli_bin", return_value="/usr/bin/opencli"):
            with mock.patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["opencli"], timeout=5),
            ):
                with self.assertRaises(bridge.BridgeError) as ctx:
                    bridge.run_opencli(["gemini", "status"], timeout=5)
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.TIMEOUT)


class SessionLockTests(unittest.TestCase):
    def test_lock_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"GEMINI_BRIDGE_STATE_DIR": tmp}):
                with bridge.SessionLock("hermes-gemini", 2.0):
                    pass  # acquired and released cleanly

    def test_lock_contention_times_out_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"GEMINI_BRIDGE_STATE_DIR": tmp}):
                holder = bridge.SessionLock("hermes-gemini", 5.0)
                holder.__enter__()
                try:
                    started = time.monotonic()
                    with self.assertRaises(bridge.BridgeError) as ctx:
                        with bridge.SessionLock("hermes-gemini", 0.3):
                            pass
                    elapsed = time.monotonic() - started
                    self.assertEqual(ctx.exception.error_type, bridge.ErrorType.LOCK_BUSY)
                    self.assertLess(elapsed, 2.0)  # bounded, not a hang
                finally:
                    holder.__exit__(None, None, None)

    def test_concurrent_askers_serialize_not_interleave(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"GEMINI_BRIDGE_STATE_DIR": tmp}):
                events: list[str] = []
                lock_obj = threading.Lock()

                def worker(label: str) -> None:
                    with bridge.SessionLock("hermes-gemini", 5.0):
                        with lock_obj:
                            events.append(f"{label}-start")
                        time.sleep(0.05)
                        with lock_obj:
                            events.append(f"{label}-end")

                threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(3)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=5)

                # Each thread's start must be immediately followed by its own
                # end -- no interleaving of two holders inside the lock.
                for i in range(0, len(events), 2):
                    label = events[i].rsplit("-", 1)[0]
                    self.assertEqual(events[i + 1], f"{label}-end")


class AuditEntryTests(unittest.TestCase):
    def test_audit_entry_omits_content_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"GEMINI_BRIDGE_STATE_DIR": tmp}, clear=False):
                os.environ.pop("GEMINI_BRIDGE_CAPTURE_CONTENT", None)
                result = bridge.BridgeResult(
                    ok=True, command="ask", data={"response": "a private reply"}, latency_ms=12
                )
                bridge._write_audit_entry("hermes-gemini", result)
                audit_path = Path(tmp) / "audit.jsonl"
                entry = json.loads(audit_path.read_text().strip().splitlines()[-1])
                self.assertNotIn("response_preview", entry)
                self.assertIn("response_sha256", entry)
                self.assertEqual(entry["response_size"], len("a private reply"))
                self.assertNotIn("a private reply", json.dumps(entry))

    def test_audit_entry_includes_bounded_preview_when_opted_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ, {"GEMINI_BRIDGE_STATE_DIR": tmp, "GEMINI_BRIDGE_CAPTURE_CONTENT": "1"}
            ):
                result = bridge.BridgeResult(
                    ok=True, command="ask", data={"response": "x" * 5000}, latency_ms=1
                )
                bridge._write_audit_entry("hermes-gemini", result)
                audit_path = Path(tmp) / "audit.jsonl"
                entry = json.loads(audit_path.read_text().strip().splitlines()[-1])
                self.assertEqual(len(entry["response_preview"]), bridge.DEFAULT_CAPTURE_PREVIEW_CHARS)

    def test_audit_entry_respects_configured_preview_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ,
                {
                    "GEMINI_BRIDGE_STATE_DIR": tmp,
                    "GEMINI_BRIDGE_CAPTURE_CONTENT": "1",
                    "GEMINI_BRIDGE_CAPTURE_CONTENT_MAX_CHARS": "10",
                },
            ):
                result = bridge.BridgeResult(
                    ok=True, command="ask", data={"response": "x" * 5000}, latency_ms=1
                )
                bridge._write_audit_entry("hermes-gemini", result)
                audit_path = Path(tmp) / "audit.jsonl"
                entry = json.loads(audit_path.read_text().strip().splitlines()[-1])
                self.assertEqual(len(entry["response_preview"]), 10)

    def test_audit_entry_never_captures_prompt_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ, {"GEMINI_BRIDGE_STATE_DIR": tmp, "GEMINI_BRIDGE_CAPTURE_CONTENT": "1"}
            ):
                result = bridge.BridgeResult(
                    ok=True,
                    command="ask",
                    data={"response": "reply text", "prompt": "the secret prompt text"},
                    latency_ms=1,
                )
                bridge._write_audit_entry("hermes-gemini", result)
                audit_path = Path(tmp) / "audit.jsonl"
                entry = json.loads(audit_path.read_text().strip().splitlines()[-1])
                self.assertNotIn("prompt", entry)
                self.assertNotIn("the secret prompt text", json.dumps(entry))


class CaptureConfigTests(unittest.TestCase):
    def test_disabled_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(bridge.CAPTURE_CONTENT_ENV, None)
            os.environ.pop(bridge.CAPTURE_CONTENT_MAX_CHARS_ENV, None)
            self.assertIsNone(bridge._resolve_capture_max_chars())

    def test_opted_in_default_size(self) -> None:
        with mock.patch.dict(os.environ, {bridge.CAPTURE_CONTENT_ENV: "1"}, clear=False):
            os.environ.pop(bridge.CAPTURE_CONTENT_MAX_CHARS_ENV, None)
            self.assertEqual(bridge._resolve_capture_max_chars(), bridge.DEFAULT_CAPTURE_PREVIEW_CHARS)

    def test_opted_in_custom_size_within_hard_cap(self) -> None:
        with mock.patch.dict(
            os.environ,
            {bridge.CAPTURE_CONTENT_ENV: "1", bridge.CAPTURE_CONTENT_MAX_CHARS_ENV: "1024"},
        ):
            self.assertEqual(bridge._resolve_capture_max_chars(), 1024)

    def test_rejects_non_integer_value(self) -> None:
        with mock.patch.dict(
            os.environ,
            {bridge.CAPTURE_CONTENT_ENV: "1", bridge.CAPTURE_CONTENT_MAX_CHARS_ENV: "not-a-number"},
        ):
            with self.assertRaises(bridge.CaptureConfigError):
                bridge._resolve_capture_max_chars()

    def test_rejects_zero_or_negative_value(self) -> None:
        with mock.patch.dict(
            os.environ, {bridge.CAPTURE_CONTENT_ENV: "1", bridge.CAPTURE_CONTENT_MAX_CHARS_ENV: "0"}
        ):
            with self.assertRaises(bridge.CaptureConfigError):
                bridge._resolve_capture_max_chars()

    def test_rejects_value_above_hard_cap(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                bridge.CAPTURE_CONTENT_ENV: "1",
                bridge.CAPTURE_CONTENT_MAX_CHARS_ENV: str(bridge.HARD_MAX_CAPTURE_CHARS + 1),
            },
        ):
            with self.assertRaises(bridge.CaptureConfigError):
                bridge._resolve_capture_max_chars()

    def test_hard_cap_boundary_is_accepted(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                bridge.CAPTURE_CONTENT_ENV: "1",
                bridge.CAPTURE_CONTENT_MAX_CHARS_ENV: str(bridge.HARD_MAX_CAPTURE_CHARS),
            },
        ):
            self.assertEqual(bridge._resolve_capture_max_chars(), bridge.HARD_MAX_CAPTURE_CHARS)

    def test_invalid_config_falls_back_to_metadata_only_not_a_crash(self) -> None:
        # An operator misconfiguration must degrade this best-effort audit
        # log gracefully -- it must never break the primary status/read/ask
        # call, and must never fall back to unbounded/unvalidated capture.
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ,
                {
                    "GEMINI_BRIDGE_STATE_DIR": tmp,
                    bridge.CAPTURE_CONTENT_ENV: "1",
                    bridge.CAPTURE_CONTENT_MAX_CHARS_ENV: "99999999",
                },
            ):
                result = bridge.BridgeResult(
                    ok=True, command="ask", data={"response": "x" * 100}, latency_ms=1
                )
                bridge._write_audit_entry("hermes-gemini", result)  # must not raise
                audit_path = Path(tmp) / "audit.jsonl"
                entry = json.loads(audit_path.read_text().strip().splitlines()[-1])
                self.assertNotIn("response_preview", entry)
                self.assertIn("response_sha256", entry)


class ExtractHelpersTests(unittest.TestCase):
    def test_extract_ask_response_string_shape(self) -> None:
        self.assertEqual(bridge._extract_ask_response("plain text reply"), "plain text reply")

    def test_extract_ask_response_list_shape_from_opencli_1_8_6(self) -> None:
        self.assertEqual(bridge._extract_ask_response([{"response": "PONG"}]), "PONG")

        with self.assertRaises(bridge.BridgeError) as ctx:
            bridge._extract_ask_response({"nope": "nothing useful"})
        self.assertEqual(ctx.exception.error_type, bridge.ErrorType.UI_MISMATCH)


if __name__ == "__main__":
    unittest.main()
