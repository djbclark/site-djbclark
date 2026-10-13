#!/usr/bin/env python3
"""Tests for the Codex rollout adapter.

The risky behaviors here, beyond the shared tail semantics: event identity
must come from the `session_meta` id inside the file (a rollout that moves
between month directories must resume, not restart), and the path allow-list
must keep every non-rollout sibling — auth files, indexes, planted symlinks —
unopened.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import s1_evidence as s1  # noqa: E402
import s1_codex as adapter  # noqa: E402

SESSION_ID = "01a0fec1-638a-71e3-aa2a-fad65b0a2d3d"


def meta_line(**kw) -> str:
    payload = {
        "id": SESSION_ID,
        "timestamp": "2026-10-02T18:34:42.000Z",
        "cwd": "/tmp",
        "cli_version": "0.160.0",
        "originator": "codex_exec",
    }
    payload.update(kw)
    return json.dumps({"timestamp": payload["timestamp"], "type": "session_meta",
                       "payload": payload})


def record(ordinal: int, ptype: str = "message", **payload) -> str:
    body = {"type": ptype}
    body.update(payload)
    return json.dumps({
        "timestamp": f"2026-10-02T18:35:{ordinal:02d}.000Z",
        "type": "response_item", "ordinal": ordinal, "payload": body,
    })


class AdapterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = s1.EvidenceStore(self.root / "db.sqlite3", self.root / "cas")
        self.sessions = self.root / "sessions"
        day = self.sessions / "2026" / "10" / "02"
        day.mkdir(parents=True)
        self.rollout = day / f"rollout-2026-10-02T18-34-42-{SESSION_ID}.jsonl"

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def write(self, *lines: str, mode: str = "w") -> None:
        with self.rollout.open(mode) as handle:
            for line in lines:
                handle.write(line + "\n")

    def ingest(self, **kw):
        return adapter.ingest_file(self.store, self.rollout, batch="test", **kw)


class TestBasicIngest(AdapterTestCase):
    def test_ingests_every_record_once(self) -> None:
        self.write(meta_line(), record(1, role="user"), record(2, role="assistant"))
        result = self.ingest()
        self.assertEqual((result["read"], result["created"]), (3, 3))
        self.assertEqual(self.store.stats()["events"], 3)

    def test_rerunning_creates_nothing_new(self) -> None:
        self.write(meta_line(), record(1, role="user"))
        self.ingest()
        second = self.ingest()
        self.assertEqual(second["created"], 0)
        self.assertEqual(self.store.stats()["events"], 2)

    def test_raw_bytes_are_the_exact_source_line(self) -> None:
        line = record(1, role="user", content=[{"type": "input_text", "text": "hi"}])
        self.write(meta_line(), line)
        self.ingest()
        rows = list(self.store.db.execute(
            "SELECT event_id FROM event ORDER BY ingest_lsn"))
        raw = self.store.raw_for(rows[1]["event_id"])
        self.assertEqual(raw, (line + "\n").encode())

    def test_malformed_json_is_retained_not_dropped(self) -> None:
        self.write(meta_line(), "{not valid json")
        result = self.ingest()
        self.assertEqual(result["created"], 2)

    def test_dry_run_writes_nothing(self) -> None:
        self.write(meta_line(), record(1))
        result = self.ingest(dry_run=True)
        self.assertEqual(result["read"], 2)
        self.assertEqual(self.store.stats()["events"], 0)


class TestTailSemantics(AdapterTestCase):
    def test_resumes_from_checkpoint_and_ingests_only_new_records(self) -> None:
        self.write(meta_line(), record(1, role="user"))
        self.ingest()
        self.write(record(2, role="assistant"), mode="a")
        second = self.ingest()
        self.assertEqual(second["read"], 1, "should only read the appended record")
        self.assertEqual(self.store.stats()["events"], 3)

    def test_incomplete_final_line_is_not_ingested_until_terminated(self) -> None:
        with self.rollout.open("w") as handle:
            handle.write(meta_line() + "\n")
            handle.write('{"timestamp":"2026-10-02T18:35:10.000Z","type":"response_item"')
        first = self.ingest()
        self.assertEqual(first["created"], 1, "partial record must be skipped")
        with self.rollout.open("a") as handle:
            handle.write(',"payload":{"type":"message","role":"user"}}\n')
        second = self.ingest()
        self.assertEqual(second["created"], 1)
        self.assertEqual(self.store.stats()["events"], 2)

    def test_truncation_is_recorded_as_a_gap(self) -> None:
        self.write(meta_line(), record(1), record(2))
        self.ingest()
        self.write(meta_line(), record(9, content="totally different"))  # rewritten
        self.ingest()
        self.assertGreaterEqual(self.store.stats()["gaps"], 1)


class TestContentKeyedIdentity(AdapterTestCase):
    """The survey's lesson: the month directory is not evidence; the id is."""

    def test_moved_rollout_resumes_by_session_id(self) -> None:
        self.write(meta_line(), record(1, role="user"), record(2, role="assistant"))
        self.ingest()
        self.assertEqual(self.store.stats()["events"], 3)
        # Re-lay the file into a different month directory, bytes unchanged.
        new_day = self.sessions / "2026" / "09" / "15"
        new_day.mkdir(parents=True)
        moved = new_day / self.rollout.name
        self.rollout.rename(moved)
        self.rollout = moved
        second = self.ingest()
        self.assertEqual(second["read"], 0, "same session id + same bytes must resume")
        self.assertEqual(second["created"], 0)
        self.assertEqual(self.store.stats()["events"], 3)
        self.assertEqual(self.store.stats()["gaps"], 0)

    def test_source_uri_derives_from_session_id(self) -> None:
        self.write(meta_line(), record(1))
        self.ingest()
        row = self.store.db.execute(
            "SELECT DISTINCT source_uri, producer_session_id FROM event").fetchone()
        self.assertEqual(row["source_uri"], f"codex://sessions/{SESSION_ID}")
        self.assertEqual(row["producer_session_id"], SESSION_ID)

    def test_rollout_without_session_id_records_gap_not_path_identity(self) -> None:
        with self.rollout.open("w") as handle:
            handle.write(json.dumps({"type": "session_meta", "payload": {}}) + "\n")
            handle.write(record(1) + "\n")
        result = self.ingest()
        self.assertEqual(result["read"], 0)
        self.assertEqual(self.store.stats()["events"], 0)
        self.assertGreaterEqual(self.store.stats()["gaps"], 1)

    def test_first_line_still_being_written_is_transient_skip(self) -> None:
        with self.rollout.open("w") as handle:
            handle.write('{"type":"session_meta","payload":{"id":')  # no newline
        result = self.ingest()
        self.assertEqual(result["read"], 0)
        self.assertEqual(self.store.stats()["gaps"], 0, "a partial first line is not a gap")


