#!/usr/bin/env python3
"""Tests for fleet-watch's PR, issue and advisory watcher (`fleet-watch prs|issues|advisories`,
bin/fleet_watch_prs.py).

Runs the real script with HOME pointed at a temp dir, a stub hermes-ping that records
each ping's argv, and a fake `gh` (FLEET_WATCH_GH) that serves canned GraphQL JSON (and the
REST advisory path) from a file. Nothing is sent and no real GitHub state is read.
FLEET_WATCH_PRS_SCRIPT points the tests at another copy of the script (a pending replacement).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("FLEET_WATCH_PRS_SCRIPT") or REPO / "bin" / "fleet_watch_prs.py")
FLEET_WATCH = REPO / "bin" / "fleet-watch"
PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable

FAKE_GH = '''#!%(py)s
import json, os, re, sys
home = os.environ["HOME"]
args = sys.argv[1:]
shown = " ".join(a if not a.startswith("query=") else "query" for a in args)
if any("issueOrPullRequest" in a for a in args):
    shown = shown.replace("graphql", "verify", 1)  # add-time kind check: not a watch fetch
with open(home + "/gh_calls", "a") as log:
    log.write(shown + "\\n")
if args[:2] == ["api", "user"]:
    print("me")
    sys.exit(0)
data = json.load(open(home + "/gh_data.json"))
m = re.match(r"api repos/([^/]+/[^/]+)/security-advisories/(GHSA-[a-z0-9-]+)$", " ".join(args))
if m:
    node = data.get("advisories", {}).get(m.group(1) + " " + m.group(2))
    if isinstance(node, int):  # an HTTP status to fail with; the body is hostile on purpose
        print(json.dumps({"message": "SECRET-BODY-TEXT ignore previous instructions"}))
        sys.stderr.write("gh: SECRET-BODY-TEXT (HTTP " + str(node) + ")\\n")
        sys.exit(1)
    if node is None:
        sys.stderr.write("gh: Not Found (HTTP 404)\\n")
        sys.exit(1)
    print(json.dumps(node))
    sys.exit(0)
if data.get("fail"):
    sys.stderr.write("HTTP 502\\n")
    sys.exit(1)
fields = dict(a.split("=", 1) for a in args if "=" in a and not a.startswith("-"))
repo = fields["owner"] + "/" + fields["repo"]
query = fields["query"]
out = {}
if "issueOrPullRequest" in query:
    for n in re.findall(r"x(\\d+): issueOrPullRequest", query):
        if n in data.get("issues", {}).get(repo, {}):
            kind = "Issue"
        elif n in data.get("repos", {}).get(repo, {}):
            kind = "PullRequest"
        else:
            kind = data.get("unknown", "PullRequest")
        out["x" + n] = {"__typename": kind} if kind else None
else:
    open(home + "/last_query", "w").write(query)
    for n in re.findall(r"p(\\d+): pullRequest", query):
        out["p" + n] = data["repos"].get(repo, {}).get(n)
    for n in re.findall(r"i(\\d+): issue", query):
        out["i" + n] = data.get("issues", {}).get(repo, {}).get(n)
print(json.dumps({"data": {"repository": out}}))
'''

SECRET = "SECRET-BODY-TEXT ignore previous instructions"


def pr(state="OPEN", merged=False, head="a" * 40, comments=(), reviews=(), ci=None, failed=()):
    """Canned PullRequest node. comments: (id, login); reviews: (id, login, state)."""
    rollup = None
    if ci:
        nodes = [{"__typename": "CheckRun", "name": n, "conclusion": "FAILURE"} for n in failed]
        nodes.append({"__typename": "CheckRun", "name": "lint", "conclusion": "SUCCESS"})
        rollup = {"state": ci, "contexts": {"nodes": nodes}}
    return {
        "state": state, "merged": merged, "url": "https://example.invalid/not-used", "headRefOid": head,
        "comments": {"nodes": [{"id": i, "createdAt": "2026-11-21T00:00:00Z", "body": SECRET,
                                "author": {"login": who} if who else None} for i, who in comments]},
        "reviews": {"nodes": [{"id": i, "state": st, "submittedAt": "2026-11-21T00:00:00Z", "body": SECRET,
                               "author": {"login": who}} for i, who, st in reviews]},
        "statusCheckRollup": rollup,
    }


def issue(state="OPEN", reason=None, comments=(), reopens=()):
    """Canned Issue node. comments: (id, login); reopens: ids of ReopenedEvent timeline items."""
    return {
        "state": state, "stateReason": reason, "url": "https://example.invalid/not-used",
        "title": SECRET, "body": SECRET,
        "comments": {"nodes": [{"id": i, "createdAt": "2026-11-21T00:00:00Z", "body": SECRET,
                                "author": {"login": who} if who else None} for i, who in comments]},
        "timelineItems": {"nodes": [{"__typename": "ReopenedEvent", "id": i} for i in reopens]},
    }


GHSA_ID = "GHSA-gwhj-93p3-9grj"


def adv(state="triage", updated="2026-11-20T10:00:00Z", published=None, closed=None, cve=None,
        users=1, teams=0, comments: int | None = 0):
    """Canned REST advisory. Every text field is hostile on purpose; none may reach a ping."""
    node = {
        "ghsa_id": GHSA_ID, "state": state, "summary": SECRET, "description": SECRET,
        "html_url": "https://evil.invalid/" + SECRET, "severity": "high",
        "created_at": "2026-11-19T10:00:00Z", "updated_at": updated, "published_at": published,
        "closed_at": closed, "cve_id": cve,
        "collaborating_users": [{"login": SECRET}] * users, "collaborating_teams": [{"slug": SECRET}] * teams,
        "credits": [{"login": SECRET}], "vulnerabilities": [{"package": {"name": SECRET}}],
    }
    if comments is not None:
        node["comments"] = comments
    return node


class Harness(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        (self.home / ".local" / "bin").mkdir(parents=True)
        ping = self.home / ".local" / "bin" / "hermes-ping"
        ping.write_text(
            "#!/bin/bash\n"
            'rc=$(cat "$HOME/ping_rc" 2>/dev/null || echo 0)\n'
            '[ "$rc" = 0 ] && echo "$*" >> "$HOME/pings"\n'
            'exit "$rc"\n'
        )
        ping.chmod(0o755)
        gh = self.home / "gh"
        gh.write_text(FAKE_GH % {"py": PY})
        gh.chmod(0o755)
        self.state = self.home / "state"
        self.data: dict = {"repos": {}}
        self.serve()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def serve(self, **repos) -> None:
        """repos: {"o/r": {number: PR node or None}}; replaces the served data."""
        self.data["repos"] = {r: {str(n): v for n, v in prs.items()} for r, prs in repos.items()}
        (self.home / "gh_data.json").write_text(json.dumps(self.data))

    def serve_issues(self, **repos) -> None:
        """repos: {"o/r": {number: Issue node or None}}; replaces the served issues."""
        self.data["issues"] = {r: {str(n): v for n, v in items.items()} for r, items in repos.items()}
        (self.home / "gh_data.json").write_text(json.dumps(self.data))

    def serve_adv(self, **advisories) -> None:
        """advisories: {"o/r GHSA-...": advisory node, an int HTTP status to fail with, or None (404)}."""
        self.data["advisories"] = advisories
        (self.home / "gh_data.json").write_text(json.dumps(self.data))

    def run_cli(self, *args: str, kind: str = "prs", **env: str) -> subprocess.CompletedProcess:
        full = dict(os.environ, HOME=str(self.home), FLEET_WATCH_GH=str(self.home / "gh"),
                    FLEET_WATCH_TO="telegram:0:0", PATH="/usr/bin:/bin")
        full.pop("FLEET_WATCH_PRS_SELF", None)
        full.pop("HERMES_BIN", None)
        full.pop("HERMES_PING_TARGET", None)
        full.update(env)
        return subprocess.run([PY, str(SCRIPT), "--kind", kind, "--state-dir", str(self.state), *args], env=full,
                              capture_output=True, text=True, timeout=60)

    def add(self, repo: str, *numbers: int | str, kind: str = "prs") -> None:
        r = self.run_cli("add", repo, *map(str, numbers), kind=kind)
        self.assertEqual(r.returncode, 0, r.stderr)

    def check(self, *flags: str, **env: str) -> subprocess.CompletedProcess:
        r = self.run_cli("check", *flags, **env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def sent(self) -> list[str]:
        path = self.home / "pings"
        return path.read_text().splitlines() if path.exists() else []

    def gh_calls(self) -> list[str]:
        path = self.home / "gh_calls"
        return [c for c in path.read_text().splitlines() if "graphql" in c] if path.exists() else []

    def baselined(self, repo="o/r", number=1, **kw) -> None:
        """Watch o/r#1 and take its (silent) baseline from the given PR node."""
        self.add(repo, number)
        self.serve(**{repo: {number: kw.get("node", pr())}})
        self.check()
        self.assertEqual(self.sent(), [])


