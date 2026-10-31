"""net-watch: episode logic, reboot policy, probe, discovery, snapshot, state. No network, no real hermes-ping, no Deco."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parent.parent / "bin" / "net-watch"


@pytest.fixture()
def nw(tmp_path, monkeypatch):
    loader = importlib.machinery.SourceFileLoader("net_watch_under_test", str(BIN))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    monkeypatch.setattr(mod, "STATE_DIR", tmp_path / "state")
    return mod


def C(nw, **kw):
    """Config of a configured home: explicit [deco] host and the gateway MAC pin (net-watch measures nothing without them)."""
    kw.setdefault("deco_host", "192.0.2.1")
    kw.setdefault("home_gateway_macs", ["aa:bb:cc:dd:ee:ff"])
    return nw.Config(**kw)


class Rig:
    """Fake clock + injected side effects around one Watch."""

    def __init__(self, nw, cfg=None, creds=(True, ""), reboot_result=None):
        self.nw = nw
        self.t = 1_800_000_000.0
        self.pings: list[str] = []
        self.snaps: list[str] = []
        self.reboots: list[str] = []
        self.creds_calls = 0
        self.cfg = cfg or C(nw)
        self.creds = creds
        self.home = True
        self.reboot_result = reboot_result or {"ok": True, "outcome": "requested for 2 node(s)"}
        self.next_mbps = 100.0
        self.next_unknown = ""
        self.probes = 0
        self.unsure = False
        self.next_default = {"mbps": 1.0}
        self.next_kind = ""
        self.deps = nw.Deps(
            now=lambda: self.t,
            probe=self._probe,
            discover=lambda cfg: {"interface": "en0", "gateway": "192.0.2.1", "gateway_mac": "aa:bb:cc:dd:ee:ff", "source": "test",
                                  "home": self.home, "home_why": "" if self.home else "gateway MAC differs",
                                  "home_unsure": (not self.home) and self.unsure},
            notify=lambda m: self.pings.append(m) or True,
            snapshot=self._snap,
            creds=self._creds,
            deco_reboot=self._reboot,
        )
        self.st = nw.new_state()
        self.w = nw.Watch(self.cfg, self.deps, self.st)

    def _probe(self, cfg, net):
        self.probes += 1
        return {"t": self.t, "interface": net["interface"], "mbps": self.next_mbps, "errors": [], "default_route": dict(self.next_default),
                "unknown": self.next_unknown, "unknown_kind": self.next_kind, "gateway_ok": True}

    def _snap(self, cfg, st, label, short=False, now=None):
        p = f"/snap/{len(self.snaps)}-{label}"
        self.snaps.append(p)
        return p

    def _creds(self):
        self.creds_calls += 1
        return self.creds

    def _reboot(self, host):
        self.reboots.append(host)
        return self.reboot_result

    def sample(self, mbps, advance=60.0):
        """Advance the clock, take one sample through the full tick path."""
        self.t += advance
        self.next_mbps = mbps
        assert self.w.tick(force=True)

    def run_slow(self, minutes, mbps=5.0, step=60.0):
        for _ in range(int(minutes * 60 / step)):
            self.sample(mbps, step)


# ---------------------------------------------------------------- episode start


def test_single_slow_sample_never_starts(nw, tmp_path, monkeypatch):
    r = Rig(nw)
    r.sample(100)
    r.sample(2)
    assert r.pings == [] and r.st["episode"] is None
    r.sample(100)
    assert r.st["slow_since"] is None


def test_start_only_after_ten_minutes_of_slow_samples(nw, tmp_path):
    r = Rig(nw)
    r.sample(100)
    r.run_slow(9)  # slow samples at +1..+9 min: covers 8 min
    assert r.pings == []
    r.sample(5)  # +10 min after the first slow sample: covers 9 min
    assert r.pings == []
    r.sample(5)  # covers 10 min
    assert len(r.pings) == 1
    assert r.st["episode"] is not None


def test_start_ping_format_and_snapshot_and_baseline(nw):
    r = Rig(nw)
    for _ in range(3):
        r.sample(120)
    r.run_slow(11, mbps=4.2)
    (ping,) = r.pings
    assert ping.startswith("djbclark: net-watch: download 4.2 Mbps (baseline 120.0) for ")
    assert "min on en0; snapshot /snap/0-start; reboot will try" in ping


def test_flapping_before_start_resets_the_ten_minutes(nw):
    r = Rig(nw)
    r.run_slow(6)
    r.sample(100)  # healthy sample in between: coverage resets
    r.run_slow(6)
    assert r.pings == [] and r.st["episode"] is None


def test_one_missing_tick_is_tolerated_a_long_gap_is_not(nw):
    r = Rig(nw)
    r.sample(5)
    r.sample(5, 60)
    r.sample(5, 120)  # one tick missing
    r.run_slow(8)
    assert len(r.pings) == 1
    r2 = Rig(nw)
    r2.sample(5)
    r2.sample(5, 3 * 3600)  # machine slept for 3 h: the gap is not "covered"
    r2.sample(5, 60)
    assert r2.pings == [] and r2.st["episode"] is None


# ---------------------------------------------------------------- once-only notifications


def test_exactly_one_start_and_one_end_ping_over_a_long_episode(nw):
    r = Rig(nw)
    r.sample(100)
    r.run_slow(120, mbps=3.0)
    assert len(r.pings) == 1  # not one per sample, not "still slow"
    r.sample(90)
    assert len(r.pings) == 1  # one healthy sample is not recovery
    r.sample(95)
    assert len(r.pings) == 2
    assert "recovered after" in r.pings[1] and "min 3.0" in r.pings[1]
    assert r.st["episode"] is None and r.st["last_episode"]["min_mbps"] == 3.0


def test_recovery_needs_two_consecutive_healthy_samples(nw):
    r = Rig(nw)
    r.run_slow(12)
    assert len(r.pings) == 1
    for mbps in (90, 4, 90, 4, 90, 4):  # flapping inside an episode: never recovered, never a second ping
        r.sample(mbps)
    assert len(r.pings) == 1 and r.st["episode"] is not None
    r.sample(90)
    r.sample(90)
    assert len(r.pings) == 2 and r.st["episode"] is None


def test_new_episode_after_recovery_pings_again(nw):
    r = Rig(nw)
    r.run_slow(12)
    r.sample(90)
    r.sample(90)
    r.run_slow(12)
    assert len(r.pings) == 3 and r.pings[2].startswith("djbclark: net-watch: download 5.0 Mbps")


def test_cadence_five_minutes_healthy_one_minute_after_slow(nw):
    r = Rig(nw)
    r.sample(100)
    assert not r.w.tick() and not nw.probe_due(r.st, r.cfg, r.t + 100)
    assert nw.probe_due(r.st, r.cfg, r.t + 300)
    r.sample(3)
    assert nw.probe_due(r.st, r.cfg, r.t + 60) and not nw.probe_due(r.st, r.cfg, r.t + 20)
    r.sample(100)  # healthy again, no episode: back to five minutes
    assert not nw.probe_due(r.st, r.cfg, r.t + 100)


def test_periodic_snapshots_every_five_minutes_only_in_episode(nw):
    r = Rig(nw)
    r.run_slow(11)
    n0 = len(r.snaps)
    r.run_slow(11)
    labels = [s.split("-", 1)[1] for s in r.snaps[n0:]]
    assert labels.count("periodic") == 1 and labels.count("post-reboot-still-slow") == 1


# ---------------------------------------------------------------- reboot policy


def test_reboot_once_per_episode_even_if_it_stays_slow(nw):
    r = Rig(nw)
    r.run_slow(90)
    assert r.reboots == ["192.0.2.1"]
    assert r.st["episode"]["reboot"]["state"] == "done"


def test_failed_reboot_is_not_retried_in_same_episode(nw):
    r = Rig(nw, reboot_result={"ok": False, "error": "login refused"})
    r.run_slow(90)
    assert len(r.reboots) == 1
    assert r.st["episode"]["reboot"]["state"] == "failed"
    r.sample(90)
    r.sample(90)
    assert "login refused" in r.pings[1]


def test_reboot_respects_cooldown_across_episodes(nw):
    r = Rig(nw)
    r.run_slow(12)
    assert len(r.reboots) == 1
    r.sample(90)
    r.sample(90)
    r.run_slow(12)  # second episode 25 min later: inside the 2 h cooldown
    assert len(r.reboots) == 1
    assert "reboot skipped: cooldown" in r.pings[2]
    r.t += 3 * 3600
    r.sample(90)
    r.sample(90)
    r.run_slow(12)
    assert len(r.reboots) == 2


def test_missing_credentials_is_skipped_not_error(nw):
    r = Rig(nw, creds=(False, "no credentials (DECO_ADMIN_USER/DECO_ADMIN_PASSWORD not set in sudo-secretspec)"))
    r.run_slow(12)
    assert r.reboots == []
    assert "reboot skipped: no credentials" in r.pings[0]
    assert r.st["episode"]["reboot"]["state"] == "skipped"
    assert not any("tool error" in p for p in r.pings)


def test_reboot_disabled_in_config(nw):
    cfg = C(nw, reboot_enabled=False)
    r = Rig(nw, cfg=cfg)
    r.run_slow(12)
    assert r.reboots == [] and "reboot skipped: disabled" in r.pings[0] and r.creds_calls == 0


def test_end_ping_reports_recovery_time_after_reboot(nw):
    r = Rig(nw)
    r.run_slow(12)
    reboot_t = r.st["episode"]["reboot"]["t"]
    r.run_slow(4)
    r.sample(90)
    r.sample(90)
    assert f"reboot done at {nw.fmt_t(reboot_t)}, speed recovered 6 min after it" in r.pings[1]
    assert any("post-reboot-recovered" in s for s in r.snaps)


def test_reboot_after_min_delays_the_reboot(nw):
    r = Rig(nw, cfg=C(nw, reboot_after_min=15))
    r.run_slow(12)
    assert r.reboots == [] and "reboot will try" in r.pings[0]
    r.run_slow(6)
    assert len(r.reboots) == 1


def test_reboot_dry_run_touches_nothing(nw, capsys):
    r = Rig(nw)
    a = type("A", (), {"dry_run": True})()
    assert nw.cmd_reboot(a, r.cfg, r.deps) == 0
    assert r.reboots == [] and r.pings == []
    assert not (nw.STATE_DIR / "state.json").exists()
    assert "dry-run" in capsys.readouterr().out


def test_reboot_command_without_credentials_exits_cleanly(nw, capsys):
    r = Rig(nw, creds=(False, "no credentials"))
    st = nw.new_state()
    st["net"] = {"gateway": "192.0.2.1"}
    nw.save_state(st)
    a = type("A", (), {"dry_run": False})()
    assert nw.cmd_reboot(a, r.cfg, r.deps) == 0
    assert r.reboots == [] and "reboot skipped: no credentials" in capsys.readouterr().out


FAKE_USER, FAKE_PW = "svc-user@example.invalid", "Pw/ZXCV+9876=="
VAULT = {"OVH_APPLICATION_SECRET": "ovh-secret-VALUE", "GITHUB_PAT": "ghp_VALUEVALUE", "LITELLM_KEY": "sk-VALUEVALUE"}


def set_creds(nw):
    nw._CREDS.clear()
    nw._CREDS.update({"DECO_ADMIN_USER": FAKE_USER, "DECO_ADMIN_PASSWORD": FAKE_PW})


def test_creds_are_read_with_get_argv_lists_and_a_missing_secretspec_is_clean(nw):
    ok, why = nw.deco_creds_ok(lambda argv, t, env=None: nw.Res(127, "", "no such file"))
    assert not ok and "no credentials" in why
    ok, why = nw.deco_creds_ok(lambda argv, t, env=None: nw.Res(1))
    assert not ok and "no credentials" in why
    ok, why = nw.deco_creds_ok(lambda argv, t, env=None: nw.Res(0, "\n"))  # set but empty
    assert not ok
    seen = []
    ok, _ = nw.deco_creds_ok(lambda argv, t, env=None: seen.append(argv) or nw.Res(0, "value\n"))
    assert ok
    assert [a[:3] for a in seen] == [["sudo-secretspec", "get", "DECO_ADMIN_USER"], ["sudo-secretspec", "get", "DECO_ADMIN_PASSWORD"]]
    assert all(isinstance(a, list) and "run" not in a and "sh" not in a for a in seen)
    nw.deco_creds_ok(lambda *a, **k: pytest.fail("creds are read once per process"))


def test_run_gives_children_no_stdin(nw, monkeypatch):
    import subprocess
    kw = {}
    monkeypatch.setattr(nw.subprocess, "run", lambda argv, **k: kw.update(k) or subprocess.CompletedProcess(argv, 0, "", ""))
    nw.run(["true"], 5)
    assert kw["stdin"] == subprocess.DEVNULL


def test_helper_runs_with_only_path_home_and_the_two_secrets(nw, monkeypatch):
    for k, v in VAULT.items():
        monkeypatch.setenv(k, v)  # the rest of the vault is in OUR env, as under `sudo-secretspec run`
    set_creds(nw)
    seen = {}

    def runner(argv, timeout, env=None):
        seen.update(argv=argv, env=env, timeout=timeout)
        return nw.Res(0, json.dumps({"ok": True, "nodes": 2, "sent": "dropped", "confirmed": True}))

    r = nw.deco_run("reboot", "192.0.2.1", runner)
    assert r["ok"] and "confirmed: the mesh dropped and came back" in r["outcome"]
    assert set(seen["env"]) == {"PATH", "HOME", "DECO_ADMIN_USER", "DECO_ADMIN_PASSWORD"}
    assert seen["argv"][:4] == ["uv", "run", "--script", "--locked"] and "--offline" in seen["argv"] and "--with" not in seen["argv"]
    assert seen["argv"][-3:] == ["reboot", "--host", "192.0.2.1"] and "sudo-secretspec" not in seen["argv"]
    assert not any(FAKE_PW in a or FAKE_USER in a for a in seen["argv"])


def test_no_secret_reaches_state_snapshot_ping_or_log_when_the_helper_fails(nw, monkeypatch, tmp_path):
    set_creds(nw)
    for k, v in VAULT.items():
        monkeypatch.setenv(k, v)
    leak = f"login for {FAKE_USER} with {FAKE_PW} {VAULT['GITHUB_PAT']} failed"
    outputs = [  # what the helper, uv or the library might print on failure
        nw.Res(1, json.dumps({"ok": False, "error_class": "AuthenticationError", "error": leak, "status_code": 401})),
        nw.Res(1, json.dumps({"ok": False, "error": leak})),
        nw.Res(1, "", leak),
        nw.Res(0, "Traceback...\n" + leak),
        nw.Res(124, leak, leak, True),
    ]
    for res in outputs:
        r = Rig(nw, cfg=C(nw, reboot_after_min=10))
        r.deps.deco_reboot = lambda host, res=res: nw.deco_run("reboot", host, lambda argv, t, env=None: res)
        r.run_slow(14)
        r.sample(90)
        r.sample(90)
        blob = json.dumps(r.st) + "\n".join(r.pings) + ((nw.STATE_DIR / "net-watch.log").read_text() if (nw.STATE_DIR / "net-watch.log").exists() else "")
        for secret in (FAKE_USER, FAKE_PW, *VAULT.values()):
            assert secret not in blob
        assert r.st["last_episode"]["reboot"]["state"] == "failed" and "failed:" in r.pings[1]


def test_exception_text_never_reaches_pings_log_or_snapshot_index(nw, tmp_path):
    r = Rig(nw)
    r.deps.probe = lambda cfg, net: (_ for _ in ()).throw(RuntimeError(f"boom {FAKE_PW}"))
    a = type("A", (), {})()
    nw.cmd_tick(a, r.cfg, r.deps)
    r2 = Rig(nw)
    r2.deps.snapshot = lambda *a, **k: (_ for _ in ()).throw(RuntimeError(f"snap {FAKE_PW}"))
    r2.deps.notify = lambda m: (_ for _ in ()).throw(RuntimeError(f"ping {FAKE_PW}"))
    r2.run_slow(12)
    st = nw.new_state()
    st["net"] = {"interface": "en0", "gateway": "192.0.2.1", "home": True}
    path = nw.take_snapshot(C(nw), st, "manual", True, 1_800_000_000.0, lambda a, t, env=None: (_ for _ in ()).throw(RuntimeError(f"item {FAKE_PW}")),
                            lambda s: None, tmp_path / "eps", deco_fn=None, creds_fn=lambda: (False, ""))
    blob = "\n".join(p.read_text() for p in Path(path).iterdir()) + (nw.STATE_DIR / "net-watch.log").read_text() + "\n".join(r.pings + r2.pings) + json.dumps(r2.st)
    assert FAKE_PW not in blob and "tick failed: RuntimeError" in (nw.STATE_DIR / "net-watch.log").read_text()


@pytest.fixture()
def deco():
    loader = importlib.machinery.SourceFileLoader("net_watch_deco_under_test", str(BIN.with_name("net-watch-deco")))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


class FakeDecoError(Exception):
    pass


class FakeClient:
    """Stands in for tplink_deco_api.DecoClient: scripted per-call behaviour, no network."""
    reboot_exc: BaseException | None = None
    logins: list = []  # per login: raise this (None = ok); consumed in order, last one repeats
    calls: list = []

    def __init__(self, host, user, pw, timeout=10.0):
        pass

    def __enter__(self):
        if FakeClient.logins:
            exc = FakeClient.logins.pop(0) if len(FakeClient.logins) > 1 else FakeClient.logins[0]
            if exc:
                raise exc
        return self

    def __exit__(self, *a):
        return None

    def request(self, path, form, data):
        FakeClient.calls.append(form)
        if form == "system" and FakeClient.reboot_exc:
            raise FakeClient.reboot_exc
        return {"device_list": [{"mac": "AA-00", "role": "slave"}, {"mac": "AA-01", "role": "master", "device_ip": "192.0.2.1"}]}


def run_helper(deco, action, exc=None, logins=(None,), confirm_s=60.0):
    FakeClient.reboot_exc, FakeClient.logins, FakeClient.calls = exc, list(logins), []
    t = [0.0]

    def clock():
        t[0] += 1.0
        return t[0]

    env = {"DECO_ADMIN_USER": FAKE_USER, "DECO_ADMIN_PASSWORD": FAKE_PW}
    return deco.run(action, "192.0.2.1", env, FakeClient, (FakeDecoError,), sleep=lambda s: None, clock=clock, confirm_s=confirm_s)


def test_helper_reboot_succeeds_only_when_the_failure_came_after_the_request_was_sent(deco):
    for exc in (TimeoutError("read timed out"), ConnectionResetError("reset"), deco.http.client.RemoteDisconnected("closed")):
        res, rc = run_helper(deco, "reboot", exc)
        assert res["ok"] and res["sent"] == "dropped" and rc == 0, exc
    for exc in (FakeDecoError("transport wrapped a refused connection"), OSError("no route"), ValueError("x")):
        res, rc = run_helper(deco, "reboot", exc)
        assert res["ok"] is False and rc == 1 and res["error_class"] == type(exc).__name__, exc
        assert "refused" not in json.dumps(res) and "no route" not in json.dumps(res)
    res, _ = run_helper(deco, "reboot", None)
    assert res["ok"] and res["sent"] == "accepted" and res["nodes"] == 2


def test_helper_confirms_only_when_the_mesh_dropped_and_came_back(deco):
    down_then_up = [None, ConnectionResetError("down"), ConnectionResetError("down"), None]  # login 1 = the reboot call itself
    res, _ = run_helper(deco, "reboot", TimeoutError("t"), logins=down_then_up)
    assert res["ok"] and res["confirmed"] is True
    res, _ = run_helper(deco, "reboot", TimeoutError("t"), logins=[None])  # never saw it go down
    assert res["ok"] and res["confirmed"] is False
    res, _ = run_helper(deco, "reboot", TimeoutError("t"), logins=[None, ConnectionResetError("down")])  # went down, never returned
    assert res["ok"] and res["confirmed"] is False


def test_helper_errors_are_a_class_and_a_fixed_message_never_the_exception_text(deco):
    leak = f"{FAKE_USER} {FAKE_PW}"
    res, rc = run_helper(deco, "info", logins=[FakeDecoError(leak)])
    assert rc == 1 and res["error_class"] == "FakeDecoError" and FAKE_PW not in json.dumps(res) and FAKE_USER not in json.dumps(res)
    res, rc = deco.run("info", "h", {}, FakeClient, (FakeDecoError,))
    assert rc == 3 and res["error"] == "no credentials"


def test_helper_info_keeps_only_allowlisted_wan_fields(deco, nw):
    import dataclasses

    @dataclasses.dataclass(frozen=True)
    class Ip:
        ip: str = "203.0.113.9"
        mask: str = "255.255.255.0"
        mac: str = "aa:bb"
        gateway: str = "203.0.113.1"
        dns1: str = "1.1.1.1"
        dns2: str = ""
        ppp_username: str = "isp-login"
        ppp_password: str = "isp-secret"

    @dataclasses.dataclass(frozen=True)
    class Wan:
        ip_info: Ip = Ip()
        dial_type: str = "pppoe"
        enable_auto_dns: bool = True
        pppoe_password: str = "isp-secret"

    @dataclasses.dataclass(frozen=True)
    class Info:
        wan: Wan = Wan()
        lan: Wan = Wan()

    class C2(FakeClient):
        def get_wan_info(self):
            return Info()

        def get_performance(self):
            return type("P", (), {})()

    FakeClient.logins, FakeClient.reboot_exc, FakeClient.calls = [], None, []
    res, _ = deco.run("info", "h", {"DECO_ADMIN_USER": "u", "DECO_ADMIN_PASSWORD": "p"}, C2, (FakeDecoError,))
    blob = json.dumps(res)
    assert res["ok"] and "isp-secret" not in blob and "isp-login" not in blob and res["info"]["wan"]["wan"]["dial_type"] == "pppoe"
    # the parent re-filters whatever comes back, so a modified helper cannot smuggle a field into a snapshot
    cleaned = nw.clean_info({"wan": {"wan": {"ip_info": {"ip": "1.2.3.4", "ppp_password": "x"}, "token": "y"}}, "env": {"A": "b"}})
    assert cleaned == {"wan": {"wan": {"ip_info": {"ip": "1.2.3.4"}}}}


# ---------------------------------------------------------------- home network (nothing runs elsewhere)


def test_off_the_home_network_nothing_is_measured_snapshotted_or_sent(nw):
    r = Rig(nw)
    r.home = False
    for _ in range(40):
        r.sample(2)
    assert r.probes == 0 and r.snaps == [] and r.pings == [] and r.reboots == [] and r.st["episode"] is None
    assert r.st["not_measuring"]["why"] == "gateway MAC differs" and r.st["slow_since"] is None


def test_leaving_home_during_an_episode_closes_it_with_one_ping_and_no_reboot(nw):
    r = Rig(nw, cfg=C(nw, reboot_after_min=30))
    r.run_slow(12)
    assert len(r.pings) == 1 and r.st["episode"]["reboot"]["state"] == "pending"
    r.home = False
    for _ in range(30):
        r.sample(2)
    assert len(r.pings) == 2 and "left the home network" in r.pings[1] and r.reboots == [] and r.st["episode"] is None


def test_home_identity_needs_explicit_host_and_gateway_mac(nw):
    net = {"interface": "en0", "gateway": "192.0.2.1", "gateway_mac": "aa:bb:cc:dd:ee:ff"}
    assert nw.check_home(C(nw), net) == (True, "")
    assert not nw.check_home(nw.Config(home_gateway_macs=["aa:bb:cc:dd:ee:ff"]), net)[0]  # no [deco] host
    assert not nw.check_home(nw.Config(deco_host="192.0.2.1"), net)[0]  # no MAC pin
    assert not nw.check_home(C(nw), {**net, "gateway_mac": "11:22:33:44:55:66"})[0]  # same subnet, other router
    assert not nw.check_home(C(nw), {**net, "gateway_mac": ""})[0]
    assert not nw.check_home(C(nw), {**net, "interface": ""})[0]


def test_discovery_reads_the_gateway_mac_from_arp_and_pads_octets(nw):
    outs = {"netstat": nw.Res(0, NETSTAT), "arp": nw.Res(0, "? (192.0.2.1) at AA:b:cc:d:ee:f on en0 ifscope [ethernet]\n")}
    seen = []
    d = nw.discover_net(C(nw, home_gateway_macs=["aa:0b:cc:0d:ee:0f"]), lambda argv, t, env=None: seen.append(argv) or outs.get(argv[0], nw.Res(1)))
    assert d["gateway_mac"] == "aa:0b:cc:0d:ee:0f" and d["home"] is True and ["arp", "-n", "192.0.2.1"] in seen
    d = nw.discover_net(C(nw, home_gateway_macs=["11:22:33:44:55:66"]), lambda argv, t, env=None: outs.get(argv[0], nw.Res(1)))
    assert d["home"] is False and "not the home gateway" in d["home_why"]


def test_an_idle_gateway_with_no_arp_entry_is_primed_with_one_ping(nw):
    arp = [nw.Res(1, "192.0.2.1 (192.0.2.1) -- no entry"), nw.Res(0, "? (192.0.2.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]")]
    seen = []

    def runner(argv, t, env=None):
        seen.append(argv[0])
        return nw.Res(0, NETSTAT) if argv[0] == "netstat" else (arp.pop(0) if argv[0] == "arp" else nw.Res(0))

    d = nw.discover_net(C(nw), runner)
    assert d["home"] is True and seen == ["netstat", "arp", "ping", "arp"]
    d = nw.discover_net(C(nw), lambda argv, t, env=None: nw.Res(0, NETSTAT) if argv[0] == "netstat" else nw.Res(1))
    assert d["home"] is False and "arp has no entry" in d["home_why"]  # still unknown after the ping: not home, never a guess


def test_snapshot_does_not_call_the_deco_off_the_home_network(nw, tmp_path):
    st = nw.new_state()
    st["net"] = {"interface": "en0", "gateway": "192.0.2.1", "home": False}
    called = []
    nw.take_snapshot(C(nw), st, "manual", True, 1_800_000_000.0, lambda a, t, env=None: nw.Res(0, "ok"), lambda s: None, tmp_path / "e",
                     deco_fn=lambda host: called.append(host) or {"ok": True, "info": {}}, creds_fn=lambda: pytest.fail("no creds read off-network"))
    assert called == []
    nw.take_snapshot(C(nw), st, "manual", True, 1_800_001_000.0, lambda a, t, env=None: nw.Res(0, "ok"), lambda s: None, tmp_path / "e",
                     deco_fn=None, creds_fn=lambda: pytest.fail("no creds read off-network"))


# ---------------------------------------------------------------- UNKNOWN samples (an outage is not a slowdown)


def test_probe_total_failure_is_unknown_not_zero_mbps(nw):
    p = nw.do_probe(nw.Config(), {"interface": "en0", "gateway": "192.0.2.1"},
                    lambda argv, timeout, env=None: nw.Res(6, "0 0.000 0 000", "curl: (6) Could not resolve host"))
    assert p["unknown"] and "every stream failed" in p["unknown"] and p["default_route"]["streams"] == []


def test_probe_unknown_for_http_errors_zero_bytes_and_missing_interface(nw):
    net = {"interface": "en0", "gateway": "g"}
    p = nw.do_probe(nw.Config(), net, lambda argv, t, env=None: nw.Res(0, "312 0.2 1560 429"))  # CDN rate limit: tiny body, rc 0
    assert "HTTP status" in p["unknown"]
    p = nw.do_probe(nw.Config(), net, lambda argv, t, env=None: nw.Res(0, "0 1.0 0 200"))
    assert p["unknown"] == "zero bytes on every stream"
    calls = []
    p = nw.do_probe(nw.Config(), {"interface": "", "gateway": "g"}, lambda argv, t, env=None: calls.append(argv) or nw.Res(0, "5000000 1.0 5000000 200"))
    assert "no physical interface" in p["unknown"] and calls == []  # nothing downloaded through the tunnel
    n = [0]

    def one_good(argv, t, env=None):  # one stream fine, the rest 403: measured (the 403 bytes are not counted)
        n[0] += 1
        return nw.Res(0, "5000000 1.0 5000000 206") if n[0] == 1 else nw.Res(0, "300 0.1 3000 403")

    p = nw.do_probe(nw.Config(), net, one_good)
    assert not p["unknown"] and p["bytes"] == 5_000_000


def test_a_total_outage_never_starts_an_episode_or_reboots(nw):
    r = Rig(nw)
    r.sample(100)
    r.next_unknown = "every stream failed"
    for _ in range(180):
        r.sample(0.0)
    assert r.pings == [] and r.reboots == [] and r.st["episode"] is None and r.st["slow_since"] is None and r.snaps == []


def test_unknown_samples_neither_extend_nor_reset_slow_time(nw):
    r = Rig(nw)
    r.run_slow(4)
    since = r.st["slow_since"]
    r.next_unknown = "x"
    r.sample(0.0)  # one tick unknown: inside the tolerance
    assert r.st["slow_since"] == since
    r.next_unknown = ""
    r.run_slow(6)
    assert len(r.pings) == 1  # slow time before and after the unknown tick joined up
    r2 = Rig(nw)
    r2.run_slow(3)
    r2.next_unknown = "x"
    for _ in range(20):
        r2.sample(0.0)  # a 20 min outage must not bridge two slow samples into "10 minutes of slowness"
    r2.next_unknown = ""
    r2.sample(5)
    r2.run_slow(5)
    assert r2.pings == [] and r2.st["episode"] is None


def test_unknown_samples_inside_an_episode_change_nothing_and_the_reboot_link_drop_does_not_close_it(nw):
    r = Rig(nw)
    r.run_slow(12)
    n = r.st["episode"]["n"]
    r.next_unknown = "link down while the Deco restarts"
    for _ in range(5):
        r.sample(0.0)
    assert r.st["episode"]["n"] == n and r.st["healthy_streak"] == 0 and len(r.pings) == 1 and len(r.reboots) == 1
    r.next_unknown = ""
    r.run_slow(2)
    assert len(r.pings) == 1 and r.st["episode"] is not None


# ---------------------------------------------------------------- manual reboot bookkeeping


def reboot_args(dry=False):
    return type("A", (), {"dry_run": dry})()


def test_manual_reboot_records_the_cooldown_before_the_call_and_the_outcome_after(nw, capsys):
    r = Rig(nw)
    seen = {}

    def deco_reboot(host):
        seen["state_during"] = json.loads((nw.STATE_DIR / "state.json").read_text())
        return {"ok": True, "outcome": "requested for 2 node(s), accepted; unconfirmed: the mesh was not seen to drop and return"}

    r.deps.deco_reboot = deco_reboot
    assert nw.cmd_reboot(reboot_args(), r.cfg, r.deps) == 0
    assert seen["state_during"]["last_reboot_t"] == r.t
    after = nw.load_state()
    assert after["last_reboot"]["manual"] is True and after["last_reboot"]["state"] == "done" and after["last_reboot_t"] == r.t
    assert "unconfirmed" in after["last_reboot"]["outcome"]
    nw.cmd_reboot(reboot_args(), r.cfg, r.deps)  # and the next automatic decision sees the cooldown
    w = nw.Watch(r.cfg, r.deps, nw.load_state())
    assert "cooldown" in w._reboot_decision(r.t + 600)


def test_manual_reboot_waits_for_the_tick_lock_and_never_calls_the_deco_without_it(nw, monkeypatch, capsys):
    r = Rig(nw)
    monkeypatch.setattr(nw, "REBOOT_LOCK_WAIT_S", 0.6)
    with nw.lock(nw.STATE_DIR / "lock"):
        assert nw.cmd_reboot(reboot_args(), r.cfg, r.deps) == 1
    assert r.reboots == [] and "a tick holds the lock" in capsys.readouterr().out
    assert not (nw.STATE_DIR / "state.json").exists()


def test_manual_reboot_inside_an_episode_settles_its_reboot_so_the_tick_does_not_repeat_it(nw):
    r = Rig(nw, cfg=C(nw, reboot_after_min=15))
    r.run_slow(12)
    assert r.st["episode"]["reboot"]["state"] == "pending"
    nw.save_state(r.st)
    assert nw.cmd_reboot(reboot_args(), r.cfg, r.deps) == 0
    r.st.clear()
    r.st.update(nw.load_state())  # the tick re-reads state under the lock
    assert r.st["episode"]["reboot"]["state"] == "done" and r.st["episode"]["reboot"]["manual"] is True
    r.run_slow(8)  # past reboot_after_min: no second reboot
    assert len(r.reboots) == 1
    r.sample(90)
    r.sample(90)
    assert "(manual)" in r.pings[1]


def test_manual_reboot_refuses_off_the_home_network_and_dry_run_says_why(nw, capsys):
    r = Rig(nw)
    r.home = False
    assert nw.cmd_reboot(reboot_args(), r.cfg, r.deps) == 1
    assert r.reboots == [] and "not on the home network" in capsys.readouterr().out
    assert nw.cmd_reboot(reboot_args(True), r.cfg, r.deps) == 0 and "NO:" in capsys.readouterr().out


def test_automatic_reboot_rechecks_the_cooldown_when_it_finally_fires(nw):
    r = Rig(nw, cfg=C(nw, reboot_after_min=15))
    r.run_slow(12)
    assert r.st["episode"]["reboot"]["state"] == "pending"
    r.st["last_reboot_t"] = r.t  # someone rebooted since the start decision
    r.run_slow(8)
    assert r.reboots == [] and r.st["episode"]["reboot"]["state"] == "skipped"


def test_failed_reboot_starts_the_cooldown_for_the_next_episode(nw):
    r = Rig(nw, reboot_result={"ok": False, "error": "TransportError: Deco helper failed"})
    r.run_slow(12)
    r.sample(90)
    r.sample(90)
    r.run_slow(12)
    assert len(r.reboots) == 1 and "reboot skipped: cooldown" in r.pings[2]


def test_the_attempt_is_saved_to_disk_before_the_deco_is_called(nw):
    r = Rig(nw)
    seen = {}

    def deco_reboot(host):
        on_disk = json.loads((nw.STATE_DIR / "state.json").read_text())
        seen.update(t=on_disk["last_reboot_t"], state=on_disk["episode"]["reboot"]["state"])
        raise KeyboardInterrupt  # we die mid-call

    r.deps.deco_reboot = deco_reboot
    with pytest.raises(KeyboardInterrupt):
        r.run_slow(12)
    assert seen["t"] is not None and seen["state"] == "attempted"


# ---------------------------------------------------------------- gaps, sleep, abandonment, backoff


def test_gap_tolerance_is_three_ticks_not_two_and_not_a_hundred(nw):
    def episode_after_gap(gap_s):
        r = Rig(nw)
        r.sample(5)
        r.sample(5, gap_s)
        r.run_slow(9)
        return len(r.pings)

    assert episode_after_gap(170) == 1  # one or two missing ticks are fine
    assert episode_after_gap(180) == 1
    for gap in (200, 20 * 60, 30 * 60):  # a sleep: the gap is not covered, ten minutes start over
        assert episode_after_gap(gap) == 0, gap


def test_sleep_inside_an_episode_closes_it_as_a_gap_instead_of_counting_the_sleep(nw):
    r = Rig(nw)
    r.run_slow(12)
    assert len(r.pings) == 1
    r.sample(3, 8 * 3600)  # the Mac slept 8 h and is still slow when it wakes
    assert len(r.pings) == 2 and "Mac asleep or off" in r.pings[1] and "recovery unknown" in r.pings[1]
    assert r.st["last_episode"]["duration_min"] <= 13 and r.st["episode"] is None and r.st["last_episode"]["end_reason"] == "gap"
    r.run_slow(12)
    assert len(r.pings) == 3 and r.pings[2].startswith("djbclark: net-watch: download")


def test_an_episode_open_too_long_is_abandoned_with_one_noted_ping(nw):
    r = Rig(nw, cfg=C(nw, episode_max_h=2.0, reboot_enabled=False))
    r.run_slow(12)
    r.run_slow(2 * 60)
    abandoned = [p for p in r.pings if "abandoned after" in p]
    assert len(abandoned) == 1 and "recovery unknown" in abandoned[0] and r.st["last_episode"]["end_reason"] == "abandoned"
    assert len(r.pings) == 3  # start, abandoned, and the next episode's start 10 min later; nothing per sample


def test_periodic_snapshots_back_off_5_15_60_then_hourly(nw):
    r = Rig(nw, cfg=C(nw, reboot_enabled=False))
    r.run_slow(11)
    n0 = len(r.snaps)
    assert r.snaps[0].endswith("-start")
    r.run_slow(240)
    assert [s.split("-", 1)[1] for s in r.snaps[n0:]] == ["periodic"] * 5  # +5, +20, +80, +140, +200 min (fixed 5 min would be 48)


def test_total_snapshot_bytes_are_capped_oldest_first(nw, tmp_path, monkeypatch):
    root = tmp_path / "eps"
    for i in range(4):
        d = root / f"d{i}"
        d.mkdir(parents=True)
        (d / "f").write_text("x" * 100)
        os.utime(d, (1_800_000_000 - 1000 + i, 1_800_000_000 - 1000 + i))
    nw.prune_episodes(root, 1_800_000_000.0, total_cap=250)
    assert sorted(p.name for p in root.iterdir()) == ["d2", "d3"]
    monkeypatch.setattr(nw, "SNAP_TOTAL_CAP", 150)
    st = nw.new_state()
    nw.take_snapshot(C(nw), st, "manual", True, 1_800_000_000.0, lambda a, t, env=None: nw.Res(0, "ok"), lambda s: None, root, deco_fn=None, creds_fn=lambda: (False, ""))
    assert not (root / "d2").exists() and (root / "d3").exists()


def test_snapshots_are_owner_only_whatever_the_umask(nw, tmp_path):
    old = os.umask(0o022)
    try:
        path = nw.take_snapshot(C(nw), nw.new_state(), "manual", True, 1_800_000_000.0, lambda a, t, env=None: nw.Res(0, "ok"), lambda s: None,
                                tmp_path / "eps", deco_fn=None, creds_fn=lambda: (False, ""))
    finally:
        os.umask(old)
    assert (Path(path).stat().st_mode & 0o777) == 0o700 and (Path(path).parent.stat().st_mode & 0o777) == 0o700
    assert all((f.stat().st_mode & 0o777) == 0o600 for f in Path(path).iterdir())


def test_urls_come_after_double_dash_so_a_dash_url_is_not_an_option(nw):
    argv = nw.curl_download_argv("-o/etc/passwd", "en0", 8, 1000)
    assert argv[-2:] == ["--", "-o/etc/passwd"]


def test_config_values_that_would_break_the_state_machine_fall_back_to_defaults(nw, tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('sustain_min = 0\nrecover_samples = 0\nslow_interval_s = 1\nthreshold_mbps = "fast"\n[home]\ngateway_mac = ["AA:b:cc:d:ee:f"]\n[deco]\nhost = "192.0.2.1"\n')
    cfg = nw.load_config(p)
    assert cfg.sustain_min == 10 and cfg.recover_samples == 2 and cfg.slow_interval_s == 60 and cfg.threshold_mbps == 30
    assert cfg.home_gateway_macs == ["aa:0b:cc:0d:ee:0f"] and cfg.deco_host == "192.0.2.1"


def test_public_config_template_loads_to_the_defaults_plus_only_placeholder_required_values(nw):
    """The template is public: it must carry placeholders for the two required values and otherwise mirror the defaults."""
    import dataclasses

    cfg = nw.load_config(BIN.parent.parent / "config" / "net-watch.toml.example")
    assert cfg.deco_host == "192.0.2.1" and cfg.home_gateway_macs == ["aa:bb:cc:dd:ee:ff"]
    # urls: the template lists each speed-test host once; the probe cycles them (urls[i % len]), the default repeats the pair
    assert cfg == dataclasses.replace(nw.Config(), deco_host=cfg.deco_host, home_gateway_macs=cfg.home_gateway_macs, urls=cfg.urls)
    assert [cfg.urls[i % len(cfg.urls)] for i in range(4)] == nw.Config().urls

# ---------------------------------------------------------------- probe


def test_probe_zero_streams_total_failure_keeps_the_default_route_untouched(nw):
    p = nw.do_probe(nw.Config(), {"interface": "en0", "gateway": "192.0.2.1"},
                    lambda argv, timeout, env=None: nw.Res(6, "0 0.000 0 000", "curl: (6) Could not resolve host"))
    assert p["mbps"] == 0.0 and p["bytes"] == 0 and p["errors"] and p["unknown"]


def test_probe_timeout_with_partial_bytes_counts_what_arrived(nw):
    def runner(argv, timeout, env=None):
        return nw.Res(28, "1000000 8.000 125000 200", "curl: (28) Operation timed out")

    p = nw.do_probe(nw.Config(), {"interface": "en0", "gateway": "192.0.2.1"}, runner)
    assert p["mbps"] == pytest.approx(4 * 1_000_000 * 8 / 8 / 1e6)  # 4 MB in 8 s = 4 Mbps
    assert p["errors"] == []


def test_probe_binds_physical_interface_and_default_route_sample_does_not(nw):
    seen = []

    def runner(argv, timeout, env=None):
        seen.append(argv)
        return nw.Res(0, "5000000 1.0 5000000 200")

    p = nw.do_probe(nw.Config(), {"interface": "en0", "gateway": "x"}, runner)
    bound = [a for a in seen if "--interface" in a and "-X" not in a]  # the 4 downloads; the direct upload is covered below
    assert len(bound) == 4 and all(a[a.index("--interface") + 1] == "en0" for a in bound)
    assert len([a for a in seen if "-X" not in a]) - len(bound) == 2 and all(isinstance(a, list) for a in seen)
    assert all(a[a.index("--max-time") + 1] == "8" for a in seen)
    assert p["mbps"] == pytest.approx(160.0)


def test_probe_through_a_real_subprocess_with_a_curl_shim(nw, tmp_path, monkeypatch):
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "curl").write_text('#!/bin/sh\nprintf "2500000 2.5 1000000 200"\n')
    (shim / "curl").chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim}:{os.environ['PATH']}")
    p = nw.do_probe(nw.Config(), {"interface": "en0", "gateway": "x"})
    assert p["bytes"] == 10_000_000 and p["mbps"] == pytest.approx(32.0)


# ---------------------------------------------------------------- discovery

NETSTAT = """Routing tables

