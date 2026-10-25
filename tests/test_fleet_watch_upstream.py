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
PASEO_PROMPT = REPO / "prompts" / "paseo-contribution-review.md"

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

RELAY_STUB = """#!/bin/bash
echo "$*" >> "$HOME/relay.log"
exit "$(cat "$HOME/relay_rc" 2>/dev/null || echo 0)"
"""

REPO_NAME = "cfengine/core"
THREAD = "9001"
T0 = "2026-10-16T08:00:00Z"


def review(rid: int, login: str, at: str, body: str, state: str = "COMMENTED") -> dict:
    return {"id": rid, "user": {"login": login, "type": "User"}, "state": state,
            "submitted_at": at, "body": body}


class Harness(unittest.TestCase):
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
                           (self.bin / "aiuse", AIUSE_STUB), (self.bin / "relay.py", RELAY_STUB)):
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
                    FLEET_WATCH_UPSTREAM_PROMPT=str(PROMPT), FLEET_WATCH_UPSTREAM_CHAIN=str(self.home / "chain"),
                    FLEET_WATCH_RELAY=str(self.bin / "relay.py"), FLEET_WATCH_PASEO_PROMPT=str(PASEO_PROMPT))
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


class UpstreamWatch(Harness):
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
        self.assertIn("`fix/x-prep`", brief)
        self.assertNotIn("git push --force-with-lease origin <branch>`", brief)
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


def note(tid: str, updated: str, repo: str, typ: str, n: int) -> dict:
    kind = {"PullRequest": "pulls", "Issue": "issues", "Discussion": "discussions"}[typ]
    return {"id": tid, "updated_at": updated, "repository": {"full_name": repo},
            "subject": {"type": typ, "url": f"https://api.github.com/repos/{repo}/{kind}/{n}"}}


def dcomment(cid: str, login: str, at: str, body: str, replies=(), typename: str = "User") -> dict:
    return {"id": cid, "createdAt": at, "body": body, "author": {"login": login, "__typename": typename},
            "replies": {"nodes": list(replies)}}


