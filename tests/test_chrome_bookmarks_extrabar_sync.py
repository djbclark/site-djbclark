#!/usr/bin/env python3
"""Tests for bin/chrome-bookmarks-extrabar-sync: tree building and escaping, hash stability, the
decision logic, and whole runs against a fake extrabar-mcp server script (never the live app)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_loader = SourceFileLoader("cbes", str(ROOT / "bin" / "chrome-bookmarks-extrabar-sync"))
_spec = spec_from_loader("cbes", _loader)
assert _spec is not None
cbes = module_from_spec(_spec)
_loader.exec_module(cbes)

PRESET = "PRESET-1"
T0 = 1_800_000_000.0  # a clock far past any 24 h window

FAKE_MCP = """#!/usr/bin/env python3
import json, os, sys, uuid

path = os.environ["FAKE_XB_STATE"]
st = json.load(open(path))
approve_after = int(os.environ.get("FAKE_XB_APPROVE_AFTER", "-1"))  # polls until approved; -1 never
confirmations = {}
approved = set()
polls = []


def save():
    json.dump(st, open(path, "w"))


def reply(i, structured=None, error=None):
    if error:
        res = {"isError": True, "content": [{"type": "text", "text": error}]}
    else:
        res = {"isError": False, "content": [{"type": "text", "text": json.dumps(structured)}], "structuredContent": structured}
    print(json.dumps({"jsonrpc": "2.0", "id": i, "result": res}), flush=True)


for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("method") == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"serverInfo": {"name": "fake"}}}), flush=True)
        continue
    if msg.get("method") != "tools/call":
        continue
    i, tool, a = msg["id"], msg["params"]["name"], msg["params"]["arguments"]
    if st.get("mode") == "app_not_running":
        reply(i, error="app_not_running: ExtraBar is not running or the MCP bridge is off.")
    elif tool == "extrabar_get_status":
        reply(i, {"activePresetId": st["active"], "activePresetName": "x"})
    elif tool == "extrabar_get_preset":
        reply(i, {"id": a["presetId"], "items": st["items"]})
    elif tool == "extrabar_remove_item":
        st["log"].append(["remove", a]); save()
        if not any(x["id"] == a["itemId"] for x in st["items"]):
            reply(i, error="not_found: no such item")
        elif a["itemId"] in approved:
            st["items"] = [x for x in st["items"] if x["id"] != a["itemId"]]; save()
            reply(i, {"removed": True})
        else:
            cid = str(uuid.uuid4())
            confirmations[cid] = [a["itemId"], 0]
            reply(i, {"status": "pending_user_confirmation", "confirmationId": cid})
    elif tool == "extrabar_get_confirmation_status":
        c = confirmations.get(a["confirmationId"])
        if c is None:
            reply(i, error="not_found: No confirmation exists for this client and confirmationId.")
            continue
        c[1] += 1
        if approve_after >= 0 and c[1] >= approve_after:
            approved.add(c[0])
            reply(i, {"status": "approved"})
        else:
            reply(i, {"status": "pending"})
    elif tool == "extrabar_add_folder_widget":
        new = str(uuid.uuid4())
        st["items"].append({"id": new, "name": a["title"]})
        st["log"].append(["add", {"title": a["title"], "items": a["items"]}]); save()
        reply(i, {"itemId": new})
    elif tool == "extrabar_reorder_items":
        st["log"].append(["reorder", a]); save()
        ids = [x["id"] for x in st["items"]]
        if sorted(ids) != sorted(a["orderedItemIds"]):
            reply(i, error="invalid_argument: ids differ")
        else:
            by = {x["id"]: x for x in st["items"]}
            st["items"] = [by[x] for x in a["orderedItemIds"]]; save()
            reply(i, {"ok": True})
    elif tool == "extrabar_add_action_widget":
        new = str(uuid.uuid4())
        st["items"].append({"id": new, "name": a["title"]})
        st["log"].append(["add_action", {"title": a["title"], "action": a["action"]}]); save()
        reply(i, {"itemId": new, "scriptActions": [{"actionId": "ACT-" + new}]})
    elif tool == "extrabar_update_widget_item":
        st["log"].append(["update", a]); save()
        reply(i, {"changedFields": ["isVisible"]})
    elif tool == "extrabar_run_action":
        st["log"].append(["run", a]); save()
        polls.clear()
        reply(i, {"runId": "RUN-1", "status": "running"})
    elif tool == "extrabar_get_last_run_output":
        polls.append(1)
        if len(polls) < 2:
            reply(i, {"status": "running", "exitCode": None, "stdout": "", "stderr": ""})
        else:
            code = int(os.environ.get("FAKE_XB_RUN_EXIT", "0"))
            reply(i, {"status": "succeeded" if code == 0 else "failed", "exitCode": code,
                      "stdout": os.environ.get("FAKE_XB_RUN_STDOUT", ""), "stderr": ""})
    else:
        reply(i, error="unknown_tool: " + tool)