Internet:
Destination        Gateway            Flags               Netif Expire
default            link#25            UCSIg               utun4
default            192.0.2.1       UGScg                 en0
100.64/10          link#25            UCS                 utun4
"""
NWI = """Network information

IPv4 network interface information
     utun4 : flags      : 0x5 (IPv4,DNS)
             address    : 100.0.0.2
       en0 : flags      : 0x5 (IPv4,DNS)
             address    : 192.0.2.57

   REACH : flags 0x00000002 (Reachable)
"""


def test_discovery_skips_the_tunnel_default_route(nw):
    assert nw.parse_netstat_default(NETSTAT) == ("en0", "192.0.2.1")
    assert nw.parse_netstat_default("default link#25 UCSIg utun4\n") is None
    assert nw.parse_nwi_interface(NWI) == "en0"


def test_discovery_falls_back_to_scutil_and_ipconfig_and_honors_config(nw):
    outs = {
        "netstat": nw.Res(1, "", "boom"),
        "scutil": nw.Res(0, NWI),
        "ipconfig": nw.Res(0, "192.0.2.1\n"),
    }
    outs["arp"], outs["ping"] = nw.Res(1), nw.Res(0)
    d = nw.discover_net(nw.Config(), lambda argv, t, env=None: outs[argv[0]])
    assert d["interface"] == "en0" and d["gateway"] == "192.0.2.1" and d["home"] is False
    seen = []
    d = nw.discover_net(nw.Config(interface="en7", gateway="10.0.0.1"), lambda argv, t, env=None: seen.append(argv[0]) or nw.Res(1))
    assert (d["interface"], d["gateway"], d["source"]) == ("en7", "10.0.0.1", "config") and seen == ["arp", "ping", "arp"]  # only the MAC lookup (primed once)
    d = nw.discover_net(nw.Config(), lambda argv, t, env=None: nw.Res(0, NETSTAT) if argv[0] == "netstat" else nw.Res(1))
    assert d["interface"] == "en0"


# ---------------------------------------------------------------- snapshot


def test_snapshot_item_failure_does_not_abort_the_rest(nw, tmp_path):
    calls = []

    def runner(argv, timeout, env=None):
        calls.append(argv[0])
        if argv[0] in ("wdutil", "tailscale", "nettop"):
            raise RuntimeError("kaboom")
        if argv[0] == "ping":
            return nw.Res(0, "10 packets transmitted, 10 packets received, 0.0% packet loss\nround-trip min/avg/max/stddev = 1.0/2.0/3.0/0.5 ms\n")
        return nw.Res(0, "ok\n")

    st = nw.new_state()
    st["net"] = {"interface": "en0", "gateway": "192.0.2.1"}
    root = tmp_path / "eps"
    path = nw.take_snapshot(nw.Config(), st, "manual", False, 1_800_000_000.0, runner, lambda s: None, root, deco_fn=None, creds_fn=lambda: (False, ""))
    d = Path(path)
    idx = json.loads((d / "index.json").read_text())
    assert idx["tailscale"]["ok"] is False and idx["top-talkers"]["ok"] is False
    assert idx["ping-gateway"]["ok"] and idx["traceroute"]["ok"] and idx["dns"]["ok"]
    assert (d / "tailscale.error.txt").exists() and (d / "ping-gateway.txt").exists()
    assert (d / "deco.txt").read_text().startswith("skipped: no credentials")
    assert json.loads((d / "ping-gateway.txt").read_text().split("\n\n")[0])["avg"] == 2.0


def test_snapshot_caps_file_size_and_prunes_old_episodes(nw, tmp_path):
    root = tmp_path / "eps"
    old = root / "20200101T000000-start"
    old.mkdir(parents=True)
    os.utime(old, (1, 1))
    fresh = root / "20261001T000000-start"
    fresh.mkdir()
    os.utime(fresh, (1_800_000_000 - 86400, 1_800_000_000 - 86400))
    nw.prune_episodes(root, 1_800_000_000.0)
    assert not old.exists() and fresh.exists()
    st = nw.new_state()
    big = nw.Res(0, "x" * 500_000)
    path = nw.take_snapshot(nw.Config(), st, "manual", True, 1_800_000_000.0, lambda a, t, env=None: big, lambda s: None, root, deco_fn=None, creds_fn=lambda: (False, ""))
    assert all(f.stat().st_size <= nw.SNAP_FILE_CAP + 200 for f in Path(path).iterdir())


def test_parsers_on_canned_output(nw):
    assert nw.parse_ping("20 packets transmitted, 19 packets received, 5.0% packet loss\nround-trip min/avg/max/stddev = 6.9/47.0/88.4/33.2 ms")["loss_pct"] == 5.0
    ib = nw.parse_netstat_ib("Name Mtu Network Address Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll\nen0 1500 <Link#14> aa:bb:cc:dd:ee:ff 100 2 5000 90 1 4000 0\nen0 1500 192.0.2/24 192.0.2.57 100 - 5000 90 - 4000 -\n")
    assert ib == {"ipkts": 100, "ierrs": 2, "ibytes": 5000, "opkts": 90, "oerrs": 1, "obytes": 4000}
    assert nw.parse_tcp_stats("\t10 packets sent\n\t3 data packets (400 bytes) retransmitted\n")["data_packets_retransmitted"] == 3
    top = nw.parse_nettop("time,,interface,state,bytes_in,bytes_out,rx_dupe,rx_ooo,re-tx\n22:00:00.1,a.1,,,10,10,0,0,0\ntime,,interface,state,bytes_in,bytes_out,rx_dupe,rx_ooo,re-tx\n22:00:05.1,a.1,,,50,5,0,0,1\n22:00:05.1,b.2,,,900,1,0,0,0\n")
    assert [t["proc"] for t in top] == ["b.2", "a.1"] and top[1]["bytes_in"] == 40 and top[0]["window"] == "delta"
    ts = nw.trim_tailscale(json.dumps({"BackendState": "Running", "ExitNodeStatus": {"ID": "x"}, "Self": {"HostName": "m"}, "Peer": {"k": {"HostName": "p", "ExitNode": True, "Relay": "nyc"}}}))
    assert ts["using_exit_node"] and ts["peers"][0]["Relay"] == "nyc"
    assert nw.wifi_from_wdutil("must be run as root") is None
    assert nw.wifi_from_wdutil("    RSSI : -61 dBm\n    Noise : -90 dBm\n")["RSSI"] == "-61 dBm"


# ---------------------------------------------------------------- state


def test_state_write_is_atomic_and_leaves_no_temp_files(nw, tmp_path, monkeypatch):
    st = nw.new_state()
    st["last_probe_t"] = 5.0
    p = tmp_path / "s" / "state.json"
    nw.save_state(st, p)
    assert json.loads(p.read_text())["last_probe_t"] == 5.0
    monkeypatch.setattr(nw.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    st["last_probe_t"] = 9.0
    with pytest.raises(OSError):
        nw.save_state(st, p)
    assert json.loads(p.read_text())["last_probe_t"] == 5.0  # the old file is intact
    assert [f.name for f in p.parent.iterdir()] == ["state.json"]


def test_old_or_corrupt_state_files_still_load(nw, tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"samples": [{"t": 1, "mbps": 50}], "last_probe_t": 3}))  # no version, no episode keys
    st = nw.load_state(p)
    assert st["episode"] is None and st["last_reboot_t"] is None and st["samples"][0]["mbps"] == 50
    assert nw.Watch(nw.Config(), nw.Deps(), st).st["healthy_streak"] == 0
    p.write_text("{not json")
    assert nw.load_state(p)["samples"] == []
    p.write_text(json.dumps(["a list"]))
    assert nw.load_state(p)["samples"] == []
    assert nw.load_state(tmp_path / "missing.json")["samples"] == []


def test_baseline_is_median_of_healthy_samples_in_last_24h(nw):
    r = Rig(nw)
    st = r.st
    now = r.t
    st["samples"] = [{"t": now - 100000, "mbps": 900}, {"t": now - 50, "mbps": 100}, {"t": now - 40, "mbps": 300},
                     {"t": now - 30, "mbps": 200}, {"t": now - 20, "mbps": 4}]
    assert nw.baseline(st, r.cfg, now) == 200.0


def test_overlapping_tick_does_nothing(nw, tmp_path):
    r = Rig(nw)
    with nw.lock(nw.STATE_DIR / "lock"):
        a = type("A", (), {})()
        assert nw.cmd_tick(a, r.cfg, r.deps) == 0
    assert not (nw.STATE_DIR / "state.json").exists()


def test_tick_end_to_end_saves_state_and_status_runs(nw, capsys):
    r = Rig(nw)
    a = type("A", (), {"json": True})()
    assert nw.cmd_tick(a, r.cfg, r.deps) == 0
    st = json.loads((nw.STATE_DIR / "state.json").read_text())
    assert len(st["samples"]) == 1 and st["net"]["interface"] == "en0"
    assert nw.cmd_status(a, r.cfg, r.deps) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "healthy"


def test_tool_errors_ping_at_most_once_a_day(nw):
    r = Rig(nw)
    r.deps.probe = lambda cfg, net: (_ for _ in ()).throw(RuntimeError("boom"))
    a = type("A", (), {})()
    for _ in range(3):
        r.t += 400
        nw.cmd_tick(a, r.cfg, r.deps)
    assert len([p for p in r.pings if "tool error" in p]) == 1


# ================================================================ repair round 2
# ---------------------------------------------------------------- one bad third-party host must not make a sample SLOW


def host_runner(nw, cloudflare, hetzner, ping=None):
    """Per-host canned curl results: cloudflare()/hetzner() build the Res for each stream by the URL's host."""
    seen = []

    def runner(argv, timeout, env=None):
        seen.append(argv)
        if argv[0] == "ping":
            return ping or nw.Res(0)
        return (cloudflare if "cloudflare" in argv[-1] else hetzner)()

    runner.seen = seen
    return runner


