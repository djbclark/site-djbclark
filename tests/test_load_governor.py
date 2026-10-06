"""Tests for bin/load-governor with a fake machine (stdlib unittest; also runs under pytest).

    python3 -m unittest tests/test_load_governor.py -v
"""
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "bin", "load-governor")
_spec = importlib.util.spec_from_loader("load_governor", importlib.machinery.SourceFileLoader("load_governor", PATH))
lg = importlib.util.module_from_spec(_spec)
sys.modules["load_governor"] = lg
_spec.loader.exec_module(lg)

T0 = time.mktime((2026, 10, 4, 12, 0, 0, 0, 0, -1))
OLD = "Sun Oct  4 11:00:00 2026"  # long before T0
ME = 4242  # the governor's pid in the fake world
UID = 501


class FakeEnv:
    """A scripted machine. advance() moves the clock and feeds CPU counters, load and per-process CPU."""

    cores = 8

    def __init__(self):
        self.t = T0
        self.procs = {}
        self.busy = {}  # pid -> cores' worth of CPU per second
        self.ticks = [0, 0, 0, 0]
        self.load = 1.0
        self.tp_calls = []
        self.background = set()
        self.tp_rc = 0
        self.ident_override = {}  # pid -> (start, cmd) | None
        self.add(1, 0, "/sbin/launchd", uid=0)
        self.add(ME, 1, "python3 /x/bin/load-governor --apply")

    def add(self, pid, ppid, cmd, start=OLD, uid=UID, stat="R", busy=0.0):
        self.procs[pid] = lg.Proc(pid, ppid, uid, stat, 100.0, start, cmd)
        self.busy[pid] = busy
        return self.procs[pid]

    def kill(self, pid):
        self.procs.pop(pid, None)

    def advance(self, dt=5.0, idle=5.0, sys=20.0, load_per_core=6.0):
        self.t += dt
        total = 10000
        user = max(0.0, 100.0 - idle - sys)
        for i, share in enumerate((user, sys, idle, 0.0)):
            self.ticks[i] += int(total * share / 100.0)
        self.load = load_per_core * self.cores
        for pid, p in self.procs.items():
            p.cpu_s += self.busy.get(pid, 0.0) * dt

    # --- the Env interface -------------------------------------------------
    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def uid(self):
        return UID

    def self_pid(self):
        return ME

    def loadavg(self):
        return self.load

    def list_procs(self):
        return [lg.Proc(p.pid, p.ppid, p.uid, p.stat, p.cpu_s, p.start, p.cmd) for p in self.procs.values()]

    def proc_identity(self, pid):
        if pid in self.ident_override:
            return self.ident_override[pid]
        p = self.procs.get(pid)
        return (p.start, p.cmd) if p else None

    def read_cpu(self):
        return lg.CpuTimes(*self.ticks)

    def taskpolicy(self, args):
        self.tp_calls.append(list(args))
        if self.tp_rc == 0:
            pid = int(args[-1])
            if args[0] == "-b":
                self.background.add(pid)
            elif args[0] == "-B":
                self.background.discard(pid)
        return self.tp_rc, ""


def make(cfg=None, apply=True, env=None, **kw):
    env = env or FakeEnv()
    cfg = cfg or lg.Config()
    if not kw.get("persist") is False:
        cfg.state_dir = tempfile.mkdtemp(prefix="lg-test-")
    logs = []
    gov = lg.Governor(cfg, env, apply=apply, log=lambda m, l="INFO": logs.append((l, m)), **kw)
    gov.logs = logs
    return gov, env


def overload(env, gov, n=1, idle=5.0):
    d = None
    for _ in range(n):
        env.advance(idle=idle)
        d = gov.tick()
    return d


def calm(env, gov, n=1):
    d = None
    for _ in range(n):
        env.advance(idle=60.0, sys=5.0, load_per_core=0.3)
        d = gov.tick()
    return d


def builds(env, n, base=100, busy=1.0, ppid=1):
    pids = []
    for i in range(n):
        pid = base + i
        env.add(pid, ppid, "/usr/bin/swift-frontend -c file%d.swift" % i, busy=busy + i * 0.1)
        pids.append(pid)
    return pids