class FleetWatchPrs(Harness):
    # ---- baseline -------------------------------------------------------
    def test_baseline_is_silent_even_with_history_and_failing_ci(self) -> None:
        self.add("o/r", 1)
        node = pr(comments=[("c1", "alice"), ("c2", "bob")], reviews=[("r1", "carol", "APPROVED")],
                  ci="FAILURE", failed=["build"])
        self.serve(**{"o/r": {1: node}})
        self.check()
        self.assertEqual(self.sent(), [])
        self.check()  # and a second run, nothing new
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.run_cli("ls").stdout.strip(), "o/r#1 active baselined")

    def test_baseline_of_an_already_merged_pr_is_silent_and_inactive(self) -> None:
        self.add("o/r", 1)
        self.serve(**{"o/r": {1: pr(state="MERGED", merged=True)}})
        self.check()
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.run_cli("ls").stdout.strip(), "o/r#1 inactive baselined")

    # ---- comments, reviews, self ---------------------------------------
    def test_new_comment_pings_with_url_and_author(self) -> None:
        self.baselined(node=pr(comments=[("c1", "alice")]))
        self.serve(**{"o/r": {1: pr(comments=[("c1", "alice"), ("c2", "bob")])}})
        self.check()
        self.assertEqual(self.sent(), ["prs: https://github.com/o/r/pull/1 1 comment by bob"])
        self.check()
        self.assertEqual(len(self.sent()), 1)

    def test_own_comments_and_reviews_are_filtered_but_bots_count(self) -> None:
        self.baselined()
        self.serve(**{"o/r": {1: pr(comments=[("c1", "me"), ("c2", "ME")],
                                    reviews=[("r1", "me", "COMMENTED")])}})
        self.check()
        self.assertEqual(self.sent(), [])  # `gh api user` says "me"; compared case-insensitively
        self.serve(**{"o/r": {1: pr(comments=[("c1", "me"), ("c2", "ME"), ("c3", "github-actions[bot]")])}})
        self.check()
        self.assertEqual(self.sent(), ["prs: https://github.com/o/r/pull/1 1 comment by github-actions bot"])

    def test_self_override_env(self) -> None:
        self.baselined()
        self.serve(**{"o/r": {1: pr(comments=[("c1", "alice")])}})
        self.check(FLEET_WATCH_PRS_SELF="alice")
        self.assertEqual(self.sent(), [])

    def test_new_review_state_appears(self) -> None:
        self.baselined(node=pr(reviews=[("r1", "carol", "COMMENTED")]))
        self.serve(**{"o/r": {1: pr(reviews=[("r1", "carol", "COMMENTED"), ("r2", "dave", "CHANGES_REQUESTED"),
                                             ("r3", "erin", "PENDING")])}})
        self.check()
        self.assertEqual(self.sent(), ["prs: https://github.com/o/r/pull/1 review CHANGES_REQUESTED by dave"])

    # ---- CI -------------------------------------------------------------
    def test_ci_failure_pings_once_per_head_and_failure_set(self) -> None:
        self.baselined(node=pr(ci="PENDING"))
        failing = pr(ci="FAILURE", failed=["build", "test"], head="b" * 40)
        self.serve(**{"o/r": {1: failing}})
        self.check()
        self.assertEqual(self.sent(), ["prs: https://github.com/o/r/pull/1 CI failing on bbbbbbb: build, test"])
        self.check()
        self.assertEqual(len(self.sent()), 1)
        # Same head, a different failed set: new ping. A new head failing again: new ping.
        self.serve(**{"o/r": {1: pr(ci="ERROR", failed=["build"], head="b" * 40)}})
        self.check()
        self.serve(**{"o/r": {1: pr(ci="FAILURE", failed=["build", "test"], head="c" * 40)}})
        self.check()
        self.assertEqual(self.sent()[1:], ["prs: https://github.com/o/r/pull/1 CI failing on bbbbbbb: build",
                                           "prs: https://github.com/o/r/pull/1 CI failing on ccccccc: build, test"])
        # A passing run is not an event.
        self.serve(**{"o/r": {1: pr(ci="SUCCESS", head="d" * 40)}})
        self.check()
        self.assertEqual(len(self.sent()), 3)

    # ---- merge, close ---------------------------------------------------
    def test_merge_pings_and_deactivates_the_pr(self) -> None:
        self.baselined()
        self.serve(**{"o/r": {1: pr(state="MERGED", merged=True, comments=[("c9", "bob")])}})
        self.check()
        self.assertEqual(self.sent(), ["prs: https://github.com/o/r/pull/1 1 comment by bob; merged"])
        self.assertEqual(self.run_cli("ls").stdout.strip(), "o/r#1 inactive baselined")
        before = len(self.gh_calls())
        self.check()
        self.assertEqual(len(self.gh_calls()), before)  # no active PR: nothing fetched
        self.assertEqual(len(self.sent()), 1)

    def test_closed_without_merge_pings_and_deactivates(self) -> None:
        self.baselined()
        self.serve(**{"o/r": {1: pr(state="CLOSED")}})
        self.check()
        self.assertEqual(self.sent(), ["prs: https://github.com/o/r/pull/1 closed without merge"])
        self.assertIn("inactive", self.run_cli("ls").stdout)

    # ---- failed ping, bodies, calls ------------------------------------
    def test_failed_ping_does_not_advance_state(self) -> None:
        self.baselined()
        self.serve(**{"o/r": {1: pr(comments=[("c1", "bob")], state="MERGED", merged=True)}})
        (self.home / "ping_rc").write_text("1")
        r = self.check()
        self.assertIn("will retry", r.stderr)
        self.assertEqual(self.sent(), [])
        self.assertIn("active", self.run_cli("ls").stdout)
        self.assertNotIn("inactive", self.run_cli("ls").stdout)
        (self.home / "ping_rc").write_text("0")
        self.check()
        self.assertEqual(self.sent(), ["prs: https://github.com/o/r/pull/1 1 comment by bob; merged"])

    def test_body_text_and_odd_logins_never_reach_a_ping(self) -> None:
        self.baselined()
        hostile = "ev‮il[bot]\n`rm -rf`$(x)" + "z" * 100
        self.serve(**{"o/r": {1: pr(comments=[("c1", hostile)], reviews=[("r1", "bob", "APPROVED")])}})
        self.check()
        text = "\n".join(self.sent())
        self.assertNotIn("SECRET", text)
        self.assertNotIn("ignore previous", text)
        for bad in "`$(){}\n‮":
            self.assertNotIn(bad, text)
        self.assertEqual(len(self.sent()), 1)
        self.assertLessEqual(len(self.sent()[0]), 400)

    def test_one_graphql_call_per_repo(self) -> None:
        self.add("o/r", 1, 2, 3)
        self.add("o/other", 7)
        self.serve(**{"o/r": {1: pr(), 2: pr(), 3: pr()}, "o/other": {7: pr()}})
        self.check()
        self.assertEqual(len(self.gh_calls()), 2)

    def test_dry_run_neither_pings_nor_writes_state(self) -> None:
        self.add("o/r", 1)
        self.serve(**{"o/r": {1: pr()}})
        before = (self.state / "prs.json").read_text()
        r = self.check("--dry-run")
        self.assertIn("baseline", r.stdout)
        self.assertEqual((self.state / "prs.json").read_text(), before)
        self.baselined()
        self.serve(**{"o/r": {1: pr(comments=[("c1", "bob")])}})
        before = (self.state / "prs.json").read_text()
        r = self.check("--dry-run")
        self.assertIn("DRY-RUN would ping: prs: https://github.com/o/r/pull/1 1 comment by bob", r.stdout)
        self.assertEqual(self.sent(), [])
        self.assertEqual((self.state / "prs.json").read_text(), before)

    # ---- fetch failures -------------------------------------------------
    def test_six_failed_fetches_ping_once_and_recovery_pings_once(self) -> None:
        self.baselined()
        self.data["fail"] = True
        (self.home / "gh_data.json").write_text(json.dumps(self.data))
        for _ in range(5):
            r = self.run_cli("check")
            self.assertEqual(r.returncode, 1)
        self.assertEqual(self.sent(), [])
        for _ in range(3):
            self.run_cli("check")
        self.assertEqual(self.sent(), ["prs: fetch failing for o/r"])
        self.data["fail"] = False
        (self.home / "gh_data.json").write_text(json.dumps(self.data))
        self.serve(**{"o/r": {1: pr()}})
        self.check()
        self.assertEqual(self.sent()[1:], ["prs: fetch recovered for o/r"])
        self.check()
        self.assertEqual(len(self.sent()), 2)

    def test_missing_alias_counts_as_failure_but_siblings_are_processed(self) -> None:
        self.add("o/r", 1, 2)
        self.serve(**{"o/r": {1: pr(comments=[("c0", "alice")]), 2: pr()}})
        self.check()
        self.assertEqual(self.sent(), [])
        self.serve(**{"o/r": {1: pr(comments=[("c0", "alice"), ("c1", "bob")]), 2: None}})
        r = self.run_cli("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("#2", r.stderr)
        self.assertEqual(self.sent(), ["prs: https://github.com/o/r/pull/1 1 comment by bob"])
        fetch = json.loads((self.state / "prs.json").read_text())["fetch"]["o/r"]
        self.assertEqual(fetch["fails"], 1)
        self.run_cli("check")
        self.assertEqual(json.loads((self.state / "prs.json").read_text())["fetch"]["o/r"]["fails"], 2)
        self.assertEqual(len(self.sent()), 1)

    def test_failed_fetch_keeps_state(self) -> None:
        self.baselined(node=pr(comments=[("c1", "alice")]))
        self.data["fail"] = True
        (self.home / "gh_data.json").write_text(json.dumps(self.data))
        self.run_cli("check")
        self.data["fail"] = False
        self.serve(**{"o/r": {1: pr(comments=[("c1", "alice"), ("c2", "bob")])}})
        self.check()
        self.assertEqual(self.sent(), ["prs: https://github.com/o/r/pull/1 1 comment by bob"])

    # ---- add / rm / ls and the fleet-watch entry point -----------------
    def test_add_rm_ls(self) -> None:
        self.assertIn("nothing watched", self.run_cli("ls").stdout)
        self.add("o/r", 5, 6)
        self.add("o/r", 5)  # again: harmless
        self.assertEqual(self.run_cli("ls").stdout.splitlines(), ["o/r#5 active new", "o/r#6 active new"])
        self.assertEqual(self.run_cli("rm", "o/r", "5").returncode, 0)
        self.assertEqual(self.run_cli("ls").stdout.splitlines(), ["o/r#6 active new"])
        self.assertEqual(oct((self.state / "prs.json").stat().st_mode & 0o777), "0o600")
        self.assertEqual(self.run_cli("add", "no-slash", "1").returncode, 1)
        self.assertEqual(self.run_cli("add", "o/r", "x1").returncode, 1)

    def test_fleet_watch_prs_subcommand(self) -> None:
        env = dict(os.environ, HOME=str(self.home), FLEET_WATCH_GH=str(self.home / "gh"), FLEET_WATCH_TO="telegram:0:0")
        base = ["bash", str(FLEET_WATCH), "prs", "--state-dir", str(self.state)]
        r = subprocess.run(base + ["add", "o/r", "4"], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(base + ["ls"], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), "o/r#4 active new")


class FleetWatchIssues(Harness):
    def watched(self, node=None, number=1) -> None:
        """Watch o/r issue `number` and take its (silent) baseline from `node`."""
        before = len(self.sent())
        self.serve_issues(**{"o/r": {number: node or issue()}})
        self.add("o/r", number, kind="issues")
        self.check()
        self.assertEqual(len(self.sent()), before)  # a baseline never pings

    def test_baseline_is_silent_even_with_history_and_a_closed_issue_is_inactive(self) -> None:
        self.watched(issue(comments=[("c1", "alice"), ("c2", "bob")], reopens=["e1"]))
        self.check()
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.run_cli("ls", kind="issues").stdout.strip(), "o/r#1 active baselined")
        self.serve_issues(**{"o/r": {1: issue(), 2: issue(state="CLOSED", reason="COMPLETED")}})
        self.add("o/r", 2, kind="issues")
        self.check()
        self.assertEqual(self.sent(), [])
        self.assertIn("o/r#2 inactive baselined", self.run_cli("ls", kind="issues").stdout)

    def test_new_comment_pings_with_url_and_author_once(self) -> None:
        self.watched(issue(comments=[("c1", "alice")]))
        self.serve_issues(**{"o/r": {1: issue(comments=[("c1", "alice"), ("c2", "bob"), ("c3", "erin")])}})
        self.check()
        self.assertEqual(self.sent(), ["issues: https://github.com/o/r/issues/1 2 comments by bob, erin"])
        self.check()
        self.assertEqual(len(self.sent()), 1)

    def test_own_comments_are_filtered_but_bots_count(self) -> None:
        self.watched()
        self.serve_issues(**{"o/r": {1: issue(comments=[("c1", "me"), ("c2", "ME")])}})
        self.check()
        self.assertEqual(self.sent(), [])
        self.serve_issues(**{"o/r": {1: issue(comments=[("c1", "me"), ("c2", "ME"), ("c3", "github-actions[bot]")])}})
        self.check()
        self.assertEqual(self.sent(), ["issues: https://github.com/o/r/issues/1 1 comment by github-actions bot"])

    def test_close_pings_once_with_the_reason_and_deactivates(self) -> None:
        for number, (reason, words) in enumerate([("COMPLETED", "completed"), ("NOT_PLANNED", "not planned"),
                                                   ("DUPLICATE", "duplicate"), (None, None)], start=1):
            self.watched(number=number)
            self.serve_issues(**{"o/r": {number: issue(state="CLOSED", reason=reason)}})
            self.check()
            expect = "closed as " + words if words else "closed"
            self.assertEqual(self.sent()[-1], "issues: https://github.com/o/r/issues/%d %s" % (number, expect))
            self.assertIn("o/r#%d inactive baselined" % number, self.run_cli("ls", kind="issues").stdout)
        self.assertEqual(len(self.sent()), 4)
        before = len(self.gh_calls())
        self.check()
        self.assertEqual(len(self.gh_calls()), before)  # nothing active: nothing fetched
        self.assertEqual(len(self.sent()), 4)

    def test_close_with_a_comment_aggregates_into_one_ping(self) -> None:
        self.watched()
        self.serve_issues(**{"o/r": {1: issue(state="CLOSED", reason="COMPLETED", comments=[("c9", "bob")])}})
        self.check()
        self.assertEqual(self.sent(), ["issues: https://github.com/o/r/issues/1 1 comment by bob; closed as completed"])

    def test_reopen_pings_once(self) -> None:
        self.watched(issue(reopens=["e1"]))
        self.serve_issues(**{"o/r": {1: issue(reason="REOPENED", reopens=["e1", "e2"])}})
        self.check()
        self.assertEqual(self.sent(), ["issues: https://github.com/o/r/issues/1 reopened"])
        self.check()
        self.assertEqual(len(self.sent()), 1)
        # Closed, then reopened again later: the second reopen is a new timeline event.
        self.serve_issues(**{"o/r": {1: issue(reason="REOPENED", reopens=["e1", "e2", "e3"])}})
        self.check()
        self.assertEqual(self.sent()[1:], ["issues: https://github.com/o/r/issues/1 reopened"])

    def test_failed_ping_does_not_advance_state(self) -> None:
        self.watched()
        self.serve_issues(**{"o/r": {1: issue(state="CLOSED", reason="NOT_PLANNED")}})
        (self.home / "ping_rc").write_text("1")
        r = self.check()
        self.assertIn("will retry", r.stderr)
        self.assertNotIn("inactive", self.run_cli("ls", kind="issues").stdout)
        (self.home / "ping_rc").write_text("0")
        self.check()
        self.assertEqual(self.sent(), ["issues: https://github.com/o/r/issues/1 closed as not planned"])

    def test_one_graphql_call_per_repo_with_prs_and_issues_mixed(self) -> None:
        self.serve(**{"o/r": {1: pr(), 2: pr()}, "o/other": {7: pr()}})
        self.serve_issues(**{"o/r": {3: issue(), 4: issue()}, "o/third": {9: issue()}})
        self.add("o/r", 1, 2)
        self.add("o/r", 3, 4, kind="issues")
        self.add("o/other", 7)
        self.add("o/third", 9, kind="issues")
        self.check()
        self.assertEqual(len(self.gh_calls()), 3)
        self.serve(**{"o/r": {1: pr(comments=[("c1", "bob")]), 2: pr()}, "o/other": {7: pr()}})
        self.serve_issues(**{"o/r": {3: issue(comments=[("c2", "erin")]), 4: issue()}, "o/third": {9: issue()}})
        before = len(self.gh_calls())
        self.check()
        self.assertEqual(len(self.gh_calls()) - before, 3)
        query = (self.home / "last_query").read_text()
        self.assertTrue(query)
        self.assertEqual(sorted(self.sent()), ["issues: https://github.com/o/r/issues/3 1 comment by erin",
                                               "prs: https://github.com/o/r/pull/1 1 comment by bob"])

    def test_the_repo_query_holds_both_kinds(self) -> None:
        self.serve(**{"o/r": {1: pr()}})
        self.serve_issues(**{"o/r": {3: issue()}})
        self.add("o/r", 1)
        self.add("o/r", 3, kind="issues")
        self.check()
        query = (self.home / "last_query").read_text()
        self.assertIn("p1: pullRequest(number:1)", query)
        self.assertIn("i3: issue(number:3)", query)
        self.assertIn("stateReason", query)

    def test_add_refuses_the_wrong_kind_and_missing_numbers(self) -> None:
        self.serve(**{"o/r": {5: pr()}})
        self.serve_issues(**{"o/r": {6: issue()}})
        r = self.run_cli("add", "o/r", "5", kind="issues")
        self.assertEqual(r.returncode, 1)
        self.assertIn("o/r#5 is a pull request, not an issue", r.stderr)
        self.assertIn("fleet-watch prs add", r.stderr)
        r = self.run_cli("add", "o/r", "6", kind="prs")
        self.assertEqual(r.returncode, 1)
        self.assertIn("o/r#6 is an issue, not a pull request", r.stderr)
        self.data["unknown"] = None
        self.serve_issues(**{"o/r": {6: issue()}})
        r = self.run_cli("add", "o/r", "7", kind="issues")
        self.assertEqual(r.returncode, 1)
        self.assertIn("o/r#7 does not exist", r.stderr)
        # One bad number refuses the whole add: nothing is written for the good one.
        r = self.run_cli("add", "o/r", "6", "5", kind="issues")
        self.assertEqual(r.returncode, 1)
        self.assertIn("nothing watched", self.run_cli("ls", kind="issues").stdout)
        self.assertEqual(self.run_cli("add", "o/r", "6", kind="issues").returncode, 0)
        self.assertEqual(self.run_cli("ls", kind="issues").stdout.strip(), "o/r#6 active new")
        self.assertIn("nothing watched", self.run_cli("ls", kind="prs").stdout)

    def test_add_when_github_cannot_be_asked_is_refused(self) -> None:
        self.data["fail"] = True
        (self.home / "gh_data.json").write_text(json.dumps(self.data))
        r = self.run_cli("add", "o/r", "6", kind="issues")
        self.assertEqual(r.returncode, 1)
        self.assertIn("graphql failed", r.stderr)
        self.assertIn("nothing watched", self.run_cli("ls", kind="issues").stdout)

    def test_titles_bodies_and_odd_logins_never_reach_a_ping(self) -> None:
        self.watched()
        hostile = "ev‮il[bot]\n`rm -rf`$(x)" + "z" * 100
        self.serve_issues(**{"o/r": {1: issue(state="CLOSED", reason="COMPLETED", comments=[("c1", hostile)])}})
        r = self.check()
        text = "\n".join(self.sent())
        self.assertNotIn("SECRET", text + r.stdout + r.stderr)
        self.assertNotIn("ignore previous", text)
        for bad in "`$(){}\n‮":
            self.assertNotIn(bad, text)
        self.assertEqual(len(self.sent()), 1)
        self.assertLessEqual(len(self.sent()[0]), 400)

    def test_missing_issue_counts_as_failure_but_siblings_are_processed(self) -> None:
        self.serve_issues(**{"o/r": {1: issue(), 2: issue()}})
        self.add("o/r", 1, 2, kind="issues")
        self.check()
        self.serve_issues(**{"o/r": {1: issue(comments=[("c1", "bob")]), 2: None}})
        r = self.run_cli("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("issue(s) not found: #2", r.stderr)
        self.assertEqual(self.sent(), ["issues: https://github.com/o/r/issues/1 1 comment by bob"])

    def test_six_failed_fetches_ping_once_with_issues_only_repo(self) -> None:
        self.watched()
        self.data["fail"] = True
        (self.home / "gh_data.json").write_text(json.dumps(self.data))
        for _ in range(8):
            self.run_cli("check")
        self.assertEqual(self.sent(), ["issues: fetch failing for o/r"])

    def test_dry_run_neither_pings_nor_writes_state(self) -> None:
        self.watched()
        self.serve_issues(**{"o/r": {1: issue(state="CLOSED", reason="COMPLETED")}})
        before = (self.state / "prs.json").read_text()
        r = self.check("--dry-run")
        self.assertIn("DRY-RUN would ping: issues: https://github.com/o/r/issues/1 closed as completed", r.stdout)
        self.assertEqual(self.sent(), [])
        self.assertEqual((self.state / "prs.json").read_text(), before)

    def test_rm_and_the_fleet_watch_entry_point(self) -> None:
        self.serve_issues(**{"o/r": {4: issue()}})
        env = dict(os.environ, HOME=str(self.home), FLEET_WATCH_GH=str(self.home / "gh"), FLEET_WATCH_TO="telegram:0:0")
        base = ["bash", str(FLEET_WATCH), "issues", "--state-dir", str(self.state)]
        r = subprocess.run(base + ["add", "o/r", "4"], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(base + ["ls"], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), "o/r#4 active new")
        self.assertEqual(self.run_cli("rm", "o/r", "4", kind="issues").returncode, 0)
        self.assertIn("nothing watched", self.run_cli("ls", kind="issues").stdout)


class FleetWatchAdvisories(Harness):
    KEY = "o/r " + GHSA_ID
    URL = "https://github.com/o/r/security/advisories/" + GHSA_ID

    def watched(self, node=None) -> None:
        self.serve_adv(**{self.KEY: node or adv()})
        self.add("o/r", GHSA_ID, kind="advisories")
        self.check()
        self.assertEqual(self.sent(), [])

    def adv_calls(self) -> list[str]:
        path = self.home / "gh_calls"
        return [c for c in path.read_text().splitlines() if "security-advisories" in c] if path.exists() else []

    def test_baseline_is_silent_and_one_rest_call_per_advisory(self) -> None:
        self.watched(adv(cve="CVE-2026-1234", users=2))
        self.check()
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.run_cli("ls", kind="advisories").stdout.strip(), "o/r#%s active baselined" % GHSA_ID)
        self.assertEqual(self.adv_calls(), ["api repos/o/r/security-advisories/%s" % GHSA_ID] * 2)
        self.assertFalse([c for c in (self.home / "gh_calls").read_text().splitlines() if "api user" in c],
                         "an advisory-only watch needs no login lookup")

    def test_baseline_of_an_already_published_advisory_is_silent_and_inactive(self) -> None:
        self.watched(adv(state="published", published="2026-11-20T00:00:00Z", cve="CVE-2026-1"))
        self.assertIn("inactive baselined", self.run_cli("ls", kind="advisories").stdout)
        self.check()
        self.assertEqual(len(self.adv_calls()), 1)  # not fetched again

    def test_state_change_pings_with_the_new_and_old_state(self) -> None:
        self.watched()
        self.serve_adv(**{self.KEY: adv(state="draft", updated="2026-11-21T08:00:00Z")})
        self.check()
        self.assertEqual(self.sent(), ["advisory: %s state triage to draft" % self.URL])
        self.check()
        self.assertEqual(len(self.sent()), 1)

    def test_cve_assigned_pings(self) -> None:
        self.watched()
        self.serve_adv(**{self.KEY: adv(cve="CVE-2026-12345", updated="2026-11-21T08:00:00Z")})
        self.check()
        self.assertEqual(self.sent(), ["advisory: %s CVE assigned CVE-2026-12345" % self.URL])

    def test_a_bare_updated_pings_with_the_short_date(self) -> None:
        self.watched()
        self.serve_adv(**{self.KEY: adv(updated="2026-11-21T08:00:00Z")})
        self.check()
        self.assertEqual(self.sent(), ["advisory: %s updated 2026-11-21, see the advisory page" % self.URL])
        self.check()
        self.assertEqual(len(self.sent()), 1)

    def test_collaborator_and_comment_count_changes_ping(self) -> None:
        self.watched()
        self.serve_adv(**{self.KEY: adv(users=2, teams=1, comments=3, updated="2026-11-21T08:00:00Z")})
        self.check()
        self.assertEqual(self.sent(), ["advisory: %s collaborating users 1 to 2; collaborating teams 0 to 1; 3 new comments" % self.URL])

    def test_missing_comment_field_is_tolerated(self) -> None:
        self.watched(adv(comments=None))
        self.serve_adv(**{self.KEY: adv(comments=None, updated="2026-11-21T08:00:00Z")})
        self.check()
        self.assertEqual(len(self.sent()), 1)
        self.assertIn("updated 2026-11-21", self.sent()[0])

    def test_published_pings_once_and_deactivates(self) -> None:
        self.watched()
        self.serve_adv(**{self.KEY: adv(state="published", published="2026-11-21T09:00:00Z", cve="CVE-2026-0777",
                                        updated="2026-11-21T09:00:00Z")})
        self.check()
        self.assertEqual(self.sent(), ["advisory: %s published; CVE assigned CVE-2026-0777" % self.URL])
        self.assertIn("inactive baselined", self.run_cli("ls", kind="advisories").stdout)
        before = len(self.adv_calls())
        self.check()
        self.assertEqual(len(self.adv_calls()), before)
        self.assertEqual(len(self.sent()), 1)

    def test_closed_pings_once_and_deactivates(self) -> None:
        self.watched(adv(state="draft"))
        self.serve_adv(**{self.KEY: adv(state="closed", closed="2026-11-21T09:00:00Z", updated="2026-11-21T09:00:00Z")})
        self.check()
        self.assertEqual(self.sent(), ["advisory: %s closed" % self.URL])
        self.assertIn("inactive", self.run_cli("ls", kind="advisories").stdout)

    def test_failed_ping_does_not_advance_state(self) -> None:
        self.watched()
        self.serve_adv(**{self.KEY: adv(state="published", published="2026-11-21T09:00:00Z")})
        (self.home / "ping_rc").write_text("1")
        r = self.check()
        self.assertIn("will retry", r.stderr)
        self.assertNotIn("inactive", self.run_cli("ls", kind="advisories").stdout)
        (self.home / "ping_rc").write_text("0")
        self.check()
        self.assertEqual(self.sent(), ["advisory: %s published" % self.URL])

    def test_403_counts_as_a_fetch_failure_and_six_give_one_ping_then_recovery(self) -> None:
        self.watched()
        self.serve_adv(**{self.KEY: 403})
        for _ in range(5):
            r = self.run_cli("check")
            self.assertEqual(r.returncode, 1)
            self.assertIn("advisory fetch failed: HTTP 403", r.stderr)
            self.assertNotIn("SECRET", r.stdout + r.stderr)
        self.assertEqual(self.sent(), [])
        for _ in range(3):
            self.run_cli("check")
        self.assertEqual(self.sent(), ["advisory: fetch failing for o/r " + GHSA_ID])
        self.serve_adv(**{self.KEY: adv()})
        self.check()
        self.assertEqual(self.sent()[1:], ["advisory: fetch recovered for o/r " + GHSA_ID])
        self.check()
        self.assertEqual(len(self.sent()), 2)
        self.assertNotIn("SECRET", (self.state / "fleet-watch.log").read_text())

    def test_404_counts_as_a_fetch_failure_too(self) -> None:
        self.watched()
        self.serve_adv(**{self.KEY: None})
        for _ in range(6):
            self.assertEqual(self.run_cli("check").returncode, 1)
        self.assertEqual(self.sent(), ["advisory: fetch failing for o/r " + GHSA_ID])

    def test_a_failed_fetch_keeps_state(self) -> None:
        self.watched()
        self.serve_adv(**{self.KEY: 403})
        self.run_cli("check")
        self.serve_adv(**{self.KEY: adv(state="draft")})
        self.check()
        self.assertEqual(self.sent(), ["advisory: %s state triage to draft" % self.URL])

    def test_bad_ghsa_ids_and_repos_are_refused_at_add(self) -> None:
        for bad in ("GHSA-aaaa-bbbb-cccc", "ghsa-gwhj-93p3-9grj", "GHSA-gwhj-93p3", "GHSA-gwhj-93p3-9grj-9grj",
                    "GHSA-GWHJ-93P3-9GRJ", "GHSA-gwhj-93p3-9grj/../x", "12", "GHSA-gwhj-93p3-9gr!"):
            r = self.run_cli("add", "o/r", bad, kind="advisories")
            self.assertEqual(r.returncode, 1, bad)
            self.assertIn("advisory id must look like", r.stderr)
        self.assertEqual(self.run_cli("add", "no-slash", GHSA_ID, kind="advisories").returncode, 1)
        self.assertEqual(self.run_cli("add", "o/r", GHSA_ID + "\n", kind="advisories").returncode, 1)
        self.assertIn("nothing watched", self.run_cli("ls", kind="advisories").stdout)
        self.assertEqual(self.adv_calls(), [])

    def test_a_hostile_state_file_entry_never_builds_a_url_or_a_call(self) -> None:
        self.add("o/r", GHSA_ID, kind="advisories")
        state = json.loads((self.state / "prs.json").read_text())
        state["advisories"]["o/r#" + GHSA_ID]["ghsa"] = "GHSA-aaaa-bbbb-cccc"
        (self.state / "prs.json").write_text(json.dumps(state))
        r = self.run_cli("check")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.adv_calls(), [])

    def test_no_advisory_text_ever_reaches_a_ping_a_log_or_the_output(self) -> None:
        self.watched()
        hostile = adv(state="dr\naft`$(x)", updated="2026-11-21T08:00:00Z", cve="CVE-2026-1\n" + SECRET)
        hostile["html_url"] = "https://evil.invalid/" + SECRET
        self.serve_adv(**{self.KEY: hostile})
        r = self.check()
        text = "\n".join(self.sent())
        self.assertEqual(len(self.sent()), 1)
        for blob in (text, r.stdout, r.stderr, (self.state / "fleet-watch.log").read_text() if (self.state / "fleet-watch.log").exists() else ""):
            self.assertNotIn("SECRET", blob)
            self.assertNotIn("ignore previous", blob)
            self.assertNotIn("evil.invalid", blob)
        for bad in "`$(){}\n‮":
            self.assertNotIn(bad, text)
        self.assertTrue(text.startswith("advisory: " + self.URL))
        self.assertLessEqual(len(text), 400)
        self.assertNotIn(SECRET, (self.state / "prs.json").read_text())

    def test_advisories_run_beside_prs_and_issues(self) -> None:
        self.serve(**{"o/r": {1: pr()}})
        self.serve_issues(**{"o/r": {2: issue()}})
        self.serve_adv(**{self.KEY: adv()})
        self.add("o/r", 1)
        self.add("o/r", 2, kind="issues")
        self.add("o/r", GHSA_ID, kind="advisories")
        self.check()
        self.assertEqual(self.sent(), [])
        self.serve(**{"o/r": {1: pr(state="MERGED", merged=True)}})
        self.serve_issues(**{"o/r": {2: issue(state="CLOSED", reason="COMPLETED")}})
        self.serve_adv(**{self.KEY: adv(state="closed", closed="2026-11-21T00:00:00Z")})
        self.check()
        self.assertEqual(sorted(self.sent()), sorted([
            "prs: https://github.com/o/r/pull/1 merged",
            "issues: https://github.com/o/r/issues/2 closed as completed",
            "advisory: %s closed" % self.URL]))
        self.assertEqual(len(self.gh_calls()), 2)  # one GraphQL call for the first run, one for the second

    def test_dry_run_neither_pings_nor_writes_state(self) -> None:
        self.watched()
        self.serve_adv(**{self.KEY: adv(cve="CVE-2026-0005", updated="2026-11-21T08:00:00Z")})
        before = (self.state / "prs.json").read_text()
        r = self.check("--dry-run")
        self.assertIn("DRY-RUN would ping: advisory: %s CVE assigned CVE-2026-0005" % self.URL, r.stdout)
        self.assertEqual(self.sent(), [])
        self.assertEqual((self.state / "prs.json").read_text(), before)

    def test_rm_and_the_fleet_watch_entry_point(self) -> None:
        env = dict(os.environ, HOME=str(self.home), FLEET_WATCH_GH=str(self.home / "gh"), FLEET_WATCH_TO="telegram:0:0")
        base = ["bash", str(FLEET_WATCH), "advisories", "--state-dir", str(self.state)]
        r = subprocess.run(base + ["add", "o/r", GHSA_ID], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(base + ["ls"], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), "o/r#%s active new" % GHSA_ID)
        self.assertEqual(self.run_cli("rm", "o/r", GHSA_ID, kind="advisories").returncode, 0)
        self.assertIn("nothing watched", self.run_cli("ls", kind="advisories").stdout)


