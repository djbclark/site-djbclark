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
            return (self.state.parent / "fleet-watch.log").read_text()

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
    [row(state="expired", overdue=False)],
    [{"id": "ask-1", "state": "open"}],
    [],
])
def test_ledger_key_is_pruned_once_its_expectation_is_no_longer_open(watch, pending):
    watch.run()
    assert set(json.loads(watch.state.read_text())) == {"ask-1"}
    watch.set("sweep", "acks: 1 resolved, 0 overdue\n")
    watch.set("pending", json.dumps(pending))
    watch.run()
    assert json.loads(watch.state.read_text()) == {}
    assert len(watch.sent()) == 1


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


@pytest.mark.parametrize("output", ["", "acks: 0 resolved, 0 overdue\n", "not OVERDUE ack ask-1: fake\n"])
def test_no_overdue_output_never_pings(watch, output):
    watch.set("sweep", output)
    watch.run()
    assert watch.sent() == []
    assert json.loads(watch.state.read_text()) == {}
    if not output:
        assert "printed nothing" in watch.log()


@pytest.mark.parametrize("mode", ["failure", "malformed", "wrong-shape"])
def test_pending_failure_retains_deduplication(watch, mode):
    watch.run()
    if mode == "failure":
        watch.set("pending-rc", "1")
    else:
        watch.set("pending", "bad json" if mode == "malformed" else "{}")
    watch.run()
    assert len(watch.sent()) == 1
    assert "ask-1" in json.loads(watch.state.read_text())
    assert "pending unavailable; retained ledger" in watch.log()


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


@pytest.mark.parametrize("pending", [
    [row("ask-1", state="acked", overdue=False)],
    [row("ask-1", overdue=False)],
    [row("ask-1", kind="message")],
    [row("other")],
    [],
])
def test_only_open_overdue_expect_rows_are_paged(watch, pending):
    watch.set("pending", json.dumps(pending))
    watch.run()
    assert watch.sent() == []
    assert json.loads(watch.state.read_text()) == {}


def test_unparsed_pending_pages_only_conservative_ids_from_the_sweep(watch):
    watch.set("pending-rc", "1")
    watch.set("sweep", "OVERDUE ack a$(b): x\nOVERDUE ack " + "z" * 81 + ": x\n" + LINE + "\n")
    watch.run()
    assert watch.sent() == ["fleet-watch: " + LINE]
    assert set(json.loads(watch.state.read_text())) == {"ask-1"}


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
    watch.run({"FLEET_WATCH_ACK_DEADLINE": "3"})
    first = watch.sent()
    assert 0 < len(first) < 4
    assert "step deadline of 3 seconds reached" in watch.log()
    (watch.home / "ping-sleep").unlink()
    watch.run()
    assert sorted(watch.sent()) == sorted("fleet-watch: " + LINE.replace("ask-1", f"c-{i}") for i in range(4))


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


def test_oversized_sweep_line_is_clipped_in_the_unparsed_fallback(watch):
    watch.set("pending-rc", "1")
    watch.set("sweep", "OVERDUE ack ask-1: \x1b]52;c;AAAA\x07" + "A" * 2_000_000 + "\n")
    watch.run()
    (message,) = watch.sent()
    assert len(message) <= 500 and all(c.isprintable() for c in message)


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
    assert "corrupt ledger moved to ack-overdue.json.bad" in watch.log()
    assert watch.sent() == ["fleet-watch: " + LINE]
    assert set(json.loads(watch.state.read_text())) == {"ask-1"}
