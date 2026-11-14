"""bin/paseo-local-upgrade: gate, swap, verify, rollback (2026-11-14). A fake runner models paseo and the app."""

import fcntl
import importlib.machinery
import importlib.util
import json
import plistlib
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
    if updater:
        (path / "Contents/Resources/app-update.yml").write_text("provider: github\n")


class Fake:
    """Stands in for paseo, codesign, osascript, ps and open."""

    def __init__(self, tmp, agents=None, perms=None, bad_plugin=None, open_fails_after_swap=False,
                 status_unreadable_after_stop=False, app_never_quits=False, plugin_item_without_id=False,
                 busy_after_swap=False, ls_shape=UNSET, terminals=None, keeps_daemon_on_quit=False,
                 busy_after_quit=False, interrupt_on_open=False, plugin_item_without_id_always=False,
                 osascript_running_errors=False):
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
        if head == "codesign":
            if argv[1] == "-dv":
                return plu.Result(0, "", "Signature=adhoc\n" if self.fork_installed() else "Authority=Developer ID\n")
            return plu.Result(0)
        if head == "lsof":
            return plu.Result(0, f"p{self.pid}\nn{self.installed}/Contents/MacOS/Paseo\n")
        if head == "osascript":
            if "is running" in argv[2]:
                if self.osascript_running_errors:
                    return plu.Result(1, "", "osascript: error")
                return plu.Result(0, "true\n" if self.app_up else "false\n")
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
def env(tmp_path):
    make_app(tmp_path / "Paseo.app", updater=True)
    make_app(tmp_path / "Paseo-local.app", updater=False)
    return tmp_path


def run_main(env, fake, *extra, with_backup=True):
    argv = ["--installed", str(env / "Paseo.app"), "--staged", str(env / "Paseo-local.app"),
            "--state-dir", str(env / "state"), "--home", str(env / "home"),
            "--updater-cache", str(env / "updates"), "--settle", "0", "--timeout", "1", *extra]
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
    ls = [c for c in fake.calls if c[:2] == ["paseo", "ls"]]
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
                     "--home", str(env / "home"), "--apply"], runner=fake2, sleep=lambda s: None) == 2
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
    name = plu.hashlib.sha256(str(plu.os.path.realpath(env / "Paseo.app")).encode()).hexdigest()[:16]
    with open(Path(plu.tempfile.gettempdir()) / f"paseo-local-upgrade-{name}.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        fake = Fake(env)
        assert run_main(env, fake, "--apply") == 2
    assert not touched(fake)


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


def test_refuses_inside_a_paseo_terminal(env, monkeypatch):
    monkeypatch.setenv("PASEO_TERMINAL_ID", "abc")
    fake = Fake(env)
    assert run_main(env, fake, "--apply") == 2
    assert not fake.calls


def test_gate_runs_again_after_the_app_quits(env):
    """N4: a daemon that outlives the app can start a turn while the script waits for the quit."""
    fake = Fake(env, keeps_daemon_on_quit=True, busy_after_quit=True)
    assert run_main(env, fake, "--apply") == 4
    assert not any(c[:3] == ["paseo", "daemon", "stop"] for c in fake.calls)
    assert upstream_in_place(env) and fake.calls[-1][0] == "open"  # the app is relaunched


def test_pending_update_for_another_version_refuses(env):
    (env / "updates").mkdir()
    (env / "updates" / "Paseo-0.16.0-beta.9-arm64.zip").write_text("x")
    fake = Fake(env)
    assert run_main(env, fake, "--apply") == 2
    assert not touched(fake)


def test_pending_update_for_the_installed_version_is_fine(env):
    (env / "updates").mkdir()
    (env / "updates" / "Paseo-0.16.0-beta.2-arm64.zip").write_text("x")
    assert run_main(env, Fake(env), "--apply") == 0


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
