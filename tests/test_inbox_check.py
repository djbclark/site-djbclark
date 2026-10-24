from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import textwrap
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

# bin/inbox-check has no .py suffix, so it can't be `import`ed normally;
# load it by path like the other no-extension bin/ scripts' tests do
# (mirrors tests/test_inbox_target.py).
SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "inbox-check"
_loader = SourceFileLoader("inbox_check", str(SCRIPT))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
assert _spec is not None
inbox_check = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = inbox_check
_loader.exec_module(inbox_check)


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

    [retired.99]
    was = "Inbox"
    retired = "2026-10-23"
    split_into = ["pings", "watch", "triage"]

    [routes]
    "hermes-ping" = "pings"

    [cron.routes]

    [cron]
    unmanaged = {}

    [config_yaml]
    extra_ignored_threads = []
    """
)

FIXTURE_CONFIG_CLEAN = textwrap.dedent(
    """\
    platforms:
      telegram:
        channel_overrides:
          '30':
            provider: goose-scout
        extra:
          ignored_threads:
            - 10
            - 20
    """
)


def _write_fixture(tmp: Path, toml_text: str = FIXTURE_TOML, config_text: str = FIXTURE_CONFIG_CLEAN) -> tuple[Path, Path]:
    register_path = tmp / "telegram-inbox.toml"
    config_path = tmp / "config.yaml"
    register_path.write_text(toml_text)
    config_path.write_text(config_text)
    return register_path, config_path


def _run_config(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = inbox_check.cmd_config(argv)
    return rc, out.getvalue(), err.getvalue()


def _run_cron(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = inbox_check.cmd_cron(argv)
    return rc, out.getvalue(), err.getvalue()


class ConfigCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_ctx = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp_ctx.name)
        self.addCleanup(self._tmp_ctx.cleanup)

    def test_clean_pass(self) -> None:
        register_path, config_path = _write_fixture(self.tmp)
        rc, out, err = _run_config(["--register", str(register_path), "--config", str(config_path)])
        self.assertEqual(rc, 0, msg=out + err)
        self.assertIn("OK", out)

    def test_sink_not_ignored_drift(self) -> None:
        config_text = textwrap.dedent(
            """\
            platforms:
              telegram:
                channel_overrides:
                  '30':
                    provider: goose-scout
                extra:
                  ignored_threads:
                    - 10
            """
        )
        register_path, config_path = _write_fixture(self.tmp, config_text=config_text)
        rc, out, _err = _run_config(["--register", str(register_path), "--config", str(config_path)])
        self.assertEqual(rc, 1)
        self.assertIn("watch", out)
        self.assertIn("ignored_threads", out)

    def test_bound_missing_override_drift(self) -> None:
        config_text = textwrap.dedent(
            """\
            platforms:
              telegram:
                channel_overrides: {}
                extra:
                  ignored_threads:
                    - 10
                    - 20
            """
        )
        register_path, config_path = _write_fixture(self.tmp, config_text=config_text)
        rc, out, _err = _run_config(["--register", str(register_path), "--config", str(config_path)])
        self.assertEqual(rc, 1)
        self.assertIn("triage", out)
        self.assertIn("channel_overrides", out)

    def test_bound_override_mismatched_provider_drift(self) -> None:
        config_text = textwrap.dedent(
            """\
            platforms:
              telegram:
                channel_overrides:
                  '30':
                    provider: some-other-agent
                extra:
                  ignored_threads:
                    - 10
                    - 20
            """
        )
        register_path, config_path = _write_fixture(self.tmp, config_text=config_text)
        rc, out, _err = _run_config(["--register", str(register_path), "--config", str(config_path)])
        self.assertEqual(rc, 1)
        self.assertIn("goose-scout", out)

    def test_retired_thread_as_live_route_drift(self) -> None:
        config_text = textwrap.dedent(
            """\
            platforms:
              telegram:
                channel_overrides:
                  '30':
                    provider: goose-scout
                  '99':
                    provider: some-agent
                extra:
                  ignored_threads:
                    - 10
                    - 20
            """
        )
        register_path, config_path = _write_fixture(self.tmp, config_text=config_text)
        rc, out, _err = _run_config(["--register", str(register_path), "--config", str(config_path)])
        self.assertEqual(rc, 1)
        self.assertIn("retired", out)
        self.assertIn("99", out)

    def test_unparsable_yaml_exit2(self) -> None:
        register_path, config_path = _write_fixture(self.tmp)
        config_path.write_text("not: valid: yaml: [")
        rc, _out, err = _run_config(["--register", str(register_path), "--config", str(config_path)])
        self.assertEqual(rc, 2)
        self.assertIn("FAIL", err)

    def test_missing_register_exit2(self) -> None:
        _register_path, config_path = _write_fixture(self.tmp)
        rc, _out, err = _run_config(["--register", str(self.tmp / "nope.toml"), "--config", str(config_path)])
        self.assertEqual(rc, 2)
        self.assertIn("FAIL", err)


class CronCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_ctx = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp_ctx.name)
        self.addCleanup(self._tmp_ctx.cleanup)
        self.register_path = self.tmp / "telegram-inbox.toml"
        self.register_path.write_text(FIXTURE_TOML)

    def _write_jobs(self, jobs: list[dict]) -> Path:
        jobs_path = self.tmp / "jobs.json"
        jobs_path.write_text(json.dumps({"jobs": jobs, "updated_at": "2026-10-24T00:00:00"}))
        return jobs_path

    def test_known_destinations_and_local_origin_ok(self) -> None:
        jobs_path = self._write_jobs(
            [
                {"id": "a1", "name": "Pings job", "deliver": "telegram:111:10"},
                {"id": "a2", "name": "Local job", "deliver": "local"},
                {"id": "a3", "name": "Origin job", "deliver": "origin"},
            ]
        )
        rc, out, _err = _run_cron(["--jobs", str(jobs_path), "--register", str(self.register_path)])
        self.assertEqual(rc, 0, msg=out)
        self.assertIn("OK (pings)", out)
        self.assertIn("OK (local)", out)

    def test_retired_id_delivery_is_error(self) -> None:
        jobs_path = self._write_jobs(
            [{"id": "a1", "name": "Stale job", "deliver": "telegram:111:99"}]
        )
        rc, out, _err = _run_cron(["--jobs", str(jobs_path), "--register", str(self.register_path)])
        self.assertEqual(rc, 1)
        self.assertIn("retired", out)
        self.assertIn("ERROR", out)

    def test_bare_telegram_warns_but_does_not_fail(self) -> None:
        jobs_path = self._write_jobs(
            [{"id": "a1", "name": "Home channel job", "deliver": "telegram"}]
        )
        rc, out, _err = _run_cron(["--jobs", str(jobs_path), "--register", str(self.register_path)])
        self.assertEqual(rc, 0, msg=out)
        self.assertIn("WARN", out)
        self.assertIn("unmanaged home-channel delivery", out)

    def test_unparsable_json_exit2(self) -> None:
        jobs_path = self.tmp / "jobs.json"
        jobs_path.write_text("{not valid json")
        rc, _out, err = _run_cron(["--jobs", str(jobs_path), "--register", str(self.register_path)])
        self.assertEqual(rc, 2)
        self.assertIn("FAIL", err)


if __name__ == "__main__":
    unittest.main()