class Hysteresis(unittest.TestCase):
    def test_engage_needs_n_consecutive_overloaded_samples(self):
        gov, env = make()
        builds(env, 3)
        gov.tick()  # warm-up
        overload(env, gov, 2)
        self.assertFalse(gov.engaged)
        calm(env, gov)  # a calm sample resets the run
        overload(env, gov, 2)
        self.assertFalse(gov.engaged)
        overload(env, gov, 1)
        self.assertTrue(gov.engaged)

    def test_neutral_sample_resets_engage_count(self):
        gov, env = make()
        builds(env, 2)
        gov.tick()
        overload(env, gov, 2)
        env.advance(idle=25.0, sys=10.0, load_per_core=1.0)  # neither overloaded nor calm
        gov.tick()
        overload(env, gov, 2)
        self.assertFalse(gov.engaged)

    def test_idle_low_alone_is_not_overload_without_load_or_sys(self):
        gov, env = make()
        builds(env, 2)
        gov.tick()
        for _ in range(5):
            env.advance(idle=5.0, sys=10.0, load_per_core=1.0)  # busy but not contended
            gov.tick()
        self.assertFalse(gov.engaged)

    def test_high_sys_time_counts_as_overload(self):
        gov, env = make()
        builds(env, 2)
        gov.tick()
        for _ in range(3):
            env.advance(idle=11.0, sys=50.0, load_per_core=0.5)
            gov.tick()
        self.assertTrue(gov.engaged)

    def test_release_needs_m_consecutive_calm_samples_then_restores_all(self):
        gov, env = make()
        builds(env, 3)
        gov.tick()
        overload(env, gov, 4)
        self.assertTrue(gov.engaged)
        self.assertTrue(env.background)
        calm(env, gov, 5)
        self.assertTrue(gov.engaged, "5 calm samples are not enough")
        overload(env, gov, 1)  # relapse resets the calm run
        calm(env, gov, 5)
        self.assertTrue(gov.engaged)
        calm(env, gov, 1)
        self.assertFalse(gov.engaged)
        self.assertEqual(env.background, set(), "everything restored on release")
        self.assertEqual(gov.tracked, {})

    def test_counter_wraparound(self):
        gov, env = make()
        env.ticks = [2**32 - 100, 2**32 - 100, 2**32 - 100, 0]
        gov.tick()
        env.advance(idle=5.0)
        sig = gov.signals(env.read_cpu())
        self.assertAlmostEqual(sig.idle_pct, 5.0, delta=1.0)


