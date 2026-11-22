"""bgrun approve-local and the sudo-ask approval window (roles/sudo_ask_grant, bin/approval-gate).

Real bin/bgrun in a throwaway HOME. The window is decided by ~/.local/bin/approval-gate, so each test installs a FAKE one there
(it reads `window_until`, records its argv in gate.calls) next to the stub sudo-ask that records its argv. Nothing here calls the
real gate, sudo, sudo-ask or the real grant file, so an open window on the machine running the tests cannot change the result.
"""

import os
import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bg_ci_mode import make_home, repo  # noqa: E402,F401  (repo is a fixture)
from test_bgrun_ticket import ap, log, run, tickets  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="bgrun's gates are asserted on the Mac's tool set")

FAKE_GATE = """#!/bin/bash
echo "$*" >> "{home}/gate.calls"
[ "$1" = check ] && [ "$2" = --gate ] || exit 2
[ -f "{home}/window_until" ] || exit 1
e=$(cat "{home}/window_until")
rem=$((e - $(/bin/date +%s)))
[ "$rem" -ge 1 ] || exit 1
ttl=$rem
[ "$3" = bgrun-approve-local ] && [ "$ttl" -gt 3600 ] && ttl=3600          # the registry's max_ttl for this gate
[ "$4" = --max-ttl ] && [ "$5" -lt "$ttl" ] && ttl=$5
echo ttl=$ttl; echo expires_epoch=$e; echo expires_utc=x
"""


def open_window(home, secs):
    g = home / ".local" / "bin" / "approval-gate"
    g.parent.mkdir(parents=True, exist_ok=True)
    g.write_text(FAKE_GATE.format(home=home))
    g.chmod(0o755)
    until = int(time.time()) + secs
    (home / "window_until").write_text(str(until))
    return until


def gate_calls(home):
    f = home / "gate.calls"
    return f.read_text().splitlines() if f.exists() else []


def expiries(paths):
    return [int(re.search(r"^expires=(\d+)$", p.read_text(), re.M).group(1)) for p in paths]


@pytest.fixture
def home(tmp_path_factory):
    return make_home(tmp_path_factory, "allow")


def tokens(home):
    d = home / ".local" / "state" / "bg" / "approvals"
    return sorted(p for p in d.glob("*") if not p.name.startswith(".")) if d.is_dir() else []


def test_one_shot_in_a_window_has_no_dialog_and_never_outlives_the_window(repo, home):
    until = open_window(home, 600)
    a = ap(repo, home, "--ttl", "1h", "--", "vitest", "run")
    assert a.returncode == 0, a.stderr
    assert not (home / "sudo-ask.calls").exists()  # no dialog, no Touch ID
    assert "approval window" in a.stderr
    [t] = tokens(home)
    assert expiries([t])[0] <= until  # capped at the window's end, not now + 1h
    assert "check --gate bgrun-approve-local --max-ttl 3600" in gate_calls(home)
    assert run(repo, home, "vitest", "run").returncode == 0  # the token is honoured once...
    assert run(repo, home, "vitest", "run").returncode == 3  # ...and is single-use as before


def test_one_shot_ttl_is_the_smaller_of_the_request_and_the_window(repo, home):
    open_window(home, 7200)
    ap(repo, home, "--ttl", "10m", "--", "vitest", "run")
    [t] = tokens(home)
    assert abs(expiries([t])[0] - (time.time() + 600)) < 30  # the request (10 m), the window has 2 h
    ap(repo, home, "revoke")
    ap(repo, home, "--ttl", "24h", "--", "vitest", "run")
    [t] = tokens(home)
    assert abs(expiries([t])[0] - (time.time() + 3600)) < 30  # the gate's own cap (1 h), the window has 2 h


def test_one_shot_without_a_window_is_unchanged(repo, home):
    open_window(home, 600)
    (home / "window_until").unlink()
    a = ap(repo, home, "--ttl", "1h", "--", "vitest", "run")
    assert a.returncode == 0, a.stderr
    assert (home / "sudo-ask.calls").read_text().count("bg approve-local (one run") == 1  # the dialog path
    assert gate_calls(home)  # the gate was asked, and said no


def test_a_window_that_ended_does_not_cover_a_one_shot(repo, home):
    open_window(home, 600)
    (home / "window_until").write_text(str(int(time.time()) - 5))
    assert ap(repo, home, "--ttl", "1h", "--", "vitest", "run").returncode == 0
    assert (home / "sudo-ask.calls").read_text().count("bg approve-local (one run") == 1


