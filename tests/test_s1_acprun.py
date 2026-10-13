#!/usr/bin/env python3
"""Tests for the acp-run capture adapter.

Beyond the shared tail semantics, the properties that matter here: agent and
model identity come from the records (never the file name), and only `*.jsonl`
directly under the log dir is ever opened — the `.stderr` siblings stay out.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import s1_evidence as s1  # noqa: E402
import s1_acprun as adapter  # noqa: E402


def record(kind: str, data: dict | None = None, t: float = 1791052338.0) -> str:
    return json.dumps({"t": t, "kind": kind, "data": data or {}})


INITIALIZE = record("initialize", {
    "protocolVersion": 1,
    "agentInfo": {"name": "OpenCode", "version": "2.0.22"},
    "agentCapabilities": {},
})
NEW_SESSION = record("new_session", {
    "sessionId": "sess-abc",
    "configOptions": [
        {"id": "model", "category": "model", "currentValue": "opencode/test-model",
         "options": []},
        {"id": "mode", "currentValue": "build", "options": []},
    ],
})


class AdapterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = s1.EvidenceStore(self.root / "db.sqlite3", self.root / "cas")
        self.log_dir = self.root / "acp-run"
        self.log_dir.mkdir()
        # The file name deliberately names the WRONG agent: identity must come
        # from the records, not the name.
        self.log = self.log_dir / "20261003-143217-wrongagent-14336.jsonl"

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def write(self, *lines: str, mode: str = "w") -> None:
        with self.log.open(mode) as handle:
            for line in lines:
                handle.write(line + "\n")

    def ingest(self, **kw):
        return adapter.ingest_file(self.store, self.log, batch="test", **kw)


class TestBasicIngest(AdapterTestCase):
    def test_ingests_every_record_once(self) -> None:
        self.write(INITIALIZE, NEW_SESSION,
                   record("update", {"sessionUpdate": "user_message_chunk",
                                     "content": {"type": "text", "text": "hi"}}))
        result = self.ingest()
        self.assertEqual((result["read"], result["created"]), (3, 3))
        self.assertEqual(self.store.stats()["events"], 3)

    def test_rerunning_creates_nothing_new(self) -> None:
        self.write(INITIALIZE, NEW_SESSION)
        self.ingest()
        second = self.ingest()
        self.assertEqual(second["created"], 0)
        self.assertEqual(self.store.stats()["events"], 2)

    def test_resumes_after_append(self) -> None:
        self.write(INITIALIZE)
        self.ingest()
        self.write(NEW_SESSION, mode="a")
        second = self.ingest()
        self.assertEqual(second["read"], 1)
        self.assertEqual(self.store.stats()["events"], 2)

    def test_incomplete_final_line_is_not_ingested_until_terminated(self) -> None:
        with self.log.open("w") as handle:
            handle.write(INITIALIZE + "\n")
            handle.write('{"t":1791052339.0,"kind":"new_session"')  # no newline yet
        first = self.ingest()
        self.assertEqual(first["created"], 1)
        with self.log.open("a") as handle:
            handle.write(',"data":{"sessionId":"sess-abc"}}\n')
        second = self.ingest()
        self.assertEqual(second["created"], 1)
        self.assertEqual(self.store.stats()["events"], 2)

    def test_truncation_is_recorded_as_a_gap(self) -> None:
        self.write(INITIALIZE, NEW_SESSION)
        self.ingest()
        self.write(record("result", {"exit": 0}))  # rewritten from scratch
        self.ingest()
        self.assertGreaterEqual(self.store.stats()["gaps"], 1)

    def test_dry_run_writes_nothing(self) -> None:
        self.write(INITIALIZE)
        result = self.ingest(dry_run=True)
        self.assertEqual(result["read"], 1)
        self.assertEqual(self.store.stats()["events"], 0)


class TestContentIdentity(AdapterTestCase):
    def test_agent_and_model_come_from_records_not_filename(self) -> None:
        self.write(INITIALIZE, NEW_SESSION,
                   record("update", {"sessionUpdate": "agent_message_chunk",
                                     "content": {"type": "text", "text": "ok"}}))
        self.ingest()
        rows = list(self.store.db.execute(
            "SELECT scope, producer_version FROM event ORDER BY ingest_lsn"))
        self.assertEqual(rows[0]["producer_version"], "2.0.22")
        # File name says "wrongagent"; records say OpenCode + its model.
        self.assertEqual(rows[0]["scope"], "opencode")
        self.assertEqual(rows[2]["scope"], "opencode/opencode/test-model")

    def test_session_id_groups_conversation(self) -> None:
        self.write(INITIALIZE, NEW_SESSION,
                   record("update", {"sessionUpdate": "user_message_chunk"}))
        self.ingest()
        # initialize precedes the new_session announcement, so it is ingested
        # before the session id exists; everything from new_session on groups.
        self.assertEqual(
            len(list(self.store.conversation("acp-run:sess-abc"))), 2)

    def test_epoch_timestamp_is_producer_time(self) -> None:
        self.write(INITIALIZE)
        self.ingest()
        row = self.store.db.execute(
            "SELECT ts_utc, ts_source FROM event").fetchone()
        self.assertEqual(row["ts_source"], "producer")
        self.assertTrue(row["ts_utc"].endswith("Z"))

    def test_role_and_tool_mapping(self) -> None:
        self.write(
            INITIALIZE,
            record("update", {"sessionUpdate": "user_message_chunk"}),
            record("update", {"sessionUpdate": "tool_call", "title": "Bash",
                              "toolCallId": "call-3"}),
            record("prompt_response", {"stopReason": "end_turn"}),
        )
        self.ingest()
        rows = list(self.store.db.execute(
            "SELECT role, origin, event_type, tool_name, tool_call_id FROM event"
            " ORDER BY ingest_lsn"))
        self.assertEqual((rows[1]["role"], rows[1]["origin"]), ("user", "human"))
        self.assertEqual((rows[2]["role"], rows[2]["origin"]), ("tool", "tool"))
        self.assertEqual(rows[2]["tool_name"], "Bash")
        self.assertEqual(rows[2]["tool_call_id"], "call-3")
        self.assertEqual((rows[3]["role"], rows[3]["event_type"]),
                         ("assistant", "prompt_response"))

    def test_handshake_failure_records_are_retained(self) -> None:
        self.write(record("handshake_timeout", {"attempt": 1, "secs": 5}))
        result = self.ingest()
        self.assertEqual(result["created"], 1)
        row = self.store.db.execute("SELECT scope, role FROM event").fetchone()
        self.assertEqual(row["scope"], "acp-run")  # no initialize: safe default
        self.assertEqual(row["role"], "system")


class TestAllowList(AdapterTestCase):
    def test_stderr_and_non_jsonl_siblings_are_never_listed(self) -> None:
        self.write(INITIALIZE)
        (self.log_dir / "20261003-143217-wrongagent-14336.stderr").write_text("err")
        (self.log_dir / "notes.txt").write_text("hello")
        (self.log_dir / "subdir").mkdir()
        (self.log_dir / "subdir" / "nested.jsonl").write_text(INITIALIZE + "\n")
        paths = adapter.log_paths(self.log_dir)
        self.assertEqual(paths, [self.log.resolve()])

    def test_path_option_refuses_non_allowlisted_file(self) -> None:
        stderr = self.log_dir / "x.stderr"
        stderr.write_text("secret-ish")
        with self.assertRaises(SystemExit) as ctx:
            adapter.main(["scan", "--log-dir", str(self.log_dir),
                          "--path", str(stderr),
                          "--db", str(self.root / "x.sqlite3"),
                          "--cas", str(self.root / "x-cas")])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_log_dir_scans_zero_files(self) -> None:
        rc = adapter.main(["--db", str(self.root / "n.sqlite3"),
                           "--cas", str(self.root / "n-cas"),
                           "--log-dir", str(self.root / "no-such-dir"),
                           "scan", "--quiet"])
        self.assertEqual(rc, 0)

    def test_scan_end_to_end_through_main(self) -> None:
        self.write(INITIALIZE, NEW_SESSION)
        rc = adapter.main(["--db", str(self.root / "m.sqlite3"),
                           "--cas", str(self.root / "m-cas"),
                           "--log-dir", str(self.log_dir),
                           "scan", "--quiet"])
        self.assertEqual(rc, 0)
        store = s1.EvidenceStore(self.root / "m.sqlite3", self.root / "m-cas")
        self.assertEqual(store.stats()["events"], 2)
        store.close()


if __name__ == "__main__":
    unittest.main()