class LiveFileCompat(Harness):
    """The watch list the live launchd run reads (omercnet/paseo-plugins 662 inactive, 672 and 676
    active, from before issues and advisories existed) loads unchanged: no re-baseline, no ping."""

    def test_the_current_schema_loads_with_no_ping_and_no_rebaseline(self) -> None:
        head = "a" * 40
        slug = "omercnet/paseo-plugins"
        fixture = {
            "version": 1, "self": "me",
            "fetch": {slug: {"alerted": False, "fails": 0}},
            "prs": {
                slug + "#662": {"repo": slug, "number": 662, "active": False, "baselined": True,
                                "seen_comments": ["c1"], "seen_reviews": ["r1"], "ci_pinged": []},
                slug + "#672": {"repo": slug, "number": 672, "active": True, "baselined": True,
                                "seen_comments": ["c1", "c2"], "seen_reviews": [], "ci_pinged": [head + ":build"]},
                slug + "#676": {"repo": slug, "number": 676, "active": True, "baselined": True,
                                "seen_comments": [], "seen_reviews": ["r7"], "ci_pinged": []},
            },
        }
        self.state.mkdir(parents=True)
        (self.state / "prs.json").write_text(json.dumps(fixture))
        self.serve(**{slug: {
            672: pr(comments=[("c1", "alice"), ("c2", "bob")], ci="FAILURE", failed=["build"], head=head),
            676: pr(reviews=[("r7", "carol", "APPROVED")]),
        }})
        self.check()
        self.assertEqual(self.sent(), [])
        after = json.loads((self.state / "prs.json").read_text())
        self.assertEqual(after["prs"], fixture["prs"])
        self.assertEqual((after["self"], after["fetch"]), (fixture["self"], fixture["fetch"]))
        self.assertEqual((after["issues"], after["advisories"]), ({}, {}))
        self.assertEqual(len(self.gh_calls()), 1)
        self.assertNotIn("p662", (self.home / "last_query").read_text())  # inactive: not fetched
        self.assertNotIn("api user", (self.home / "gh_calls").read_text())
        self.assertEqual(self.run_cli("ls").stdout.splitlines(),
                         [slug + "#662 inactive baselined", slug + "#672 active baselined", slug + "#676 active baselined"])
        # And a real event on a watched PR still pings, as before.
        self.serve(**{slug: {672: pr(comments=[("c1", "alice"), ("c2", "bob"), ("c3", "dave")], ci="FAILURE",
                                     failed=["build"], head=head), 676: pr(reviews=[("r7", "carol", "APPROVED")])}})
        self.check()
        self.assertEqual(self.sent(), ["prs: https://github.com/omercnet/paseo-plugins/pull/672 1 comment by dave"])


if __name__ == "__main__":
    unittest.main()
