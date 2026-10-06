"""bin/watchdogd.py: decision logic against fakes. No live service is touched.

The HTTP and UNIX-socket probe tests run tiny local servers on ephemeral
ports; everything else drives `decide` / `Runner` with a fake System.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import re
import signal
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import tomllib

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "watchdogd", REPO / "bin" / "watchdogd.py"
)
assert SPEC and SPEC.loader
wd = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wd
SPEC.loader.exec_module(wd)

NOW = 1_000_000.0
CALM = {"stressed": False, "why": ""}
STRESSED = {"stressed": True, "why": "load/cpu 9.0 > 3"}


def svc(**kw) -> wd.ServiceCfg:
    base = {
        "name": "svc",
        "label": "com.test.svc",
        "port": 4000,
        "slow_before_action": 3,
        "down_before_action": 2,
        "grace_s": 900,
        "max_restarts": 3,
        "healthy_reset_s": 21600,
        "renotify_s": 21600,
    }
    base.update(kw)
    return wd.ServiceCfg(**base)


def obs(status="ok", detail="", now=NOW, stress=CALM, age=5000.0, **kw) -> wd.Obs:
    o = wd.Obs(now=now, stress=stress, loaded=True, lpid=100, instance_age=age)
    o.port_holders = [101]
    o.probe = None if status is None else wd.ProbeResult(status, detail or status)
    for k, v in kw.items():
        setattr(o, k, v)
    return o


def kinds(d: wd.Decision) -> list[str]:
    return [a.kind for a in d.actions]


class SlowVersusDownTests(unittest.TestCase):
    """basic-memory semantics: 5 slow in a row, or 1 refused, restarts."""

    def setUp(self) -> None:
        self.cfg = svc(slow_before_action=5, down_before_action=1, grace_s=300)
        self.st = wd.fresh_state()

    def test_four_slow_wait_fifth_restarts(self) -> None:
        for i in range(4):
            d = wd.decide(self.cfg, self.st, obs("slow", now=NOW + i * 120))
            self.assertEqual(kinds(d), [], d.verdict)
            self.assertIn("waiting", d.verdict)
        d = wd.decide(self.cfg, self.st, obs("slow", now=NOW + 480))
        self.assertEqual(kinds(d), ["kickstart"], d.verdict)
        self.assertEqual(self.st["consecutive_slow"], 0)

    def test_refused_restarts_immediately(self) -> None:
        d = wd.decide(self.cfg, self.st, obs("down", "connection refused"))
        self.assertEqual(kinds(d), ["kickstart"])
        self.assertTrue(any("DOWN" in a for a in d.alerts))

    def test_ok_resets_the_slow_run(self) -> None:
        for i in range(4):
            wd.decide(self.cfg, self.st, obs("slow", now=NOW + i))
        wd.decide(self.cfg, self.st, obs("ok", now=NOW + 5))
        self.assertEqual(self.st["consecutive_slow"], 0)
        d = wd.decide(self.cfg, self.st, obs("slow", now=NOW + 6))
        self.assertEqual(kinds(d), [])

    def test_slow_does_not_count_toward_down(self) -> None:
        cfg = svc(slow_before_action=3, down_before_action=2)
        st = wd.fresh_state()
        wd.decide(cfg, st, obs("slow"))
        d = wd.decide(cfg, st, obs("down", now=NOW + 1))
        self.assertEqual(
            kinds(d), [], "1 slow + 1 down must not reach either threshold"
        )


class GraceTests(unittest.TestCase):
    def test_young_instance_is_not_restarted(self) -> None:
        cfg, st = svc(down_before_action=1), wd.fresh_state()
        d = wd.decide(cfg, st, obs("down", age=120))
        self.assertEqual(kinds(d), [])
        self.assertIn("WAIT", d.verdict)
        d = wd.decide(cfg, st, obs("down", age=901, now=NOW + 800))
        self.assertEqual(kinds(d), ["kickstart"])

    def test_grace_counts_from_our_last_action_when_launchd_has_no_pid(self) -> None:
        cfg, st = svc(down_before_action=1), wd.fresh_state()
        st["last_action_at"] = NOW - 60
        d = wd.decide(cfg, st, obs("down", age=None, lpid=None, port_holders=[]))
        self.assertEqual(kinds(d), [])
        d = wd.decide(
            cfg, st, obs("down", age=None, lpid=None, port_holders=[], now=NOW + 900)
        )
        self.assertEqual(kinds(d), ["kickstart"])

    def test_orphan_is_killed_even_in_grace_and_under_stress(self) -> None:
        cfg, st = svc(), wd.fresh_state()
        orphan = wd.Proc(555, 1, 30, "litellm --port 4000")
        d = wd.decide(cfg, st, obs("down", age=10, stress=STRESSED, orphans=[orphan]))
        self.assertEqual([(a.kind, a.pid) for a in d.actions], [("kill", 555)])
        self.assertIn("ORPHAN", d.actions[0].alert)


class StressTests(unittest.TestCase):
    def test_restart_is_deferred_under_stress_then_happens(self) -> None:
        cfg, st = svc(down_before_action=1), wd.fresh_state()
        d = wd.decide(cfg, st, obs("down", stress=STRESSED))
        self.assertEqual(kinds(d), [])
        self.assertIn("DEFER", d.verdict)
        self.assertEqual(len(d.alerts), 1, "one DOWN alert, saying it is deferred")
        self.assertIn("deferred", d.alerts[0])
        d = wd.decide(cfg, st, obs("down", stress=STRESSED, now=NOW + 60))
        self.assertEqual(
            (kinds(d), d.alerts), ([], []), "no repeat alert while deferred"
        )
        d = wd.decide(cfg, st, obs("down", now=NOW + 120))
        self.assertEqual(kinds(d), ["kickstart"])

    def test_strays_are_killed_under_stress(self) -> None:
        cfg, st = svc(), wd.fresh_state()
        stray = wd.Proc(777, 1, 99, "litellm")
        d = wd.decide(cfg, st, obs("ok", stress=STRESSED, strays=[stray]))
        self.assertEqual([(a.kind, a.pid) for a in d.actions], [("kill", 777)])

    def test_assess_stress_thresholds(self) -> None:
        g = wd.GlobalCfg(load_per_cpu=3, swap_percent=70, memory_pressure_level=0)
        self.assertFalse(wd.assess_stress(g, 2.9, 69, 4)["stressed"])
        self.assertTrue(wd.assess_stress(g, 3.1, 0, 1)["stressed"])
        self.assertTrue(wd.assess_stress(g, 0.1, 71, 1)["stressed"])
        g.swap_percent = 0
        self.assertFalse(wd.assess_stress(g, 0.1, 99, 1)["stressed"], "0 disables swap")
        g.memory_pressure_level = 2
        self.assertTrue(wd.assess_stress(g, 0.1, 0, 2)["stressed"])


class BudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = svc(down_before_action=1, grace_s=60)
        self.st = wd.fresh_state()
        self.t = NOW

    def step(self, status: str, dt: float = 120) -> wd.Decision:
        self.t += dt
        return wd.decide(self.cfg, self.st, obs(status, now=self.t))

    def test_budget_exhausts_and_alerts_once(self) -> None:
        restarts = sum(kinds(self.step("down")) == ["kickstart"] for _ in range(3))
        self.assertEqual(restarts, 3)
        d = self.step("down")
        self.assertEqual(kinds(d), [])
        self.assertIn("BUDGET EXHAUSTED", d.verdict)
        self.assertEqual(sum("BUDGET EXHAUSTED" in a for a in d.alerts), 1)
        d = self.step("down")
        self.assertEqual(d.alerts, [], "exhaustion is not re-alerted every run")
        d = self.step("down", dt=21600)
        self.assertEqual(sum("BUDGET EXHAUSTED" in a for a in d.alerts), 1, "renotify")

    def test_one_clean_run_does_not_reset_the_budget(self) -> None:
        for _ in range(3):
            self.step("down")
        self.step("ok")
        d = self.step("down")
        self.assertEqual(kinds(d), [], "one healthy probe must not give restarts back")
        self.assertIn("BUDGET EXHAUSTED", d.verdict)

    def test_budget_resets_after_a_long_healthy_stretch(self) -> None:
        for _ in range(3):
            self.step("down")
        self.step("ok")
        self.step("ok", dt=6 * 3600)
        self.assertEqual(self.st["restarts"], [])
        d = self.step("down")
        self.assertEqual(kinds(d), ["kickstart"])

    def test_a_slow_probe_breaks_the_healthy_stretch(self) -> None:
        for _ in range(3):
            self.step("down")
        self.step("ok")
        self.step("slow", dt=3 * 3600)
        self.step("ok", dt=60)
        self.step("ok", dt=3 * 3600)
        self.assertEqual(
            len(self.st["restarts"]), 3, "the stretch restarted at the slow probe"
        )


class VerificationTests(unittest.TestCase):
    def test_restart_is_pending_until_the_probe_passes(self) -> None:
        cfg, st = svc(down_before_action=1, grace_s=300), wd.fresh_state()
        d = wd.decide(cfg, st, obs("down"))
        self.assertEqual(kinds(d), ["kickstart"])
        self.assertIsNotNone(st["pending"])
        d = wd.decide(cfg, st, obs("ok", now=NOW + 120))
        self.assertIsNone(st["pending"])
        self.assertTrue(any("RECOVERED" in a for a in d.alerts))
        self.assertTrue(any("verified" in n for n in d.notes))

    def test_still_failing_after_grace_is_unverified_once(self) -> None:
        cfg, st = (
            svc(down_before_action=1, grace_s=300, max_restarts=1),
            wd.fresh_state(),
        )
        wd.decide(cfg, st, obs("down"))
        d = wd.decide(cfg, st, obs("down", now=NOW + 120, age=100))
        self.assertFalse(any("UNVERIFIED" in a for a in d.alerts), "still within grace")
        d = wd.decide(cfg, st, obs("down", now=NOW + 301, age=301))
        self.assertEqual(sum("UNVERIFIED" in a for a in d.alerts), 1)
        d = wd.decide(cfg, st, obs("down", now=NOW + 420, age=420))
        self.assertFalse(any("UNVERIFIED" in a for a in d.alerts))

    def test_kickstart_exit_zero_is_not_success(self) -> None:
        """A restart counts only when the probe passes, not when launchctl says 0."""
        cfg, st = svc(down_before_action=1, grace_s=60), wd.fresh_state()
        wd.decide(cfg, st, obs("down"))
        self.assertEqual(st["health"], "down")
        self.assertIsNotNone(st["pending"])


class StallTests(unittest.TestCase):
    def test_stall_signature_alone_never_restarts(self) -> None:
        cfg, st = svc(down_before_action=1), wd.fresh_state()
        hits = ["Prisma DB reconnect failed (5 consecutive)"]
        d = wd.decide(cfg, st, obs("ok", stall_hits=hits))
        self.assertEqual(kinds(d), [])
        self.assertTrue(any("ignored" in n for n in d.notes))

    def test_stall_with_a_slow_probe_counts_as_down(self) -> None:
        cfg, st = svc(slow_before_action=3, down_before_action=1), wd.fresh_state()
        hits = ["Prisma DB reconnect failed (3 consecutive)"]
        d = wd.decide(cfg, st, obs("slow", stall_hits=hits))
        self.assertEqual(kinds(d), ["kickstart"])

    def test_stall_matches_respects_min_count(self) -> None:
        text = (
            "x Prisma DB reconnect failed (1 consecutive)\n"
            "y Prisma DB reconnect failed (2 consecutive)\n"
            "z Prisma DB reconnect failed (12 consecutive)\n"
        )
        pat = r"Prisma DB reconnect failed \((?P<count>\d+) consecutive\)"
        self.assertEqual(len(wd.stall_matches(text, pat, 3)), 1)


class ProbeBrokenAndAlertOnlyTests(unittest.TestCase):
    def test_unexpected_4xx_never_restarts_and_alerts_once(self) -> None:
        cfg, st = svc(down_before_action=1), wd.fresh_state()
        d = wd.decide(cfg, st, obs("bad", "HTTP 400: Invalid model name"))
        self.assertEqual(kinds(d), [])
        self.assertEqual(sum("PROBE BROKEN" in a for a in d.alerts), 1)
        d = wd.decide(cfg, st, obs("bad", "HTTP 400", now=NOW + 60))
        self.assertEqual(d.alerts, [])

    def test_alert_only_service(self) -> None:
        cfg, st = svc(action="alert", down_before_action=1), wd.fresh_state()
        d = wd.decide(cfg, st, obs("down"))
        self.assertEqual(kinds(d), [])
        self.assertEqual(len(d.alerts), 1)
        d = wd.decide(cfg, st, obs("down", now=NOW + 60))
        self.assertEqual(d.alerts, [], "alert on change only")
        d = wd.decide(cfg, st, obs("ok", now=NOW + 120))
        self.assertTrue(any("RECOVERED" in a for a in d.alerts))

    def test_first_healthy_run_is_silent(self) -> None:
        d = wd.decide(svc(), wd.fresh_state(), obs("ok"))
        self.assertEqual((d.actions, d.alerts), ([], []))

    def test_skip_does_not_count(self) -> None:
        cfg, st = svc(down_before_action=1), wd.fresh_state()
        d = wd.decide(cfg, st, obs("skip", "internet unreachable"))
        self.assertEqual((kinds(d), st["consecutive_down"]), ([], 0))


class StrayDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = svc(stray_match=r"litellm --config \S+ .*--port 4000\b")
        cmd = (
            "python /h/.local/bin/litellm --config /h/.litellm/config.yaml --port 4000"
        )
        self.procs = {
            1: wd.Proc(1, 0, 9e5, "/sbin/launchd"),
            100: wd.Proc(
                100, 1, 600, f"python logpipe.py --out x -- {cmd}"
            ),  # launchd's
            101: wd.Proc(101, 100, 590, cmd),  # its child
            200: wd.Proc(200, 1, 7000, cmd),  # stray
            300: wd.Proc(300, 1, 50, f"python logpipe.py -- {cmd}"),  # another job's
            400: wd.Proc(400, 77, 50, cmd),  # parent alive: not a stray
            500: wd.Proc(500, 1, 50, "unrelated"),
        }
        self.jobs = {"com.test.svc": 100, "com.other": 300}

    def test_only_unsupervised_ppid1_matches_are_strays(self) -> None:
        strays, jobs, orphans, unknown = wd.classify_processes(
            self.cfg, self.procs, self.jobs, [101], self_pid=999
        )
        self.assertEqual([p.pid for p in strays], [200])
        self.assertEqual([p.pid for p in jobs], [300])
        self.assertEqual((orphans, unknown), ([], []))

    def test_stray_holding_the_port_is_an_orphan(self) -> None:
        strays, _, orphans, _ = wd.classify_processes(
            self.cfg, self.procs, self.jobs, [200], self_pid=999
        )
        self.assertEqual([p.pid for p in orphans], [200])
        self.assertEqual(strays, [], "killed once, as the ORPHAN")

    def test_nothing_is_a_stray_without_a_launchd_instance(self) -> None:
        strays, _, orphans, _ = wd.classify_processes(
            self.cfg, self.procs, {"com.test.svc": None}, [200], self_pid=999
        )
        self.assertEqual((strays, orphans), ([], []))

    def test_another_jobs_listener_is_not_killed(self) -> None:
        _, _, orphans, unknown = wd.classify_processes(
            self.cfg, self.procs, self.jobs, [300, 4242], self_pid=999
        )
        self.assertEqual(orphans, [])
        self.assertEqual(unknown, [300, 4242])

    def test_unloaded_job_is_not_kickstarted(self) -> None:
        cfg, st = svc(down_before_action=1), wd.fresh_state()
        o = obs("down", loaded=False, lpid=None, age=None, port_holders=[])
        d = wd.decide(cfg, st, o)
        self.assertEqual(kinds(d), [])
        self.assertEqual(
            st["restarts"], [], "no budget spent on a job that is not loaded"
        )
        self.assertTrue(any("NOT LOADED" in a for a in d.alerts))

    def test_unsupervised_is_alerted_once_and_not_restarted(self) -> None:
        cfg, st = svc(down_before_action=1), wd.fresh_state()
        o = obs("down", lpid=None, age=None, port_holders=[200])
        d = wd.decide(cfg, st, o)
        self.assertEqual(kinds(d), [])
        self.assertEqual(sum("UNSUPERVISED" in a for a in d.alerts), 1)
        d = wd.decide(
            cfg, st, obs("down", lpid=None, age=None, port_holders=[200], now=NOW + 60)
        )
        self.assertFalse(any("UNSUPERVISED" in a for a in d.alerts))


class RestartRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = svc(
            action="alert",
            request_file="/x/req.json",
            request_cooldown_s=600,
            request_command=["true"],
        )
        self.st = wd.fresh_state()

    def test_fresh_request_restarts(self) -> None:
        d = wd.decide(
            self.cfg, self.st, obs(None, request={"requested_at": NOW, "reason": "r"})
        )
        self.assertEqual(kinds(d), ["request_restart"])
        self.assertIsNone(self.st["pending"], "a graceful restart is not verifiable")
        self.assertEqual(self.st["request_last_at"], NOW)

    def test_nonzero_exit_of_the_detached_restart_is_alerted(self) -> None:
        self.st["detached"] = {"what": "requested restart", "exit_file": "/x"}
        d = wd.decide(self.cfg, self.st, obs(None, detached_rc=1))
        self.assertEqual(d.alerts, ["svc requested restart exited 1"])
        self.assertIsNone(self.st["detached"])

    def test_cooldown_drops_the_request(self) -> None:
        self.st["request_last_at"] = NOW - 100
        d = wd.decide(
            self.cfg, self.st, obs(None, request={"requested_at": NOW, "reason": "r"})
        )
        self.assertEqual(kinds(d), ["drop_request"])

    def test_shared_cooldown_file_is_respected(self) -> None:
        o = obs(
            None, request={"requested_at": NOW, "reason": "r"}, cooldown_at=NOW - 30
        )
        d = wd.decide(self.cfg, self.st, o)
        self.assertEqual(kinds(d), ["drop_request"])

    def test_stress_defers_and_keeps_the_request(self) -> None:
        o = obs(None, stress=STRESSED, request={"requested_at": NOW, "reason": "r"})
        d = wd.decide(self.cfg, self.st, o)
        self.assertEqual(kinds(d), [])

    def test_stale_request_is_dropped(self) -> None:
        d = wd.decide(self.cfg, self.st, obs(None, request_problem="stale"))
        self.assertEqual(kinds(d), ["drop_request"])


class FakeSystem(wd.System):
    def __init__(self, alert_rc=0, dies_on_term=True) -> None:
        self.t = NOW
        self.signals: list[tuple[int, int]] = []
        self.runs: list[list[str]] = []
        self.alert_rc = alert_rc
        self.dies_on_term = dies_on_term
        self.dead: set[int] = set()

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s

    def kill(self, pid: int, sig: int) -> bool:
        self.signals.append((pid, sig))
        if sig == signal.SIGKILL or self.dies_on_term:
            self.dead.add(pid)
        return True

    def alive(self, pid: int) -> bool:
        return pid not in self.dead

    def run(self, cmd, timeout, env=None):
        self.runs.append(cmd)
        return self.alert_rc, ""

    def kickstart(self, label):
        self.runs.append(["kickstart", label])
        return 0, ""


class RunnerTests(unittest.TestCase):
    def runner(self, system, tmp) -> wd.Runner:
        g = wd.GlobalCfg(alert_command=["ping"])
        return wd.Runner(
            g, system, Path(tmp) / "state", Path(tmp) / "logs", dry_run=False
        )

    def test_kill_escalates_to_sigkill_when_sigterm_is_ignored(self) -> None:
        fs = FakeSystem(dies_on_term=False)
        with tempfile.TemporaryDirectory() as tmp:
            result = self.runner(fs, tmp).kill(42, wait_s=10)
        self.assertEqual(fs.signals, [(42, signal.SIGTERM), (42, signal.SIGKILL)])
        self.assertIn("SIGKILL", result)

    def test_kill_stops_at_sigterm_when_it_works(self) -> None:
        fs = FakeSystem()
        with tempfile.TemporaryDirectory() as tmp:
            self.runner(fs, tmp).kill(42, wait_s=10)
        self.assertEqual(fs.signals, [(42, signal.SIGTERM)])

    def test_undelivered_alert_is_logged_not_raised(self) -> None:
        fs = FakeSystem(alert_rc=None)  # hermes-ping timed out
        with (
            tempfile.TemporaryDirectory() as tmp,
            self.assertLogs("watchdogd", "WARNING") as cm,
        ):
            self.runner(fs, tmp).alert("litellm DOWN")
        self.assertIn("ALERT NOT DELIVERED (timed out", cm.output[0])
        self.assertEqual(fs.runs, [["ping", "watchdogd: litellm DOWN"]])

    def test_stray_kill_is_reported_with_its_result(self) -> None:
        fs = FakeSystem()
        alerts: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            r = self.runner(fs, tmp)
            r.alert_fn = alerts.append
            a = wd.Action("kill", 9, "stray", alert="svc STRAY killed pid 9")
            r.execute(svc(), wd.fresh_state(), [a])
        self.assertEqual(alerts, ["svc STRAY killed pid 9 (exited on SIGTERM)"])

    def test_state_round_trips_and_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = self.runner(FakeSystem(), tmp)
            st = wd.fresh_state()
            st["restarts"] = [1.0]
            r.save_state(svc(), st)
            self.assertEqual(r.load_state(svc())["restarts"], [1.0])
            dry = wd.Runner(
                wd.GlobalCfg(), FakeSystem(), Path(tmp) / "d", Path(tmp), True
            )
            dry.save_state(svc(), st)
            self.assertFalse((Path(tmp) / "d").exists())


class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/sleep":
                    time.sleep(2)
                code = {"/ok": 200, "/404": 404, "/500": 500, "/sleep": 200}.get(
                    self.path, 400
                )
                body = b'{"content": "OK"}' if code == 200 else b"nope"
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def probe(self, path, **kw) -> wd.ProbeResult:
        p = wd.ProbeCfg(
            kind="http", url=f"http://127.0.0.1:{self.port}{path}", timeout_s=1, **kw
        )
        return wd.probe_http(p, None)

    def test_http_classification(self) -> None:
        self.assertEqual(self.probe("/ok", expect_body='"OK"').status, "ok")
        self.assertEqual(self.probe("/ok", expect_body="nothere").status, "down")
        self.assertEqual(self.probe("/404", ok_status=["404"]).status, "ok")
        self.assertEqual(self.probe("/404", ok_status=["200-499"]).status, "ok")
        self.assertEqual(self.probe("/400").status, "bad")
        self.assertEqual(self.probe("/500").status, "down")
        self.assertEqual(self.probe("/sleep").status, "slow")

    def test_refused_is_down(self) -> None:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        p = wd.ProbeCfg(kind="http", url=f"http://127.0.0.1:{port}/", timeout_s=1)
        r = wd.probe_http(p, None)
        self.assertEqual((r.status, r.detail), ("down", "connection refused"))

    def test_unix_loop_tick_probe(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            path = f"{tmp}/t.sock"
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(path)
            srv.listen(1)

            def answer():
                c, _ = srv.accept()
                c.sendall(b"1")
                c.close()

            threading.Thread(target=answer, daemon=True).start()
            p = wd.ProbeCfg(kind="unix", path=path, expect="1", timeout_s=1)
            self.assertEqual(wd.probe_socket(socket.AF_UNIX, path, p).status, "ok")
            srv.close()
            self.assertEqual(
                wd.probe_socket(socket.AF_UNIX, f"{tmp}/none", p).status, "down"
            )


class ConfigTests(unittest.TestCase):
    def test_parse_service_sections(self) -> None:
        cfg = wd.parse_service(
            {
                "interval_s": 120,
                "launchd": {"label": "com.x", "port": 1},
                "probe": {"kind": "tcp"},
                "policy": {"action": "command", "command": ["true"], "timeout_s": 5},
                "stall": {"log": "/l", "pattern": "x", "min_count": 3},
                "strays": {"match": "y", "term_wait_s": 2},
                "restart_request": {"file": "/r", "command": ["c"]},
            },
            "x",
        )
        self.assertEqual(
            (
                cfg.action_command,
                cfg.action_timeout_s,
                cfg.stall_min_count,
                cfg.request_file,
            ),
            (["true"], 5, 3, "/r"),
        )

    def test_unknown_keys_are_errors(self) -> None:
        with self.assertRaises(ValueError):
            wd.parse_service({"policy": {"slow_before_restart": 3}}, "x")
        with self.assertRaises(ValueError):
            wd.parse_service({"probe": {"kind": "http", "urll": "x"}}, "x")

    def test_every_role_template_renders_to_valid_config(self) -> None:
        """Substitute the Jinja variables crudely and parse every template."""
        tdir = REPO / "roles" / "watchdogd" / "templates"
        for path in sorted((tdir / "watchdogd.d").glob("*.toml.j2")):
            text = re.sub(
                r"\{\{\s*(\w+)[^}]*\}\}",
                lambda m: "4000" if m.group(1).endswith("_port") else "/tmp/x",
                path.read_text(),
            )
            name = path.name.removesuffix(".toml.j2")
            with self.subTest(name):
                cfg = wd.parse_service(tomllib.loads(text), name)
                self.assertEqual(cfg.name, name)
                if cfg.probe.body:
                    json.loads(cfg.probe.body)

    def test_basic_memory_entry_keeps_the_old_watchdog_semantics(self) -> None:
        text = (
            REPO / "roles/watchdogd/templates/watchdogd.d/basic-memory-mcp.toml.j2"
        ).read_text()
        text = re.sub(r"\{\{[^}]*\}\}", "4000", text)
        cfg = wd.parse_service(tomllib.loads(text), "basic-memory-mcp")
        self.assertEqual(
            (
                cfg.interval_s,
                cfg.probe.timeout_s,
                cfg.slow_before_action,
                cfg.down_before_action,
            ),
            (120, 30, 5, 1),
        )
        self.assertIn("/mcp", cfg.notify["recovered"])

    def test_parse_etime(self) -> None:
        self.assertEqual(wd.parse_etime("05:03"), 303)
        self.assertEqual(wd.parse_etime("01:00:01"), 3601)
        self.assertEqual(wd.parse_etime("2-00:00:10"), 172810)


if __name__ == "__main__":
    unittest.main()