def test_the_plain_sudo_fallback_honours_the_window(repo, tmp_path_factory):
    home = make_home(tmp_path_factory, None)  # no sudo-ask: bgrun would fall back to `sudo -k /usr/bin/true`
    open_window(home, 600)
    a = ap(repo, home, "--ttl", "1h", "--", "vitest", "run")
    assert a.returncode == 0, a.stderr
    assert "approval window" in a.stderr and len(tokens(home)) == 1  # no sudo was run (the test would have waited on a prompt)


def test_ticket_in_a_window_is_capped_at_the_window_and_asks_nothing(repo, home):
    until = open_window(home, 3600)
    a = ap(repo, home, "--for", "7h")
    assert a.returncode == 0, a.stderr
    assert not (home / "sudo-ask.calls").exists()
    assert "capped" in a.stderr
    [t] = tickets(home)
    assert expiries([t])[0] == until
    assert run(repo, home, "vitest", "run").returncode == 0  # and the ticket works


def test_ticket_shorter_than_the_window_keeps_its_own_expiry(repo, home):
    open_window(home, 7200)
    a = ap(repo, home, "--for", "30m")
    assert a.returncode == 0 and not (home / "sudo-ask.calls").exists()
    [t] = tickets(home)
    assert abs(expiries([t])[0] - (time.time() + 1800)) < 30
    assert "capped" not in a.stderr


def test_ask_skips_the_chooser_in_a_window(repo, home, tmp_path):
    until = open_window(home, 3600)
    c = tmp_path / "chooser"
    c.write_text(f'#!/bin/bash\necho chooser-was-shown > "{tmp_path}/shown"\necho for:1h\n')
    c.chmod(0o755)
    a = ap(repo, home, "--ask", "--", "vitest", "run", BG_APPROVE_CHOOSER=str(c), BG_APPROVE_CHOOSER_TEST="1")
    assert a.returncode == 0, a.stderr
    assert not (tmp_path / "shown").exists()  # no duration question
    assert not (home / "sudo-ask.calls").exists()
    [t] = tickets(home)
    assert expiries([t])[0] <= until


def test_ask_without_a_window_still_shows_the_chooser(repo, home, tmp_path):
    open_window(home, 3600)
    (home / "window_until").unlink()
    c = tmp_path / "chooser"
    c.write_text(f'#!/bin/bash\necho chooser-was-shown > "{tmp_path}/shown"\necho for:1h\n')
    c.chmod(0o755)
    a = ap(repo, home, "--ask", "--", "vitest", "run", BG_APPROVE_CHOOSER=str(c), BG_APPROVE_CHOOSER_TEST="1")
    assert a.returncode == 0, a.stderr
    assert (tmp_path / "shown").exists() and "bgrun TICKET" in (home / "sudo-ask.calls").read_text()


def test_the_gate_cannot_be_swapped_through_the_environment(repo, home, tmp_path):
    # no window at the gate bgrun trusts; an env var naming another gate must change nothing
    other = tmp_path / "other-gate"
    other.write_text("#!/bin/bash\necho ttl=3600; echo expires_epoch=99999999999\n")
    other.chmod(0o755)
    a = ap(repo, home, "--for", "1h", BG_GATE=str(other), APPROVAL_GATE=str(other), PATH=f"{tmp_path}:{os.environ['PATH']}")
    assert a.returncode == 0, a.stderr
    assert "bgrun TICKET" in (home / "sudo-ask.calls").read_text()  # the dialog path ran


def test_a_gate_that_answers_nonsense_means_prompt(repo, home):
    g = home / ".local" / "bin" / "approval-gate"
    g.parent.mkdir(parents=True, exist_ok=True)
    for body in ("echo ttl=abc; echo expires_epoch=1", "echo ttl=5", "echo ttl=0; echo expires_epoch=9999999999", "exit 0"):
        g.write_text("#!/bin/bash\n" + body + "\n")
        g.chmod(0o755)
        (home / "sudo-ask.calls").unlink(missing_ok=True)
        assert ap(repo, home, "--for", "1h").returncode == 0
        assert (home / "sudo-ask.calls").exists(), body  # still asked
        ap(repo, home, "revoke")
    assert log(home)
