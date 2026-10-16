#!/usr/bin/env python3
"""Tests for fleet-watch's upstream-PR watcher (`fleet-watch upstream`).

Runs the real script with HOME pointed at a temp dir and stubs for gh, aiuse, acp-dispatch and
hermes-ping: gh answers from fixture files, the others record their arguments. Nothing is sent,
no worker is dispatched and the live GitHub account is never contacted.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FLEET_WATCH = Path(os.environ.get("FLEET_WATCH_SCRIPT", REPO / "bin" / "fleet-watch"))
PROMPT = REPO / "prompts" / "upstream-pr-review.md"

GH_STUB = r"""#!/bin/bash
# api <path> [--paginate] [--jq EXPR] [-X GET] [-f k=v ...]: answer from $FIX/<path with / as _>
[ "$1" = api ] || exit 2
path=$2; shift 2; expr=
while [ $# -gt 0 ]; do case $1 in --jq) expr=$2; shift ;; esac; shift; done
f="$FIX/${path//\//_}"
[ -f "$f" ] || { echo "stub gh: no fixture for $path" >&2; exit 1; }
[ -f "$FIX/gh_fail" ] && { echo "stub gh: failing" >&2; exit 1; }
if [ -n "$expr" ]; then jq -r "$expr" "$f" | { [ "$expr" = '.[]' ] && jq -c . || cat; }; else cat "$f"; fi
"""

DISPATCH_STUB = """#!/bin/bash
echo "$*" >> "$HOME/dispatch.log"
exit "$(cat "$HOME/dispatch_rc" 2>/dev/null || echo 0)"
"""

AIUSE_STUB = """#!/bin/bash
cat "$FIX/aiuse.json"
exit "$(cat "$HOME/aiuse_rc" 2>/dev/null || echo 0)"
"""

PING_STUB = """#!/bin/bash
rc=$(cat "$HOME/ping_rc" 2>/dev/null || echo 0)
[ "$rc" = 0 ] && echo "$*" >> "$HOME/pings"
exit "$rc"
"""

REPO_NAME = "cfengine/core"
THREAD = "9001"
T0 = "2026-10-16T08:00:00Z"


def review(rid: int, login: str, at: str, body: str, state: str = "COMMENTED") -> dict:
    return {"id": rid, "user": {"login": login, "type": "User"}, "state": state,
            "submitted_at": at, "body": body}


class UpstreamWatch(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.home = root / "home"
        self.fix = root / "fix"
        self.bin = root / "bin"
        for d in (self.home / ".local" / "bin", self.fix, self.bin):
            d.mkdir(parents=True)
        for path, text in ((self.home / ".local" / "bin" / "hermes-ping", PING_STUB),
                           (self.bin / "gh", GH_STUB), (self.bin / "acp-dispatch", DISPATCH_STUB),
                           (self.bin / "aiuse", AIUSE_STUB)):
            path.write_text(text)
            path.chmod(0o755)
        self.state = self.home / ".local" / "state" / "fleet-watch"
        self.bigteam = root / "bigteam"
        self.set("user", {"login": "djbclark"})
        self.set("aiuse.json", {"available": [
            {"provider": "claude", "pool_family": "default", "usable_now": True, "headroom_percent": 90}]},
            raw=True)
        self.thread(T0)
        self.pr(reviews=[review(1, "larsewi", "2026-10-16T07:00:00Z", "old comment")])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def set(self, path: str, data, raw: bool = False) -> None:
        name = path if raw else path.replace("/", "_")
        (self.fix / name).write_text(json.dumps(data))

    def thread(self, updated: str, repo: str = REPO_NAME, tid: str = THREAD, n: int = 6412,
               typ: str = "PullRequest") -> None:
        self.set("notifications", [{
            "id": tid, "updated_at": updated, "subject": {"type": typ, "url": f"https://api.github.com/repos/{repo}/pulls/{n}"},
            "repository": {"full_name": repo}}])

    def pr(self, reviews=(), rcomments=(), icomments=(), state="open", merged=False, n: int = 6412) -> None:
        base = f"repos/{REPO_NAME}"
        self.set(f"{base}/issues/{n}", {"title": "A title", "state": state, "closed_at": "2026-10-16T09:00:00Z" if state == "closed" else None,
                                        "closed_by": {"login": "larsewi", "type": "User"}})
        self.set(f"{base}/pulls/{n}", {"head": {"ref": "fix/x"}, "merged": merged,
                                       "merged_by": {"login": "larsewi", "type": "User"} if merged else None})
        self.set(f"{base}/pulls/{n}/reviews", list(reviews))
        self.set(f"{base}/pulls/{n}/comments", list(rcomments))
        self.set(f"{base}/issues/{n}/comments", list(icomments))

    def run_fw(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        full = dict(os.environ, HOME=str(self.home), FIX=str(self.fix),
                    FLEET_WATCH_GH=str(self.bin / "gh"), FLEET_WATCH_AIUSE=str(self.bin / "aiuse"),
                    FLEET_WATCH_DISPATCH=str(self.bin / "acp-dispatch"), ACP_DISPATCH_STATE=str(self.bigteam),
                    FLEET_WATCH_UPSTREAM_PROMPT=str(PROMPT), FLEET_WATCH_UPSTREAM_CHAIN=str(self.home / "chain"))
        full.update(env)
        return subprocess.run(["bash", str(FLEET_WATCH), "upstream", *args], env=full,
                              capture_output=True, text=True, timeout=120)

    def pings(self) -> list[str]:
        p = self.home / "pings"
        return p.read_text().splitlines() if p.exists() else []

    def dispatches(self) -> list[str]:
        p = self.home / "dispatch.log"
        return p.read_text().splitlines() if p.exists() else []

    def pending(self) -> list[dict]:
        return json.loads((self.state / "upstream-pr.json").read_text())["pending"]

    def seed(self) -> None:
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(self.pings(), [])

    def new_review(self, at: str = "2026-10-16T09:00:00Z", body: str = "Please use StringContains()") -> None:
        self.thread(at)
        self.pr(reviews=[review(1, "larsewi", "2026-10-16T07:00:00Z", "old comment"), review(2, "larsewi", at, body)])

    def test_seed_run_emits_nothing_and_a_second_run_is_quiet(self) -> None:
        self.seed()
        self.assertEqual(self.dispatches(), [])
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(self.pings(), [])
        self.assertEqual(self.dispatches(), [])

    def test_dry_run_lists_candidate_and_writes_nothing(self) -> None:
        result = self.run_fw("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("candidate: cfengine/core#6412: review (commented) by larsewi", result.stdout)
        self.assertFalse((self.state / "upstream-pr.json").exists())
        self.assertEqual((self.pings(), self.dispatches()), ([], []))

    def test_new_review_pings_once_and_dispatches_one_detached_worker(self) -> None:
        self.seed()
        self.new_review()
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(self.pings(), ["cfengine-core: cfengine/core#6412 review (commented) by larsewi: Please use StringContains()"])
        (line,) = self.dispatches()
        for word in ("claude", "--model sonnet", "--task upstream-pr", "--detach", "--no-wait", "-C "):
            self.assertIn(word, line)
        self.assertEqual(self.pending(), [])
        brief = next(self.state.glob("upstream-pr-core-6412-*-input.md")).read_text()
        self.assertTrue(brief.startswith("/baton"))
        self.assertIn("untrusted data", brief)
        self.assertIn("`fix/x`", brief)
        # Same thread state again: nothing new.
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual((len(self.pings()), len(self.dispatches())), (1, 1))

    def test_operator_activity_alone_is_not_an_event(self) -> None:
        self.seed()
        self.thread("2026-10-16T09:00:00Z")
        self.pr(reviews=[review(1, "larsewi", "2026-10-16T07:00:00Z", "old comment"),
                         review(3, "djbclark", "2026-10-16T08:59:00Z", "done")])
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual((self.pings(), self.dispatches()), ([], []))

    def test_bots_and_ignored_logins_are_not_events(self) -> None:
        self.seed()
        self.thread("2026-10-16T09:00:00Z")
        self.pr(icomments=[{"id": 5, "user": {"login": "cf-bottom", "type": "User"}, "created_at": "2026-10-16T08:30:00Z", "body": "CI"},
                           {"id": 6, "user": {"login": "some-bot", "type": "Bot"}, "created_at": "2026-10-16T08:31:00Z", "body": "x"}])
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(self.pings(), [])

    def test_merge_pings_but_dispatches_nothing(self) -> None:
        self.seed()
        self.thread("2026-10-16T09:00:00Z")
        self.pr(state="closed", merged=True)
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(len(self.pings()), 1)
        self.assertIn("merged by larsewi", self.pings()[0])
        self.assertEqual((self.dispatches(), self.pending()), ([], []))

    def test_other_repos_are_ignored(self) -> None:
        self.seed()
        self.thread("2026-10-16T09:00:00Z", repo="someone/else")
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(self.pings(), [])

    def test_no_quota_keeps_the_event_pending_pings_once_and_retries(self) -> None:
        self.seed()
        self.new_review()
        (self.home / "aiuse_rc").write_text("3")
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(self.dispatches(), [])
        self.assertEqual(len(self.pending()), 1)
        self.assertEqual(len(self.pings()), 2)
        self.assertIn("no quota, not dispatching", self.pings()[1])
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(len(self.pings()), 2)  # one ping per cause
        (self.home / "aiuse_rc").write_text("0")
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(len(self.dispatches()), 1)
        self.assertEqual(self.pending(), [])

    def test_an_open_job_record_blocks_dispatch(self) -> None:
        self.seed()
        self.new_review()
        jobs = self.bigteam / "upstream-pr" / "jobs"
        jobs.mkdir(parents=True)
        import time
        (jobs / "w.json").write_text(json.dumps({
            "name": "w", "done": str(self.home / "w.done"), "started": time.time(), "timeout": 3600}))
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(self.dispatches(), [])
        self.assertIn("a session is already on it", self.pings()[1])
        (self.home / "w.done").write_text("")
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(len(self.dispatches()), 1)

    def test_a_closed_job_record_does_not_block(self) -> None:
        self.seed()
        self.new_review()
        jobs = self.bigteam / "upstream-pr" / "jobs"
        jobs.mkdir(parents=True)
        import time
        (jobs / "w.json").write_text(json.dumps({"name": "w", "done": "/nonexistent", "started": time.time(),
                                                 "closed": True}))
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(len(self.dispatches()), 1)

    def test_a_live_lock_file_blocks_dispatch(self) -> None:
        self.seed()
        self.new_review()
        holder = subprocess.Popen(["sleep", "30"])
        try:
            (self.state / "upstream-pr.lock").write_text(f"{holder.pid}\n")
            self.assertEqual(self.run_fw().returncode, 0)
            self.assertEqual(self.dispatches(), [])
            self.assertIn("lock held by pid", self.pings()[1])
        finally:
            holder.kill()
            holder.wait()
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(len(self.dispatches()), 1)

    def test_a_failed_ping_is_retried_on_the_next_run(self) -> None:
        self.seed()
        self.new_review()
        (self.home / "ping_rc").write_text("1")
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual((self.pings(), self.dispatches()), ([], []))
        (self.home / "ping_rc").write_text("0")
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(len(self.pings()), 1)
        self.assertEqual(len(self.dispatches()), 1)

    def test_dispatch_failing_three_times_is_dropped_with_a_ping(self) -> None:
        self.seed()
        self.new_review()
        (self.home / "dispatch_rc").write_text("1")
        for _ in range(3):
            self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(len(self.dispatches()), 3)
        self.assertIn("dispatch failed 3 times", self.pings()[-1])
        self.assertEqual(self.pending(), [])

    def test_a_failed_notification_fetch_changes_nothing(self) -> None:
        self.seed()
        self.new_review()
        (self.fix / "gh_fail").write_text("")
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual((self.pings(), self.dispatches()), ([], []))
        (self.fix / "gh_fail").unlink()
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(len(self.dispatches()), 1)

    def test_the_scheduled_check_is_throttled(self) -> None:
        self.seed()
        self.new_review()
        # `check` runs every other check; a stamp younger than the interval skips the pass.
        (self.state / "upstream-pr.last").write_text("")
        full = dict(os.environ, HOME=str(self.home), FIX=str(self.fix), FLEET_WATCH_GH=str(self.bin / "gh"),
                    FLEET_WATCH_AIUSE=str(self.bin / "aiuse"), FLEET_WATCH_DISPATCH=str(self.bin / "acp-dispatch"),
                    FLEET_WATCH_HOSTS="", FLEET_WATCH_REPOS="", FLEET_WATCH_VPS="off", FLEET_WATCH_S1="0",
                    FLEET_WATCH_UPSTREAM_PROMPT=str(PROMPT), FLEET_WATCH_HELM=str(self.bin / "nohelm"))
        subprocess.run(["bash", str(FLEET_WATCH), "check"], env=full, capture_output=True, text=True, timeout=120)
        self.assertEqual(self.dispatches(), [])


if __name__ == "__main__":
    unittest.main()
