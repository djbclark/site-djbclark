"""change-hermes concurrency: mkdir lock (stale by pid/age, busy exit 73) and --auto cooldown."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("ruamel.yaml")
from test_change_hermes_auto import P, load  # noqa: E402


def test_lock_exclusive_and_busy(tmp_path):
    ch = load()
    a = ch.Lock(tmp_path / "l", wait_s=0).acquire()
    with pytest.raises(ch.Busy):
        ch.Lock(tmp_path / "l", wait_s=0.6).acquire()
    a.release()
    assert not (tmp_path / "l").exists()
    ch.Lock(tmp_path / "l", wait_s=0).acquire().release()


def test_stale_lock_dead_pid_is_broken(tmp_path):
    ch = load()
    p = subprocess.Popen([sys.executable, "-c", "pass"]); p.wait()
    (tmp_path / "l").mkdir()
    (tmp_path / "l" / "owner.json").write_text(json.dumps({"pid": p.pid, "host": os.uname().nodename, "at": time.time()}))
    ch.Lock(tmp_path / "l", wait_s=0).acquire().release()


def test_stale_lock_by_age_is_broken(tmp_path):
    ch = load()
    (tmp_path / "l").mkdir()
    (tmp_path / "l" / "owner.json").write_text(json.dumps({"pid": os.getpid(), "host": "elsewhere", "at": time.time() - 5000}))
    ch.Lock(tmp_path / "l", wait_s=0).acquire().release()


def test_live_foreign_lock_not_broken(tmp_path):
    ch = load()
    (tmp_path / "l").mkdir()
    (tmp_path / "l" / "owner.json").write_text(json.dumps({"pid": os.getpid(), "host": "elsewhere", "at": time.time()}))
    with pytest.raises(ch.Busy):
        ch.Lock(tmp_path / "l", wait_s=0).acquire()


def test_waiter_gets_lock_after_release(tmp_path):
    ch = load()
    holder = subprocess.Popen([sys.executable, "-c", f"""
import importlib.machinery, importlib.util, sys, time
l = importlib.machinery.SourceFileLoader('c', {str(P)!r}); s = importlib.util.spec_from_loader('c', l)
m = importlib.util.module_from_spec(s); sys.modules['c'] = m; l.exec_module(m)
k = m.Lock({str(tmp_path / 'l')!r}, wait_s=0).acquire(); print('held', flush=True); time.sleep(1.5); k.release()
"""], stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "held"
    t0 = time.monotonic()
    ch.Lock(tmp_path / "l", wait_s=10).acquire().release()
    assert time.monotonic() - t0 > 0.5
    holder.wait()


def test_cooldown(tmp_path, monkeypatch):
    ch = load()
    monkeypatch.setattr(ch, "AUTO_STAMP", tmp_path / "s.json")
    monkeypatch.setenv("CHANGE_HERMES_AUTO_COOLDOWN_S", "600")
    assert ch.auto_cooldown_left() == 0
    ch.write_json_atomic(ch.AUTO_STAMP, {"at": time.time() - 100})
    assert 490 < ch.auto_cooldown_left() <= 500
    ch.write_json_atomic(ch.AUTO_STAMP, {"at": time.time() - 700})
    assert ch.auto_cooldown_left() == 0


def _home(tmp_path):
    h = tmp_path / "hermes"; h.mkdir()
    (h / "config.yaml").write_text("fallback_providers:\n  - provider: cline2\n    model: cline2-pass/deepseek-v4-flash\n")
    return h


def _run(h, *a, **env):
    e = dict(os.environ, HERMES_HOME=str(h), **env)
    return subprocess.run(["uv", "run", "--quiet", "--script", str(P), *a], capture_output=True, text=True, env=e, timeout=120)


@pytest.mark.skipif(not __import__("shutil").which("uv"), reason="uv missing")
def test_cli_busy_73_and_cooldown_rechecks(tmp_path):
    h = _home(tmp_path)
    lock = h / "state" / "change-hermes.lock"; lock.mkdir(parents=True)
    (lock / "owner.json").write_text(json.dumps({"pid": os.getpid(), "host": os.uname().nodename, "at": time.time()}))
    r = _run(h, "--auto", "--dry-run", CHANGE_HERMES_LOCK_WAIT_S="0")
    assert r.returncode == 73 and "busy" in r.stderr
    lock.joinpath("owner.json").unlink(); lock.rmdir()
    (h / "state" / "change-hermes-auto.json").write_text(json.dumps({"at": time.time()}))
    r = _run(h, "--auto")  # in cooldown: re-check only (no key in this HERMES_HOME -> 10), never writes
    assert "cooldown" in r.stdout and r.returncode == 10
    assert not list(h.glob("config.yaml.bak-*"))
    assert not lock.exists()


@pytest.mark.skipif(not __import__("shutil").which("uv"), reason="uv missing")
def test_cli_skip_window(tmp_path):
    r = _run(_home(tmp_path), "--check", "--skip-window", "0000-2359")
    assert r.returncode == 75