FAST = lambda nw: nw.Res(0, "5000000 0.7 7142857 206")  # noqa: E731  ~57 Mbps per stream


@pytest.mark.parametrize("bad", [
    pytest.param(lambda nw: nw.Res(28, "0 4.000 0 000", "curl: (28) Connection timed out"), id="syn-blackholed"),
    pytest.param(lambda nw: nw.Res(28, "0 8.000 0 000", "curl: (28) Operation timed out"), id="tls-stall-to-max-time"),
    pytest.param(lambda nw: nw.Res(28, "1250000 8.000 156250 206", "curl: (28) Operation timed out"), id="congested-5mbps-per-stream"),
    pytest.param(lambda nw: nw.Res(7, "0 0.010 0 000", "curl: (7) Failed to connect"), id="refused-fast"),
])
def test_one_slow_stalled_or_blackholed_speed_test_host_does_not_make_the_sample_slow(nw, bad):
    runner = host_runner(nw, lambda: FAST(nw), lambda: bad(nw))
    p = nw.do_probe(nw.Config(), {"interface": "en0", "gateway": "g"}, runner)
    assert not p["unknown"] and p["mbps"] > 100  # 10 MB from the healthy host in 0.7 s: the link is fast; the bad host's time is not ours
    assert p["default_route"]["mbps"] > 50