class Selection(unittest.TestCase):
    def test_only_heaviest_k_are_throttled_rest_left_alone(self):
        gov, env = make()
        pids = builds(env, 6)  # busy rises with index; pid 105 heaviest
        gov.tick()
        overload(env, gov, 3)
        self.assertEqual(set(env.background), {105, 104})  # initial_k = 2
        self.assertEqual(set(env.background) & {100, 101, 102, 103}, set())

    def test_escalates_one_per_escalate_samples_up_to_max_k(self):
        cfg = lg.Config(initial_k=1, max_k=3, escalate_samples=2)
        gov, env = make(cfg)
        builds(env, 8)
        gov.tick()
        overload(env, gov, 3)  # engaged on 3rd, k=1
        self.assertEqual(len(env.background), 1)
        overload(env, gov, 2)  # +1 after 2 more samples
        self.assertEqual(len(env.background), 2)
        overload(env, gov, 20)
        self.assertEqual(len(env.background), 3, "never beyond max_k")

    def test_idle_low_cpu_and_young_processes_are_not_candidates(self):
        gov, env = make()
        env.add(100, 1, "/usr/bin/swift-frontend a", busy=0.02)  # 2% of a core
        env.add(101, 1, "/usr/bin/swift-frontend b", busy=1.0, start="Sun Oct  4 12:00:14 2026")  # 1 s old when engaged
        env.add(102, 1, "/usr/bin/swift-frontend c", busy=1.0)
        gov.tick()
        overload(env, gov, 3)
        self.assertEqual(env.background, {102})

    def test_not_allow_listed_and_other_users_are_untouched(self):
        gov, env = make()
        env.add(100, 1, "/usr/bin/some-random-tool --spin", busy=2.0)
        env.add(101, 1, "/usr/bin/swift-frontend root-owned", busy=2.0, uid=0)
        env.add(102, 1, "/usr/bin/swift-frontend zombie", busy=2.0, stat="Z")
        gov.tick()
        overload(env, gov, 4)
        self.assertEqual(env.tp_calls, [])

    def test_allow_list_samples(self):
        m = lg.Matcher(lg.Config())
        yes = [
            "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift-frontend -frontend -c a.swift",
            "/usr/bin/swift test --parallel",
            "node (vitest 3)",
            "/opt/homebrew/bin/python3 -m pytest -q tests/",
            "/usr/local/go/pkg/tool/darwin_arm64/compile -o x.a",
            "/usr/bin/java -cp gradle-launcher.jar org.gradle.launcher.daemon.bootstrap.GradleDaemon",
            "/usr/bin/clang -c foo.c",
            "node /p/node_modules/.bin/tsc -p .",
            "/opt/homebrew/bin/ruff check .",
            "/Users/x/.cargo/bin/cargo build",
        ]
        no = [
            "/usr/bin/vim notes.txt",
            "/opt/homebrew/bin/ruff server",
            "/usr/bin/ssh host",
        ]
        for c in yes:
            self.assertIsNone(m.classify(c), c)
        for c in no:
            self.assertIsNotNone(m.classify(c), c)

    def test_allow_extra_and_allow_only(self):
        cfg = lg.Config(allow_extra=[r"my-special-job"])
        self.assertIsNone(lg.Matcher(cfg).classify("/bin/x my-special-job"))
        only = lg.Matcher(lg.Config(), allow_only=[r"marker-zzz"])
        self.assertIsNone(only.classify("python3 marker-zzz"))
        self.assertIsNotNone(only.classify("/usr/bin/swift-frontend a"))


class DenyList(unittest.TestCase):
    def test_deny_wins_over_allow(self):
        m = lg.Matcher(lg.Config(allow_extra=[r"pytest"]))
        denied = [
            "node /opt/homebrew/lib/node_modules/@openai/codex/bin/codex.js exec run pytest",
            "claude --resume pytest",
            "/Users/x/.local/bin/cursor-agent -p run pytest",
            "/opt/homebrew/bin/opencode run pytest",
            "bash -c cd x && pytest -q",
            "/Applications/Ghostty.app/Contents/MacOS/ghostty pytest",
            "/Applications/Orca.app/Contents/MacOS/Orca --x pytest",
            "/Applications/CodexBar.app/Contents/MacOS/CodexBar vitest",
            "python3 /Users/x/ops/site-private/bin/load-governor --allow-only pytest",
            "/usr/bin/python3 /x/hermes pytest",
            "grok agent stdio pytest",
            "/usr/sbin/WindowServer -daemon",
            "/Applications/OpenUsage.app/Contents/MacOS/OpenUsage vitest",
        ]
        for c in denied:
            self.assertIsNotNone(m.denied(c), "should be denied: " + c)
            self.assertIsNotNone(m.classify(c), c)
        self.assertIsNone(m.classify("python3 -m pytest tests/test_claude.py"), "a test file named claude is fine")
        py = "/opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
        self.assertIsNone(m.classify(py + " -m pytest -q"), "framework Python is how pytest shows up in ps")
        self.assertIsNotNone(m.classify("/Applications/Xcode.app/Contents/MacOS/Xcode pytest"))

    def test_denied_process_is_never_throttled_even_if_it_is_the_heaviest(self):
        gov, env = make(lg.Config(allow_extra=["pytest"]))
        env.add(100, 1, "node /opt/lib/codex/bin/codex.js exec pytest", busy=5.0)
        env.add(101, 1, "/usr/bin/swift-frontend a", busy=1.0)
        gov.tick()
        overload(env, gov, 6)
        self.assertEqual(env.background, {101})

    def test_governor_and_its_children_are_never_touched(self):
        gov, env = make(lg.Config(allow_extra=["pytest"]))
        env.add(100, ME, "python3 -m pytest child-of-governor", busy=3.0)
        env.add(101, 100, "python3 -m pytest grandchild-of-governor", busy=3.0)
        env.procs[ME].cmd = "python3 -m pytest self"  # even if its own command line matched
        env.busy[ME] = 3.0
        gov.tick()
        overload(env, gov, 6)
        self.assertEqual(env.tp_calls, [])

    def test_pid_one_never(self):
        gov, env = make(lg.Config(allow_extra=["launchd"]))
        env.busy[1] = 4.0
        env.procs[1].uid = UID
        gov.tick()
        overload(env, gov, 6)
        self.assertEqual(env.tp_calls, [])