class TestAllowList(AdapterTestCase):
    def test_non_rollout_siblings_are_never_listed(self) -> None:
        self.write(meta_line(), record(1))
        (self.rollout.parent / "auth.json").write_text('{"OPENAI_API_KEY":"x"}')
        (self.rollout.parent / "tokens.jsonl").write_text('{"token":"x"}\n')
        (self.rollout.parent / "notes.txt").write_text("hello")
        paths = adapter.rollout_paths(self.sessions)
        self.assertEqual(paths, [self.rollout.resolve()])

    def test_symlink_escaping_the_tree_is_refused(self) -> None:
        outside = self.root / "elsewhere.jsonl"
        outside.write_text(meta_line() + "\n")
        planted = self.rollout.parent / "rollout-2099-01-01T00-00-00-deadbeef.jsonl"
        planted.symlink_to(outside)
        self.assertFalse(adapter.is_allowed(planted, self.sessions))
        self.assertEqual(adapter.rollout_paths(self.sessions), [])

    def test_path_option_refuses_non_allowlisted_file(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            adapter.main(["scan", "--sessions", str(self.sessions),
                          "--path", str(self.root / "auth.json"),
                          "--db", str(self.root / "x.sqlite3"),
                          "--cas", str(self.root / "x-cas")])
        self.assertEqual(ctx.exception.code, 2)

    def test_scan_end_to_end_through_main(self) -> None:
        self.write(meta_line(), record(1, role="user"))
        rc = adapter.main(["--db", str(self.root / "m.sqlite3"),
                           "--cas", str(self.root / "m-cas"),
                           "--sessions", str(self.sessions),
                           "scan", "--quiet"])
        self.assertEqual(rc, 0)
        store = s1.EvidenceStore(self.root / "m.sqlite3", self.root / "m-cas")
        self.assertEqual(store.stats()["events"], 2)
        store.close()

    def test_missing_source_tree_scans_zero_files(self) -> None:
        rc = adapter.main(["--db", str(self.root / "n.sqlite3"),
                           "--cas", str(self.root / "n-cas"),
                           "--sessions", str(self.root / "no-such-tree"),
                           "scan", "--quiet"])
        self.assertEqual(rc, 0)


class TestMetadata(AdapterTestCase):
    def test_conversation_grouping_by_session(self) -> None:
        self.write(meta_line(), record(1, role="user"), record(2, role="assistant"))
        self.ingest()
        self.assertEqual(len(list(self.store.conversation(f"codex:{SESSION_ID}"))), 3)

    def test_role_and_tool_mapping(self) -> None:
        self.write(
            meta_line(),
            record(1, role="user"),
            record(2, "custom_tool_call", name="shell", call_id="call-9"),
            record(3, "custom_tool_call_output", call_id="call-9"),
        )
        self.ingest()
        rows = list(self.store.db.execute(
            "SELECT role, origin, event_type, tool_name, tool_call_id FROM event"
            " ORDER BY ingest_lsn"))
        self.assertEqual((rows[1]["role"], rows[1]["origin"]), ("user", "human"))
        self.assertEqual((rows[2]["role"], rows[2]["origin"]), ("tool", "tool"))
        self.assertEqual(rows[2]["tool_name"], "shell")
        self.assertEqual(rows[2]["tool_call_id"], "call-9")
        self.assertEqual(rows[3]["tool_call_id"], "call-9")

    def test_missing_timestamp_falls_back_to_filesystem(self) -> None:
        line = json.dumps({"type": "response_item",
                           "payload": {"type": "message", "role": "user"}})
        self.write(meta_line(), line)
        self.ingest()
        row = self.store.db.execute(
            "SELECT ts_source FROM event ORDER BY ingest_lsn DESC LIMIT 1").fetchone()
        self.assertEqual(row["ts_source"], "filesystem")


if __name__ == "__main__":
    unittest.main()
