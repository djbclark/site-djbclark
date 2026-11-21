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
    assert (home / "sudo-ask.calls").read_text().count("bgrun TICKET") == 1  # one authentication
    assert NY_12H.search((home / "sudo-ask.calls").read_text()) and NY_12H.search(a.stderr)  # the dialog and the output show NY 12-hour time
    [t] = tickets(home)
    assert t.stat().st_mode & 0o777 == 0o600 and t.parent.stat().st_mode & 0o777 == 0o700
    for argv in (["vitest", "run"], ["pytest"]):  # two different bare suites, both refused without a ticket
        r = run(repo, home, *argv)
        assert r.returncode == 0, r.stderr
        assert "approval ticket" in r.stderr
    assert (home / "sudo-ask.calls").read_text().count("bgrun TICKET") == 1  # still just the one
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
        return {"BG_APPROVE_CHOOSER": str(c), "BG_APPROVE_CHOOSER_TEST": "1"}

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


# ---- 288 repair round 1 (adversary BLOCK on 24e0df3: the dialog must always show the expiry and the scope) ----

def forge(home, name, *, tid, created, expires, scope="*", argv="*"):
    """A ticket signed with the install's real salt (as a same-user process could), to probe what bgrun still refuses."""
    import hashlib

    state = home / ".local" / "state" / "bg"
    salt = (state / "ticket.salt").read_bytes()
    parts = [salt, tid.encode(), str(created).encode(), str(expires).encode(), scope.encode(), argv.encode(), str(os.getuid()).encode()]
    sig = hashlib.sha256(b"\0".join(parts)).hexdigest()
    f = state / "tickets" / name
    f.write_text(f"id={tid}\ncreated={created}\nexpires={expires}\nscope={scope}\nargv={argv}\nuid={os.getuid()}\nsig={sig}\n")
    f.chmod(0o600)
    return f


def test_the_dialog_starts_with_expiry_and_scope_and_never_cuts_them(repo, home):
    sub = repo / "sub"
    sub.mkdir()
    cmd = ["vitest", "run", *[f"packages/some-long-package-name/src/features/area-{i:02d}/very.long.test.name.spec.ts" for i in range(14)]]
    a = ap(repo, home, "--for", "52w", "--scope", str(sub), "--", *cmd)
    assert a.returncode == 0, a.stderr
    msg = (home / "sudo-ask.calls").read_text().splitlines()[-1]
    assert len(msg) <= 700, len(msg)  # sudo-ask cuts at 700; nothing the operator must see may be past that
    first = msg[:700]
    assert NY_12H.search(first) and "364 d" in first and "LONG-LIVED" in first and str(sub.resolve()) in first
    assert "command truncated:" in first and "argv hash" in first and "area-13" not in first  # the command, not the period, is what is cut
    assert first.index("until") < first.index("vitest")


def test_a_scope_too_long_to_show_whole_is_refused(repo, home):
    deep = repo
    for _ in range(6):
        deep = deep / ("d" * 50)
    deep.mkdir(parents=True)
    r = ap(repo, home, "--for", "1h", "--scope", str(deep))
    assert r.returncode == 2 and "too long to show" in r.stderr
    assert tickets(home) == [] and not (home / "sudo-ask.calls").exists()


def test_a_period_that_overflows_is_refused_before_the_dialog(repo, home):
    for v in ("99999999999999999999", "9999999999", "1h99999999999999999999"):
        assert ap(repo, home, "--for", v).returncode == 2, v
    assert tickets(home) == [] and not (home / "sudo-ask.calls").exists()


def test_a_ticket_needs_the_sudo_ask_dialog(repo, tmp_path_factory):
    home = make_home(tmp_path_factory, None)  # no sudo-ask: a bare sudo prompt would not show the expiry or scope
    r = ap(repo, home, "--for", "1h")
    assert r.returncode == 1 and "needs the sudo-ask dialog" in r.stderr and tickets(home) == []


def test_a_ticket_id_must_be_its_file_name_and_a_path_is_no_id(repo, home):
    ap(repo, home, "--for", "1h")
    now = int(time.time())
    forge(home, "deadbeef.ticket", tid="../../../escape", created=now, expires=now + 3600)
    forge(home, "cafef00d.ticket", tid="deadbeef", created=now, expires=now + 3600)  # a different name than its id
    [real] = [t for t in tickets(home) if t.stem not in ("deadbeef", "cafef00d")]
    real.unlink()
    assert run(repo, home, "vitest", "run").returncode == 3
    assert not list(home.glob("**/escape.uses")) and log(home).count("ticket-refused-id-not-file-name") >= 2


def test_revoking_one_id_also_kills_a_copy_under_another_name(repo, home):
    ap(repo, home, "--for", "1h")
    [t] = tickets(home)
    copy = t.with_name("zzzzcopy.ticket")
    copy.write_bytes(t.read_bytes())
    copy.chmod(0o600)
    ap(repo, home, "revoke", t.stem)
    assert run(repo, home, "vitest", "run").returncode == 3  # the copy is not honoured under another name


def test_revoke_all_rotates_the_salt_so_a_restored_ticket_is_dead(repo, home):
    ap(repo, home, "--for", "1h")
    [t] = tickets(home)
    saved = t.read_bytes()
    salt = t.parents[1] / "ticket.salt"
    old_salt = salt.read_bytes()
    assert ap(repo, home, "revoke").returncode == 0
    assert salt.read_bytes() != old_salt and salt.stat().st_mode & 0o777 == 0o600
    t.write_bytes(saved)  # a backup restore, or a copy kept aside
    t.chmod(0o600)
    assert run(repo, home, "vitest", "run").returncode == 3 and "ticket-refused-bad-signature" in log(home)


def test_a_ticket_dated_in_the_future_is_refused(repo, home):
    ap(repo, home, "--for", "1h")
    [t] = tickets(home)
    t.unlink()
    now = int(time.time())
    forge(home, "deadbeef.ticket", tid="deadbeef", created=now + 7200, expires=now + 9000)
    assert run(repo, home, "vitest", "run").returncode == 3 and "ticket-refused-clock-before-created" in log(home)


def test_scope_root_covers_every_directory(repo, home):
    assert ap(repo, home, "--for", "1h", "--scope", "/").returncode == 0
    assert run(repo, home, "vitest", "run").returncode == 0 and ap(repo, home, "check", str(repo)).returncode == 0