def test_throughput_is_the_best_host_or_all_hosts_together_and_failed_streams_take_no_part(nw):
    ok = lambda host, b, secs: {"host": host, "bytes": b, "secs": secs, "http": 206, "rc": 0}  # noqa: E731
    bad = {"host": "b", "bytes": 900_000, "secs": 0.1, "http": 403, "rc": 0}
    assert nw.throughput_mbps([ok("a", 5_000_000, 1.0), ok("a", 5_000_000, 1.0), ok("b", 5_000_000, 1.0), ok("b", 5_000_000, 1.0)])[0] == pytest.approx(160.0)
    mbps, total = nw.throughput_mbps([ok("a", 5_000_000, 1.0), ok("a", 5_000_000, 1.0), ok("b", 1_000_000, 8.0), bad])
    assert mbps == pytest.approx(80.0) and total == 11_000_000  # host a alone beats everything dragged down by host b's 8 s
    assert nw.throughput_mbps([bad]) == (0.0, 0)


# ---------------------------------------------------------------- UNKNOWN kinds, the gateway check and the outage ping


def test_no_answer_on_any_stream_is_an_internet_unknown_with_a_gateway_check_and_http_errors_are_not(nw):
    net = {"interface": "en0", "gateway": "192.0.2.1"}
    dead = lambda: nw.Res(28, "0 4.000 0 000", "curl: (28) Connection timed out")  # noqa: E731
    p = nw.do_probe(nw.Config(), net, host_runner(nw, dead, dead, ping=nw.Res(0)))
    assert p["unknown"] and p["unknown_kind"] == "internet" and p["gateway_ok"] is True
    runner = host_runner(nw, dead, dead, ping=nw.Res(2))
    p = nw.do_probe(nw.Config(), net, runner)
    assert p["gateway_ok"] is False
    pings = [a for a in runner.seen if a[0] == "ping"]
    assert pings == [["ping", "-c", "2", "-t", "3", "-b", "en0", "192.0.2.1"]]  # bound to the physical link, to the gateway
    busy = lambda: nw.Res(0, "312 0.2 1560 429")  # noqa: E731
    runner = host_runner(nw, busy, busy)
    p = nw.do_probe(nw.Config(), net, runner)
    assert p["unknown"] and p["unknown_kind"] == "cdn" and "gateway_ok" not in p and not [a for a in runner.seen if a[0] == "ping"]


def test_a_long_outage_with_home_verified_pings_once_and_never_reboots(nw):
    r = Rig(nw)
    r.sample(100)
    r.next_unknown, r.next_kind = "no stream got an HTTP answer", "internet"
    for _ in range(3):
        r.sample(0.0, 300)
    assert len(r.pings) == 1 and "internet unusable at home" in r.pings[0] and "the gateway answers" in r.pings[0]
    for _ in range(40):
        r.sample(0.0, 300)
    assert len(r.pings) == 1 and r.reboots == [] and r.snaps == [] and r.st["episode"] is None  # once, not every tick
    r.next_unknown, r.next_kind = "", ""
    r.sample(100, 300)  # the internet answered: the next outage is a new one
    r.next_unknown, r.next_kind = "no stream got an HTTP answer", "internet"
    for _ in range(3):
        r.sample(0.0, 300)
    assert len(r.pings) == 2


def test_outage_ping_waits_for_sustain_min_and_needs_no_answer_not_just_cdn_errors(nw):
    r = Rig(nw)
    r.next_unknown, r.next_kind = "no stream got an HTTP answer", "internet"
    for _ in range(2):
        r.sample(0.0, 300)  # 5 min: not yet
    assert r.pings == []
    r2 = Rig(nw)
    r2.next_unknown, r2.next_kind = "every stream got an HTTP status outside 2xx", "cdn"
    for _ in range(40):
        r2.sample(0.0, 300)
    assert r2.pings == []  # a CDN that answers with errors is the CDN's problem
    r3 = Rig(nw)
    r3.next_unknown, r3.next_kind = "x", "internet"
    r3.sample(0.0, 300)
    r3.sample(0.0, 4000)  # the Mac slept: the outage clock restarts
    r3.sample(0.0, 300)
    assert r3.pings == []


# ---------------------------------------------------------------- reboot.trigger


def episode_for(nw, trigger, direct, default, minutes=13):
    r = Rig(nw, cfg=C(nw, reboot_trigger=trigger))
    r.next_default = default if isinstance(default, dict) else {"mbps": default}
    for _ in range(minutes):
        r.sample(direct)
    return r


@pytest.mark.parametrize("trigger,direct,default,reboots", [
    ("direct", 5, 100, 1), ("direct", 100, 5, 0), ("direct", 5, 5, 1), ("direct", 100, 100, 0),
    ("tunnel", 100, 5, 1), ("tunnel", 5, 100, 0), ("tunnel", 5, 5, 1), ("tunnel", 100, 100, 0),
    ("either", 5, 100, 1), ("either", 100, 5, 1), ("either", 5, 5, 1), ("either", 100, 100, 0),
])
def test_reboot_trigger_picks_which_slow_path_arms_the_episode_and_so_the_one_reboot(nw, trigger, direct, default, reboots):
    r = episode_for(nw, trigger, direct, default)
    assert len(r.reboots) == reboots and (r.st["episode"] is not None) == bool(reboots) and len(r.pings) == reboots


