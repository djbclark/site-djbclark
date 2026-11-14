"""bin/paseo-local-upgrade: gate, swap, verify, rollback (2026-11-14). A fake runner models paseo and the app."""

import fcntl
import importlib.machinery
import importlib.util
import json
import os
import plistlib
import signal
import subprocess
import sys
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parent.parent / "bin" / "paseo-local-upgrade"
_loader = importlib.machinery.SourceFileLoader("paseo_local_upgrade", str(BIN))
_spec = importlib.util.spec_from_loader("paseo_local_upgrade", _loader)
plu = importlib.util.module_from_spec(_spec)
sys.modules["paseo_local_upgrade"] = plu  # dataclass looks its module up here
_loader.exec_module(plu)

UNSET = object()
IDLE = {"id": "a" * 32, "shortId": "aaaaaaa", "status": "idle", "name": "x", "cwd": "/w"}


def make_app(path: Path, version="0.16.0-beta.2", updater=False):
    (path / "Contents" / "Resources").mkdir(parents=True)
    with (path / "Contents" / "Info.plist").open("wb") as fh:
        plistlib.dump({"CFBundleIdentifier": "sh.paseo.desktop", "CFBundleShortVersionString": version}, fh)
    (path / "Contents/Resources/bin").mkdir()
    (path / "Contents/Resources/bin/paseo").write_text("#!/bin/sh\n")
    if updater:
        (path / "Contents/Resources/app-update.yml").write_text("provider: github\n")


