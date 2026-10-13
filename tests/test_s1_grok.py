#!/usr/bin/env python3
"""Tests for the grok updates.jsonl adapter.

Beyond the shared tail semantics: only `<sessions>/<cwd>/<uuid>/updates.jsonl`
is ever opened (auth.json, chat_history.jsonl, system_prompt.txt, the .lock
siblings all stay out), and the session id comes from `params.sessionId` with
the directory uuid as fallback.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import s1_evidence as s1  # noqa: E402
import s1_grok as adapter  # noqa: E402

SESSION_ID = "01a029e7-8756-76b1-9be1-b59674ae6d09"


def update(subtype: str, n: int = 0, **fields) -> str:
    body = {"sessionUpdate": subtype}
    body.update(fields)
    return json.dumps({
        "method": "_x.ai/session/update",
        "timestamp": 1789979008 + n,
        "params": {"sessionId": SESSION_ID, "update": body,
                   "_meta": {"eventId": f"{SESSION_ID}-{n}"}},
    })


class AdapterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = s1.EvidenceStore(self.root / "db.sqlite3", self.root / "cas")
        self.sessions = self.root / "sessions"
        session_dir = self.sessions / "%2FUsers%2Ftest" / SESSION_ID
        session_dir.mkdir(parents=True)
        self.updates = session_dir / "updates.jsonl"

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def write(self, *lines: str, mode: str = "w") -> None:
        with self.updates.open(mode) as handle:
            for line in lines:
                handle.write(line + "\n")

    def ingest(self, **kw):
        return adapter.ingest_file(self.store, self.updates, batch="test", **kw)


class TestBasicIngest(AdapterTestCase):
    def test_ingests_every_record_once(self) -> None:
        self.write(update("user_message_chunk"), update("agent_message_chunk", n=1))
        result = self.ingest()
        self.assertEqual((result["read"], result["created"]), (2, 2))
        self.assertEqual(self.store.stats()["events"], 2)

    def test_rerunning_creates_nothing_new(self) -> None:
        self.write(update("user_message_chunk"))
        self.ingest()
        second = self.ingest()
        self.assertEqual(second["created"], 0)
        self.assertEqual(self.store.stats()["events"], 1)

    def test_resumes_after_append(self) -> None:
        self.write(update("user_message_chunk"))
        self.ingest()
        self.write(update("agent_message_chunk", n=1), mode="a")
        second = self.ingest()
        self.assertEqual(second["read"], 1)
        self.assertEqual(self.store.stats()["events"], 2)

    def test_incomplete_final_line_is_not_ingested_until_terminated(self) -> None:
        with self.updates.open("w") as handle:
            handle.write(update("user_message_chunk") + "\n")
            handle.write('{"method":"_x.ai/session/update","timestamp":1789979009')
        first = self.ingest()
        self.assertEqual(first["created"], 1)
        with self.updates.open("a") as handle:
            handle.write(',"params":{"sessionId":"%s","update":{"sessionUpdate":"agent_message_chunk"}}}\n' % SESSION_ID)
        second = self.ingest()
        self.assertEqual(second["created"], 1)
        self.assertEqual(self.store.stats()["events"], 2)

    def test_truncation_is_recorded_as_a_gap(self) -> None:
        self.write(update("user_message_chunk"), update("agent_message_chunk", n=1))
        self.ingest()
        self.write(update("task_completed", n=9))  # rewritten from scratch
        self.ingest()
        self.assertGreaterEqual(self.store.stats()["gaps"], 1)

    def test_dry_run_writes_nothing(self) -> None:
        self.write(update("user_message_chunk"))
        result = self.ingest(dry_run=True)
        self.assertEqual(result["read"], 1)
        self.assertEqual(self.store.stats()["events"], 0)


class TestAllowList(AdapterTestCase):
    def test_siblings_are_never_listed(self) -> None:
        self.write(update("user_message_chunk"))
        d = self.updates.parent
        (d / "chat_history.jsonl").write_text("{}\n")
        (d / "updates.jsonl.lock").write_text("")
        (d / "system_prompt.txt").write_text("you are grok")
        (d / "summary.json").write_text("{}")
        (self.sessions / "auth.json").write_text('{"token":"x"}')
        (self.sessions / "%2FUsers%2Ftest" / "auth.json").write_text('{"token":"x"}')
        paths = adapter.updates_paths(self.sessions)
        self.assertEqual(paths, [self.updates.resolve()])

    def test_wrong_depth_is_refused(self) -> None:
        shallow = self.sessions / "%2FUsers%2Ftest" / "updates.jsonl"
        shallow.write_text(update("user_message_chunk") + "\n")
        deep = self.updates.parent / "nested" / "updates.jsonl"
        deep.parent.mkdir()
        deep.write_text(update("user_message_chunk") + "\n")
        self.assertFalse(adapter.is_allowed(shallow, self.sessions))
        self.assertFalse(adapter.is_allowed(deep, self.sessions))

    def test_symlink_escaping_the_tree_is_refused(self) -> None:
        outside_dir = self.root / "elsewhere" / "sub"
        outside_dir.mkdir(parents=True)
        outside = outside_dir / "updates.jsonl"
        outside.write_text(update("user_message_chunk") + "\n")
        planted = self.sessions / "%2Fevil" / "deadbeef" / "updates.jsonl"
        planted.parent.mkdir(parents=True)
        planted.symlink_to(outside)
        self.assertFalse(adapter.is_allowed(planted, self.sessions))
        self.assertEqual(adapter.updates_paths(self.sessions), [])

    def test_path_option_refuses_non_allowlisted_file(self) -> None:
        auth = self.sessions / "%2FUsers%2Ftest" / "auth.json"
        auth.write_text('{"token":"x"}')
        with self.assertRaises(SystemExit) as ctx:
            adapter.main(["scan", "--sessions", str(self.sessions),
                          "--path", str(auth),
                          "--db", str(self.root / "x.sqlite3"),
                          "--cas", str(self.root / "x-cas")])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_source_tree_scans_zero_files(self) -> None:
        rc = adapter.main(["--db", str(self.root / "n.sqlite3"),
                           "--cas", str(self.root / "n-cas"),
                           "--sessions", str(self.root / "no-such-tree"),
                           "scan", "--quiet"])
        self.assertEqual(rc, 0)

    def test_scan_end_to_end_through_main(self) -> None:
        self.write(update("user_message_chunk"), update("tool_call", n=1, title="Bash",
                                                        toolCallId="tc-1"))
        rc = adapter.main(["--db", str(self.root / "m.sqlite3"),
                           "--cas", str(self.root / "m-cas"),
                           "--sessions", str(self.sessions),
                           "scan", "--quiet"])
        self.assertEqual(rc, 0)
        store = s1.EvidenceStore(self.root / "m.sqlite3", self.root / "m-cas")
        self.assertEqual(store.stats()["events"], 2)
        store.close()


class TestMetadata(AdapterTestCase):
    def test_conversation_grouped_by_session(self) -> None:
        self.write(update("user_message_chunk"), update("agent_message_chunk", n=1))
        self.ingest()
        self.assertEqual(
            len(list(self.store.conversation(f"grok:{SESSION_ID}"))), 2)

    def test_session_id_falls_back_to_directory_name(self) -> None:
        line = json.dumps({"method": "_x.ai/session/update", "timestamp": 1789979008,
                           "params": {"update": {"sessionUpdate": "background_tasks"}}})
        self.write(line)
        self.ingest()
        row = self.store.db.execute(
            "SELECT producer_session_id FROM event").fetchone()
        self.assertEqual(row["producer_session_id"], SESSION_ID)

    def test_role_and_tool_mapping(self) -> None:
        self.write(
            update("user_message_chunk"),
            update("tool_call", n=1, title="Bash", toolCallId="tc-9"),
            update("agent_thought_chunk", n=2),
            update("hook_execution", n=3, event_name="pre"),
        )
        self.ingest()
        rows = list(self.store.db.execute(
            "SELECT role, origin, event_type, tool_name, tool_call_id FROM event"
            " ORDER BY ingest_lsn"))
        self.assertEqual((rows[0]["role"], rows[0]["origin"]), ("user", "human"))
        self.assertEqual((rows[1]["role"], rows[1]["origin"]), ("tool", "tool"))
        self.assertEqual(rows[1]["tool_name"], "Bash")
        self.assertEqual(rows[1]["tool_call_id"], "tc-9")
        self.assertEqual((rows[2]["role"], rows[2]["origin"]), ("assistant", "model"))
        self.assertEqual((rows[3]["role"], rows[3]["origin"]), ("system", "system"))
        self.assertEqual(rows[3]["event_type"], "_x.ai/session/update.hook_execution")

    def test_epoch_timestamp_is_producer_time(self) -> None:
        self.write(update("user_message_chunk"))
        self.ingest()
        row = self.store.db.execute(
            "SELECT ts_utc, ts_source FROM event").fetchone()
        self.assertEqual(row["ts_source"], "producer")
        self.assertTrue(row["ts_utc"].endswith("Z"))


if __name__ == "__main__":
    unittest.main()