@pytest.mark.parametrize("trigger", ["direct", "tunnel", "either"])
def test_every_trigger_keeps_once_per_episode_and_the_cooldown(nw, trigger):
    r = episode_for(nw, trigger, 5, 5)
    for _ in range(60):
        r.sample(5)
    assert len(r.reboots) == 1  # still slow for an hour: not again
    r.next_default = {"mbps": 100.0}
    r.sample(100)
    r.sample(100)
    r.next_default = {"mbps": 5.0}
    for _ in range(13):
        r.sample(5)  # a new episode inside the 2 h cooldown
    assert len(r.reboots) == 1 and "skipped: cooldown" in r.pings[-1]
    r.t += 3 * 3600
    r.next_default = {"mbps": 100.0}
    r.sample(100)
    r.sample(100)
    r.next_default = {"mbps": 5.0}
    for _ in range(13):
        r.sample(5)
    assert len(r.reboots) == 2


def test_an_unmeasurable_tunnel_is_unknown_when_the_trigger_is_tunnel_and_ignored_for_either(nw):
    broken = {"mbps": 0.0, "unknown": "every stream failed"}
    r = episode_for(nw, "tunnel", 5, broken, minutes=30)
    assert r.reboots == [] and r.pings == [] and r.st["episode"] is None  # cannot judge the tunnel: no verdict
    r = episode_for(nw, "either", 5, broken)
    assert len(r.reboots) == 1  # the direct path alone is enough for "either"
    r = episode_for(nw, "either", 100, broken, minutes=30)
    assert r.reboots == [] and r.st["episode"] is None


def test_trigger_other_than_direct_names_both_paths_in_the_start_ping_and_direct_does_not(nw):
    assert "[trigger" not in episode_for(nw, "direct", 5, 5).pings[0]
    ping = episode_for(nw, "tunnel", 100, 4.0).pings[0]
    assert "download 4.0 Mbps" in ping and "[trigger tunnel: direct 100.0, default route 4.0 Mbps]" in ping


# ---------------------------------------------------------------- tunnel in/out diagnostic (never a verdict)


def test_a_tunnel_default_route_gets_one_upload_through_it_recorded_apart_from_the_download(nw):
    cf = lambda: nw.Res(0, "5000000 0.7 7142857 206")  # noqa: E731
    runner = host_runner(nw, cf, cf)
    calls = []

    def run2(argv, t, env=None):
        calls.append(argv)
        return nw.Res(0, "1000000 2.0 500000 200") if "-X" in argv else runner(argv, t, env)

    p = nw.do_probe(nw.Config(), {"interface": "en0", "gateway": "g", "tunnel_iface": "utun4"}, run2)
    ups = [a for a in calls if "-X" in a]
    tun = [a for a in ups if "--interface" not in a]
    direct = [a for a in ups if "--interface" in a]
    assert len(ups) == 2 and len(tun) == 1 and len(direct) == 1 and direct[0][direct[0].index("--interface") + 1] == "en0"
    assert tun[0][-1] == nw.UP_URL and tun[0][tun[0].index("--data-binary") + 1].startswith("@")
    assert p["default_route"]["up"] == {"mbps": 4.0, "bytes": 1_000_000, "ok": True, "http": 200, "via": "utun4"}
    assert p["up"] == {"mbps": 4.0, "bytes": 1_000_000, "ok": True, "http": 200, "via": "en0"}  # the home uplink, recorded apart
    assert p["default_route"]["mbps"] > 50  # inbound through the tunnel is its own number
    calls.clear()
    nw.do_probe(nw.Config(), {"interface": "en0", "gateway": "g", "tunnel_iface": ""}, run2)
    only = [a for a in calls if "-X" in a]
    assert len(only) == 1 and only[0][only[0].index("--interface") + 1] == "en0"  # no tunnel: only the direct-path upload
    calls.clear()
    dead = lambda: nw.Res(6, "0 0 0 000")  # noqa: E731
    p = nw.do_probe(nw.Config(), {"interface": "en0", "gateway": "g", "tunnel_iface": "utun4"}, host_runner(nw, dead, dead))
    assert p["unknown"] and "up" not in p["default_route"] and "up" not in p  # an unknown sample moves no extra bytes


def test_a_failed_or_slow_tunnel_upload_never_changes_the_verdict(nw):
    r = Rig(nw)
    r.next_default = {"mbps": 90.0, "up": {"mbps": 0.4, "ok": True, "bytes": 1_000_000, "http": 200, "via": "utun4"}}
    for _ in range(30):
        r.sample(100)
    assert r.pings == [] and r.st["episode"] is None
    assert r.st["samples"][-1]["default_up_mbps"] == 0.4 and r.st["samples"][-1]["slow"] is False


def test_discovery_reports_the_tunnel_that_is_the_default_route(nw):
    assert nw.parse_netstat_tunnel(NETSTAT) == "utun4"
    assert nw.parse_netstat_tunnel("default 192.0.2.1 UGScg en0\n") == ""
    outs = {"netstat": nw.Res(0, NETSTAT), "arp": nw.Res(0, "? (192.0.2.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]")}
    assert nw.discover_net(C(nw), lambda argv, t, env=None: outs.get(argv[0], nw.Res(1)))["tunnel_iface"] == "utun4"


def test_the_default_route_sample_is_judged_by_the_same_rules_as_the_direct_one(nw):
    def runner(argv, t, env=None):
        return nw.Res(0, "5000000 1.0 5000000 206") if "--interface" in argv else nw.Res(0, "300 0.1 3000 403")

    p = nw.do_probe(nw.Config(), {"interface": "en0", "gateway": "g"}, runner)
    assert not p["unknown"] and p["default_route"]["mbps"] == 0.0 and "HTTP status" in p["default_route"]["unknown"]  # a 403 body is not throughput


# ---------------------------------------------------------------- one lost ARP reply is not "left home"


def flapping_episode(nw):
    r = Rig(nw, cfg=C(nw, reboot_after_min=30))
    r.run_slow(12)
    assert len(r.pings) == 1 and r.st["episode"] is not None
    return r


def test_an_unreadable_identity_for_two_ticks_does_not_close_the_episode_or_restart_the_clock(nw):
    r = flapping_episode(nw)
    since = r.st["episode"]["start_t"]
    r.home, r.unsure = False, True
    r.sample(2)
    r.sample(2)
    assert r.st["episode"] is not None and len(r.pings) == 1
    r.home, r.unsure = True, False
    r.run_slow(3)
    assert len(r.pings) == 1 and r.st["episode"]["start_t"] == since  # one start ping, the same episode, no second reboot decision


def test_an_identity_unreadable_for_longer_closes_it_as_away_and_positive_evidence_closes_at_once(nw):
    r = flapping_episode(nw)
    r.home, r.unsure = False, True
    for _ in range(3):
        r.sample(2)
    assert len(r.pings) == 2 and "left the home network" in r.pings[1] and r.st["episode"] is None
    r = flapping_episode(nw)
    r.home, r.unsure = False, False  # the MAC is readable and differs: another network
    r.sample(2)
    assert len(r.pings) == 2 and "left the home network" in r.pings[1] and r.st["episode"] is None


def test_an_unsure_tick_keeps_a_pending_slow_clock_and_a_known_other_network_resets_it(nw):
    r = Rig(nw)
    r.run_slow(5)
    since = r.st["slow_since"]
    r.home, r.unsure = False, True
    r.sample(2)
    r.sample(2)
    assert r.st["slow_since"] == since and r.probes == 5
    r.home, r.unsure = False, False
    r.sample(2)
    assert r.st["slow_since"] is None  # no episode open: only _not_measuring resets it


def test_discovery_marks_a_missing_mac_unsure_and_a_different_mac_not(nw):
    net = lambda arp: nw.discover_net(C(nw), lambda argv, t, env=None: nw.Res(0, NETSTAT) if argv[0] == "netstat" else arp(argv))  # noqa: E731
    d = net(lambda argv: nw.Res(1) if argv[0] == "arp" else nw.Res(0))
    assert d["home"] is False and d["home_unsure"] is True
    d = net(lambda argv: nw.Res(0, "? (192.0.2.1) at 11:22:33:44:55:66 on en0 ifscope [ethernet]") if argv[0] == "arp" else nw.Res(0))
    assert d["home"] is False and d["home_unsure"] is False
    d = net(lambda argv: nw.Res(0, "? (192.0.2.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]") if argv[0] == "arp" else nw.Res(0))
    assert d["home"] is True and d["home_unsure"] is False
    assert nw.home_unsure(nw.Config(), {"interface": "", "gateway_mac": ""}) is False  # not configured: never "maybe home"


def test_a_gateway_mac_that_can_never_be_read_sends_one_tool_error_ping_after_half_an_hour(nw):
    r = Rig(nw)
    r.deps.discover = lambda cfg: {"interface": "en0", "gateway": "192.0.2.1", "gateway_mac": "", "source": "t", "home": False,
                                   "home_why": "gateway MAC unknown (arp has no entry)", "home_unsure": True}
    for _ in range(25):
        r.sample(2)
    assert r.pings == []
    for _ in range(30):
        r.sample(2)
    assert len(r.pings) == 1 and "inert" in r.pings[0] and "cannot be read" in r.pings[0]
    assert r.probes == 0 and r.reboots == []


def test_priming_ping_goes_to_the_gateway_with_a_short_timeout_and_only_when_arp_missed(nw):
    seen = []

    def runner(argv, t, env=None):
        seen.append(argv)
        return nw.Res(0, NETSTAT) if argv[0] == "netstat" else nw.Res(0, "? (192.0.2.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]")

    nw.discover_net(C(nw), runner)
    assert not [a for a in seen if a[0] == "ping"]  # arp hit: no ping
    arp = [nw.Res(1), nw.Res(0, "? (192.0.2.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]")]
    seen.clear()
    nw.discover_net(C(nw), lambda argv, t, env=None: seen.append(argv) or (nw.Res(0, NETSTAT) if argv[0] == "netstat" else (arp.pop(0) if argv[0] == "arp" else nw.Res(0))))
    assert [a for a in seen if a[0] == "ping"] == [["ping", "-c", "1", "-t", "2", "192.0.2.1"]]


# ---------------------------------------------------------------- a chronic slowdown does not reboot the mesh every 12 h


def test_after_an_abandoned_episode_no_automatic_reboot_until_a_healthy_sample(nw):
    r = Rig(nw, cfg=C(nw, episode_max_h=1, reboot_min_cooldown_h=0.5))
    r.run_slow(100)  # episode at 10 min, reboot, abandoned at 70 min, a second episode at ~80 min
    assert len(r.reboots) == 1
    starts = [p for p in r.pings if "download" in p and "Mbps (baseline" in p]
    assert len(starts) == 2 and "skipped: an earlier episode was abandoned" in starts[1]
    assert any("abandoned after" in p for p in r.pings)
    r.run_slow(300)  # hours later, still slow: never again
    assert len(r.reboots) == 1
    r.sample(100)  # a healthy sample re-arms it
    r.sample(100)
    r.run_slow(12)
    assert len(r.reboots) == 2


def test_gap_and_away_closes_do_not_block_the_next_reboot(nw):
    r = Rig(nw, cfg=C(nw, reboot_min_cooldown_h=0.0, reboot_after_min=30))
    r.run_slow(12)
    r.t += 3600
    r.sample(5)  # asleep inside the episode: closed as a gap
    assert r.st["last_episode"]["end_reason"] == "gap" and not r.st.get("reboot_blocked")


def test_at_most_max_per_day_automatic_reboots_in_any_24_hours(nw):
    r = Rig(nw, cfg=C(nw, reboot_min_cooldown_h=0.0, reboot_max_per_day=2))
    for _ in range(3):
        r.run_slow(12)
        r.sample(100)
        r.sample(100)
    assert len(r.reboots) == 2
    assert "reboot.max_per_day = 2" in [p for p in r.pings if "Mbps (baseline" in p][2]
    r.t += 24 * 3600 + 60
    r.run_slow(12)
    assert len(r.reboots) == 3


def test_a_delayed_reboot_rechecks_the_daily_limit_when_it_finally_fires(nw):
    r = Rig(nw, cfg=C(nw, reboot_min_cooldown_h=0.0, reboot_max_per_day=1, reboot_after_min=20))
    r.run_slow(12)
    assert r.st["episode"]["reboot"]["state"] == "pending"
    r.st["reboot_log"] = [r.t - 60]  # a manual reboot used the day's allowance meanwhile
    r.run_slow(10)
    assert r.reboots == [] and r.st["episode"]["reboot"]["state"] == "skipped" and "max_per_day" in r.st["episode"]["reboot"]["reason"]


# ---------------------------------------------------------------- the end ping does not claim an unconfirmed reboot


@pytest.mark.parametrize("confirmed,words", [(False, "UNCONFIRMED"), (True, "reboot done at")])
def test_end_ping_says_unconfirmed_when_the_helper_did_not_see_the_mesh_drop_and_return(nw, confirmed, words):
    r = Rig(nw, reboot_result={"ok": True, "outcome": "requested for 2 node(s)", "confirmed": confirmed})
    r.run_slow(13)
    r.sample(100)
    r.sample(100)
    assert words in r.pings[-1] and (confirmed or "reboot done at" not in r.pings[-1])


def test_a_refused_login_while_polling_does_not_count_as_the_mesh_going_down(deco):
    res, _ = deco.run("reboot", "h", {"DECO_ADMIN_USER": "u", "DECO_ADMIN_PASSWORD": "p"}, FakeClient, (FakeDecoError,), sleep=lambda s: None,
                      clock=iter(range(0, 1000)).__next__, confirm_s=60.0) if not setattr(FakeClient, "logins", [None, FakeDecoError("session busy"), None]) and not setattr(FakeClient, "reboot_exc", TimeoutError("t")) else (None, 0)
    assert res["ok"] and res["confirmed"] is False  # one refused login then a good one is not a reboot
    FakeClient.logins, FakeClient.reboot_exc = [None, FakeDecoError("transport"), None], TimeoutError("t")
    res, _ = deco.run("reboot", "h", {"DECO_ADMIN_USER": "u", "DECO_ADMIN_PASSWORD": "p"}, FakeClient, (FakeDecoError,), sleep=lambda s: None,
                      clock=iter(range(0, 1000)).__next__, confirm_s=60.0, link_errors=(FakeDecoError,))
    assert res["ok"] and res["confirmed"] is True  # the library's own TransportError is a link failure when named as one


# ---------------------------------------------------------------- manual reboot after an automatic one


