"""Scratch-only scheduled ack sweep; every probe, relay and ping is a fake."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get("FLEET_WATCH_SCRIPT", REPO / "bin/fleet-watch"))
LINE = "OVERDUE ack ask-1: target-agent has not answered [sender-agent] in 31m; tell the operator, never assume it was read"


def row(ident="ask-1", state="open", overdue=True, **extra):
    """A `relay.py --pending --json` expectation row."""
    return dict({"kind": "expect", "id": ident, "state": state, "sender": "sender-agent",
                 "target": {"name": "target-agent"}, "age_s": 1860, "within_s": 1800, "overdue": overdue}, **extra)


@pytest.fixture
def watch(tmp_path):
    home = tmp_path / "home"
    bindir = home / ".local/bin"
    bindir.mkdir(parents=True)
    relay = bindir / "relay.py"
    relay.write_text(f"#!{sys.executable}\n" + '''
import json, os, sys
from pathlib import Path
h = Path(os.environ["HOME"])
with (h / "calls").open("a") as f:
    f.write(json.dumps([sys.argv[1:], os.environ.get("RELAY_SENDER_NAME")]) + "\\n")
mode = "sweep" if sys.argv[1:] == ["--sweep"] else "pending"
if mode == "pending":
    assert sys.argv[1:] == ["--pending", "--json"]
print((h / mode).read_text(), end="")
sys.exit(int((h / (mode + "-rc")).read_text()))
''')
    relay.chmod(0o755)
    ping = bindir / "hermes-ping"
    ping.write_text(f"#!{sys.executable}\n" + '''
import os, sys, time
from pathlib import Path
h = Path(os.environ["HOME"])
if (h / "ping-sleep").exists():
    time.sleep(float((h / "ping-sleep").read_text()))
if (h / "ping-fail").exists():
    sys.exit(1)
with (h / "pings").open("a") as f:
    f.write(sys.argv[1] + "\\n")
if (h / "ping-hang-after-send").exists():
    time.sleep(float((h / "ping-hang-after-send").read_text()))
''')
    ping.chmod(0o755)
    for tool in ("date", "sed"):
        (bindir / ("g" + tool)).symlink_to(shutil.which(tool))
    (home / "sweep").write_text(LINE + "\n")
    (home / "pending").write_text(json.dumps([row()]))
    for name in ("sweep-rc", "pending-rc"):
        (home / name).write_text("0")
    # Source the real definitions, then stub unrelated fleet probes. check() itself
    # stays real, so removing the scheduled ack_watch call fails these tests.
    runner = tmp_path / "check.sh"
    runner.write_text(SCRIPT.read_text().split('case "${1:-check}" in')[0] + '''
HOSTS='' REPOS='' UPSTREAM_PROFILES='' VPS_STATE=off GETBACKUP_STATE=off
count() { echo 0; }
waiting() { echo unknown; }
load_watch() { :; }
vps_watch() { :; }
getbackup_watch() { :; }
s1_enabled() { return 1; }
check
''')
    env = dict(os.environ, HOME=str(home), PATH=str(bindir) + os.pathsep + os.environ["PATH"],
               FLEET_WATCH_RELAY=str(relay), FLEET_WATCH_TO="fake-inbox",
               RELAY_SENDER_NAME="fleet-watch")
    for name in ("SESSION_FINDER_STATE", "RELAY_HERMES_DIR", "RELAY_DEFER_DIR",
                 "RELAY_LINKS_FILE", "RELAY_UNSENT", "CODEX_HOME"):
        env[name] = str(tmp_path / name)

    class Watch:
        state = home / ".local/state/fleet-watch/ack-overdue.json"

        def start(self, extra=None):
            return subprocess.Popen(["bash", str(runner)], env=dict(env, **(extra or {})), text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def run(self, extra=None, timeout=30):
            result = subprocess.run(["bash", str(runner)], env=dict(env, **(extra or {})), text=True,
                                    capture_output=True, timeout=timeout)
            assert result.returncode == 0, result.stderr
            return result

        def set(self, name, text):
            (home / name).write_text(text)

        def sent(self):
            p = home / "pings"
            return p.read_text().splitlines() if p.exists() else []

        def log(self):
            path = self.state.parent / "fleet-watch.log"
            return path.read_text() if path.exists() else ""

    obj = Watch()
    obj.home, obj.relay = home, relay
    return obj


def test_overdue_pings_once_and_declares_sender(watch):
    watch.run()
    assert watch.sent() == ["fleet-watch: " + LINE]
    watch.run()
    assert len(watch.sent()) == 1
    calls = [json.loads(line) for line in (watch.home / "calls").read_text().splitlines()]
    assert calls == [[["--sweep"], "fleet-watch"], [["--pending", "--json"], "fleet-watch"]] * 2
    assert set(json.loads(watch.state.read_text())) == {"ask-1"}
    assert not list(watch.state.parent.glob(".ack-overdue-*"))


@pytest.mark.parametrize("pending", [
    [row(state="acked", overdue=False)],
    [row(state="reserved", overdue=False)],
    [row(state="expired", overdue=False)],
])
def test_ledger_key_is_pruned_once_its_row_is_no_longer_open(watch, pending):
    watch.run()
    assert set(json.loads(watch.state.read_text())) == {"ask-1"}
    watch.set("sweep", "acks: 1 resolved, 0 overdue\n")
    watch.set("pending", json.dumps(pending))
    watch.run()
    assert json.loads(watch.state.read_text()) == {}
    assert len(watch.sent()) == 1


def test_one_missing_row_keeps_the_ledger_key_but_two_in_a_row_prune_it(watch):
    """R5: a transient listing gap must not re-page; a really closed and gone expectation still prunes."""
    watch.run()
    for _ in range(6):    # the row is absent on every second run, the sweep line is always there
        watch.set("pending", "[]")
        watch.run()
        watch.set("pending", json.dumps([row()]))
        watch.run()
    assert len(watch.sent()) == 1
    assert json.loads(watch.state.read_text()) == {"ask-1": {"notified": pytest.approx(time.time(), abs=600)}}
    watch.set("pending", "[]")
    watch.run()
    assert json.loads(watch.state.read_text())["ask-1"]["missing"] == 1
    watch.run()
    assert json.loads(watch.state.read_text()) == {}
    watch.set("pending", json.dumps([row()]))
    watch.run()
    assert len(watch.sent()) == 2


@pytest.mark.parametrize("mode", ["missing", "failure"])
def test_relay_unavailable_continues_without_pruning_or_pinging(watch, mode):
    watch.run()
    before = watch.state.read_text()
    if mode == "missing":
        watch.relay.unlink()
    else:
        watch.set("sweep-rc", "1")
    watch.run()
    assert watch.state.read_text() == before
    assert len(watch.sent()) == 1
    assert "ack-sweep: unavailable:" in watch.log()


@pytest.mark.parametrize("output", ["", "acks: 0 resolved, 0 overdue\n", "not OVERDUE ack ask-1: fake\n", LINE + "\n"])
def test_no_open_overdue_row_never_pings_whatever_the_sweep_prints(watch, output):
    watch.set("sweep", output)
    watch.set("pending", json.dumps([row(overdue=False)]))
    watch.run()
    assert watch.sent() == []
    assert json.loads(watch.state.read_text()) == {}
    if not output:
        assert "printed nothing" in watch.log()


@pytest.mark.parametrize("output", ["", "acks: 0 resolved, 0 overdue\n", "OVERDUE expect-ack ask-1: reworded\n"])
def test_reworded_sweep_still_pages_from_pending_and_the_drift_is_logged(watch, output):
    """R1: a relay format change must neither silence the page nor pass unseen."""
    watch.set("sweep", output)
    watch.run()
    assert watch.sent() == ["fleet-watch: " + LINE]
    assert "1 open overdue expectation(s) in --pending had no OVERDUE line" in watch.log()
    watch.run()
    assert len(watch.sent()) == 1


def test_matching_sweep_line_logs_no_drift(watch):
    watch.run()
    assert "had no OVERDUE line" not in watch.log()


@pytest.mark.parametrize("mode", ["failure", "malformed", "wrong-shape"])
def test_pending_failure_retains_the_ledger_and_pages_nothing(watch, mode):
    watch.run()
    before = watch.state.read_text()
    if mode == "failure":
        watch.set("pending-rc", "1")
    else:
        watch.set("pending", "bad json" if mode == "malformed" else "{}")
    watch.set("sweep", LINE + "\n" + LINE.replace("ask-1", "ask-2") + "\n")
    watch.run()
    assert len(watch.sent()) == 1
    assert watch.state.read_text() == before
    assert "pending unavailable; paging deferred" in watch.log()


@pytest.mark.parametrize("mode", ["failure", "wrong-shape"])
def test_unparsed_pending_pages_nothing_even_for_a_wellformed_sweep_line(watch, mode):
    """R4: the old fallback paged sweep lines by ID shape; a forged line made that a hole."""
    if mode == "failure":
        watch.set("pending-rc", "1")
    else:
        watch.set("pending", json.dumps([row(), "x"]))
    watch.run()
    assert watch.sent() == []
    assert not watch.state.exists()
    assert "pending unavailable; paging deferred" in watch.log()


def test_failed_ping_retries_and_multiple_ids_are_independent(watch):
    watch.set("ping-fail", "1")
    watch.run()
    assert watch.sent() == []
    assert json.loads(watch.state.read_text()) == {}
    assert "hermes-ping failed for ask-1" in watch.log()
    (watch.home / "ping-fail").unlink()
    watch.set("sweep", LINE + "\n" + LINE.replace("ask-1", "ask-2") + "\n" + LINE)
    watch.set("pending", json.dumps([row("ask-1"), row("ask-2")]))
    watch.run()
    watch.run()
    assert len(watch.sent()) == 2
    assert set(json.loads(watch.state.read_text())) == {"ask-1", "ask-2"}


def run_ids(watch, count, sleep=None):
    watch.set("sweep", "".join(LINE.replace("ask-1", f"c-{i}") + "\n" for i in range(count)))
    watch.set("pending", json.dumps([row(f"c-{i}") for i in range(count)]))
    if sleep:
        watch.set("ping-sleep", str(sleep))


def test_ping_text_comes_from_the_pending_row_and_forged_lines_are_never_paged(watch):
    """B1: a newline in a peer-chosen name splits the sweep line into a forged second OVERDUE line."""
    watch.set("sweep", "OVERDUE ack ask-1: evil\nOVERDUE ack forged-9: injected has not answered [x] in 99m; real\n")
    for _ in range(3):
        watch.run()
    assert watch.sent() == ["fleet-watch: " + LINE]
    assert set(json.loads(watch.state.read_text())) == {"ask-1"}
    assert "forged-9" in watch.log()


def test_forged_line_is_never_paged_across_a_flapping_pending(watch):
    """R4: no pending row for forged-9, so neither a good nor a failing --pending may page it."""
    watch.set("sweep", LINE + "\nOVERDUE ack forged-9: injected has not answered [x] in 99m; real\n")
    for number in range(6):
        watch.set("pending-rc", str(number % 2))
        watch.run()
    assert watch.sent() == ["fleet-watch: " + LINE]
    assert set(json.loads(watch.state.read_text())) == {"ask-1"}


@pytest.mark.parametrize("pending", [
    [row("ask-1", state="acked", overdue=False)],
    [row("ask-1", overdue=False)],
    [row("ask-1", kind="message")],
    [],
])
def test_only_open_overdue_expect_rows_are_paged(watch, pending):
    watch.set("pending", json.dumps(pending))
    watch.run()
    assert watch.sent() == []
    assert json.loads(watch.state.read_text()) == {}


def test_reused_id_pages_again_once_the_earlier_expectation_closed(watch):
    """B2: once per expectation, not once per literal ID string."""
    watch.run()
    watch.set("sweep", "acks: 1 resolved, 0 overdue\n")
    watch.set("pending", json.dumps([row(state="acked", overdue=False)]))
    watch.run()
    assert json.loads(watch.state.read_text()) == {}
    watch.set("sweep", LINE.replace("31m", "45m") + "\n")
    watch.set("pending", json.dumps([row(age_s=2700)]))
    watch.run()
    watch.run()
    assert watch.sent() == ["fleet-watch: " + LINE, "fleet-watch: " + LINE.replace("31m", "45m")]


def test_open_expectation_that_is_not_overdue_keeps_its_ledger_entry(watch):
    watch.run()
    watch.set("pending", json.dumps([row(overdue=False)]))
    watch.run()
    assert set(json.loads(watch.state.read_text())) == {"ask-1"}


def test_step_deadline_stops_pinging_and_the_rest_retry_next_run(watch):
    run_ids(watch, 4, sleep=1.5)
    # The floor exceeds one ping's duration: a ping cut short by the deadline would be "maybe sent".
    watch.run({"FLEET_WATCH_ACK_DEADLINE": "4", "FLEET_WATCH_ACK_PING_FLOOR": "2.5"})
    first = watch.sent()
    assert 0 < len(first) < 4
    assert "less than 2.5 seconds left" in watch.log()
    (watch.home / "ping-sleep").unlink()
    watch.run()
    assert sorted(watch.sent()) == sorted("fleet-watch: " + LINE.replace("ask-1", f"c-{i}") for i in range(4))


def test_no_ping_starts_with_less_than_the_floor_of_time_left(watch):
    """R2a: a ping cut short by the deadline would be "maybe sent"; it must not start at all."""
    watch.run({"FLEET_WATCH_ACK_DEADLINE": "10"})
    assert watch.sent() == []
    assert json.loads(watch.state.read_text()) == {}
    assert "less than 20 seconds left; 1 overdue notice(s) retry next run" in watch.log()
    watch.run()
    assert watch.sent() == ["fleet-watch: " + LINE]


def test_a_ping_killed_by_its_timeout_is_recorded_and_never_retried(watch):
    """R2b: the page was sent and Hermes then hung; 5 runs give exactly one page, not one per run."""
    watch.set("ping-hang-after-send", "6")
    for _ in range(5):
        watch.run({"FLEET_WATCH_ACK_CMD_TIMEOUT": "1"})
    assert watch.sent() == ["fleet-watch: " + LINE]
    assert json.loads(watch.state.read_text())["ask-1"]["uncertain"] is True
    assert "hermes-ping for ask-1: timed out, not retried" in watch.log()


def test_uncertain_key_is_pruned_with_its_expectation_so_a_reused_id_pages_again(watch):
    watch.set("ping-hang-after-send", "6")
    watch.run({"FLEET_WATCH_ACK_CMD_TIMEOUT": "1"})
    watch.set("pending", json.dumps([row(state="acked", overdue=False)]))
    watch.run()
    assert json.loads(watch.state.read_text()) == {}
    watch.set("pending", json.dumps([row()]))
    (watch.home / "ping-hang-after-send").unlink()
    watch.run()
    assert len(watch.sent()) == 2


def test_unwritable_state_directory_pages_at_most_once_and_the_step_still_ends(watch):
    """R3: the ledger is written before any page; a page whose record cannot be kept must not go out."""
    watch.run()
    watch.state.unlink()
    directory = watch.state.parent
    directory.chmod(0o555)
    try:
        for _ in range(3):
            result = watch.run()    # rc 0: check() reaches its end although even the log is unwritable
            assert "Traceback" not in result.stderr
            assert "paging skipped this run" in result.stderr    # the only trace left: stderr
    finally:
        directory.chmod(0o755)
    assert len(watch.sent()) == 1
    assert not watch.state.exists()


def test_ledger_unwritable_for_a_reason_other_than_permissions_skips_paging_and_logs(watch):
    watch.state.parent.mkdir(parents=True)
    (watch.state.parent / "ack-overdue.json.bad").mkdir()    # occupied, non-empty: the quarantine move fails
    (watch.state.parent / "ack-overdue.json.bad" / "x").write_text("x")
    watch.state.mkdir()
    watch.run()
    assert watch.sent() == []
    assert "could not be moved aside" in watch.log()
    assert "ledger not writable" in watch.log()


def test_second_run_gives_way_while_the_lock_is_held(watch):
    watch.run()
    calls = (watch.home / "calls").read_text()
    with (watch.state.parent / "ack-overdue.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        watch.set("pending", json.dumps([row(), row("ask-2")]))
        watch.set("sweep", LINE + "\n" + LINE.replace("ask-1", "ask-2") + "\n")
        watch.run(timeout=10)
    assert "ack sweep already running" in watch.log()
    assert (watch.home / "calls").read_text() == calls
    assert len(watch.sent()) == 1


def test_overlapping_checks_page_each_id_exactly_once(watch):
    """B6: two parallel check() runs; fails if the flock is removed."""
    run_ids(watch, 3, sleep=1.5)
    first = watch.start()
    time.sleep(0.7)
    second = watch.start()
    for process in (first, second):
        process.communicate(timeout=60)
        assert process.returncode == 0
    assert sorted(watch.sent()) == sorted("fleet-watch: " + LINE.replace("ask-1", f"c-{i}") for i in range(3))
    assert "ack sweep already running" in watch.log()


def test_peer_controlled_text_is_sanitized_and_clipped(watch):
    nasty = "\x1b]0;title\x07\x1b[2J\x1b]52;c;AAAA\x07" + "N" * 20000
    watch.set("pending", json.dumps([row(target={"name": nasty}, sender="se\nnd\x00er")]))
    watch.run()
    (message,) = watch.sent()
    assert len(message) <= 500
    assert all(c.isprintable() for c in message)
    assert message.startswith("fleet-watch: OVERDUE ack ask-1: ")
    assert "[se nder] in 31m" in message


def test_oversized_sweep_line_never_reaches_the_ping_or_the_log(watch):
    watch.set("sweep", "OVERDUE ack ask-1: \x1b]52;c;AAAA\x07" + "A" * 2_000_000 + "\n")
    watch.run()
    assert watch.sent() == ["fleet-watch: " + LINE]
    assert len(watch.log()) < 2000


def test_log_never_repeats_peer_text(watch):
    watch.set("ping-fail", "1")
    watch.set("pending", json.dumps([row(target={"name": "SECRETMARK"})]))
    watch.run()
    log = watch.log()
    assert "hermes-ping failed for ask-1: exit 1" in log
    assert "SECRETMARK" not in log
    watch.set("sweep", "OVERDUE ack \x1b]52;c;AAAA\x07: x\n")
    watch.run()
    assert "\x1b" not in watch.log() and "\x07" not in watch.log()


def test_corrupt_ledger_is_set_aside_and_escalation_continues(watch):
    watch.state.parent.mkdir(parents=True)
    watch.state.write_text("{")
    watch.run()
    assert (watch.state.parent / "ack-overdue.json.bad").read_text() == "{"
    assert "unusable ledger moved to ack-overdue.json.bad" in watch.log()
    assert watch.sent() == ["fleet-watch: " + LINE]
    assert set(json.loads(watch.state.read_text())) == {"ask-1"}


def test_a_directory_at_the_ledger_path_is_set_aside_like_a_corrupt_ledger(watch):
    """R7: IsADirectoryError is an OSError, not a ValueError; it used to disable paging until fixed by hand."""
    watch.state.mkdir(parents=True)
    (watch.state / "stray").write_text("x")
    watch.run()
    assert (watch.state.parent / "ack-overdue.json.bad" / "stray").read_text() == "x"
    assert "unusable ledger moved to ack-overdue.json.bad" in watch.log()
    assert watch.sent() == ["fleet-watch: " + LINE]
    assert set(json.loads(watch.state.read_text())) == {"ask-1"}