class Fake:
    """Stands in for paseo, codesign, osascript, ps and open."""

    def __init__(self, tmp, agents=None, perms=None, bad_plugin=None, open_fails_after_swap=False,
                 status_unreadable_after_stop=False, app_never_quits=False, plugin_item_without_id=False,
                 busy_after_swap=False, ls_shape=UNSET, terminals=None, keeps_daemon_on_quit=False,
                 busy_after_quit=False, interrupt_on_open=False, plugin_item_without_id_always=False,
                 osascript_running_errors=False, fork_cli_broken=False, lsof_fails=False,
                 quit_request_fails=False, shipit_stays=False,
                 quit_needs_running=False):
        self.agents = agents if agents is not None else [dict(IDLE)]
        self.perms = perms or []
        self.bad_plugin = bad_plugin
        self.open_fails_after_swap = open_fails_after_swap
        self.status_unreadable_after_stop = status_unreadable_after_stop
        self.app_never_quits = app_never_quits
        self.plugin_item_without_id = plugin_item_without_id
        self.busy_after_swap = busy_after_swap
        self.ls_shape = ls_shape
        self.terminals = terminals or []
        self.keeps_daemon_on_quit = keeps_daemon_on_quit
        self.busy_after_quit = busy_after_quit
        self.interrupt_on_open = interrupt_on_open
        self.plugin_item_without_id_always = plugin_item_without_id_always
        self.osascript_running_errors = osascript_running_errors
        self.fork_cli_broken = fork_cli_broken  # the staged build's own CLI (and daemon start) does not work
        self.lsof_fails = lsof_fails
        self.quit_request_fails = quit_request_fails
        self.shipit_stays = shipit_stays
        self.quit_needs_running = quit_needs_running  # a quit sent to a closed app errors (-600)
        self.fork_cli_calls = 0
        self.daemon_up = True
        self.app_up = True
        self.pid = 100
        self.calls = []
        self.installed = tmp / "Paseo.app"

    def fork_installed(self):
        return not (self.installed / "Contents/Resources/app-update.yml").exists()

    def __call__(self, argv, timeout=60):
        self.calls.append(argv)
        head = argv[0]
        shim = "/Contents/Resources/bin/paseo"
        if head.endswith(shim):  # an absolute CLI path inside a bundle: only that bundle's CLI answers
            bundle = Path(head[: -len(shim)])
            if self.fork_cli_broken and not (bundle / "Contents/Resources/app-update.yml").exists():
                self.fork_cli_calls += 1
                return plu.Result(127, "", "Paseo Helper: no such file")
            head, argv = "paseo", ["paseo", *argv[1:]]
        if head == "ps":
            if "comm=" in argv[-1]:
                return plu.Result(0, "  77 /Users/x/Library/Caches/sh.paseo.desktop.ShipIt/ShipIt\n" if self.shipit_stays else "  1 /sbin/launchd\n")
            return plu.Result(0, "")
        if head == "codesign":
            if argv[1] == "-dv":
                return plu.Result(0, "", "Signature=adhoc\n" if self.fork_installed() else "Authority=Developer ID\n")
            return plu.Result(0)
        if head == "lsof":
            if self.lsof_fails:
                return plu.Result(1, "", "lsof: boom")
            return plu.Result(0, f"p{self.pid}\nn{self.installed}/Contents/MacOS/Paseo\n")
        if head == "osascript":
            if "is running" in argv[2]:
                if self.osascript_running_errors:
                    return plu.Result(1, "", "osascript: error")
                return plu.Result(0, "true\n" if self.app_up else "false\n")
            if self.quit_request_fails or (self.quit_needs_running and not self.app_up):
                return plu.Result(1, "", "not allowed to send Apple events")
            if not self.app_never_quits:
                self.app_up = False
                if not self.keeps_daemon_on_quit:
                    self.daemon_up = False  # the real default: quitting the app stops its daemon
            if self.busy_after_quit:
                self.agents = [{**IDLE, "status": "running", "name": "started-during-quit"}]
            return plu.Result(0)
        if head == "open":
            if self.interrupt_on_open and self.fork_installed():
                self.interrupt_on_open = False
                raise KeyboardInterrupt()
            if self.open_fails_after_swap and self.fork_installed():
                return plu.Result(1, "", "launch failed")
            if self.fork_cli_broken and self.fork_installed():
                return plu.Result(0)  # the fork launches, but its daemon never comes up
            self.app_up = self.daemon_up = True
            self.pid += 1
            if self.busy_after_swap and self.fork_installed():
                self.agents = [{**IDLE, "status": "running", "name": "resumed"}]
            return plu.Result(0)
        assert head == "paseo", argv
        sub = argv[1:]
        if sub[:2] == ["daemon", "stop"]:
            self.daemon_up = False
            return plu.Result(0)
        if sub[:2] == ["daemon", "status"]:
            if not self.daemon_up:
                if self.status_unreadable_after_stop:
                    return plu.Result(1, "", "DAEMON_REPLACED")
                return plu.Result(0, json.dumps({"localDaemon": "stopped", "pid": None}))
            return plu.Result(0, json.dumps({"localDaemon": "running", "pid": self.pid, "daemonVersion": "0.16.0-beta.2"}))
        if sub[0] in ("ls", "permit", "plugin", "terminal") and not self.daemon_up:
            return plu.Result(1, "", "connect ECONNREFUSED")  # the CLI does not autostart a daemon
        if sub[:2] == ["terminal", "ls"]:
            return plu.Result(0, json.dumps(self.terminals))
        if sub[0] == "ls":
            if self.ls_shape is not UNSET:
                return plu.Result(0, json.dumps(self.ls_shape))
            return plu.Result(0, json.dumps(self.agents))
        if sub[:2] == ["permit", "ls"]:
            return plu.Result(0, json.dumps(self.perms))
        if sub[:2] == ["plugin", "ls"]:
            ids = ["ade-yolo", "ade-claim", "baton"]
            plugins = [{"id": i, "enabled": True, "status": "running"} for i in ids]
            plugins.append({"id": "paseo-screen", "enabled": False, "status": "disabled"})
            if self.fork_installed() and self.bad_plugin:
                plugins = [p for p in plugins if p["id"] != self.bad_plugin]
            if self.plugin_item_without_id_always or (self.fork_installed() and self.plugin_item_without_id):
                plugins.append({"status": "running"})
            return plu.Result(0, json.dumps(plugins))
        raise AssertionError(argv)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(plu, "LOCK_DIR", str(tmp_path / "locks"))
    for var in ("PASEO_TERMINAL_ID", "PASEO_AGENT_ID"):  # the suite itself may run inside a Paseo agent
        monkeypatch.delenv(var, raising=False)
    make_app(tmp_path / "Paseo.app", updater=True)
    make_app(tmp_path / "Paseo-local.app", updater=False)
    return tmp_path


