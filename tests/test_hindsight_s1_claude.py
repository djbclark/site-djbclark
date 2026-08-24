#!/usr/bin/env python3
"""Tests for the Claude Code transcript adapter.

The risky behaviors here are the tail semantics: resuming at the right byte,
refusing to ingest a half-written record, and noticing when a file stops being
the file we were tailing.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import hindsight_s1 as s1  # noqa: E402
import hindsight_s1_claude as adapter  # noqa: E402


def record(**kw) -> str:
    base = {
        "type": "user",
        "sessionId": "sess-1",
        "timestamp": "2026-08-23T20:00:00Z",
        "uuid": "u1",
        "cwd": "/tmp",
        "version": "2.0.0",
    }
    base.update(kw)
    return json.dumps(base)


class AdapterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = s1.EvidenceStore(self.root / "db.sqlite3", self.root / "cas")
        self.transcript = self.root / "sess-1.jsonl"

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def write(self, *lines: str, mode: str = "w") -> None:
        with self.transcript.open(mode) as handle:
            for line in lines:
                handle.write(line + "\n")

    def ingest(self, **kw):
        return adapter.ingest_file(self.store, self.transcript, batch="test", **kw)


class TestBasicIngest(AdapterTestCase):
    def test_ingests_every_record_once(self) -> None:
        self.write(record(uuid="a"), record(uuid="b", type="assistant"))
        result = self.ingest()
        self.assertEqual(result["read"], 2)
        self.assertEqual(result["created"], 2)
        self.assertEqual(self.store.stats()["events"], 2)

    def test_rerunning_creates_nothing_new(self) -> None:
        self.write(record(uuid="a"), record(uuid="b"))
        self.ingest()
        second = self.ingest()
        self.assertEqual(second["created"], 0)
        self.assertEqual(self.store.stats()["events"], 2)

    def test_raw_bytes_are_the_exact_source_line(self) -> None:
        line = record(uuid="exact")
        self.write(line)
        self.ingest()
        stored = list(self.store.db.execute("SELECT event_id FROM event"))
        raw = self.store.raw_for(stored[0]["event_id"])
        self.assertEqual(raw, (line + "\n").encode())

    def test_unknown_record_types_are_still_retained(self) -> None:
        self.write(record(type="some-future-type", uuid="x"))
        self.ingest()
        row = self.store.db.execute("SELECT role, origin, event_type FROM event").fetchone()
        self.assertEqual(row["event_type"], "some-future-type")
        self.assertEqual(row["role"], "unknown")

    def test_malformed_json_is_retained_not_dropped(self) -> None:
        with self.transcript.open("w") as handle:
            handle.write("{not valid json\n")
        result = self.ingest()
        self.assertEqual(result["created"], 1)


class TestTailSemantics(AdapterTestCase):
    def test_resumes_from_checkpoint_and_ingests_only_new_records(self) -> None:
        self.write(record(uuid="a"))
        self.ingest()
        self.write(record(uuid="b"), mode="a")
        second = self.ingest()
        self.assertEqual(second["read"], 1, "should only read the appended record")
        self.assertEqual(second["created"], 1)
        self.assertEqual(self.store.stats()["events"], 2)

    def test_incomplete_final_line_is_not_ingested_until_terminated(self) -> None:
        with self.transcript.open("w") as handle:
            handle.write(record(uuid="complete") + "\n")
            handle.write('{"type":"user","uuid":"partial"')  # no newline yet
        first = self.ingest()
        self.assertEqual(first["created"], 1, "partial record must be skipped")

        with self.transcript.open("a") as handle:
            handle.write(',"sessionId":"sess-1"}\n')  # completes the record
        second = self.ingest()
        self.assertEqual(second["created"], 1, "record ingested once complete")
        self.assertEqual(self.store.stats()["events"], 2)

    def test_truncation_is_recorded_as_a_gap(self) -> None:
        self.write(record(uuid="a"), record(uuid="b"))
        self.ingest()
        # rewritten from scratch with different opening bytes
        self.write(record(uuid="totally-different-opening-record"))
        self.ingest()
        self.assertGreaterEqual(self.store.stats()["gaps"], 1)

    def test_checkpoint_advances(self) -> None:
        self.write(record(uuid="a"))
        self.ingest()
        uri = self.transcript.resolve().as_uri()
        first = self.store.checkpoint(adapter.PRODUCER, uri)["committed_locator"]
        self.write(record(uuid="b"), mode="a")
        self.ingest()
        second = self.store.checkpoint(adapter.PRODUCER, uri)["committed_locator"]
        self.assertNotEqual(first, second)
        self.assertGreater(adapter.parse_locator(second), adapter.parse_locator(first))

    def test_dry_run_writes_nothing(self) -> None:
        self.write(record(uuid="a"))
        result = self.ingest(dry_run=True)
        self.assertEqual(result["read"], 1)
        self.assertEqual(self.store.stats()["events"], 0)
        self.assertIsNone(self.store.checkpoint(
            adapter.PRODUCER, self.transcript.resolve().as_uri()))


class TestMetadata(AdapterTestCase):
    def test_conversation_grouping_by_session(self) -> None:
        self.write(record(uuid="a", sessionId="s9"), record(uuid="b", sessionId="s9"))
        self.ingest()
        rows = list(self.store.conversation("claude-code:s9"))
        self.assertEqual(len(rows), 2)

    def test_scope_records_repo_attribution_at_ingest(self) -> None:
        # cwd inside this checkout resolves to the git toplevel's name
        repo = str(Path(__file__).resolve().parent)
        self.write(record(uuid="a", cwd=repo))
        self.ingest()
        scope = self.store.db.execute("SELECT scope FROM event").fetchone()["scope"]
        self.assertNotEqual(scope, "unknown")

    def test_missing_timestamp_falls_back_to_filesystem(self) -> None:
        self.write(json.dumps({"type": "user", "sessionId": "s1", "uuid": "n"}))
        self.ingest()
        row = self.store.db.execute("SELECT ts_source FROM event").fetchone()
        self.assertEqual(row["ts_source"], "filesystem")

    def test_tool_fields_extracted(self) -> None:
        self.write(record(
            type="assistant", uuid="t",
            message={"content": [{"type": "tool_use", "name": "Bash", "id": "call-7"}]},
        ))
        self.ingest()
        row = self.store.db.execute("SELECT tool_name, tool_call_id FROM event").fetchone()
        self.assertEqual(row["tool_name"], "Bash")
        self.assertEqual(row["tool_call_id"], "call-7")

    def test_locator_parsing_round_trip(self) -> None:
        self.assertEqual(adapter.parse_locator("100:250#3"), 250)
        self.assertEqual(adapter.parse_locator(None), 0)
        self.assertEqual(adapter.parse_locator("garbage"), 0)


if __name__ == "__main__":
    unittest.main()
