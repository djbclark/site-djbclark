#!/usr/bin/env python3
"""Tests for the Copilot CLI adapter.

Beyond the shared tail semantics: only `<session-state>/<uuid>/events.jsonl`
is ever opened (workspace.yaml, checkpoints/, the summary db stay out), and
the session id comes from `session.start` with the directory uuid as fallback.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import s1_evidence as s1  # noqa: E402
import s1_copilot as adapter  # noqa: E402

SESSION_ID = "0198a9ed-b61c-4a95-948e-e9ab4d469a42"


def record(rtype: str, data: dict | None = None, n: int = 0, **kw) -> str:
    body = {
        "id": f"ev-{n}",
        "parentId": None,
        "timestamp": f"2026-10-03T18:32:{48 + n:02d}.000Z",
        "type": rtype,
        "data": data or {},
    }
    body.update(kw)
    return json.dumps(body)


SESSION_START = record("session.start", {
    "sessionId": SESSION_ID,
    "producer": "copilot-agent",
    "copilotVersion": "0.0.0",
    "context": {"cwd": "/tmp"},
})


class AdapterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = s1.EvidenceStore(self.root / "db.sqlite3", self.root / "cas")
        self.state = self.root / "session-state"
        session_dir = self.state / SESSION_ID
        session_dir.mkdir(parents=True)
        self.events = session_dir / "events.jsonl"

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def write(self, *lines: str, mode: str = "w") -> None:
        with self.events.open(mode) as handle:
            for line in lines:
                handle.write(line + "\n")

    def ingest(self, **kw):
        return adapter.ingest_file(self.store, self.events, batch="test", **kw)


class TestBasicIngest(AdapterTestCase):
    def test_ingests_every_record_once(self) -> None:
        self.write(SESSION_START, record("user.message", n=1),
                   record("assistant.message", {"model": "test-model"}, n=2))
        result = self.ingest()
        self.assertEqual((result["read"], result["created"]), (3, 3))
        self.assertEqual(self.store.stats()["events"], 3)

    def test_rerunning_creates_nothing_new(self) -> None:
        self.write(SESSION_START, record("user.message", n=1))
        self.ingest()
        second = self.ingest()
        self.assertEqual(second["created"], 0)
        self.assertEqual(self.store.stats()["events"], 2)

    def test_resumes_after_append(self) -> None:
        self.write(SESSION_START)
        self.ingest()
        self.write(record("user.message", n=1), mode="a")
        second = self.ingest()
        self.assertEqual(second["read"], 1)
        self.assertEqual(self.store.stats()["events"], 2)

    def test_incomplete_final_line_is_not_ingested_until_terminated(self) -> None:
        with self.events.open("w") as handle:
            handle.write(SESSION_START + "\n")
            handle.write('{"id":"ev-9","type":"user.message"')  # no newline yet
        first = self.ingest()
        self.assertEqual(first["created"], 1)
        with self.events.open("a") as handle:
            handle.write(',"data":{}}\n')
        second = self.ingest()
        self.assertEqual(second["created"], 1)
        self.assertEqual(self.store.stats()["events"], 2)

    def test_truncation_is_recorded_as_a_gap(self) -> None:
        self.write(SESSION_START, record("user.message", n=1))
        self.ingest()
        self.write(record("session.shutdown"))  # rewritten from scratch
        self.ingest()
        self.assertGreaterEqual(self.store.stats()["gaps"], 1)

    def test_dry_run_writes_nothing(self) -> None:
        self.write(SESSION_START)
        result = self.ingest(dry_run=True)
        self.assertEqual(result["read"], 1)
        self.assertEqual(self.store.stats()["events"], 0)


class TestAllowList(AdapterTestCase):
    def test_siblings_are_never_listed(self) -> None:
        self.write(SESSION_START)
        (self.events.parent / "workspace.yaml").write_text("cwd: /tmp")
        (self.events.parent / "checkpoints").mkdir()
        (self.events.parent / "checkpoints" / "events.jsonl").write_text("{}\n")
        (self.state / "session-store.db").write_bytes(b"SQLite format 3\x00")
        paths = adapter.events_paths(self.state)
        self.assertEqual(paths, [self.events.resolve()])

    def test_symlink_escaping_the_tree_is_refused(self) -> None:
        outside = self.root / "elsewhere" / "events.jsonl"
        outside.parent.mkdir()
        outside.write_text(SESSION_START + "\n")
        planted = self.state / "deadbeef-dead" / "events.jsonl"
        planted.parent.mkdir()
        planted.symlink_to(outside)
        self.assertFalse(adapter.is_allowed(planted, self.state))
        self.assertEqual(adapter.events_paths(self.state), [])

    def test_path_option_refuses_non_allowlisted_file(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            adapter.main(["scan", "--session-state", str(self.state),
                          "--path", str(self.state / "session-store.db"),
                          "--db", str(self.root / "x.sqlite3"),
                          "--cas", str(self.root / "x-cas")])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_source_tree_scans_zero_files(self) -> None:
        rc = adapter.main(["--db", str(self.root / "n.sqlite3"),
                           "--cas", str(self.root / "n-cas"),
                           "--session-state", str(self.root / "no-such-tree"),
                           "scan", "--quiet"])
        self.assertEqual(rc, 0)

    def test_scan_end_to_end_through_main(self) -> None:
        self.write(SESSION_START, record("user.message", n=1))
        rc = adapter.main(["--db", str(self.root / "m.sqlite3"),
                           "--cas", str(self.root / "m-cas"),
                           "--session-state", str(self.state),
                           "scan", "--quiet"])
        self.assertEqual(rc, 0)
        store = s1.EvidenceStore(self.root / "m.sqlite3", self.root / "m-cas")
        self.assertEqual(store.stats()["events"], 2)
        store.close()


class TestMetadata(AdapterTestCase):
    def test_session_id_from_record_groups_conversation(self) -> None:
        self.write(SESSION_START, record("user.message", n=1))
        self.ingest()
        rows = list(self.store.conversation(f"copilot:{SESSION_ID}"))
        self.assertEqual(len(rows), 2)

    def test_session_id_falls_back_to_directory_name(self) -> None:
        # No session.start: the directory uuid is the source-layout fallback.
        self.write(record("user.message", n=1))
        self.ingest()
        row = self.store.db.execute(
            "SELECT producer_session_id FROM event").fetchone()
        self.assertEqual(row["producer_session_id"], SESSION_ID)

    def test_role_and_tool_mapping(self) -> None:
        self.write(
            SESSION_START,
            record("user.message", n=1),
            record("tool.execution_start",
                   {"toolName": "bash", "toolCallId": "tc-7"}, n=2),
            record("assistant.message", {"model": "m"}, n=3),
        )
        self.ingest()
        rows = list(self.store.db.execute(
            "SELECT role, origin, event_type, tool_name, tool_call_id FROM event"
            " ORDER BY ingest_lsn"))
        self.assertEqual((rows[1]["role"], rows[1]["origin"]), ("user", "human"))
        self.assertEqual((rows[2]["role"], rows[2]["origin"]), ("tool", "tool"))
        self.assertEqual(rows[2]["tool_name"], "bash")
        self.assertEqual(rows[2]["tool_call_id"], "tc-7")
        self.assertEqual((rows[3]["role"], rows[3]["origin"]), ("assistant", "model"))

    def test_unknown_types_are_retained_as_system(self) -> None:
        self.write(SESSION_START, record("some.future.type", n=1))
        self.ingest()
        row = self.store.db.execute(
            "SELECT role, event_type FROM event ORDER BY ingest_lsn DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(row["role"], "system")
        self.assertEqual(row["event_type"], "some.future.type")

    def test_missing_timestamp_falls_back_to_filesystem(self) -> None:
        line = json.dumps({"id": "ev-x", "type": "user.message", "data": {}})
        self.write(SESSION_START, line)
        self.ingest()
        row = self.store.db.execute(
            "SELECT ts_source FROM event ORDER BY ingest_lsn DESC LIMIT 1").fetchone()
        self.assertEqual(row["ts_source"], "filesystem")


if __name__ == "__main__":
    unittest.main()