def run_main(env, fake, *extra, with_backup=True):
    argv = ["--installed", str(env / "Paseo.app"), "--staged", str(env / "Paseo-local.app"),
            "--state-dir", str(env / "state"), "--home", str(env / "home"),
            "--updater-cache", str(env / "updates"), "--shipit-cache", str(env / "shipit"),
            "--settle", "0", "--timeout", "1", *extra]
    if with_backup:
        argv += ["--backup", str(env / "Paseo-prev.app")]
    if "--apply" in extra and "--yes" not in extra and "--rollback" not in extra:
        argv.append("--yes")
    return plu.main(argv, runner=fake, sleep=lambda s: None)


def touched(fake):
    return any(c[:3] == ["paseo", "daemon", "stop"] or c[0] == "open"
               or (c[0] == "osascript" and "quit" in c[2]) for c in fake.calls)


def upstream_in_place(env):
    return (env / "Paseo.app/Contents/Resources/app-update.yml").exists()


def test_dry_run_changes_nothing(env):
    fake = Fake(env)
    assert run_main(env, fake) == 0
    assert not touched(fake)
    assert upstream_in_place(env) and (env / "Paseo-local.app").exists() and not (env / "Paseo-prev.app").exists()


def test_gate_refuses_running_agent_and_names_it(env, capsys):
    fake = Fake(env, agents=[{**IDLE, "id": "b" * 32, "shortId": "bbbbbbb", "status": "running", "name": "busy"}])
    assert run_main(env, fake, "--apply") == 4
    out = capsys.readouterr().out
    assert "bbbbbbb" in out and "busy" in out
    assert not touched(fake)


@pytest.mark.parametrize("status", ["initializing", "mystery"])
def test_gate_fails_closed_on_non_quiet_status(env, status):
    fake = Fake(env, agents=[{**IDLE, "status": status}])
    assert run_main(env, fake, "--apply") == 4
    assert not touched(fake)


def test_gate_lists_background_agents(env):
    fake = Fake(env)
    run_main(env, fake)
    ls = [c for c in fake.calls if c[0].endswith("paseo") and c[1] == "ls"]
    assert ls and all("-a" in c and "-g" in c for c in ls)


def test_gate_refuses_pending_permission(env, capsys):
    fake = Fake(env, perms=[{"id": "permission-1", "agentId": "c" * 32, "agentShortId": "ccccccc"}])
    assert run_main(env, fake, "--apply") == 4
    assert "permission-1" in capsys.readouterr().out
    assert not touched(fake)


@pytest.mark.parametrize("shape", [{}, None, {"agents": []}, [1, 2], "oops"])
def test_gate_fails_closed_on_bad_json_shape(env, shape):
    fake = Fake(env, ls_shape=shape)
    assert run_main(env, fake, "--apply") == 2
    assert not touched(fake)


def test_gate_runs_again_after_the_prompt(env):
    fake = Fake(env)
    real = plu.confirm
    plu.confirm = lambda yes: setattr(fake, "agents", [{**IDLE, "status": "running", "name": "late"}])
    try:
        assert run_main(env, fake, "--apply") == 4
    finally:
        plu.confirm = real
    assert not touched(fake) and upstream_in_place(env)


def test_apply_swaps_and_verifies(env):
    fake = Fake(env)
    assert run_main(env, fake, "--apply") == 0
    assert (env / "Paseo-prev.app/Contents/Resources/app-update.yml").exists()
    assert not upstream_in_place(env) and not (env / "Paseo-local.app").exists()
    assert json.loads((env / "state/last-run.json").read_text())["phase"] == "done"
    assert list((env / "state").glob("*-apply.log"))


def test_apply_never_kills_anything(env):
    fake = Fake(env)
    run_main(env, fake, "--apply")
    assert not any(c[0] in ("kill", "pkill", "killall") for c in fake.calls)