"""


def url(u: str, name: str = "n") -> dict:
    return {"type": "url", "name": name, "url": u}


def folder(name: str, *kids: dict) -> dict:
    return {"type": "folder", "name": name, "children": list(kids)}


def bookmarks_doc(*bar: dict) -> dict:
    return {
        "roots": {
            "bookmark_bar": folder("Bookmarks Bar", *bar),
            "other": folder(
                "Other Bookmarks", url("https://other.example", "OTHERTITLE")
            ),
            "synced": folder("Mobile Bookmarks"),
        }
    }


class Tree(unittest.TestCase):
    def test_escape_template_url_only_touches_template_characters(self):
        raw = "https://a.example/p{x}/q r?k=v&w=%20z#frag"
        self.assertEqual(
            cbes.escape_template_url(raw),
            "https://a.example/p%7Bx%7D/q%20r?k=v&w=%20z#frag",
        )
        self.assertEqual(
            cbes.escape_template_url("https://a.example/\x01"), "https://a.example/%01"
        )

    def test_items_nest_and_every_link_targets_safari(self):
        nodes = [
            {"name": "A", "url": "https://a.example/{id}"},
            {"name": "F", "children": [{"name": "", "url": "https://b.example"}]},
        ]
        items = cbes.build_items(nodes)
        self.assertEqual(items[0]["kind"], "action")
        self.assertEqual(items[0]["action"]["type"], "deep_link")
        self.assertNotIn("{", items[0]["action"]["templateUrl"])
        self.assertEqual(items[0]["target"], {"bundleId": "com.apple.Safari"})
        self.assertEqual(items[1]["kind"], "folder")
        self.assertEqual(items[1]["title"], "F")
        self.assertEqual(
            items[1]["items"][0]["name"], "https://b.example"
        )  # no name: the URL
        self.assertEqual(cbes.count_items(items), (2, 1))

    def test_long_titles_are_cut(self):
        items = cbes.build_items([{"name": "x" * 500, "url": "https://a.example"}])
        self.assertLessEqual(len(items[0]["name"]), cbes.TITLE_MAX)

    def test_hash_is_stable_and_sensitive(self):
        a = cbes.build_items([{"name": "A", "url": "https://a.example"}])
        again = cbes.build_items([{"name": "A", "url": "https://a.example"}])
        self.assertEqual(cbes.tree_hash(a), cbes.tree_hash(again))
        self.assertNotEqual(
            cbes.tree_hash(a),
            cbes.tree_hash(
                cbes.build_items([{"name": "B", "url": "https://a.example"}])
            ),
        )
        two = cbes.build_items(
            [
                {"name": "A", "url": "https://a.example"},
                {"name": "B", "url": "https://b.example"},
            ]
        )
        self.assertNotEqual(cbes.tree_hash(two), cbes.tree_hash(list(reversed(two))))
        before = cbes.tree_hash(a)
        with mock.patch.object(cbes, "BUILDER_VERSION", cbes.BUILDER_VERSION + 1):
            self.assertNotEqual(before, cbes.tree_hash(a))


class Decide(unittest.TestCase):
    NOW = 1_000_000.0

    def state(self, **kw):
        return {"presetId": PRESET, "itemId": "W", "hash": "h1", **kw}

    def decide(self, state, present=("W",), new="h1", force=False):
        return cbes.decide(state, PRESET, set(present), new, force, self.NOW)

    def test_unchanged_and_present_is_noop(self):
        self.assertEqual(self.decide(self.state()), "noop")

    def test_no_state_or_widget_gone_or_other_preset_adds_without_removal(self):
        self.assertEqual(self.decide({}), "add")
        self.assertEqual(self.decide(self.state(), present=()), "add")
        self.assertEqual(
            cbes.decide(self.state(), "OTHER", {"W"}, "h1", False, self.NOW), "add"
        )

    def test_changed_replaces_unless_asked_within_24h(self):
        self.assertEqual(self.decide(self.state(), new="h2"), "replace")
        recent = self.state(lastPromptAt=self.NOW - 3600)
        self.assertEqual(self.decide(recent, new="h2"), "defer")
        old = self.state(lastPromptAt=self.NOW - 25 * 3600)
        self.assertEqual(self.decide(old, new="h2"), "replace")

    def test_force_rebuilds_unchanged_and_ignores_the_24h_limit(self):
        recent = self.state(lastPromptAt=self.NOW - 60)
        self.assertEqual(self.decide(recent, force=True), "replace")
        self.assertEqual(self.decide(recent, new="h2", force=True), "replace")


class Runs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.chrome = d / "Chrome"
        (self.chrome / "Default").mkdir(parents=True)
        self.fake = d / "fake-mcp"
        self.fake.write_text(FAKE_MCP)
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)
        self.xb_state = d / "xb.json"
        self.state_file = d / "state" / "state.json"
        self.write_bookmarks(
            url("https://a.example", "TITLE-A"),
            folder("SECRETDIR", url("https://b.example", "TITLE-B")),
        )
        self.set_xb(items=[{"id": "OTHER-ITEM", "name": "x"}], active=PRESET)
        self.env = {
            "CHROME_USER_DATA_DIR": str(self.chrome),
            "CHROME_BOOKMARKS_EXTRABAR_MCP": str(self.fake),
            "CHROME_BOOKMARKS_EXTRABAR_STATE": str(self.state_file),
            "FAKE_XB_STATE": str(self.xb_state),
        }

    def write_bookmarks(self, *bar):
        (self.chrome / "Default" / "AccountBookmarks").write_text(
            json.dumps(bookmarks_doc(*bar))
        )

    def set_xb(self, **kw):
        cur = (
            json.loads(self.xb_state.read_text())
            if self.xb_state.exists()
            else {"log": []}
        )
        cur.update(kw)
        self.xb_state.write_text(json.dumps(cur))

    def xb(self) -> dict:
        return json.loads(self.xb_state.read_text())

    def calls(self, kind):
        return [c for c in self.xb()["log"] if c[0] == kind]

    def run_sync(self, *argv, approve_after=-1, now=None):
        out, err = io.StringIO(), io.StringIO()
        env = {**self.env, "FAKE_XB_APPROVE_AFTER": str(approve_after)}
        with (
            mock.patch.dict(os.environ, env),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            args = ["--wait-seconds", "0.3", "--poll-seconds", "0", *argv]
            if now is None:
                rc = cbes.main(args)
            else:
                with mock.patch.object(cbes.time, "time", return_value=now):
                    rc = cbes.main(args)
        self.last_out, self.last_err = out.getvalue(), err.getvalue()
        return rc

    def saved(self) -> dict:
        return json.loads(self.state_file.read_text())

    def test_first_run_adds_the_widget_first_without_any_removal(self):
        self.assertEqual(self.run_sync(), 0)
        self.assertTrue(self.last_out.startswith("UPDATED "))
        self.assertIn("2 links, 1 folders", self.last_out)
        self.assertEqual(self.calls("remove"), [])
        items = self.xb()["items"]
        self.assertEqual(items[0]["name"], "Chrome bookmarks")
        self.assertEqual(items[0]["id"], self.saved()["itemId"])
        self.assertEqual(
            self.saved()["hash"],
            cbes.tree_hash(
                cbes.build_items(
                    cbes.load_chrome_module().profile_bookmarks(
                        self.chrome / "Default"
                    )[0]["children"]
                )
            ),
        )

    def test_second_run_unchanged_does_nothing_and_prints_nothing(self):
        self.run_sync()
        before = self.xb()
        self.assertEqual(self.run_sync(), 0)
        self.assertEqual((self.last_out, self.last_err), ("", ""))
        self.assertEqual(self.xb(), before)

    def test_changed_tree_removes_the_old_widget_first_after_approval(self):
        self.run_sync()
        old = self.saved()["itemId"]
        self.write_bookmarks(
            url("https://a.example", "TITLE-A"), url("https://c.example", "TITLE-C")
        )
        self.assertEqual(self.run_sync(approve_after=2, now=T0 + 5000.0), 0)
        removes = self.calls("remove")
        self.assertEqual(len(removes), 2)
        self.assertEqual(removes[0], removes[1])  # the exact same call, retried
        self.assertEqual(removes[0][1]["itemId"], old)
        kinds = [c[0] for c in self.xb()["log"]]
        self.assertLess(
            kinds.index("remove"), kinds.index("add", kinds.index("remove"))
        )
        self.assertTrue(self.last_out.startswith("UPDATED "))
        items = self.xb()["items"]
        self.assertEqual(items[0]["id"], self.saved()["itemId"])
        self.assertNotEqual(self.saved()["itemId"], old)
        self.assertEqual([i["name"] for i in items].count("Chrome bookmarks"), 1)
        self.assertEqual(self.saved()["lastPromptAt"], T0 + 5000.0)

    def test_unapproved_removal_keeps_the_old_tree_and_asks_once_per_day(self):
        self.run_sync()
        old = self.saved()["itemId"]
        self.write_bookmarks(url("https://c.example", "TITLE-C"))
        self.assertEqual(self.run_sync(approve_after=-1, now=(T0 + 10_000.0)), 0)
        self.assertEqual(self.last_out, "")
        self.assertEqual(len(self.calls("remove")), 1)
        self.assertEqual(len(self.calls("add")), 1)  # only the first build
        self.assertEqual(self.saved()["itemId"], old)
        # an hour later: no new prompt at all
        self.run_sync(approve_after=-1, now=(T0 + 10_000.0) + 3600)
        self.assertEqual(len(self.calls("remove")), 1)
        self.assertIn("retrying later", self.last_err)
        # --force asks again at once
        self.run_sync("--force", approve_after=-1, now=(T0 + 10_000.0) + 3700)
        self.assertEqual(len(self.calls("remove")), 2)
        # after 24 h it asks again without --force, and this time it is approved
        self.assertEqual(
            self.run_sync(approve_after=1, now=(T0 + 10_000.0) + 100_000), 0
        )
        self.assertTrue(self.last_out.startswith("UPDATED "))
        self.assertNotEqual(self.saved()["itemId"], old)

    def test_widget_removed_by_hand_is_added_again_without_a_removal(self):
        self.run_sync()
        self.set_xb(items=[{"id": "OTHER-ITEM", "name": "x"}])
        self.assertEqual(self.run_sync(), 0)
        self.assertEqual(self.calls("remove"), [])
        self.assertEqual(len(self.calls("add")), 2)
        self.assertEqual(self.xb()["items"][0]["name"], "Chrome bookmarks")

    def test_app_not_running_is_silent_and_changes_nothing(self):
        self.set_xb(mode="app_not_running")
        self.assertEqual(self.run_sync(), 0)
        self.assertEqual((self.last_out, self.last_err), ("", ""))
        self.assertFalse(self.state_file.exists())

    def test_missing_helper_is_silent(self):
        self.env["CHROME_BOOKMARKS_EXTRABAR_MCP"] = str(self.fake) + ".missing"
        self.assertEqual(self.run_sync(), 0)
        self.assertEqual((self.last_out, self.last_err), ("", ""))

    def test_dry_run_prints_counts_and_hash_and_never_calls_extrabar(self):
        self.env["CHROME_BOOKMARKS_EXTRABAR_MCP"] = str(self.fake) + ".missing"
        self.assertEqual(self.run_sync("--dry-run"), 0)
        self.assertRegex(self.last_out, r"^2 links, 1 folders, hash [0-9a-f]{64}\n$")
        self.assertEqual(self.xb()["log"], [])
        self.assertFalse(self.state_file.exists())

    def test_output_never_carries_bookmark_titles_or_urls(self):
        self.run_sync("--dry-run")
        self.run_sync()
        self.write_bookmarks(url("https://c.example", "TITLE-C"))
        self.run_sync(approve_after=-1, now=T0 + 1.0)
        for text in (self.last_out, self.last_err):
            for secret in ("TITLE", "SECRETDIR", "example", "OTHERTITLE"):
                self.assertNotIn(secret, text)

    def test_other_roots_are_not_in_the_static_tree(self):
        self.run_sync()
        shown = json.dumps(self.calls("add")[0][1]["items"])
        self.assertNotIn("other.example", shown)

    def test_unreadable_chrome_folder_fails_with_exit_1(self):
        real = Path.read_text

        def deny(self, *a, **k):
            if self.name == "AccountBookmarks":
                raise PermissionError(1, "Operation not permitted")
            return real(self, *a, **k)

        with mock.patch.object(Path, "read_text", deny):
            self.assertEqual(self.run_sync("--no-extrabar-fallback"), 1)
        self.assertIn("PermissionError", self.last_err)
        self.assertEqual(self.last_out, "")

    def deny_chrome(self):
        real = Path.read_text

        def deny(self, *a, **k):
            if self.name == "AccountBookmarks":
                raise PermissionError(1, "Operation not permitted")
            return real(self, *a, **k)

        return mock.patch.object(Path, "read_text", deny)

    def test_permission_error_runs_the_sync_through_a_hidden_extrabar_action(self):
        self.env["FAKE_XB_RUN_STDOUT"] = (
            "UPDATED ExtraBar Chrome bookmarks tree (2 links, 1 folders)\n"
        )
        with self.deny_chrome():
            self.assertEqual(self.run_sync(), 0)
        self.assertEqual(self.last_out, self.env["FAKE_XB_RUN_STDOUT"])
        adds = self.calls("add_action")
        self.assertEqual(len(adds), 1)
        action = adds[0][1]["action"]
        self.assertEqual(action["type"], "run_script")
        self.assertIn("chrome-bookmarks-extrabar-sync", action["content"])
        self.assertIn("--no-extrabar-fallback", action["content"])
        self.assertEqual(action["showOutputWindow"], False)
        self.assertEqual(self.calls("update")[0][1]["isVisible"], False)
        run = self.calls("run")[0][1]
        self.assertEqual(run["itemId"], self.saved()["runner"]["itemId"])
        self.assertEqual(
            self.calls("add"), []
        )  # the bookmarks widget is the inner run's job
        # the second run reuses the action
        with self.deny_chrome():
            self.assertEqual(self.run_sync(), 0)
        self.assertEqual(len(self.calls("add_action")), 1)
        self.assertEqual(len(self.calls("run")), 2)

    def test_run_under_extrabar_relays_a_failure_exit_status(self):
        self.env["FAKE_XB_RUN_EXIT"] = "1"
        with self.deny_chrome():
            self.assertEqual(self.run_sync(), 1)

    def test_no_fallback_flag_fails_instead(self):
        with self.deny_chrome():
            self.assertEqual(self.run_sync("--no-extrabar-fallback"), 1)
        self.assertEqual(self.xb()["log"], [])
        self.assertIn("PermissionError", self.last_err)

    def test_fallback_is_silent_when_extrabar_is_not_running(self):
        self.set_xb(mode="app_not_running")
        with self.deny_chrome():
            self.assertEqual(self.run_sync(), 0)
        self.assertEqual((self.last_out, self.last_err), ("", ""))

    def test_empty_bookmarks_bar_leaves_extrabar_alone(self):
        self.write_bookmarks()
        self.assertEqual(self.run_sync(), 0)
        self.assertEqual(self.xb()["log"], [])


if __name__ == "__main__":
    unittest.main()
