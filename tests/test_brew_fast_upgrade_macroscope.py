"""Exercise only shell functions with a fake macroscope; never run the real one or brew."""
import os
import re
import stat
import subprocess
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "roles/site_agents/templates/brew-fast-upgrade.sh.j2"

FAKE = """#!/bin/bash
printf '%s\\n' "$@" > "$FAKE_OUT/argv"
printf '%s' "${MACROSCOPE_REQUIRE_CHECKSUM-unset}" > "$FAKE_OUT/env"
if [ -t 0 ]; then echo tty > "$FAKE_OUT/stdin_kind"; else echo notty > "$FAKE_OUT/stdin_kind"; fi
cat > "$FAKE_OUT/stdin_bytes"
exit "${FAKE_RC:-0}"
"""


def _function(name: str) -> str:
    return re.search(rf"^{name}\(\) \{{.*?^\}}", SOURCE.read_text(), re.S | re.M).group()


def _run(home: Path, out: Path, install_fake: bool = True, rc: int = 0, state: bool = True):
    cli = home / ".local/bin/macroscope"
    if install_fake:
        cli.parent.mkdir(parents=True)
        cli.write_text(FAKE)
        cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
    if state:
        state_file = home / ".local/state/macroscope/install.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text('{"tools": ["claude"], "pathPolicy": "skip"}')
    env = dict(os.environ, HOME=str(home), FAKE_OUT=str(out), FAKE_RC=str(rc))
    env.pop("MACROSCOPE_REQUIRE_CHECKSUM", None)
    env.pop("XDG_STATE_HOME", None)
    script = _function("run_macroscope_pass") + "\nrun_macroscope_pass"
    result = subprocess.run(["bash", "-c", script], env=env, text=True, input="", capture_output=True)
    return result.returncode, result.stdout, result.stderr


def test_macroscope_pass_argv_env_and_stdin(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    rc, stdout, _ = _run(tmp_path / "home", out)
    assert rc == 0
    assert "macroscope: updating CLI + plugin" in stdout
    assert (out / "argv").read_text().split() == ["update", "--yes"]
    assert (out / "env").read_text() == "1"
    assert (out / "stdin_kind").read_text().strip() == "notty"
    assert (out / "stdin_bytes").read_text() == ""


def test_macroscope_pass_stdin_is_devnull_not_the_callers_pipe(tmp_path):
    """The caller's stdin carries data; the fake must still read EOF."""
    out = tmp_path / "out"
    out.mkdir()
    home = tmp_path / "home"
    cli = home / ".local/bin/macroscope"
    cli.parent.mkdir(parents=True)
    cli.write_text(FAKE)
    cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
    state_file = home / ".local/state/macroscope/install.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text('{"tools": ["claude"], "pathPolicy": "skip"}')
    env = dict(os.environ, HOME=str(home), FAKE_OUT=str(out), FAKE_RC="0")
    env.pop("XDG_STATE_HOME", None)
    script = _function("run_macroscope_pass") + "\nrun_macroscope_pass"
    result = subprocess.run(
        ["bash", "-c", script], env=env, text=True, input="would-block-or-leak\n", capture_output=True
    )
    assert result.returncode == 0
    assert (out / "stdin_bytes").read_text() == ""


def test_macroscope_pass_absent_cli_is_silent_success(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    rc, stdout, stderr = _run(tmp_path / "home", out, install_fake=False)
    assert (rc, stdout, stderr) == (0, "", "")
    assert not (out / "argv").exists()


def test_macroscope_pass_failing_cli_returns_one(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    rc, _, _ = _run(tmp_path / "home", out, rc=7)
    assert rc == 1


def test_macroscope_pass_skips_without_install_state(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    rc, stdout, _ = _run(tmp_path / "home", out, state=False)
    assert rc == 0
    assert "no install state" in stdout
    assert not (out / "argv").exists()


def test_macroscope_pass_respects_xdg_state_home(tmp_path):
    """site#302 carried LOW: honour XDG_STATE_HOME for macroscope/install.json."""
    out = tmp_path / "out"
    out.mkdir()
    home = tmp_path / "home"
    cli = home / ".local/bin/macroscope"
    cli.parent.mkdir(parents=True)
    cli.write_text(FAKE)
    cli.chmod(cli.stat().st_mode | stat.S_IXUSR)

    xdg_with_state = tmp_path / "xdg-present"
    state_file = xdg_with_state / "macroscope/install.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text('{"tools": ["claude"], "pathPolicy": "skip"}')

    env = dict(os.environ, HOME=str(home), XDG_STATE_HOME=str(xdg_with_state), FAKE_OUT=str(out), FAKE_RC="0")
    env.pop("MACROSCOPE_REQUIRE_CHECKSUM", None)
    script = _function("run_macroscope_pass") + "\nrun_macroscope_pass"
    res = subprocess.run(["bash", "-c", script], env=env, text=True, input="", capture_output=True)
    assert res.returncode == 0
    assert "macroscope: updating CLI + plugin" in res.stdout
    assert (out / "argv").read_text().split() == ["update", "--yes"]

    # Even when $HOME/.local/state has install.json, an explicit XDG_STATE_HOME without it skips.
    default_state = home / ".local/state/macroscope/install.json"
    default_state.parent.mkdir(parents=True)
    default_state.write_text('{"tools": ["claude"], "pathPolicy": "skip"}')
    (out / "argv").unlink()
    xdg_empty = tmp_path / "xdg-empty"
    xdg_empty.mkdir()
    env_empty = dict(env, XDG_STATE_HOME=str(xdg_empty))
    res_skip = subprocess.run(["bash", "-c", script], env=env_empty, text=True, input="", capture_output=True)
    assert res_skip.returncode == 0
    assert f"no install state at {xdg_empty}/macroscope/install.json" in res_skip.stdout
    assert not (out / "argv").exists()


def test_macroscope_pass_runs_only_on_first_attempt():
    source = SOURCE.read_text()
    calls = [
        c for c in re.findall(r"^.*\brun_macroscope_pass\b.*$", source, re.M)
        if not c.lstrip().startswith("#")
        and not re.match(r"^run_macroscope_pass\(\) \{", c)
        and "declare -f" not in c
    ]
    assert len(calls) == 1, calls
    assert re.search(r'^\s*if \[ "\$attempt" -eq 1 \] && ! run_macroscope_pass; then$', calls[0]), calls


def test_locked_run_declares_every_template_function():
    source = SOURCE.read_text()
    defined = re.findall(r"^([A-Za-z_][A-Za-z0-9_]*)\(\) \{", source, re.M)
    assert "run_macroscope_pass" in defined
    assert len(defined) == len(set(defined))
    line = re.search(r'bash -c "\$\(declare -f ([^)]*)\)', source).group(1)
    listed = line.split()
    assert len(listed) == len(set(listed))
    assert set(defined) == set(listed), (set(defined) ^ set(listed))