def test_disabled_plugin_is_not_a_failure(env):
    fake = Fake(env)
    assert run_main(env, fake, "--apply") == 0  # paseo-screen is disabled before and after


def test_missing_plugin_rolls_back(env):
    fake = Fake(env, bad_plugin="ade-yolo")
    assert run_main(env, fake, "--apply") == 1
    assert upstream_in_place(env) and (env / "Paseo-local.app").exists() and not (env / "Paseo-prev.app").exists()
    assert json.loads((env / "state/last-run.json").read_text())["phase"] == "rolled-back"


def test_want_broken_keeps_new_build(env):
    fake = Fake(env, bad_plugin="ade-yolo")
    assert run_main(env, fake, "--apply", "--want-broken") == 3
    assert not upstream_in_place(env) and (env / "Paseo-prev.app").exists()


def test_required_plugin_flag(env):
    fake = Fake(env)
    assert run_main(env, fake, "--apply", "--require-plugin", "not-installed") == 1
    assert upstream_in_place(env)


def test_open_failure_rolls_back(env):
    fake = Fake(env, open_fails_after_swap=True)
    assert run_main(env, fake, "--apply") == 1
    assert upstream_in_place(env)


def test_unexpected_json_after_swap_rolls_back(env):
    fake = Fake(env, plugin_item_without_id=True)
    assert run_main(env, fake, "--apply") == 1
    assert upstream_in_place(env)


def test_auto_rollback_is_gated(env):
    fake = Fake(env, busy_after_swap=True, bad_plugin="ade-yolo")
    assert run_main(env, fake, "--apply") == 4  # a gate refusal is 4, even for the automatic rollback
    stops = [c for c in fake.calls if c[:3] == ["paseo", "daemon", "stop"]]
    assert len(stops) <= 1  # the rollback never stopped the busy daemon
    assert not upstream_in_place(env)
    assert json.loads((env / "state/last-run.json").read_text())["phase"] == "failed-gated"


def test_unreadable_status_is_not_stopped(env):
    fake = Fake(env, status_unreadable_after_stop=True)
    assert run_main(env, fake, "--apply") == 1
    assert upstream_in_place(env) and (env / "Paseo-local.app").exists()  # never swapped


def test_app_that_will_not_quit_blocks_the_swap(env):
    fake = Fake(env, app_never_quits=True)
    assert run_main(env, fake, "--apply", "--want-broken") == 1  # before the swap, want-broken does not apply
    assert upstream_in_place(env) and (env / "Paseo-local.app").exists()
    assert fake.calls[-1][0] == "open"  # the old app is relaunched


def test_non_interactive_without_yes_refuses(env, monkeypatch):
    monkeypatch.setattr(plu.sys, "stdin", open("/dev/null"))
    fake2 = Fake(env)
    assert plu.main(["--installed", str(env / "Paseo.app"), "--staged", str(env / "Paseo-local.app"),
                     "--backup", str(env / "Paseo-prev.app"), "--state-dir", str(env / "state"),
                     "--home", str(env / "home"), "--updater-cache", str(env / "updates"),
                     "--shipit-cache", str(env / "shipit"), "--apply"], runner=fake2, sleep=lambda s: None) == 2
    assert not touched(fake2)


def test_existing_backup_blocks(env):
    make_app(env / "Paseo-prev.app")
    fake = Fake(env)
    assert run_main(env, fake, "--apply") == 2
    assert not touched(fake)


def test_symlinked_staged_app_is_refused(env, tmp_path_factory):
    real = env / "elsewhere.app"
    (env / "Paseo-local.app").rename(real)
    (env / "Paseo-local.app").symlink_to(real)
    fake = Fake(env)
    assert run_main(env, fake, "--apply") == 2
    assert not touched(fake)


def test_manual_rollback_after_upgrade(env):
    fake = Fake(env)
    assert run_main(env, fake, "--apply") == 0
    assert run_main(env, fake, "--rollback", "--apply", "--yes", with_backup=False) == 0
    assert upstream_in_place(env)
    assert (env / "Paseo-local.app").exists() and not (env / "Paseo-prev.app").exists()


