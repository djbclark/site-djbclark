from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import textwrap
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

# bin/inbox-target has no .py suffix, so it can't be `import`ed normally;
# load it by path like the other no-extension bin/ scripts' tests do.
SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "inbox-target"
_loader = SourceFileLoader("inbox_target", str(SCRIPT))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
assert _spec is not None
inbox_target = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = inbox_target
_loader.exec_module(inbox_target)


FIXTURE_TOML = textwrap.dedent(
    """\
    schema_version = 1
    default = "pings"

    [chats.dan]
    platform = "telegram"
    chat_id = 111

    [destinations.pings]
    chat = "dan"
    thread_id = 10
    mode = "sink"
    purpose = "pings purpose"

    [destinations.watch]
    chat = "dan"
    thread_id = 20
    mode = "sink"
    purpose = "watch purpose"

    [destinations.triage]
    chat = "dan"
    thread_id = 30
    mode = "bound"
    bound_to = "goose-scout"
    purpose = "triage purpose"

    [routes]
    "hermes-ping" = "pings"
    "basic-memory-watchdog" = "watch"

    [cron.routes]

    [cron]
    unmanaged = {}

    [config_yaml]
    extra_ignored_threads = []
    """
)


class ResolveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = inbox_target.tomllib.loads(FIXTURE_TOML)

    def test_route_resolves_through_destination(self) -> None:
        self.assertEqual(
            inbox_target.resolve_name(self.data, "hermes-ping"),
            (111, 10, "pings"),
        )

    def test_destination_name_resolves_directly(self) -> None:
        self.assertEqual(
            inbox_target.resolve_name(self.data, "watch"),
            (111, 20, "watch"),
        )

    def test_unknown_name_returns_none(self) -> None:
        self.assertIsNone(inbox_target.resolve_name(self.data, "nope"))

    def test_resolve_default(self) -> None:
        self.assertEqual(inbox_target.resolve_default(self.data), (111, 10, "pings"))

    def test_target_string_format(self) -> None:
        self.assertEqual(inbox_target.target_string(111, 10), "telegram:111:10")

    def test_env_key_sanitizes_dots_and_dashes(self) -> None:
        self.assertEqual(inbox_target.env_key("stayturgid.control"), "STAYTURGID_CONTROL")
        self.assertEqual(inbox_target.env_key("hermes-ping"), "HERMES_PING")


