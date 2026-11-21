"""bgrun approve-local tickets (operator 2026-11-21): one Touch ID, many local runs until an expiry (Kerberos/OpenAFS pattern).

Real bin/bgrun in a throwaway HOME whose load-watch says `ci`, with a stub `sudo-ask` that records its argv and allows or denies, so
no dialog or Touch ID is ever shown. Covers: any command / any directory by default, expiry (--for, --until), scope, a command
narrowing, status, revoke, check, the --ask chooser, and a forged, tampered or expired ticket being refused.
"""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bg_ci_mode import BG, bg_env, make_home, repo  # noqa: E402,F401  (repo is a fixture)

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="bgrun's gates are asserted on the Mac's tool set")

NY_12H = re.compile(r"\d{1,2}:\d{2} (AM|PM) E[SD]T")


def ap(repo, home, *argv, **env):
    return subprocess.run([str(BG), "approve-local", *argv], cwd=repo, env=bg_env(home, **env), capture_output=True, text=True, timeout=60)


def run(repo, home, *argv, cwd=None):
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return subprocess.run([str(BG), *argv], cwd=cwd or repo, env=bg_env(home), capture_output=True, text=True, timeout=120)


def tickets(home):
    d = home / ".local" / "state" / "bg" / "tickets"
    return sorted(d.glob("*.ticket")) if d.is_dir() else []


def log(home):
    f = home / ".local" / "state" / "bg" / "approvals.log"
    return f.read_text() if f.exists() else ""


@pytest.fixture
def home(tmp_path_factory):
    return make_home(tmp_path_factory, "allow")


def test_one_touch_id_then_any_command_runs_locally_until_the_expiry(repo, home):
    a = ap(repo, home, "--for", "7h")
    assert a.returncode == 0, a.stderr
    assert (home / "sudo-ask.calls").read_text().count("approve-local TICKET") == 1  # one authentication
    assert NY_12H.search((home / "sudo-ask.calls").read_text()) and NY_12H.search(a.stderr)  # the dialog and the output show NY 12-hour time
    [t] = tickets(home)
    assert t.stat().st_mode & 0o777 == 0o600 and t.parent.stat().st_mode & 0o777 == 0o700
    for argv in (["vitest", "run"], ["pytest"]):  # two different bare suites, both refused without a ticket
        r = run(repo, home, *argv)
        assert r.returncode == 0, r.stderr
        assert "approval ticket" in r.stderr
    assert (home / "sudo-ask.calls").read_text().count("approve-local TICKET") == 1  # still just the one
    st = ap(repo, home, "status")
    assert t.stem in st.stdout and "used 2 time(s)" in st.stdout and NY_12H.search(st.stdout)
    uses = (t.parent / f"{t.stem}.uses").read_text().splitlines()
    assert len(uses) == 2 and all(len(line.split("\t")) == 4 for line in uses)  # time, cwd, argv hash, program
    assert "ticket-used" in log(home)


def test_a_denied_dialog_writes_no_ticket(repo, tmp_path_factory):
    home = make_home(tmp_path_factory, "deny")
    assert ap(repo, home, "--for", "1h").returncode == 1
    assert tickets(home) == []


def test_an_expired_ticket_is_refused_and_removed(repo, home):
    assert ap(repo, home, "--for", "2s").returncode == 0
    time.sleep(3)
    r = run(repo, home, "vitest", "run")
    assert r.returncode == 3 and "FAKE-VITEST" not in r.stdout
    assert tickets(home) == [] and "ticket-expired" in log(home)


def test_until_takes_a_local_date_time_and_refuses_the_past(repo, home):
    a = ap(repo, home, "--until", "tomorrow 8am")
    assert a.returncode == 0 and NY_12H.search(a.stderr), a.stderr
    assert run(repo, home, "vitest", "run").returncode == 0
    n = len((home / "sudo-ask.calls").read_text().splitlines())
    p = ap(repo, home, "--until", "2020-01-01 08:00")
    assert p.returncode == 2 and "not in the future" in p.stderr
    assert ap(repo, home, "--until", "gibberish").returncode == 2
    assert len((home / "sudo-ask.calls").read_text().splitlines()) == n  # a bad time never reaches the dialog


def test_scope_limits_a_ticket_to_a_directory_tree(repo, home):
    sub = repo / "sub"
    sub.mkdir()
    assert ap(repo, home, "--for", "1h", "--scope", str(sub)).returncode == 0
    assert run(repo, home, "vitest", "run").returncode == 3  # the repo root is outside the scope
    assert run(repo, home, "vitest", "run", cwd=sub).returncode == 0
    assert ap(repo, home, "check", str(sub)).returncode == 0 and ap(repo, home, "check", str(repo)).returncode == 1