def test_rollback_without_state_file_refuses_and_touches_nothing(env):
    fake = Fake(env)
    assert run_main(env, fake, "--rollback", "--apply", "--yes", with_backup=False) == 2
    assert not touched(fake) and upstream_in_place(env)


def test_rollback_is_gated_too(env):
    fake = Fake(env)
    run_main(env, fake, "--apply")
    fake.agents = [{**IDLE, "status": "running", "name": "w"}]
    assert run_main(env, fake, "--rollback", "--apply", "--yes", with_backup=False) == 4
    assert not upstream_in_place(env)


def test_second_run_is_locked_out(env):
    held = plu.open_lock(str(env / "home"))
    try:
        fcntl.flock(held, fcntl.LOCK_EX)
        fake = Fake(env)
        assert run_main(env, fake, "--apply") == 2
    finally:
        os.close(held)
    assert not touched(fake)


def test_lock_file_is_not_followed_through_a_symlink(env):
    plu.Path(plu.LOCK_DIR).mkdir(parents=True)
    decoy = env / "decoy"
    decoy.write_text("keep")
    held = plu.open_lock(str(env / "home"))
    os.close(held)
    lock = next(plu.Path(plu.LOCK_DIR).iterdir())
    lock.unlink()
    lock.symlink_to(decoy)
    assert run_main(env, Fake(env), "--apply") == 2
    assert decoy.read_text() == "keep"


def test_half_finished_rename_reports_where_bundles_are(env, monkeypatch):
    fake = Fake(env)
    real = plu.os.rename
    state = {"n": 0}

    def flaky(a, b):
        state["n"] += 1
        if state["n"] >= 2:  # second rename and the undo both fail
            raise OSError("disk says no")
        return real(a, b)

    monkeypatch.setattr(plu.os, "rename", flaky)
    assert run_main(env, fake, "--apply") == 3
    log = next((env / "state").glob("*-apply.log")).read_text()
    assert "STUCK" in log and str(env / "Paseo-prev.app") in log


def test_rollback_works_when_the_new_daemon_never_comes_up(env):
    """N1: the CLI fails with no daemon, so a gate that needs one would strand the broken build."""
    fake = Fake(env, open_fails_after_swap=True)
    assert run_main(env, fake, "--apply") == 1
    assert upstream_in_place(env)
    assert json.loads((env / "state/last-run.json").read_text())["phase"] == "rolled-back"


def test_manual_rollback_with_daemon_down_skips_the_gate(env):
    fake = Fake(env, open_fails_after_swap=True, bad_plugin="ade-yolo")
    run_main(env, fake, "--apply", "--want-broken")
    fake.daemon_up = False
    fake.open_fails_after_swap = False
    assert run_main(env, fake, "--rollback", "--apply", "--yes", with_backup=False) == 0
    assert upstream_in_place(env)


def test_terminals_refuse_and_are_named(env, capsys):
    fake = Fake(env, terminals=[{"id": "t" * 32, "name": "claude-tui", "cwd": "/w"}])
    assert run_main(env, fake, "--apply") == 4
    assert "claude-tui" in capsys.readouterr().out and not touched(fake)


def test_allow_terminals_lets_it_proceed(env):
    fake = Fake(env, terminals=[{"id": "t" * 32, "name": "sh", "cwd": "/w"}])
    assert run_main(env, fake, "--apply", "--allow-terminals") == 0


def test_refuses_inside_a_paseo_terminal_even_with_allow_terminals(env, monkeypatch):
    monkeypatch.setenv("PASEO_TERMINAL_ID", "abc")
    for extra in ((), ("--allow-terminals",)):
        fake = Fake(env)
        assert run_main(env, fake, "--apply", *extra) == 2
        assert not fake.calls