def test_a_manual_reboot_that_waited_for_the_lock_refuses_when_a_tick_rebooted_meanwhile(nw, monkeypatch, capsys):
    r = Rig(nw)

    class Interloper:  # the tick that held the lock rebooted the mesh before we got it
        def __init__(self, path, wait_s=0.0):
            pass

        def __enter__(self):
            st = nw.load_state()
            st["last_reboot_t"] = r.t - 30
            nw.save_state(st)
            return self

        def __exit__(self, *a):
            return None

    monkeypatch.setattr(nw, "lock", Interloper)
    assert nw.cmd_reboot(reboot_args(), r.cfg, r.deps) == 1
    assert r.reboots == [] and "an automatic reboot just ran" in capsys.readouterr().out
    monkeypatch.undo()


# ---------------------------------------------------------------- config validation of [reboot]


def test_reboot_table_values_are_type_checked_and_a_bad_one_never_enables_a_reboot_or_raises(nw, tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[reboot]\nenabled = "false"\nmin_cooldown_h = "2h"\nafter_min = -5\nmax_per_day = 0\ntrigger = "sometimes"\n')
    cfg = nw.load_config(p)
    assert cfg.reboot_enabled is False and cfg.reboot_min_cooldown_h == 2.0 and cfg.reboot_after_min == 10.0
    assert cfg.reboot_max_per_day == 3 and cfg.reboot_trigger == "direct"
    p.write_text('reboot = "enabled trigger"\n')
    assert nw.load_config(p).reboot_enabled is True
    p.write_text('[reboot]\nenabled = true\nmin_cooldown_h = 0.5\nafter_min = 0\nmax_per_day = 5\ntrigger = "either"\n')
    cfg = nw.load_config(p)
    assert (cfg.reboot_enabled, cfg.reboot_min_cooldown_h, cfg.reboot_after_min, cfg.reboot_max_per_day, cfg.reboot_trigger) == (True, 0.5, 0.0, 5, "either")
    p.write_text('[reboot]\nmax_per_day = 2.5\nmin_cooldown_h = true\n')
    cfg = nw.load_config(p)
    assert cfg.reboot_max_per_day == 3 and cfg.reboot_min_cooldown_h == 2.0


def test_helper_gets_the_real_user_and_password_values_not_swapped_or_empty(nw):
    set_creds(nw)
    seen = {}
    nw.deco_run("info", "192.0.2.1", lambda argv, t, env=None: seen.update(env=env) or nw.Res(0, json.dumps({"ok": True, "info": {}})))
    assert seen["env"]["DECO_ADMIN_USER"] == FAKE_USER and seen["env"]["DECO_ADMIN_PASSWORD"] == FAKE_PW


def test_a_healthy_sample_outside_an_episode_re_arms_the_reboot_after_an_abandoned_one(nw):
    r = Rig(nw, cfg=C(nw, episode_max_h=1, reboot_min_cooldown_h=0.0))
    r.run_slow(65)  # reboot at 10 min, abandoned at ~61 min, a new slow clock running but no episode yet
    assert len(r.reboots) == 1 and r.st["reboot_blocked"] and r.st["episode"] is None
    r.sample(100)  # healthy while no episode is open
    assert not r.st.get("reboot_blocked")
    r.run_slow(12)
    assert len(r.reboots) == 2


def test_a_manual_reboot_counts_toward_the_daily_limit(nw, capsys):
    r = Rig(nw, cfg=C(nw, reboot_min_cooldown_h=0.0, reboot_max_per_day=1))
    assert nw.cmd_reboot(reboot_args(), r.cfg, r.deps) == 0
    r.st.update(nw.load_state())
    r.run_slow(12)
    assert len(r.reboots) == 1 and "max_per_day" in r.pings[0]  # the manual one used the only allowance; the tick did not add a second


def test_each_flap_gets_its_own_two_tick_grace(nw):
    r = flapping_episode(nw)
    for _ in range(2):
        r.home, r.unsure = False, True
        r.sample(2)
        r.sample(2)
        r.home, r.unsure = True, False
        r.run_slow(2)
    assert r.st["episode"] is not None and len(r.pings) == 1


def test_unmeasurable_tunnel_samples_do_not_count_toward_recovery_when_the_trigger_is_tunnel(nw):
    r = episode_for(nw, "tunnel", 100, 5)
    assert r.st["episode"] is not None and len(r.pings) == 1
    r.next_default = {"mbps": 0.0, "unknown": "every stream failed"}
    for _ in range(5):
        r.sample(100)  # direct is fine but the tunnel cannot be judged: not healthy, not slow
    assert r.st["episode"] is not None and len(r.pings) == 1 and r.st["healthy_streak"] == 0


# ---------------------------------------------------------------- the helper's HTTP goes through /usr/bin/curl (python sockets get EHOSTUNREACH on this Mac)


class FakeTransportError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class FakeTransport:
    timeout = 5.0
    _cookie = None


def stub_curl(tmp_path, monkeypatch, reply: bytes, rc: int):
    d = tmp_path / "stub"
    d.mkdir(exist_ok=True)
    (d / "curl").write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$STUB_DIR/argv"\nwhile [ $# -gt 0 ]; do [ "$1" = -K ] && cat "$2" > "$STUB_DIR/config"; shift; done\ncat > "$STUB_DIR/stdin"\ncat "$STUB_DIR/reply"\nexit $(cat "$STUB_DIR/rc")\n')
    (d / "curl").chmod(0o755)
    (d / "reply").write_bytes(reply)
    (d / "rc").write_text(str(rc))
    monkeypatch.setenv("STUB_DIR", str(d))
    return d


def curl_post(deco, d):
    import re
    return deco.make_curl_post(FakeTransportError, json.loads, re.compile(r"(sysauth=[a-f0-9]+)"), curl=str(d / "curl"))


def test_curl_transport_parses_the_last_header_block_keeps_the_cookie_and_sends_the_body_on_stdin(deco, tmp_path, monkeypatch):
    reply = b'HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: sysauth=abc123; path=/\r\n\r\n{"result": {"x": 1}}\n0.012'
    d = stub_curl(tmp_path, monkeypatch, reply, 0)
    post, t = curl_post(deco, d), FakeTransport()
    assert post(t, "https://192.0.2.1/login", b'{"operation": "read", "pw": "SECRET-BODY"}') == {"result": {"x": 1}}
    assert t._cookie == "sysauth=abc123"
    argv = (d / "argv").read_text().splitlines()
    assert argv[0] == "-sk" and "SECRET-BODY" not in " ".join(argv) and "@-" in argv and argv[-2] == "-K" and argv[-1].startswith("/dev/fd/")
    assert (d / "config").read_text() == 'url = "https://192.0.2.1/login"\n'
    assert "Expect:" in argv and "Accept-Encoding: identity" in argv and "Connection: close" in argv and "Content-Type: application/json" in argv
    assert (d / "stdin").read_bytes() == b'{"operation": "read", "pw": "SECRET-BODY"}'
    post(t, "https://192.0.2.1/x;stok=tok0123/y", b"{}")
    assert (d / "config").read_text() == 'url = "https://192.0.2.1/x;stok=tok0123/y"\nheader = "Cookie: sysauth=abc123"\n'
    argv_text = (d / "argv").read_text()
    assert "sysauth=" not in argv_text and "stok=" not in argv_text and "tok0123" not in argv_text and "abc123" not in argv_text


def test_curl_transport_session_secrets_never_reach_argv_or_an_error_message(deco, tmp_path, monkeypatch):
    d = stub_curl(tmp_path, monkeypatch, b"\n0.000", 7)  # never connected -> TransportError
    t = FakeTransport()
    t._cookie = "sysauth=deadbeef99"
    with pytest.raises(FakeTransportError) as e:
        curl_post(deco, d)(t, "https://192.0.2.1/cgi-bin/luci/;stok=feedface77/admin/device?form=device_list", b"{}")
    argv_text = (d / "argv").read_text()
    for secret in ("sysauth=", "stok=", "deadbeef99", "feedface77"):
        assert secret not in argv_text and secret not in str(e.value)
    assert "feedface77" in (d / "config").read_text() and "deadbeef99" in (d / "config").read_text()  # they did reach curl, via the fd
    d = stub_curl(tmp_path, monkeypatch, b"HTTP/1.1 403 Forbidden\r\n\r\n{}\n0.01", 0)  # HTTP error path
    with pytest.raises(FakeTransportError) as e:
        curl_post(deco, d)(t, "https://192.0.2.1/;stok=feedface77/x", b"{}")
    assert "feedface77" not in str(e.value) and "deadbeef99" not in str(e.value)
    assert deco._curl_quote('a"b\\c\nd') == '"a\\"b\\\\c\\nd"'


def test_curl_transport_failures_map_to_what_sent_then_dropped_expects(deco, tmp_path, monkeypatch):
    dead = b"HTTP/1.1 403 Forbidden\r\n\r\n{}\n0.01"
    d = stub_curl(tmp_path, monkeypatch, dead, 0)
    with pytest.raises(FakeTransportError) as e:
        curl_post(deco, d)(FakeTransport(), "https://h/", b"{}")
    assert e.value.status_code == 403 and deco.sent_then_dropped(e.value, (FakeTransportError,)) is False
    d = stub_curl(tmp_path, monkeypatch, b"\n0.000", 7)  # never connected
    with pytest.raises(FakeTransportError):
        curl_post(deco, d)(FakeTransport(), "https://h/", b"{}")
    d = stub_curl(tmp_path, monkeypatch, b"\n0.000", 28)  # connect timeout: not sent
    with pytest.raises(FakeTransportError):
        curl_post(deco, d)(FakeTransport(), "https://h/", b"{}")
    d = stub_curl(tmp_path, monkeypatch, b"\n0.011", 28)  # connected, then no answer: what a rebooting router does
    with pytest.raises(TimeoutError) as e:
        curl_post(deco, d)(FakeTransport(), "https://h/", b"{}")
    assert deco.sent_then_dropped(e.value, (FakeTransportError,)) is True
    d = stub_curl(tmp_path, monkeypatch, b"\n0.011", 52)  # empty reply
    with pytest.raises(ConnectionResetError) as e:
        curl_post(deco, d)(FakeTransport(), "https://h/", b"{}")
    assert deco.sent_then_dropped(e.value, (FakeTransportError,)) is True


# ---------------------------------------------------------------- install copies the repo's plist


def test_install_copies_the_repo_plist_whose_program_is_this_sites_net_watch_tick(nw, tmp_path, monkeypatch):
    import plistlib

    calls = []
    monkeypatch.setattr(nw, "run", lambda argv, timeout, env=None: calls.append(list(argv)) or nw.Res(0))
    monkeypatch.setattr(nw, "cmd_warm", lambda a, cfg, deps: 0)
    monkeypatch.setattr(nw, "HOME", tmp_path / "home")
    assert nw.main(["install"], cfg=C(nw)) == 0
    repo_plist = BIN.parent.parent / "macos" / "net-watch" / f"{nw.LABEL}.plist"
    dest = tmp_path / "home" / "Library/LaunchAgents" / f"{nw.LABEL}.plist"
    assert dest.read_bytes() == repo_plist.read_bytes()
    prog = plistlib.loads(dest.read_bytes())["ProgramArguments"]
    assert prog[0].endswith("site-djbclark/bin/net-watch-tick") and "tick" in prog[1:]
    assert [c[:2] for c in calls] == [["launchctl", "bootout"], ["launchctl", "bootstrap"]] and calls[1][3] == str(dest)


# ---------------------------------------------------------------- tunnel_degraded: tunnel-only collapse is an alert, never a reboot


def tunnel_rig(nw, **kw):
    r = Rig(nw, cfg=C(nw, **kw))
    r.next_default = {"mbps": 40.0}
    for _ in range(4):
        r.sample(100)  # healthy pairs: D0 = 100, T0 = 40
    return r


def degrade(r, n, tunnel=5.0, direct=100.0):
    r.next_default = {"mbps": tunnel}
    for _ in range(n):
        r.sample(direct)


def test_a_tunnel_only_collapse_gives_one_start_and_one_end_ping_a_snapshot_and_never_a_reboot(nw):
    r = tunnel_rig(nw)
    degrade(r, 3)
    assert len(r.pings) == 1 and r.reboots == []
    assert "tunnel-only slowdown" in r.pings[0] and "direct path is fine" in r.pings[0] and "no reboot attempted" in r.pings[0]
    assert r.snaps[-1].endswith("-tunnel-degraded") and r.st["episode"] is None
    degrade(r, 120)  # two hours of it: still one ping, still no reboot, however long (cooldown or not)
    assert len(r.pings) == 1 and r.reboots == [] and r.st["tunnel"]["ep"] is not None
    r.next_default = {"mbps": 40.0}
    r.sample(100)
    assert len(r.pings) == 1  # one healthy pair is not recovery
    r.sample(100)
    assert len(r.pings) == 2 and "over (the default route recovered)" in r.pings[1] and "no reboot was attempted" in r.pings[1]
    assert r.reboots == [] and r.st["tunnel"]["ep"] is None
    degrade(r, 3)
    assert len(r.pings) == 3  # a new collapse is a new episode with its own start ping


def test_three_consecutive_valid_pairs_are_needed_and_an_unmeasurable_tunnel_neither_counts_nor_resets(nw):
    r = tunnel_rig(nw)
    degrade(r, 2)
    r.next_default = {"mbps": 40.0}
    r.sample(100)  # a healthy pair in between: the count restarts
    degrade(r, 2)
    assert r.pings == []
    r.next_default = {"mbps": 0.0, "unknown": "every stream failed"}
    r.sample(100)  # timeout/error: not a pair
    assert r.pings == []
    degrade(r, 1)
    assert len(r.pings) == 1  # the 3rd valid degraded pair


def test_the_rule_needs_the_direct_path_fine_and_the_tunnel_far_below_both_its_baseline_and_the_direct_rate(nw):
    r = tunnel_rig(nw)
    degrade(r, 10, tunnel=5.0, direct=50.0)  # direct at 50% of D0: not "direct fine"
    assert r.pings == [] and r.st["tunnel"]["ep"] is None
    r = tunnel_rig(nw)
    degrade(r, 10, tunnel=12.0)  # 12 > 0.25 x 40: a slower tunnel, not a collapse
    assert r.pings == []
    r = tunnel_rig(nw)
    r.next_default = {"mbps": 100.0}
    for _ in range(4):
        r.sample(100)  # T0 is now ~70; a tunnel at 15 is below 0.25*T0 but T/D = 0.15 <= 0.2 so it alerts only if T0 says so
    degrade(r, 3, tunnel=15.0)
    assert len(r.pings) == 1


def test_baselines_are_frozen_while_degraded_so_a_long_collapse_does_not_become_the_new_normal(nw):
    r = tunnel_rig(nw)
    d0, t0 = nw.tunnel_baselines(r.st, r.t)
    degrade(r, 300)
    assert nw.tunnel_baselines(r.st, r.t) == (d0, t0) == (100.0, 40.0) and len(r.pings) == 1


def test_no_baseline_no_alert_and_a_tunnel_trigger_is_not_tunnel_degraded(nw):
    r = Rig(nw)
    r.next_default = {"mbps": 1.0}
    for _ in range(30):
        r.sample(100)
    assert r.pings == []  # never saw a healthy tunnel: nothing to compare with
    r = tunnel_rig(nw, reboot_trigger="tunnel")
    degrade(r, 13)
    assert len(r.reboots) == 1 and "tunnel-only" not in r.pings[0]  # the opt-in trigger makes it a normal episode


def test_when_the_direct_path_goes_slow_too_the_tunnel_episode_ends_and_the_normal_episode_may_reboot(nw):
    r = tunnel_rig(nw)
    degrade(r, 3)
    r.next_default = {"mbps": 3.0}
    for _ in range(14):
        r.sample(4.0)
    assert any("no longer tunnel-only" in p for p in r.pings) and len(r.reboots) == 1
    assert sum("tunnel-only slowdown" in p for p in r.pings) == 2 and r.st["tunnel"]["ep"] is None


def test_leaving_home_or_sleeping_closes_a_tunnel_episode_with_one_ping(nw):
    r = tunnel_rig(nw)
    degrade(r, 3)
    r.home = False
    r.sample(100)
    assert len(r.pings) == 2 and "left the home network" in r.pings[1] and r.st["tunnel"]["ep"] is None
    r = tunnel_rig(nw)
    degrade(r, 3)
    r.t += 3600
    r.sample(100)
    assert len(r.pings) == 2 and "no samples for over 3 intervals" in r.pings[1]
    r = tunnel_rig(nw, episode_max_h=1)
    degrade(r, 3)
    degrade(r, 70)
    assert any("abandoned after 1 h" in p for p in r.pings) and r.reboots == []


def test_a_tunnel_suspect_probes_every_minute_like_a_slow_sample(nw):
    r = tunnel_rig(nw)
    assert nw.interval_for(r.st, r.cfg) == r.cfg.healthy_interval_s
    degrade(r, 1)
    assert nw.interval_for(r.st, r.cfg) == r.cfg.slow_interval_s


def test_the_tunnel_must_also_be_far_below_the_direct_rate_not_just_its_own_baseline(nw):
    r = Rig(nw)
    r.next_default = {"mbps": 200.0}
    for _ in range(4):
        r.sample(60)  # an unusual link: the tunnel baseline (200) is above the direct one (60)
    degrade(r, 5, tunnel=40.0, direct=60.0)  # T <= 0.25*T0 = 50, but T/D = 0.67: the tunnel is not the problem
    assert r.pings == [] and r.st["tunnel"]["ep"] is None


# ---------------------------------------------------------------- ARP snapshot (Local Network privacy hides arp from this process)

ARP_AN = "? (192.0.2.1) at aa:b:cc:dd:ee:f on en0 ifscope [ethernet]\n? (192.0.2.77) at 11:22:33:44:55:66 on en0 ifscope [ethernet]\n"


def snap_net(nw, path, cfg=None, via_wrapper=True, runner=None, marker=None):
    """discover_net where `arp` finds nothing, reading the snapshot at `path`. As the wrapper's child (marker = this process's PID)
    unless via_wrapper is False (no marker at all) or `marker` names something else."""
    from unittest import mock

    nw.STATE_DIR = path.parent
    runner = runner or (lambda argv, t, env=None: nw.Res(0, NETSTAT) if argv[0] == "netstat" else nw.Res(1))
    env = {nw.ARP_SNAPSHOT_ENV: str(os.getpid()) if marker is None else marker} if via_wrapper else {}
    with mock.patch.dict(os.environ, env):
        if not via_wrapper:
            os.environ.pop(nw.ARP_SNAPSHOT_ENV, None)
        return nw.discover_net(cfg or C(nw, home_gateway_macs=["aa:0b:cc:dd:ee:0f"]), runner)


def header_for(pid):
    return f"# net-watch-tick pid {pid}\n"


def put_snapshot(nw, tmp_path, text=ARP_AN, mode=0o600, age=10, header=None):
    """A snapshot as the wrapper writes it, its first line naming this process (the reader's PID); header="" omits it."""
    import time

    p = tmp_path / "snapdir" / nw.ARP_SNAPSHOT_NAME
    p.parent.mkdir(exist_ok=True)
    p.write_text((header_for(os.getpid()) if header is None else header) + text)
    p.chmod(mode)
    t = time.time() - age
    os.utime(p, (t, t))
    return p


def as_the_reader(path):
    """Rewrite the header of a file a wrapper wrote so that it names this process, as if this process were that wrapper's child."""
    first, rest = path.read_text().split("\n", 1)
    assert first.startswith("# net-watch-tick pid ")
    path.write_text(header_for(os.getpid()) + rest)


def test_the_arp_snapshot_supplies_the_gateway_mac_when_arp_is_empty(nw, tmp_path):
    d = snap_net(nw, put_snapshot(nw, tmp_path))
    assert d["gateway_mac"] == "aa:0b:cc:dd:ee:0f" and d["arp_source"] == "snapshot" and d["home"] is True


def test_the_snapshot_is_used_only_by_a_process_the_wrapper_started(nw, tmp_path):
    p = put_snapshot(nw, tmp_path)  # fresh, valid, right MAC: manual probe/diagnose/reboot must still not trust it
    d = snap_net(nw, p, via_wrapper=False)
    assert d["gateway_mac"] == "" and d["arp_source"] == "arp" and d["home"] is False
    assert snap_net(nw, p, via_wrapper=True)["home"] is True


@pytest.mark.parametrize("marker", ["1", "0", "", "abc", "999999999"])
def test_a_marker_that_names_neither_this_process_nor_its_parent_gives_no_mac(nw, tmp_path, marker):
    # an inherited "1", or any other PID: the file names the same value, so only the marker check can refuse it
    assert snap_net(nw, put_snapshot(nw, tmp_path, header=header_for(marker)), marker=marker)["gateway_mac"] == ""


def test_the_marker_may_name_the_parent_because_uv_run_starts_python_as_the_wrappers_child(nw, tmp_path):
    ppid = str(os.getppid())
    d = snap_net(nw, put_snapshot(nw, tmp_path, header=header_for(ppid)), marker=ppid)
    assert d["gateway_mac"] == "aa:0b:cc:dd:ee:0f" and d["arp_source"] == "snapshot"


@pytest.mark.parametrize("head", [lambda: header_for(os.getpid() + 1), lambda: header_for(f"{os.getpid()}0"), lambda: header_for(os.getpid()).rstrip("\n") + " \n", lambda: ""])
def test_a_file_that_does_not_name_the_marked_pid_gives_no_mac(nw, tmp_path, head):
    # right marker, file written by another run (or by no wrapper): another PID, a longer number, a padded line, no header at all
    assert snap_net(nw, put_snapshot(nw, tmp_path, header=head()))["gateway_mac"] == ""


def test_the_header_must_be_the_first_line(nw, tmp_path):
    late = "? (192.0.2.1) at aa:0b:cc:dd:ee:0f on en0 ifscope [ethernet]\n" + header_for(os.getpid())
    assert snap_net(nw, put_snapshot(nw, tmp_path, header="", text=late))["gateway_mac"] == ""


def test_live_arp_wins_over_the_snapshot_and_is_marked_arp(nw, tmp_path):
    put_snapshot(nw, tmp_path)
    live = "? (192.0.2.1) at aa:0b:cc:dd:ee:0f on en0 ifscope [ethernet]"
    d = nw.discover_net(C(nw, home_gateway_macs=["aa:0b:cc:dd:ee:0f"]), lambda argv, t, env=None: nw.Res(0, NETSTAT if argv[0] == "netstat" else live))
    assert d["arp_source"] == "arp" and d["home"] is True


def test_a_snapshot_older_than_30_s_is_ignored(nw, tmp_path):
    assert nw.ARP_SNAPSHOT_MAX_AGE_S == 30
    assert snap_net(nw, put_snapshot(nw, tmp_path, age=25))["home"] is True
    d = snap_net(nw, put_snapshot(nw, tmp_path, age=35))
    assert d["gateway_mac"] == "" and d["arp_source"] == "arp" and d["home"] is False and d["home_unsure"] is True


def test_a_snapshot_dated_in_the_future_is_ignored(nw, tmp_path):
    assert snap_net(nw, put_snapshot(nw, tmp_path, age=-3600))["gateway_mac"] == ""


def test_a_symlinked_snapshot_is_ignored(nw, tmp_path):
    real = put_snapshot(nw, tmp_path)
    link = tmp_path / "linkdir" / nw.ARP_SNAPSHOT_NAME
    link.parent.mkdir()
    link.symlink_to(real)
    assert snap_net(nw, link)["gateway_mac"] == ""


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o602, 0o700, 0o666])
def test_a_snapshot_with_group_or_other_bits_is_ignored(nw, tmp_path, mode):
    assert snap_net(nw, put_snapshot(nw, tmp_path, mode=mode))["gateway_mac"] == ""