class PaseoWatch(Harness):
    """`fleet-watch upstream --profile paseo`: Discussions, a ping-only fallback, separate files."""

    def setUp(self) -> None:
        super().setUp()
        self.dthread(T0)
        self.discussion()

    def dthread(self, updated: str, repo: str = "getpaseo/paseo") -> None:
        self.set("notifications", [note("9100", updated, repo, "Discussion", 7828)])

    def discussion(self, comments=(), closed: bool = False) -> None:
        self.set("graphql", {"data": {"repository": {"discussion": {
            "title": "Workspace colors", "closed": closed,
            "closedAt": "2026-10-16T12:00:00Z" if closed else None, "createdAt": "2026-10-16T06:00:00Z",
            "author": {"login": "djbclark", "__typename": "User"}, "comments": {"nodes": list(comments)}}}}})

    def fw(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return self.run_fw("--profile", "paseo", *args, **env)

    def pstate(self) -> dict:
        return json.loads((self.state / "upstream-paseo.json").read_text())

    def relays(self) -> list[str]:
        p = self.home / "relay.log"
        return p.read_text().splitlines() if p.exists() else []

    def seed(self) -> None:
        self.assertEqual(self.fw().returncode, 0)
        self.assertEqual(self.pings(), [])
        self.assertTrue((self.state / "upstream-paseo.json").exists())
        self.assertFalse((self.state / "upstream-pr.json").exists())

    def maintainer_replies(self, at: str = "2026-10-16T09:00:00Z") -> None:
        self.dthread(at)
        self.discussion([dcomment("DC_1", "djbclark", "2026-10-16T07:00:00Z", "my prototype"),
                         dcomment("DC_2", "maintainer", at, "Please open it as a feature request first")])

    def test_a_comment_pings_once_and_with_no_watcher_dispatches_nothing(self) -> None:
        self.seed()
        self.maintainer_replies()
        self.assertEqual(self.fw().returncode, 0)
        self.assertEqual(self.pings(), ["paseo: getpaseo/paseo#7828 comment by maintainer: Please open it as a feature request first"])
        self.assertEqual((self.dispatches(), self.relays()), ([], []))
        self.assertEqual(len(self.pstate()["pending"]), 1)
        self.assertEqual(self.fw().returncode, 0)
        self.assertEqual(len(self.pings()), 1)

    def test_the_newest_foreign_reply_is_the_event_and_the_operator_and_bots_are_not(self) -> None:
        self.seed()
        self.dthread("2026-10-16T10:00:00Z")
        self.discussion([dcomment("DC_1", "djbclark", "2026-10-16T07:00:00Z", "mine", replies=[
            dcomment("DR_1", "some-bot", "2026-10-16T08:00:00Z", "ci", typename="Bot"),
            dcomment("DR_2", "maintainer", "2026-10-16T09:00:00Z", "looks fine"),
            dcomment("DR_3", "djbclark", "2026-10-16T09:30:00Z", "thanks")])])
        self.assertEqual(self.fw().returncode, 0)
        self.assertEqual(self.pings(), ["paseo: getpaseo/paseo#7828 reply by maintainer: looks fine"])

    def test_operator_and_bot_activity_alone_is_not_an_event(self) -> None:
        self.seed()
        self.dthread("2026-10-16T10:00:00Z")
        self.discussion([dcomment("DC_1", "djbclark", "2026-10-16T09:00:00Z", "mine"),
                         dcomment("DC_2", "some-bot", "2026-10-16T09:30:00Z", "x", typename="Bot")])
        self.assertEqual(self.fw().returncode, 0)
        self.assertEqual(self.pings(), [])

    def test_a_registered_watcher_gets_the_event_without_the_third_partys_words(self) -> None:
        self.assertEqual(self.fw("--relay-to", "sess-1", "paseowatch session").returncode, 0)
        self.assertEqual((self.state / "upstream-paseo.relay").read_text().splitlines()[0], "sess-1")
        self.assertFalse((self.state / "upstream-pr.relay").exists())
        self.seed()
        self.maintainer_replies()
        self.assertEqual(self.fw().returncode, 0)
        (line,) = self.relays()
        self.assertTrue(line.startswith(
            "sess-1 fleet-watch upstream: https://github.com/getpaseo/paseo/discussions/7828 comment by maintainer. Brief: "), line)
        self.assertNotIn("feature request", line)
        brief = next(self.state.glob("upstream-paseo-paseo-7828-*-relay.md")).read_text()
        for text in ("untrusted data", "feature request", "fleet-watch upstream --profile paseo --relay-to",
                     "paseo-contribution-review.md", ".dev/drafts/paseo-reply-getpaseo-paseo-7828.md",
                     "No PR branch: this is a Discussion"):
            self.assertIn(text, brief)
        self.assertEqual((self.pstate()["pending"], self.dispatches()), ([], []))

    def test_a_refused_relay_keeps_the_event_pending_pings_once_and_never_dispatches(self) -> None:
        self.assertEqual(self.fw("--relay-to", "sess-1").returncode, 0)
        self.seed()
        self.maintainer_replies()
        (self.home / "relay_rc").write_text("1")
        self.assertEqual(self.fw().returncode, 0)
        self.assertEqual(len(self.pings()), 2)
        self.assertIn("refused", self.pings()[1])
        self.assertEqual((self.dispatches(), len(self.pstate()["pending"])), ([], 1))
        self.assertEqual(self.fw().returncode, 0)
        self.assertEqual(len(self.pings()), 2)  # one ping per cause
        (self.home / "relay_rc").write_text("0")
        self.assertEqual(self.fw().returncode, 0)
        self.assertEqual((len(self.relays()), self.pstate()["pending"]), (3, []))

    def test_a_close_is_relayed_but_not_queued(self) -> None:
        self.assertEqual(self.fw("--relay-to", "sess-1").returncode, 0)
        self.seed()
        self.dthread("2026-10-16T12:00:00Z")
        self.discussion(closed=True)
        self.assertEqual(self.fw().returncode, 0)
        self.assertEqual(self.pings(), ["paseo: getpaseo/paseo#7828 closed by unknown: Workspace colors"])
        self.assertEqual(len(self.relays()), 1)
        self.assertEqual(self.pstate()["pending"], [])

    def test_the_cfengine_profile_does_not_track_discussions_or_paseo_repos(self) -> None:
        self.dthread(T0, repo="cfengine/core")
        self.assertEqual(self.run_fw().returncode, 0)
        self.dthread("2026-10-16T09:00:00Z", repo="cfengine/core")
        self.discussion([dcomment("DC_2", "larsewi", "2026-10-16T09:00:00Z", "hello")])
        self.assertEqual(self.run_fw().returncode, 0)
        self.assertEqual(self.pings(), [])
        self.assertEqual(json.loads((self.state / "upstream-pr.json").read_text())["threads"], {})

    def test_an_unknown_profile_is_refused(self) -> None:
        result = self.run_fw("--profile", "nope", "--dry-run")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown upstream profile: nope", result.stderr)

    def test_the_scheduled_check_runs_every_profile(self) -> None:
        self.set("notifications", [note("9001", T0, REPO_NAME, "PullRequest", 6412),
                                   note("9100", T0, "getpaseo/paseo", "Discussion", 7828)])
        full = dict(os.environ, HOME=str(self.home), FIX=str(self.fix), FLEET_WATCH_GH=str(self.bin / "gh"),
                    FLEET_WATCH_AIUSE=str(self.bin / "aiuse"), FLEET_WATCH_DISPATCH=str(self.bin / "acp-dispatch"),
                    FLEET_WATCH_HOSTS="", FLEET_WATCH_REPOS="", FLEET_WATCH_VPS="off", FLEET_WATCH_S1="0",
                    FLEET_WATCH_UPSTREAM_PROMPT=str(PROMPT), FLEET_WATCH_HELM=str(self.bin / "nohelm"))
        subprocess.run(["bash", str(FLEET_WATCH), "check"], env=full, capture_output=True, text=True, timeout=120)
        self.assertEqual(list(json.loads((self.state / "upstream-pr.json").read_text())["threads"].values())[0]["n"], 6412)
        self.assertEqual(list(self.pstate()["threads"].values())[0]["n"], 7828)


if __name__ == "__main__":
    unittest.main()