def test_refuses_when_a_paseo_app_is_an_ancestor(env, monkeypatch):
    monkeypatch.delenv("PASEO_TERMINAL_ID", raising=False)
    chain = {os.getpid(): "500 python3 paseo-local-upgrade", 500: "400 -zsh",
             400: "1 /Applications/Paseo.app/Contents/Frameworks/Paseo Helper.app/Contents/MacOS/Paseo Helper x"}

    def ps(argv, timeout=60):
        return plu.Result(0, chain[int(argv[-1])])

    assert "ancestor process 400" in plu.inside_paseo({}, ps)
    chain[400] = "1 /sbin/launchd"
    assert plu.inside_paseo({}, ps) is None


def test_gate_runs_again_after_the_app_quits(env):
    """N4: a daemon that outlives the app can start a turn while the script waits for the quit."""
    fake = Fake(env, keeps_daemon_on_quit=True, busy_after_quit=True)
    assert run_main(env, fake, "--apply") == 4
    assert not any(c[:3] == ["paseo", "daemon", "stop"] for c in fake.calls)
    assert upstream_in_place(env) and fake.calls[-1][0] == "open"  # the app is relaunched


def _pending(env, name):
    (env / "updates").mkdir(exist_ok=True)
    (env / "updates" / name).write_text("x")


@pytest.mark.parametrize("name", ["Paseo-0.16.0-beta.9-arm64.zip", "Paseo-0.16.0-beta.20-arm64.zip",
                                  "Paseo-0.16.0-beta.21-arm64.zip", "weird-name.zip"])
def test_pending_update_for_another_or_unreadable_version_refuses(env, name):
    _pending(env, name)  # beta.20 contains the installed version beta.2 as a substring
    fake = Fake(env)
    assert run_main(env, fake, "--apply") == 2
    assert not touched(fake)


def test_pending_update_for_the_installed_version_is_fine(env):
    _pending(env, "Paseo-0.16.0-beta.2-arm64.zip")
    assert run_main(env, Fake(env), "--apply") == 0