def test_a_tighter_than_0600_snapshot_is_accepted(nw, tmp_path):
    assert snap_net(nw, put_snapshot(nw, tmp_path, mode=0o400))["gateway_mac"] == "aa:0b:cc:dd:ee:0f"


def test_a_snapshot_owned_by_someone_else_is_ignored(nw, tmp_path, monkeypatch):
    p = put_snapshot(nw, tmp_path)
    uid = os.getuid()
    monkeypatch.setattr(nw.os, "getuid", lambda: uid + 1)
    assert snap_net(nw, p)["gateway_mac"] == ""


def test_a_snapshot_that_is_a_directory_or_missing_is_no_mac(nw, tmp_path):
    p = tmp_path / "snapdir" / nw.ARP_SNAPSHOT_NAME
    assert snap_net(nw, p)["gateway_mac"] == ""  # missing (and not even a directory)
    p.mkdir(parents=True)
    assert snap_net(nw, p)["gateway_mac"] == ""


def test_the_snapshot_needs_a_line_for_this_gateway_with_a_mac(nw, tmp_path):
    d = snap_net(nw, put_snapshot(nw, tmp_path, "? (192.0.2.77) at 11:22:33:44:55:66 on en0\n? (192.0.2.10) at aa:bb:cc:dd:ee:ff on en0\n"))
    assert d["gateway_mac"] == ""  # other hosts only; 192.0.2.10 is not 192.0.2.1
    d = snap_net(nw, put_snapshot(nw, tmp_path, "? (192.0.2.1) at (incomplete) on en0 ifscope [ethernet]\n"))
    assert d["gateway_mac"] == ""


def test_the_snapshot_line_must_be_on_the_discovered_interface(nw, tmp_path):
    two = "? (192.0.2.1) at 11:22:33:44:55:66 on en1 ifscope [ethernet]\n? (192.0.2.1) at aa:0b:cc:dd:ee:0f on en0 ifscope [ethernet]\n"
    assert snap_net(nw, put_snapshot(nw, tmp_path, two))["gateway_mac"] == "aa:0b:cc:dd:ee:0f"  # same IP on en1 first: en0's line wins
    only_other = "? (192.0.2.1) at aa:0b:cc:dd:ee:0f on en1 ifscope [ethernet]\n"
    assert snap_net(nw, put_snapshot(nw, tmp_path, only_other))["gateway_mac"] == ""
    assert snap_net(nw, put_snapshot(nw, tmp_path, "? (192.0.2.1) at aa:0b:cc:dd:ee:0f on en00 ifscope [ethernet]\n"))["gateway_mac"] == ""  # en0 is not en00
    assert snap_net(nw, put_snapshot(nw, tmp_path, "? (192.0.2.1) at aa:0b:cc:dd:ee:0f on en0\n"))["gateway_mac"] == "aa:0b:cc:dd:ee:0f"  # interface last on the line


def test_a_snapshot_mac_that_is_not_the_home_gateway_is_not_home(nw, tmp_path):
    d = snap_net(nw, put_snapshot(nw, tmp_path), C(nw, home_gateway_macs=["aa:bb:cc:dd:ee:ff"]))
    assert d["gateway_mac"] == "aa:0b:cc:dd:ee:0f" and d["arp_source"] == "snapshot"
    assert d["home"] is False and "not the home gateway" in d["home_why"] and d["home_unsure"] is False


# ---- bin/net-watch-tick

TICK = BIN.parent / "net-watch-tick"
HOME_NETSTAT = "Destination Gateway Flags Netif Expire\ndefault 192.0.2.99 UGScg utun4\ndefault link#25 UCSIg utun5\ndefault 192.0.2.1 UGScg en0\n"
FOREIGN_NETSTAT = "Destination Gateway Flags Netif Expire\ndefault 192.0.2.99 UGScg utun4\n"


def tick_rig(tmp_path, arp_out="? (192.0.2.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]", arp_rc=0, netstat_out=None):
    """A copy of the wrapper next to a stub `net-watch`, with stub arp/ping/netstat; nothing real is run."""
    import shutil

    bindir = tmp_path / "bin"
    bindir.mkdir()
    shutil.copy(TICK, bindir / "net-watch-tick")
    log = tmp_path / "calls.log"
    # the stub net-watch records its arguments, its own PID and whether the wrapper's marker reached it
    (bindir / "net-watch").write_text(
        f'#!/bin/bash\necho "net-watch $*" >> {log}\necho $$ > {tmp_path / "stub.pid"}\necho "${{NET_WATCH_VIA_TICK_WRAPPER-unset}}" > {tmp_path / "stub.env"}\n'
    )
    (tmp_path / "arp").write_text(f'#!/bin/bash\necho "arp $*" >> {log}\necho "{arp_out}"\nexit {arp_rc}\n')
    (tmp_path / "ping").write_text(f'#!/bin/bash\necho "ping $*" >> {log}\nexit 1\n')
    set_netstat(tmp_path, netstat_out if netstat_out is not None else HOME_NETSTAT)
    for f in (bindir / "net-watch", bindir / "net-watch-tick", tmp_path / "arp", tmp_path / "ping"):
        f.chmod(0o755)
    env = {**os.environ, "NW_ARP": str(tmp_path / "arp"), "NW_PING": str(tmp_path / "ping"), "NW_NETSTAT": str(tmp_path / "netstat"),
           "NET_WATCH_STATE_DIR": str(tmp_path / "state" / "nw"), "HOME": str(tmp_path / "home")}
    env.pop("NET_WATCH_VIA_TICK_WRAPPER", None)  # only the wrapper may set it
    return bindir / "net-watch-tick", env, log


def set_netstat(tmp_path, out):
    log = tmp_path / "calls.log"
    (tmp_path / "netstat").write_text(f'#!/bin/bash\necho "netstat $*" >> {log}\ncat <<\'EOT\'\n{out}EOT\n')
    (tmp_path / "netstat").chmod(0o755)


