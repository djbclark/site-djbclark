"""The guarded entries of claude/local-marketplace/plugins/local-lsp/.lsp.json (ADE queue 89).

Each guarded entry is `sh -c SCRIPT lsp-guard SERVER ARGS...`. Anything the script puts on stdout corrupts the LSP
framing, and a `${...}` in it is expanded by Claude Code before `sh` runs. These tests run each entry's own script
against fake servers and fake guards (no real LSP server, no network, no live config)."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LSP_JSON = ROOT / "claude/local-marketplace/plugins/local-lsp/.lsp.json"
CONFIG = json.loads(LSP_JSON.read_text())
GUARDED = [name for name, ent in CONFIG.items() if ent.get("args", [None, None, None])[2:3] == ["lsp-guard"]]
EXTRA = ["x y", "$(touch PWNED)", "*", "%s%n"]

GOOD_GUARD = '#!/bin/sh\n[ "$1" = --check ] && exit 0\nshift\necho "GUARD $*"\ncat\n'
BROKEN_GUARD = "#!/bin/sh\necho ImportError >&2\nexit 1\n"
SERVER = '#!/bin/sh\necho "SERVER $*"\ncat\n'


def run_entry(tmp_path: Path, name: str, guard: str | None, env_extra: dict[str, str] | None = None,
              home: bool = True, readonly_home: bool = False) -> tuple[subprocess.CompletedProcess[str], Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "fakesrv").write_text(SERVER)
    (bindir / "fakesrv").chmod(0o755)
    if guard is not None:
        (bindir / "lsp-root-guard").write_text(guard)
        (bindir / "lsp-root-guard").chmod(0o755)
    homedir = tmp_path / "home"
    homedir.mkdir(exist_ok=True)
    if readonly_home:
        homedir.chmod(0o500)  # mkdir -p and tee cannot create the log here
    env = {"PATH": f"{bindir}:/usr/bin:/bin"}
    if home:
        env["HOME"] = str(homedir)
    env.update(env_extra or {})
    args = list(CONFIG[name]["args"])
    argv = ["sh", args[0], args[1], args[2], "fakesrv", *EXTRA]
    try:
        done = subprocess.run(argv, env=env, cwd=tmp_path, input="HELLO\n", capture_output=True, text=True, timeout=30)
    finally:
        homedir.chmod(0o700)
    return done, homedir / ".local/state/lsp-guard/unguarded.log"


def test_the_config_has_guarded_entries_and_no_claude_expansion() -> None:
    assert set(GUARDED) == {"basedpyright", "marksman", "typescript"}, GUARDED  # an entry that stops being `sh -c` must not drop out
    assert "${" not in LSP_JSON.read_text(), "Claude Code expands ${...} before sh runs and splices the value into the script"
    for name in GUARDED:
        args = CONFIG[name]["args"]
        assert args[0] == "-c" and args[2] == "lsp-guard", name


@pytest.mark.parametrize("name", GUARDED)
@pytest.mark.parametrize("switch", [None, "on", "", "OFF", "0", 'on" ] && touch INJ && [ "x'])
def test_a_working_guard_runs_and_nothing_else_is_written(tmp_path: Path, name: str, switch: str | None) -> None:
    env = {} if switch is None else {"ADE_LSP_ROOT_GUARD": switch}
    done, log = run_entry(tmp_path, name, GOOD_GUARD, env)
    assert done.returncode == 0
    assert done.stdout.startswith("GUARD fakesrv x y $(touch PWNED) * %s%n"), done.stdout  # arguments reach the guard literally
    assert "HELLO" in done.stdout  # stdin is left alone (the check does not consume it)
    assert done.stderr == "" and not log.exists()
    assert not (tmp_path / "PWNED").exists() and not (tmp_path / "INJ").exists()


@pytest.mark.parametrize("name", GUARDED)
def test_the_off_switch_starts_the_plain_server_with_a_stderr_line_and_no_log(tmp_path: Path, name: str) -> None:
    done, log = run_entry(tmp_path, name, GOOD_GUARD, {"ADE_LSP_ROOT_GUARD": "off"})
    assert done.returncode == 0
    assert done.stdout.startswith("SERVER x y $(touch PWNED) * %s%n") and "HELLO" in done.stdout
    assert done.stderr == "lsp-guard: lsp-root-guard off; fakesrv starts UNGUARDED\n"
    assert not log.exists(), "a deliberate off must not fill the log that reports breakage"
    assert not (tmp_path / "PWNED").exists()


@pytest.mark.parametrize("name", GUARDED)
@pytest.mark.parametrize("guard", [None, BROKEN_GUARD], ids=["absent", "broken"])
def test_a_missing_or_broken_guard_falls_back_and_is_logged_as_unavailable(tmp_path: Path, name: str, guard: str | None) -> None:
    done, log = run_entry(tmp_path, name, guard)
    assert done.returncode == 0
    assert done.stdout.startswith("SERVER x y $(touch PWNED) * %s%n") and "HELLO" in done.stdout
    assert "UNGUARDED" not in done.stdout and "ImportError" not in done.stdout and "ImportError" not in done.stderr
    assert done.stderr.endswith(" lsp-guard: lsp-root-guard unavailable; fakesrv starts UNGUARDED\n")
    lines = log.read_text().splitlines()
    assert len(lines) == 1 and lines[0] + "\n" == done.stderr
    stamp = lines[0].split(" ", 1)[0]
    assert len(stamp) == 20 and stamp.endswith("Z") and stamp[10] == "T", stamp  # UTC, 2026-11-21T00:00:00Z
    assert not (tmp_path / "PWNED").exists()


@pytest.mark.parametrize("name", GUARDED)
def test_a_broken_guard_with_the_switch_off_still_starts_the_server(tmp_path: Path, name: str) -> None:
    done, log = run_entry(tmp_path, name, BROKEN_GUARD, {"ADE_LSP_ROOT_GUARD": "off"})
    assert done.returncode == 0 and done.stdout.startswith("SERVER x y")
    assert done.stderr == "lsp-guard: lsp-root-guard off; fakesrv starts UNGUARDED\n" and not log.exists()


@pytest.mark.parametrize("name", GUARDED)
def test_the_log_is_appended_and_stamped_in_utc(tmp_path: Path, name: str) -> None:
    """A `tee` without -a would keep only the newest line (every count over days reads 1); a `date` without -u stamps local
    time with a literal Z (TZ=XXX-14 is UTC+14, so the slip is a 14 hour skew here)."""
    first, log = run_entry(tmp_path, name, None, {"TZ": "XXX-14"})
    second, _ = run_entry(tmp_path, name, None, {"TZ": "XXX-14"})
    assert first.returncode == 0 and second.returncode == 0
    lines = log.read_text().splitlines()
    assert len(lines) == 2, lines
    for line in lines:
        stamp = datetime.strptime(line.split(" ", 1)[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        assert abs(datetime.now(timezone.utc) - stamp) < timedelta(minutes=2), line


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write the log whatever the mode")
@pytest.mark.parametrize("name", GUARDED)
def test_an_unwritable_log_never_stops_the_server(tmp_path: Path, name: str) -> None:
    done, log = run_entry(tmp_path, name, None, readonly_home=True)  # HOME is a directory the script cannot write to
    assert done.returncode == 0 and done.stdout.startswith("SERVER x y") and "UNGUARDED" not in done.stdout
    assert "starts UNGUARDED" in done.stderr and not log.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write /.local whatever HOME is")
@pytest.mark.parametrize("name", GUARDED)
def test_an_unset_home_never_stops_the_server(tmp_path: Path, name: str) -> None:
    done, _ = run_entry(tmp_path, name, None, home=False)  # no HOME: the log path is /.local/..., never written as a user
    assert done.returncode == 0 and done.stdout.startswith("SERVER x y") and "UNGUARDED" not in done.stdout
    assert "starts UNGUARDED" in done.stderr