def test_naming_a_command_narrows_the_ticket_to_it(repo, home):
    assert ap(repo, home, "--for", "1h", "--", "vitest", "run").returncode == 0
    assert run(repo, home, "vitest", "run").returncode == 0
    assert run(repo, home, "pytest").returncode == 3


def test_revoke_ends_every_ticket_and_one_shot_token(repo, home):
    ap(repo, home, "--for", "1h")
    ap(repo, home, "--ttl", "1h", "--", "pytest")
    r = ap(repo, home, "revoke")
    assert r.returncode == 0 and tickets(home) == []
    assert run(repo, home, "vitest", "run").returncode == 3 and run(repo, home, "pytest").returncode == 3
    assert "(none)" in ap(repo, home, "status").stdout


def test_revoke_one_ticket_by_id(repo, home):
    ap(repo, home, "--for", "1h")
    ap(repo, home, "--for", "2h")
    a, b = tickets(home)
    assert ap(repo, home, "revoke", a.stem).returncode == 0
    assert tickets(home) == [b]
    assert ap(repo, home, "revoke", "../x").returncode == 2


def test_a_hand_written_ticket_is_refused(repo, home):
    d = home / ".local" / "state" / "bg" / "tickets"
    d.mkdir(parents=True, mode=0o700)
    f = d / "deadbeef.ticket"
    f.write_text(f"id=deadbeef\ncreated=1\nexpires={int(time.time()) + 99999}\nscope=*\nargv=*\nuid={os.getuid()}\nsig=0\n")
    f.chmod(0o600)
    assert run(repo, home, "vitest", "run").returncode == 3
    assert "ticket-refused" in log(home) and "REFUSED" in ap(repo, home, "status").stdout


def test_a_tampered_ticket_is_refused(repo, home):
    ap(repo, home, "--for", "10s")
    [t] = tickets(home)
    text = t.read_text()
    exp = int(re.search(r"expires=(\d+)", text).group(1))
    t.write_text(text.replace(f"expires={exp}", f"expires={exp + 86400}"))  # extend the expiry by hand
    assert run(repo, home, "vitest", "run").returncode == 3
    assert "ticket-refused-bad-signature" in log(home)


def test_a_ticket_with_loose_permissions_or_a_symlink_is_refused(repo, home):
    ap(repo, home, "--for", "1h")
    [t] = tickets(home)
    t.chmod(0o644)
    assert run(repo, home, "vitest", "run").returncode == 3 and "ticket-refused-bad-owner-or-mode" in log(home)
    t.chmod(0o600)
    assert run(repo, home, "vitest", "run").returncode == 0  # the same file is fine again with mode 0600
    real = t.with_name("real.txt")
    t.rename(real)
    t.symlink_to(real)
    assert run(repo, home, "vitest", "run").returncode == 3 and "ticket-refused-not-a-plain-file" in log(home)


def test_ask_offers_a_chooser_and_acts_on_the_answer(repo, home, tmp_path):
    def chooser(answer):
        c = tmp_path / f"chooser-{abs(hash(answer))}"
        c.write_text(f"#!/bin/bash\n{answer}\n")
        c.chmod(0o755)
        return {"BG_APPROVE_CHOOSER": str(c)}

    a = ap(repo, home, "--ask", "--", "vitest", "run", **chooser("echo for:7h"))
    assert a.returncode == 0 and len(tickets(home)) == 1 and "ANY bgrun local run" in (home / "sudo-ask.calls").read_text()
    ap(repo, home, "revoke")
    o = ap(repo, home, "--ask", "--", "vitest", "run", **chooser("echo once"))
    assert o.returncode == 0 and tickets(home) == []  # this run only: the one-shot token, no ticket
    assert run(repo, home, "vitest", "run").returncode == 0 and run(repo, home, "vitest", "run").returncode == 3  # used up
    assert ap(repo, home, "--ask", "--", "vitest", "run", **chooser("exit 1")).returncode == 1
    u = ap(repo, home, "--ask", "--", "pytest", **chooser("echo 'until:tomorrow 8am'"))
    assert u.returncode == 0 and NY_12H.search(u.stderr)


def test_conflicting_or_incomplete_requests_are_usage_errors(repo, home):
    for argv in (["--for", "1h", "--until", "tomorrow 8am"], ["--ttl", "1h", "--for", "1h"], ["--for", "0"], ["--for", "7x"],
                 ["--scope", str(repo)], ["--for", "1h", "--scope", "/nonexistent-dir"]):
        assert ap(repo, home, *argv).returncode == 2, argv
    assert tickets(home) == [] and not (home / "sudo-ask.calls").exists()


def test_the_one_shot_form_still_works_unchanged(repo, home):
    assert ap(repo, home, "--ttl", "1h", "--", "vitest", "run").returncode == 0
    assert tickets(home) == [] and run(repo, home, "vitest", "run").returncode == 0
    assert run(repo, home, "vitest", "run").returncode == 3
