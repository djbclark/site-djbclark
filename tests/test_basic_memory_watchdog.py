from __future__ import annotations

import importlib.util
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "basic_memory_watchdog.py"
SPEC = importlib.util.spec_from_file_location("basic_memory_watchdog", SCRIPT)
assert SPEC and SPEC.loader
watchdog = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = watchdog
SPEC.loader.exec_module(watchdog)


class HealthCheckTests(unittest.TestCase):
    def test_socket_timeout_is_reported_as_slow_not_crash(self) -> None:
        with (
            mock.patch.object(
                watchdog.urllib.request,
                "urlopen",
                side_effect=socket.timeout("timed out"),
            ),
            mock.patch.object(watchdog, "log") as log,
        ):
            self.assertEqual(watchdog.health_check(), "slow")

        log.assert_called_once()

    def test_connection_refused_is_down(self) -> None:
        refused = watchdog.urllib.error.URLError(
            ConnectionRefusedError(61, "Connection refused")
        )
        with (
            mock.patch.object(watchdog.urllib.request, "urlopen", side_effect=refused),
            mock.patch.object(watchdog, "log"),
        ):
            self.assertEqual(watchdog.health_check(), "down")


class SlowServerTests(unittest.TestCase):
    def _run(self, state: dict) -> mock.MagicMock:
        with (
            mock.patch.object(watchdog, "load_state", return_value=state),
            mock.patch.object(watchdog, "health_check", return_value="slow"),
            mock.patch.object(watchdog.time, "time", return_value=1000),
            mock.patch.object(watchdog, "restart_service") as restart,
            mock.patch.object(watchdog, "save_state"),
            mock.patch.object(watchdog, "notify"),
            mock.patch.object(watchdog, "log"),
        ):
            watchdog.main()
        return restart

    def test_slow_check_below_threshold_does_not_restart(self) -> None:
        state = {
            "status": "healthy",
            "consecutive_failures": 0,
            "attempts_since_healthy": 0,
        }
        restart = self._run(state)
        restart.assert_not_called()
        self.assertEqual(state["consecutive_slow"], 1)
        self.assertEqual(state["status"], "healthy")

    def test_slow_checks_at_threshold_restart(self) -> None:
        state = {
            "status": "healthy",
            "consecutive_failures": 0,
            "attempts_since_healthy": 0,
            "consecutive_slow": watchdog.SLOW_CHECKS_BEFORE_RESTART - 1,
        }
        restart = self._run(state)
        restart.assert_called_once()
        self.assertEqual(state["consecutive_slow"], 0)


class StartupGraceTests(unittest.TestCase):
    def test_failed_check_during_startup_grace_does_not_restart_again(self) -> None:
        state = {
            "status": "down",
            "consecutive_failures": 1,
            "attempts_since_healthy": 1,
            "last_restart_at": 100,
        }
        with (
            mock.patch.object(watchdog, "load_state", return_value=state),
            mock.patch.object(watchdog, "health_check", return_value="down"),
            mock.patch.object(watchdog.time, "time", return_value=200),
            mock.patch.object(watchdog, "restart_service") as restart,
            mock.patch.object(watchdog, "save_state") as save_state,
            mock.patch.object(watchdog, "log"),
        ):
            watchdog.main()

        restart.assert_not_called()
        save_state.assert_not_called()
        self.assertEqual(state["attempts_since_healthy"], 1)

    def test_failed_check_after_startup_grace_restarts_and_records_time(self) -> None:
        state = {
            "status": "down",
            "consecutive_failures": 1,
            "attempts_since_healthy": 1,
            "last_restart_at": 100,
        }
        with (
            mock.patch.object(watchdog, "load_state", return_value=state),
            mock.patch.object(watchdog, "health_check", return_value="down"),
            mock.patch.object(watchdog.time, "time", return_value=401),
            mock.patch.object(watchdog, "restart_service") as restart,
            mock.patch.object(watchdog, "save_state") as save_state,
            mock.patch.object(watchdog, "log"),
        ):
            watchdog.main()

        restart.assert_called_once()
        save_state.assert_called_once_with(state)
        self.assertEqual(state["attempts_since_healthy"], 2)
        self.assertEqual(state["last_restart_at"], 401)


if __name__ == "__main__":
    unittest.main()