class StarvationCap(unittest.TestCase):
    def test_cap_releases_grace_blocks_retrottle_then_it_resumes(self):
        cfg = lg.Config(cap_s=20.0, grace_s=12.0, initial_k=1, max_k=1)
        gov, env = make(cfg)
        env.add(100, 1, "/usr/bin/swift-frontend only", busy=2.0)
        gov.tick()
        overload(env, gov, 3)  # throttled at t0+15
        self.assertEqual(env.background, {100})
        t_thr = gov.tracked[100].since
        overload(env, gov, 3)  # +15 s
        self.assertEqual(env.background, {100})
        overload(env, gov, 1)  # +20 s since throttle -> cap
        self.assertGreaterEqual(env.t - t_thr, 20.0)
        self.assertEqual(env.background, set(), "released at the cap")
        self.assertIn(100, gov.grace)
        overload(env, gov, 1)  # +5 s into grace
        self.assertEqual(env.background, set(), "grace: still overloaded but left alone")
        overload(env, gov, 1)  # +10 s
        self.assertEqual(env.background, set())
        overload(env, gov, 1)  # +15 s > grace_s
        self.assertEqual(env.background, {100}, "re-engaged after grace")
        self.assertNotIn(100, gov.grace)

    def test_cap_rotates_to_next_heaviest(self):
        cfg = lg.Config(cap_s=10.0, grace_s=60.0, initial_k=1, max_k=1)
        gov, env = make(cfg)
        env.add(100, 1, "/usr/bin/swift-frontend big", busy=3.0)
        env.add(101, 1, "/usr/bin/swift-frontend small", busy=1.0)
        gov.tick()
        overload(env, gov, 3)
        self.assertEqual(env.background, {100})
        overload(env, gov, 2)
        self.assertEqual(env.background, {101}, "after 100 hit the cap the next process takes the slot")

    def test_continuous_overload_never_throttles_a_pid_longer_than_cap_plus_one_tick(self):
        cfg = lg.Config(cap_s=30.0, grace_s=20.0, initial_k=1, max_k=1)
        gov, env = make(cfg)
        env.add(100, 1, "/usr/bin/swift-frontend only", busy=2.0)
        gov.tick()
        worst = 0.0
        for _ in range(80):
            overload(env, gov, 1)
            if 100 in gov.tracked:
                worst = max(worst, env.t - gov.tracked[100].since)
        self.assertLess(worst, cfg.cap_s + 5.0 + 1e-6)


class PidReuse(unittest.TestCase):
    def test_reused_pid_is_dropped_not_released(self):
        gov, env = make()
        env.add(100, 1, "/usr/bin/swift-frontend a", busy=2.0)
        gov.tick()
        overload(env, gov, 3)
        self.assertEqual(env.background, {100})
        env.tp_calls.clear()
        # pid 100 dies and a different process takes the number
        env.procs[100].start = "Sun Oct  4 12:01:00 2026"
        env.procs[100].cmd = "/usr/bin/innocent-bystander"
        overload(env, gov, 1)
        self.assertNotIn(["-B", "-p", "100"], env.tp_calls)
        self.assertNotIn(100, gov.tracked)
        self.assertTrue(any("REUSE" in m for _, m in gov.logs))

    def test_identity_checked_again_right_before_the_call(self):
        gov, env = make()
        env.add(100, 1, "/usr/bin/swift-frontend a", busy=2.0)
        gov.tick()
        overload(env, gov, 2)
        env.ident_override[100] = ("Sun Oct  4 12:00:07 2026", "/usr/bin/other")  # raced between ps and taskpolicy
        overload(env, gov, 1)
        self.assertEqual(env.tp_calls, [])
        self.assertEqual(gov.tracked, {})

    def test_release_skips_when_process_exited(self):
        gov, env = make()
        env.add(100, 1, "/usr/bin/swift-frontend a", busy=2.0)
        gov.tick()
        overload(env, gov, 3)
        env.tp_calls.clear()
        env.kill(100)
        calm(env, gov, 7)
        self.assertEqual(env.tp_calls, [])
        self.assertEqual(gov.tracked, {})