def test_installed_app_without_a_version_refuses_when_an_update_is_pending(env):
    (env / "Paseo.app/Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "sh.paseo.desktop"}))
    _pending(env, "Paseo-0.16.0-beta.2-arm64.zip")
    fake = Fake(env)
    assert run_main(env, fake, "--apply") == 2
    assert not touched(fake)


def test_update_downloaded_while_the_prompt_waits_refuses(env):
    fake = Fake(env)
    real = plu.confirm
    plu.confirm = lambda yes: _pending(env, "Paseo-0.16.0-beta.9-arm64.zip")
    try:
        assert run_main(env, fake, "--apply") == 2
    finally:
        plu.confirm = real
    assert not touched(fake) and upstream_in_place(env)


def test_shipit_leftovers_refuse(env):
    (env / "shipit" / "update.abc").mkdir(parents=True)
    fake = Fake(env)
    assert run_main(env, fake, "--apply") == 2
    assert not touched(fake)


def test_swap_waits_for_shipit_to_finish(env):
    fake = Fake(env, shipit_stays=True)
    assert run_main(env, fake, "--apply") == 1  # timed out before the swap
    assert upstream_in_place(env) and (env / "Paseo-local.app").exists()


def test_osascript_error_does_not_count_as_quit(env):
    fake = Fake(env, osascript_running_errors=True)
    assert run_main(env, fake, "--apply") == 1  # timed out waiting for the quit, nothing swapped
    assert upstream_in_place(env) and (env / "Paseo-local.app").exists()


def test_interrupt_after_swap_rolls_back(env):
    fake = Fake(env, interrupt_on_open=True)
    assert run_main(env, fake, "--apply") == 1
    assert upstream_in_place(env)


def test_malformed_plugin_list_before_the_swap_is_a_clean_refusal(env):
    fake = Fake(env, plugin_item_without_id_always=True)
    assert run_main(env, fake, "--apply") == 2
    assert not touched(fake)


def test_backup_equal_to_installed_is_refused(env):
    fake = Fake(env)
    assert run_main(env, fake, "--apply", "--backup", str(env / "Paseo.app"), with_backup=False) == 2
    assert not touched(fake)


def test_daemon_from_the_backup_bundle_fails_verification(env):
    fake = Fake(env)
    real = fake.__call__

    def lsof_from_backup(argv, timeout=60):
        if argv[0] == "lsof":
            return plu.Result(0, f"p1\nn{env}/Paseo-prev.app/Contents/MacOS/Paseo\n")
        return real(argv, timeout)

    assert run_main(env, lsof_from_backup, "--apply") == 1
    assert upstream_in_place(env)


# --- third adversary check (ef3d042) -------------------------------------------------------------------------

def test_a_broken_fork_cli_cannot_block_the_automatic_rollback(env):
    """F1: every paseo call runs the upstream bundle's CLI, never the build under test."""
    fake = Fake(env, fork_cli_broken=True)
    assert run_main(env, fake, "--apply") == 1
    assert upstream_in_place(env) and (env / "Paseo-local.app").exists()
    assert fake.fork_cli_calls == 0
    assert json.loads((env / "state/last-run.json").read_text())["phase"] == "rolled-back"
    swapped_calls = [c[0] for c in fake.calls if c[0].endswith("/bin/paseo")]
    assert str(env / "Paseo-prev.app/Contents/Resources/bin/paseo") in swapped_calls


def test_a_broken_fork_cli_cannot_block_the_manual_rollback(env):
    fake = Fake(env, fork_cli_broken=True)
    assert run_main(env, fake, "--apply", "--want-broken") == 3
    assert not upstream_in_place(env)
    assert run_main(env, fake, "--rollback", "--apply", "--yes", with_backup=False) == 0
    assert upstream_in_place(env) and fake.fork_cli_calls == 0


def test_a_fork_without_a_cli_shim_does_not_stop_the_manual_rollback(env):
    """M1: the trusted CLI is the upstream bundle's own shim, whatever PATH or the fork's layout says."""
    (env / "Paseo-local.app/Contents/Resources/bin/paseo").unlink()
    fake = Fake(env)
    assert run_main(env, fake, "--apply", "--want-broken", "--require-plugin", "nope") == 3
    assert not upstream_in_place(env)
    assert run_main(env, fake, "--rollback", "--apply", "--yes", with_backup=False) == 0
    assert upstream_in_place(env)
    shims = [c[0] for c in fake.calls if c[0].endswith("/bin/paseo")]
    assert shims and not any("Paseo-local" in x for x in shims)


def test_rollback_does_not_quit_an_app_that_is_not_running(env):
    """L1: the app is already gone after a failed open; a quit request to it would fail or launch it."""
    fake = Fake(env, open_fails_after_swap=True, quit_needs_running=True)
    assert run_main(env, fake, "--apply") == 1
    assert upstream_in_place(env)


def test_ps_failure_while_walking_ancestors_refuses():
    def ps(argv, timeout=60):
        return plu.Result(1, "", "ps: boom")

    assert "refusing" in plu.inside_paseo({}, ps)
    assert plu.inside_paseo({"PASEO_AGENT_ID": "x"}, ps) == "PASEO_AGENT_ID is set"


def test_locks_are_shared_across_installed_paths(env):
    held = plu.open_lock(str(env / "home"))
    try:
        fcntl.flock(held, fcntl.LOCK_EX)
        other = env / "other"
        other.mkdir()
        make_app(other / "Paseo.app", updater=True)
        argv = ["--installed", str(other / "Paseo.app"), "--staged", str(env / "Paseo-local.app"),
                "--backup", str(other / "prev.app"), "--state-dir", str(env / "state"),
                "--home", str(env / "home"), "--apply", "--yes"]
        assert plu.main(argv, runner=Fake(env), sleep=lambda s: None) == 2
    finally:
        os.close(held)


def _lock(env, content):
    (env / "home").mkdir(exist_ok=True)
    (env / "home" / "paseo.pid").write_text(content)


def _ctx(env):
    return plu.Ctx(installed=env / "Paseo.app", staged=env / "Paseo-local.app", backup=env / "Paseo-prev.app",
                   state_dir=env / "state", home=str(env / "home"), settle=0, timeout=1, require_plugins=[],
                   log_path=env / "t.log", runner=Fake(env), sleep=lambda s: None)


def test_a_live_pid_lock_owner_means_not_stopped_whatever_the_cli_says(env):
    ctx = _ctx(env)
    ctx.runner.daemon_up = False  # the CLI says stopped
    assert plu.daemon_is_stopped(ctx)
    _lock(env, json.dumps({"pid": os.getpid()}))
    assert not plu.daemon_is_stopped(ctx)
    dead = subprocess.Popen(["true"])
    dead.wait()
    _lock(env, json.dumps({"pid": dead.pid}))
    assert plu.daemon_is_stopped(ctx)
    _lock(env, "not json")
    assert not plu.daemon_is_stopped(ctx)  # unreadable: fail closed
    _lock(env, "")
    assert plu.daemon_is_stopped(ctx)  # abandoned


def test_a_signal_during_the_renames_still_records_the_swap(env, monkeypatch):
    """F2: the interrupt is raised after both renames; the state must already say swapped."""
    real = plu.os.rename
    n = {"i": 0}

    def rename(a, b):
        real(a, b)
        n["i"] += 1
        if n["i"] == 2:
            os.kill(os.getpid(), signal.SIGINT)  # held back by the mask until the swap is recorded

    monkeypatch.setattr(plu.os, "rename", rename)
    fake = Fake(env)
    assert run_main(env, fake, "--apply") == 1
    assert upstream_in_place(env) and (env / "Paseo-local.app").exists()  # rolled back, not relaunched as "untouched"
    assert json.loads((env / "state/last-run.json").read_text())["phase"] == "rolled-back"


def test_stuck_outranks_a_pending_signal(env, monkeypatch):
    real = plu.os.rename
    n = {"i": 0}

    def rename(a, b):
        n["i"] += 1
        if n["i"] == 1:
            os.kill(os.getpid(), signal.SIGINT)
            return real(a, b)
        raise OSError("disk says no")

    monkeypatch.setattr(plu.os, "rename", rename)
    with pytest.raises(plu.Stuck):
        plu.swap(env / "Paseo.app", env / "x.app", env / "Paseo-local.app", env / "Paseo.app")


def test_logging_survives_a_dead_tty(env, monkeypatch):
    """F3: a closed terminal makes print raise OSError; the log file still gets the line."""
    def boom(*a, **k):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(plu, "print", boom, raising=False)
    ctx = _ctx(env)
    ctx.log("still written")
    assert "still written" in ctx.log_path.read_text()


def test_a_keyboard_interrupt_in_the_gate_is_a_refusal(env, monkeypatch):
    """F6"""
    def boom(ctx):
        raise KeyboardInterrupt("signal 15")

    monkeypatch.setattr(plu, "gate", boom)
    assert plu.run_gate(_ctx(env)) == 2
    assert plu.run_gate(_ctx(env), post_swap=True) == 3


def test_lsof_failure_fails_verification(env):
    """F9"""
    fake = Fake(env, lsof_fails=True)
    assert run_main(env, fake, "--apply") == 1
    assert upstream_in_place(env)


def test_a_denied_quit_request_fails_at_once(env):
    """F10"""
    fake = Fake(env, quit_request_fails=True)
    assert run_main(env, fake, "--apply") == 1
    assert upstream_in_place(env) and (env / "Paseo-local.app").exists()
    quit_at = next(i for i, c in enumerate(fake.calls) if c[0] == "osascript" and "to quit" in c[2])
    assert not any(c[0] == "osascript" and "is running" in c[2] for c in fake.calls[quit_at + 1:])  # no waiting


def test_last_run_with_non_string_values_is_a_clean_error(env):
    (env / "state").mkdir()
    (env / "state" / "last-run.json").write_text(json.dumps({"installed": 5, "staged": "x", "backup": "y"}))
    fake = Fake(env)
    assert run_main(env, fake, "--rollback", "--apply", "--yes", with_backup=False) == 2
    assert not touched(fake)
