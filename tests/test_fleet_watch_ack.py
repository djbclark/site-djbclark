"""Scratch-only scheduled ack sweep; every probe, relay and ping is a fake."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get("FLEET_WATCH_SCRIPT", REPO / "bin/fleet-watch"))
LINE = "OVERDUE ack ask-1: target-agent has not answered [sender-agent] in 31m; tell the operator, never assume it was read"


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
import os, sys
from pathlib import Path
h = Path(os.environ["HOME"])
if (h / "ping-fail").exists():
    sys.exit(1)
with (h / "pings").open("a") as f:
    f.write(sys.argv[1] + "\\n")
''')
    ping.chmod(0o755)
    for tool in ("date", "sed"):
        (bindir / ("g" + tool)).symlink_to(shutil.which(tool))
    (home / "sweep").write_text(LINE + "\n")
    (home / "pending").write_text(json.dumps([
        {"kind": "expect", "id": "ask-1", "state": "open", "overdue": True}
    ]))
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

        def run(self):
            result = subprocess.run(["bash", str(runner)], env=env, text=True,
                                    capture_output=True, timeout=30)
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


def test_gone_expectation_is_pruned_but_retained_acked_record_is_not(watch):
    watch.run()
    watch.set("sweep", "acks: 1 resolved, 0 overdue\n")
    watch.set("pending", '[{"kind":"expect","id":"ask-1","state":"acked"}]')
    watch.run()
    assert "ask-1" in json.loads(watch.state.read_text())
    watch.set("pending", '[{"id":"ask-1","state":"open"}]')
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
    watch.set("pending", '[{"kind":"expect","id":"ask-1"},{"kind":"expect","id":"ask-2"}]')
    watch.run()
    watch.run()
    assert len(watch.sent()) == 2
    assert set(json.loads(watch.state.read_text())) == {"ask-1", "ask-2"}