class DryRun(unittest.TestCase):
    def test_dry_run_runs_nothing_and_writes_no_state(self):
        gov, env = make(apply=False)
        builds(env, 4)
        gov.tick()
        overload(env, gov, 5)
        self.assertTrue(gov.engaged)
        self.assertEqual(env.tp_calls, [])
        self.assertEqual(env.background, set())
        self.assertFalse(os.path.exists(gov.cfg.state_path))
        self.assertTrue(any(m.startswith("DRYRUN would run: taskpolicy -b") for _, m in gov.logs))
        self.assertTrue(gov.tracked, "the dry run still tracks virtually so cap/grace logic shows in the log")

    def test_dry_run_virtual_cap(self):
        gov, env = make(lg.Config(cap_s=10.0, initial_k=1, max_k=1), apply=False)
        env.add(100, 1, "/usr/bin/swift-frontend a", busy=2.0)
        gov.tick()
        overload(env, gov, 6)
        self.assertEqual(env.tp_calls, [])
        self.assertTrue(any("taskpolicy -B -p 100" in m for _, m in gov.logs))


class FailureHandling(unittest.TestCase):
    def test_taskpolicy_failure_backs_off(self):
        gov, env = make(lg.Config(retry_after_failure_s=30.0))
        env.add(100, 1, "/usr/bin/swift-frontend a", busy=2.0)
        env.tp_rc = 1
        gov.tick()
        overload(env, gov, 3)
        n = len(env.tp_calls)
        self.assertEqual(n, 1)
        overload(env, gov, 3)  # 15 s later, still inside the 30 s back-off
        self.assertEqual(len(env.tp_calls), n)
        self.assertEqual(gov.tracked, {})


class Inheritance(unittest.TestCase):
    def test_children_started_after_throttle_are_tracked_and_released_with_parent(self):
        cfg = lg.Config(cap_s=20.0, initial_k=1, max_k=1)
        gov, env = make(cfg)
        env.add(100, 1, "/usr/bin/swift-build parent", busy=3.0)
        gov.tick()
        overload(env, gov, 3)
        self.assertEqual(env.background, {100})
        # a child spawned while the parent is throttled inherits background QoS
        env.add(200, 100, "/usr/bin/swift-frontend child", start=time.strftime("%a %b %e %H:%M:%S %Y", time.localtime(env.t)), busy=0.5)
        env.background.add(200)  # the kernel inherits it; we only learn that by tracking
        env.tp_calls.clear()
        overload(env, gov, 1)
        self.assertIn(200, gov.tracked)
        self.assertEqual(gov.tracked[200].inherited_from, 100)
        overload(env, gov, 4)  # parent hits the cap -> child goes back with it
        self.assertEqual(env.background, set())
        self.assertIn(["-B", "-p", "200"], env.tp_calls)

    def test_child_started_before_the_throttle_is_not_touched(self):
        gov, env = make(lg.Config(initial_k=1, max_k=1))
        env.add(100, 1, "/usr/bin/swift-build parent", busy=3.0)
        env.add(200, 100, "/usr/bin/swift-frontend old-child", busy=0.05)  # below candidate threshold
        gov.tick()
        overload(env, gov, 3)
        overload(env, gov, 1)
        self.assertNotIn(200, gov.tracked)