def spawn(tick, env, *args):
    """Run the wrapper with launchd's umask (022), not whatever an earlier test left in this process."""
    import subprocess

    return subprocess.Popen([str(tick), *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=lambda: os.umask(0o022))


def run_wrapper(tick, env, *args):
    from types import SimpleNamespace

    p = spawn(tick, env, *args)
    out, err = p.communicate(timeout=30)
    return SimpleNamespace(returncode=p.returncode, stdout=out, stderr=err)


def run_tick(tmp_path, *args, **kw):
    tick, env, log = tick_rig(tmp_path, **kw)
    r = run_wrapper(tick, env, *args)
    return r, Path(env["NET_WATCH_STATE_DIR"]), (log.read_text().splitlines() if log.exists() else [])


def test_the_wrapper_snapshots_arp_privately_then_execs_net_watch_with_its_arguments(tmp_path):
    r, state, calls = run_tick(tmp_path, "tick")
    assert r.returncode == 0
    snap = state / "arp.snapshot"
    pid = (tmp_path / "stub.pid").read_text().strip()
    # first line binds the file to the wrapper's PID (the exec'd process keeps it), then the arp output untouched
    assert snap.read_text().splitlines() == [f"# net-watch-tick pid {pid}", "? (192.0.2.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]"]
    assert (snap.stat().st_mode & 0o777) == 0o600 and (state.stat().st_mode & 0o777) == 0o700
    assert [p.name for p in state.iterdir()] == ["arp.snapshot"]  # the temp file was moved, not left behind
    assert calls == ["netstat -rn -f inet", "ping -c 1 -t 2 192.0.2.1", "arp -an", "net-watch tick"]  # tunnel default skipped; ping before arp; exec last


def test_the_wrapper_exports_its_own_pid_once_the_snapshot_is_in_place(tmp_path):
    run_tick(tmp_path, "tick")
    assert (tmp_path / "stub.env").read_text().strip() == (tmp_path / "stub.pid").read_text().strip()


def _marker_after(tmp_path, setup=None, **kw):
    """What a net-watch started by the wrapper sees in the marker, when the caller's environment already had NET_WATCH_VIA_TICK_WRAPPER=1."""
    tick, env, log = tick_rig(tmp_path, **kw)
    env["NET_WATCH_VIA_TICK_WRAPPER"] = "1"
    state = Path(env["NET_WATCH_STATE_DIR"])
    if setup:
        setup(state)
    assert run_wrapper(tick, env, "tick").returncode == 0
    return (tmp_path / "stub.env").read_text().strip()


def test_a_skipped_or_failed_snapshot_exports_nothing_and_drops_an_inherited_marker(tmp_path):
    def case(name, **kw):
        d = tmp_path / name
        d.mkdir()
        return _marker_after(d, **kw)

    assert case("foreign", netstat_out=FOREIGN_NETSTAT) == "unset"
    assert case("arp-fails", arp_rc=1) == "unset"
    assert case("dir-in-the-way", setup=lambda s: (s / "arp.snapshot").mkdir(parents=True)) == "unset"
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, so the state dir cannot be created")
    d = tmp_path / "no-state"
    d.mkdir()
    tick, env, log = tick_rig(d)
    env["NET_WATCH_STATE_DIR"] = str(blocker / "nw")
    env["NET_WATCH_VIA_TICK_WRAPPER"] = "1"
    assert run_wrapper(tick, env, "tick").returncode == 0
    assert (d / "stub.env").read_text().strip() == "unset"
    working = case("working")  # the success case replaces the caller's "1" with the wrapper's PID
    assert working == (tmp_path / "working" / "stub.pid").read_text().strip() != "1"


def test_the_wrapper_resolves_net_watch_through_a_symlink_to_itself(tmp_path):
    tick, env, log = tick_rig(tmp_path)
    link = tmp_path / "elsewhere" / "net-watch-tick"
    link.parent.mkdir()
    link.symlink_to(tick)
    assert run_wrapper(link, env, "tick").returncode == 0
    assert log.read_text().splitlines()[-1] == "net-watch tick"


def test_a_failing_arp_leaves_no_snapshot_and_still_runs_the_tick(tmp_path):
    r, state, calls = run_tick(tmp_path, "tick", arp_rc=1)
    assert r.returncode == 0 and calls[-1] == "net-watch tick"
    assert not (state / "arp.snapshot").exists() and list(state.iterdir()) == []


def test_a_failing_arp_removes_the_previous_snapshot(tmp_path):
    tick, env, log = tick_rig(tmp_path, arp_rc=1)
    state = Path(env["NET_WATCH_STATE_DIR"])
    state.mkdir(parents=True)
    (state / "arp.snapshot").write_text("old\n")
    assert run_wrapper(tick, env, "tick").returncode == 0
    assert list(state.iterdir()) == []  # an old file may describe another network


def test_no_physical_default_route_removes_the_previous_snapshot_and_still_ticks(tmp_path):
    tick, env, log = tick_rig(tmp_path, netstat_out=FOREIGN_NETSTAT)
    state = Path(env["NET_WATCH_STATE_DIR"])
    state.mkdir(parents=True)
    (state / "arp.snapshot").write_text("old\n")
    (state / "arp.snapshot.AbCdEf").write_text("stale temp\n")
    assert run_wrapper(tick, env, "tick").returncode == 0
    assert list(state.iterdir()) == [] and log.read_text().splitlines()[-1] == "net-watch tick"


def test_no_physical_default_route_skips_the_snapshot_and_still_ticks(tmp_path):
    r, state, calls = run_tick(tmp_path, "tick", netstat_out="default 192.0.2.99 UGScg utun4\ndefault 192.0.2.98 UGScg ipsec0\n")
    assert r.returncode == 0 and calls == ["netstat -rn -f inet", "net-watch tick"]
    assert not state.exists()


def test_a_directory_in_the_snapshot_place_is_left_alone_and_gets_no_temp_file(tmp_path):
    tick, env, log = tick_rig(tmp_path)
    state = Path(env["NET_WATCH_STATE_DIR"])
    (state / "arp.snapshot").mkdir(parents=True)
    assert run_wrapper(tick, env, "tick").returncode == 0
    assert [p.name for p in state.iterdir()] == ["arp.snapshot"] and list((state / "arp.snapshot").iterdir()) == []
    assert log.read_text().splitlines()[-1] == "net-watch tick"


def test_an_unwritable_state_dir_never_fails_the_tick(tmp_path):
    tick, env, log = tick_rig(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, so the state dir cannot be created")
    env["NET_WATCH_STATE_DIR"] = str(blocker / "nw")
    assert run_wrapper(tick, env, "tick").returncode == 0
    assert log.read_text().splitlines()[-1] == "net-watch tick"


def test_the_wrapper_exec_replaces_itself_and_passes_the_exit_status(tmp_path):
    tick, env, log = tick_rig(tmp_path)
    (tick.parent / "net-watch").write_text(f'#!/bin/bash\necho $$ > {tmp_path / "stub.pid"}\nexit 7\n')
    p = spawn(tick, env, "tick")
    p.communicate(timeout=30)
    assert p.returncode == 7
    assert int((tmp_path / "stub.pid").read_text()) == p.pid  # same process: exec, not a child


def test_the_wrapper_skips_exactly_the_interfaces_net_watch_calls_tunnels(nw, tmp_path):
    # every prefix net-watch calls a tunnel is skipped; en0, the fallback route in each netstat, is not (so no extra prefix either)
    for i, prefix in enumerate(nw.TUNNEL_PREFIXES):
        d = tmp_path / f"p{i}"
        d.mkdir()
        r, state, calls = run_tick(d, "tick", netstat_out=f"default 192.0.2.99 UGScg {prefix}3\ndefault 192.0.2.1 UGScg en0\n")
        assert "ping -c 1 -t 2 192.0.2.1" in calls and not any("192.0.2.99" in c for c in calls), prefix


def test_the_wrapper_needs_a_dotted_quad_gateway(tmp_path):
    r, state, calls = run_tick(tmp_path, "tick", netstat_out="default 192.0.2 UGScg en0\ndefault 192.0.2.1x UGScg en0\ndefault 192.0.2.1 UGScg en1\n")
    assert "ping -c 1 -t 2 192.0.2.1" in calls and len([c for c in calls if c.startswith("ping")]) == 1


def test_a_home_snapshot_never_makes_a_foreign_tick_look_like_home(nw, tmp_path):
    """PoC A: tick at home writes the snapshot; the next tick, on a network with only a tunnel default, must not read it."""
    tick, env, log = tick_rig(tmp_path)
    state = Path(env["NET_WATCH_STATE_DIR"])
    assert run_wrapper(tick, env, "tick").returncode == 0 and (state / "arp.snapshot").exists()
    # net-watch finds the gateway through scutil + ipconfig even when netstat shows only a tunnel
    def runner(argv, t, env=None):
        return {"netstat": nw.Res(0, FOREIGN_NETSTAT), "scutil": nw.Res(0, NWI), "ipconfig": nw.Res(0, "192.0.2.1\n")}.get(argv[0], nw.Res(1))

    cfg = C(nw, home_gateway_macs=["aa:bb:cc:dd:ee:ff"])
    as_the_reader(state / "arp.snapshot")
    assert snap_net(nw, state / "arp.snapshot", cfg, runner=runner)["home"] is True  # the hazard is real: a fresh home file this process may read passes
    set_netstat(tmp_path, FOREIGN_NETSTAT)
    assert run_wrapper(tick, env, "tick").returncode == 0
    assert not (state / "arp.snapshot").exists()
    d = snap_net(nw, state / "arp.snapshot", cfg, runner=runner)
    assert d["home"] is False and d["gateway_mac"] == "" and d["gateway"] == "192.0.2.1"


def foreign_runner(nw):
    """A foreign network as net-watch sees it: only a tunnel default in netstat, the gateway (the home IP) from scutil + ipconfig."""
    return lambda argv, t, env=None: {"netstat": nw.Res(0, FOREIGN_NETSTAT), "scutil": nw.Res(0, NWI), "ipconfig": nw.Res(0, "192.0.2.1\n")}.get(argv[0], nw.Res(1))


def test_poc_d_a_manual_net_watch_never_reads_a_home_snapshot_whatever_it_inherited(nw, tmp_path):
    tick, env, log = tick_rig(tmp_path)
    state = Path(env["NET_WATCH_STATE_DIR"])
    assert run_wrapper(tick, env, "tick").returncode == 0
    wrapper_pid = (tmp_path / "stub.pid").read_text().strip()
    cfg = C(nw, home_gateway_macs=["aa:bb:cc:dd:ee:ff"])  # fresh home file, foreign network with the same gateway IP
    assert snap_net(nw, state / "arp.snapshot", cfg, runner=foreign_runner(nw), via_wrapper=False)["home"] is False  # marker unset
    for marker in ("1", wrapper_pid):  # an inherited "1", or the (dead) wrapper's own PID
        d = snap_net(nw, state / "arp.snapshot", cfg, runner=foreign_runner(nw), marker=marker)
        assert d["home"] is False and d["gateway_mac"] == "", marker


def test_poc_e_a_home_runs_file_landing_after_a_foreign_runs_rm_is_never_trusted(nw, tmp_path):
    tick, env, log = tick_rig(tmp_path, netstat_out=FOREIGN_NETSTAT)
    state = Path(env["NET_WATCH_STATE_DIR"])
    state.mkdir(parents=True)
    # run A's `mv` lands while run B (foreign) is reading the routing table, i.e. after B's rm: B's netstat stub writes A's file
    (tmp_path / "netstat").write_text(
        f"#!/bin/bash\n(umask 077; printf '# net-watch-tick pid 424242\\n? (192.0.2.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]\\n' > {state}/arp.snapshot)\n"
        f"cat <<'EOT'\n{FOREIGN_NETSTAT}EOT\n"
    )
    assert run_wrapper(tick, env, "tick").returncode == 0
    assert (state / "arp.snapshot").exists()  # the interleave happened
    assert (tmp_path / "stub.env").read_text().strip() == "unset"  # B found no physical default: it exports nothing
    cfg = C(nw, home_gateway_macs=["aa:bb:cc:dd:ee:ff"])
    assert snap_net(nw, state / "arp.snapshot", cfg, runner=foreign_runner(nw), via_wrapper=False)["home"] is False
    # even if B's net-watch carried a marker naming itself, A's file names A
    d = snap_net(nw, state / "arp.snapshot", cfg, runner=foreign_runner(nw))
    assert d["home"] is False and d["gateway_mac"] == ""


@pytest.mark.parametrize("second_netstat", [FOREIGN_NETSTAT, HOME_NETSTAT])
def test_poc_f_a_snapshot_the_wrapper_cannot_delete_is_never_trusted(nw, tmp_path, second_netstat):
    tick, env, log = tick_rig(tmp_path)
    state = Path(env["NET_WATCH_STATE_DIR"])
    assert run_wrapper(tick, env, "tick").returncode == 0
    first_pid = (tmp_path / "stub.pid").read_text().strip()
    set_netstat(tmp_path, second_netstat)
    env["NET_WATCH_VIA_TICK_WRAPPER"] = "1"
    state.chmod(0o500)  # rm (and mv, and mktemp) fail
    try:
        assert run_wrapper(tick, env, "tick").returncode == 0
    finally:
        state.chmod(0o700)
    assert (state / "arp.snapshot").exists()  # the old file is still there
    assert (tmp_path / "stub.env").read_text().strip() == "unset"
    cfg = C(nw, home_gateway_macs=["aa:bb:cc:dd:ee:ff"])
    assert snap_net(nw, state / "arp.snapshot", cfg, runner=foreign_runner(nw), via_wrapper=False)["home"] is False
    for marker in ("1", first_pid):
        assert snap_net(nw, state / "arp.snapshot", cfg, runner=foreign_runner(nw), marker=marker)["home"] is False, marker


def test_a_temp_file_deleted_under_the_wrapper_is_recreated_owner_only(tmp_path):
    # another run's `rm arp.snapshot.??????` removes this run's temp file just after mktemp (a stub `chmod` plays that run; launchd umask 022)
    tick, env, log = tick_rig(tmp_path)
    state = Path(env["NET_WATCH_STATE_DIR"])
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "chmod").write_text(f"#!/bin/bash\nrm -f {state}/arp.snapshot.??????\n")
    (fake / "chmod").chmod(0o755)
    env["PATH"] = f"{fake}:{env['PATH']}"
    assert run_wrapper(tick, env, "tick").returncode == 0
    snap = state / "arp.snapshot"
    assert snap.exists() and (snap.stat().st_mode & 0o777) == 0o600  # recreated by the shell's own redirection under umask 077, not 0644
    pid = (tmp_path / "stub.pid").read_text().strip()
    assert snap.read_text().splitlines()[0] == f"# net-watch-tick pid {pid}"