class FixtureRepoTests(unittest.TestCase):
    """Hermetic CLI-level tests against a small fixture register, isolated
    from the real registry/telegram-inbox.{toml,env} via patched module paths."""

    def setUp(self) -> None:
        self._tmp_ctx = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp_ctx.name)
        self.toml_path = tmp / "telegram-inbox.toml"
        self.env_path = tmp / "telegram-inbox.env"
        self.toml_path.write_text(FIXTURE_TOML)
        self._patchers = [
            mock.patch.object(inbox_target, "TOML_PATH", self.toml_path),
            mock.patch.object(inbox_target, "ENV_PATH", self.env_path),
        ]
        for p in self._patchers:
            p.start()
        self.addCleanup(self._tmp_ctx.cleanup)
        for p in self._patchers:
            self.addCleanup(p.stop)

    def _cmd_resolve(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = inbox_target.cmd_resolve(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_known_route_resolves_exit0(self) -> None:
        rc, out, err = self._cmd_resolve(["hermes-ping"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "telegram:111:10")
        self.assertEqual(err, "")

    def test_unknown_name_falls_back_to_default_exit0(self) -> None:
        rc, out, err = self._cmd_resolve(["nope"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "telegram:111:10")  # INBOX_DEFAULT = pings
        self.assertIn("WARN", err)
        self.assertIn("nope", err)

    def test_unknown_name_strict_exit1(self) -> None:
        rc, out, err = self._cmd_resolve(["nope", "--strict"])
        self.assertEqual(rc, 1)
        self.assertIn("FAIL", err)

    def test_field_thread(self) -> None:
        rc, out, _err = self._cmd_resolve(["hermes-ping", "--field", "thread"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "10")

    def test_field_chat(self) -> None:
        rc, out, _err = self._cmd_resolve(["hermes-ping", "--field", "chat"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "111")

    def test_export_writes_contract_shaped_env(self) -> None:
        rc = inbox_target.cmd_export([])
        self.assertEqual(rc, 0)
        text = self.env_path.read_text()
        self.assertIn("INBOX_SCHEMA=1\n", text)
        self.assertIn("INBOX_CHAT_ID=111\n", text)
        self.assertIn("INBOX_DEFAULT=telegram:111:10\n", text)
        self.assertIn("INBOX_DEST_PINGS=telegram:111:10\n", text)
        self.assertIn("INBOX_DEST_PINGS_THREAD=10\n", text)
        self.assertIn("INBOX_ROUTE_HERMES_PING=telegram:111:10\n", text)
        self.assertIn("INBOX_ROUTE_HERMES_PING_CHAT=111\n", text)
        self.assertIn("INBOX_ROUTE_HERMES_PING_THREAD=10\n", text)
        self.assertIn("INBOX_ROUTE_BASIC_MEMORY_WATCHDOG=telegram:111:20\n", text)
        # sorted, unquoted, no spaces
        for line in text.splitlines():
            if line.startswith("#"):
                continue
            self.assertNotIn(" ", line)
            self.assertNotIn('"', line)

    def test_export_check_passes_after_export(self) -> None:
        self.assertEqual(inbox_target.cmd_export([]), 0)
        self.assertEqual(inbox_target.cmd_export(["--check"]), 0)

    def test_export_check_fails_when_stale(self) -> None:
        self.env_path.write_text("stale content\n")
        self.assertEqual(inbox_target.cmd_export(["--check"]), 1)

    def test_export_check_fails_when_missing(self) -> None:
        self.assertFalse(self.env_path.exists())
        self.assertEqual(inbox_target.cmd_export(["--check"]), 1)

    def test_export_shell_writes_nothing(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = inbox_target.cmd_export(["--shell"])
        self.assertEqual(rc, 0)
        self.assertFalse(self.env_path.exists())
        self.assertIn("export INBOX_SCHEMA=1", out.getvalue())
        self.assertIn("export INBOX_ROUTE_HERMES_PING=telegram:111:10", out.getvalue())

    def test_list_includes_name_thread_mode_purpose_routes(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = inbox_target.cmd_list([])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("NAME", text)
        self.assertIn("THREAD", text)
        self.assertIn("MODE", text)
        self.assertIn("PURPOSE", text)
        self.assertIn("ROUTES", text)
        self.assertIn("pings", text)
        self.assertIn("hermes-ping", text)  # pings' route shows up in its row


class GateTests(unittest.TestCase):
    """site-djbclark#inbox-split S1 gate (central-register-design-report.md
    section 0 item 3): every sender's route must resolve to today's literal
    target against the real, committed registry/telegram-inbox.toml."""

    GATE: dict[str, tuple[int, int]] = {
        "hermes-ping": (838808636, 44130),
        "fleet-watch": (838808636, 44130),
        "basic-memory-watchdog": (838808636, 44132),
        "hibernate-disk-check": (838808636, 44132),
        "jobber-notify": (838808636, 44130),
        "stayturgid.control": (838808636, 44132),
        "stayturgid.apk-updates": (838808636, 44130),
        "gha.herdr-extension-releases": (838808636, 44130),
        "gha.thaw-next-access-request": (838808636, 44130),
        "gha.nixos-lock-update": (838808636, 44130),
        "gha.track-issue-activity": (838808636, 44130),
    }

    def test_every_route_matches_todays_literal(self) -> None:
        data = inbox_target.load_register()
        for name, (chat, thread) in self.GATE.items():
            with self.subTest(name=name):
                resolved = inbox_target.resolve_name(data, name)
                self.assertIsNotNone(resolved, f"{name!r} has no route or destination")
                chat_id, thread_id, _dest_name = resolved  # type: ignore[misc]
                self.assertEqual((chat_id, thread_id), (chat, thread))


if __name__ == "__main__":
    unittest.main()