class StateAndUndo(unittest.TestCase):
    def test_state_file_records_throttled_pids(self):
        gov, env = make()
        env.add(100, 1, "/usr/bin/swift-frontend a", busy=2.0)
        gov.tick()
        overload(env, gov, 3)
        with open(gov.cfg.state_path) as fh:
            d = json.load(fh)
        self.assertIn("100", d["tracked"])
        self.assertEqual(d["tracked"]["100"]["start"], OLD)
        self.assertIn("100", d["ever_throttled"])

    def test_undo_all_restores_matching_skips_reused_and_gone(self):
        gov, env = make()
        for pid in (100, 101, 102):
            env.add(pid, 1, "/usr/bin/swift-frontend %d" % pid, busy=2.0)
        gov.cfg.initial_k = 3
        gov.tick()
        overload(env, gov, 3)
        self.assertEqual(env.background, {100, 101, 102})
        # simulate a crashed governor: new instance, same state dir
        env.procs[101].start = "Sun Oct  4 12:02:00 2026"  # pid reuse
        env.kill(102)  # exited
        env.tp_calls.clear()
        logs = []
        r, s = lg.undo_all(gov.cfg, env, lambda m, l="INFO": logs.append(m))
        self.assertEqual((r, s), (1, 2))
        self.assertEqual(env.tp_calls, [["-B", "-p", "100"]])
        with open(gov.cfg.state_path) as fh:
            d = json.load(fh)
        self.assertEqual((d["tracked"], d["ever_throttled"]), ({}, {}))

    def test_undo_all_without_state_is_a_noop(self):
        cfg = lg.Config(state_dir=tempfile.mkdtemp())
        env = FakeEnv()
        self.assertEqual(lg.undo_all(cfg, env, lambda *a: None), (0, 0))
        self.assertEqual(env.tp_calls, [])

    def test_release_all_on_shutdown(self):
        gov, env = make()
        builds(env, 4)
        gov.tick()
        overload(env, gov, 3)
        self.assertTrue(env.background)
        n = gov.release_all("shutdown")
        self.assertEqual(n, 2)
        self.assertEqual(env.background, set())
        with open(gov.cfg.state_path) as fh:
            self.assertEqual(json.load(fh)["tracked"], {})


class Parsing(unittest.TestCase):
    def test_parse_ps_line(self):
        p = lg.parse_ps_line("86146 85854   501 S+     0:01.38 Sat Oct  3 17:39:37 2026     node /Users/x/graft mcp")
        self.assertEqual((p.pid, p.ppid, p.uid, p.stat), (86146, 85854, 501, "S+"))
        self.assertAlmostEqual(p.cpu_s, 1.38)
        self.assertEqual(p.start, "Sat Oct 3 17:39:37 2026")
        self.assertEqual(p.cmd, "node /Users/x/graft mcp")

    def test_parse_cputime(self):
        self.assertAlmostEqual(lg.parse_cputime("12:34.56"), 754.56)
        self.assertAlmostEqual(lg.parse_cputime("1:02:03.50"), 3723.5)
        self.assertAlmostEqual(lg.parse_cputime("2-01:00:00"), 2 * 86400 + 3600)

    def test_config_roundtrip_and_unknown_key(self):
        text = lg.config_to_toml(lg.Config(cap_s=12.5))
        import tomllib
        d = tomllib.loads(text)
        self.assertEqual(d["cap_s"], 12.5)
        self.assertEqual(d["engage_samples"], 3)
        self.assertEqual(d["allow"], lg.DEFAULT_ALLOW)
        self.assertEqual(d["deny_names"], lg.DEFAULT_DENY_NAMES)
        fd, path = tempfile.mkstemp(suffix=".toml")
        os.write(fd, b"bogus = 1\n")
        os.close(fd)
        with self.assertRaises(SystemExit):
            lg.load_config(path)

    def test_config_file_overrides_defaults(self):
        fd, path = tempfile.mkstemp(suffix=".toml")
        os.write(fd, b"cap_s = 7\nallow_extra = ['zzz']\n")
        os.close(fd)
        cfg = lg.load_config(path)
        self.assertEqual((cfg.cap_s, cfg.allow_extra, cfg.grace_s), (7, ["zzz"], 45.0))


if __name__ == "__main__":
    unittest.main()
