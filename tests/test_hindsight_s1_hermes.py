#!/usr/bin/env python3
"""Tests for the Hermes event sink.

The property that needs protecting here is that Hermes rewriting a row's
*status* (observed/active/compacted) must not look like the evidence changing,
while a change to its *content* must.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import hindsight_s1 as s1  # noqa: E402
import hindsight_s1_hermes as sink  # noqa: E402

SCHEMA = """
CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT,
  tool_call_id TEXT,
  tool_calls TEXT,
  tool_name TEXT,
  timestamp REAL NOT NULL,
  token_count INTEGER,
  finish_reason TEXT,
  reasoning TEXT,
  reasoning_content TEXT,
  reasoning_details TEXT,
  codex_reasoning_items TEXT,
  codex_message_items TEXT,
  platform_message_id TEXT,
  observed INTEGER DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  compacted INTEGER NOT NULL DEFAULT 0,
  effect_disposition TEXT,
  api_content TEXT,
  display_kind TEXT,
  display_metadata TEXT
);
"""


class HermesSinkTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.store = s1.EvidenceStore(root / "s1.sqlite3", root / "cas")
        self.state = root / "state.db"
        con = sqlite3.connect(self.state)
        con.executescript(SCHEMA)
        con.commit()
        con.close()

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def add(self, role="user", content="hello", session="s1", **kw):
        con = sqlite3.connect(self.state)
        cols = dict(session_id=session, role=role, content=content,
                    timestamp=1787500000.0)
        cols.update(kw)
        keys = ",".join(cols)
        con.execute(f"INSERT INTO messages ({keys}) VALUES ({','.join('?' * len(cols))})",
                    tuple(cols.values()))
        con.commit()
        con.close()

    def run_sink(self, **kw):
        return sink.sink(self.store, self.state, **kw)


class TestBasicSink(HermesSinkTestCase):
    def test_ingests_messages(self) -> None:
        self.add(content="first")
        self.add(role="assistant", content="second")
        r = self.run_sink()
        self.assertEqual((r["read"], r["created"]), (2, 2))
        self.assertEqual(self.store.stats()["events"], 2)

    def test_resumes_and_does_not_reingest(self) -> None:
        self.add(content="first")
        self.run_sink()
        self.add(content="second")
        r = self.run_sink()
        self.assertEqual(r["read"], 1, "should read only the new row")
        self.assertEqual(self.store.stats()["events"], 2)

    def test_rerun_with_no_new_rows_is_a_noop(self) -> None:
        self.add()
        self.run_sink()
        r = self.run_sink()
        self.assertEqual((r["read"], r["created"]), (0, 0))

    def test_roles_and_tool_fields_map(self) -> None:
        self.add(role="tool", content="result", tool_name="Bash",
                 tool_call_id="call-1")
        self.run_sink()
        row = self.store.db.execute(
            "SELECT role, origin, event_type, tool_name, tool_call_id FROM event").fetchone()
        self.assertEqual(row["role"], "tool")
        self.assertEqual(row["origin"], "tool")
        self.assertEqual(row["event_type"], "message.tool")
        self.assertEqual(row["tool_name"], "Bash")
        self.assertEqual(row["tool_call_id"], "call-1")

    def test_unknown_role_still_retained(self) -> None:
        self.add(role="session_meta", content="{}")
        self.run_sink()
        self.assertEqual(self.store.stats()["events"], 1)

    def test_dry_run_writes_nothing(self) -> None:
        self.add()
        r = self.run_sink(dry_run=True)
        self.assertEqual(r["read"], 1)
        self.assertEqual(self.store.stats()["events"], 0)


class TestMutabilityHandling(HermesSinkTestCase):
    """The core correctness property of this adapter."""

    def _mutate(self, sql: str) -> None:
        con = sqlite3.connect(self.state)
        con.execute(sql)
        con.commit()
        con.close()

    def test_status_flag_changes_do_not_look_like_mutation(self) -> None:
        # Hermes marks rows observed/compacted as conversations age. That must
        # not be mistaken for the evidence changing.
        self.add(content="stable")
        self.run_sink()
        for sql in ("UPDATE messages SET observed=1",
                    "UPDATE messages SET compacted=1",
                    "UPDATE messages SET active=0",
                    "UPDATE messages SET display_kind='collapsed'"):
            self._mutate(sql)
        # force a re-read of the same row by rewinding the checkpoint
        self.store.set_checkpoint(sink.PRODUCER, self.state.resolve().as_uri(),
                                  source_fingerprint="messages:max=0",
                                  committed_locator="messages:0",
                                  adapter_version="test")
        r = self.run_sink()
        self.assertEqual(r["read"], 1)
        self.assertEqual(r["created"], 0, "same content must be recognised, not duplicated")
        self.assertEqual(r["skipped"], 0, "status change must not register as mutation")
        self.assertEqual(self.store.stats()["gaps"], 0)

    def test_content_change_is_recorded_as_a_gap(self) -> None:
        self.add(content="original")
        self.run_sink()
        self._mutate("UPDATE messages SET content='rewritten'")
        self.store.set_checkpoint(sink.PRODUCER, self.state.resolve().as_uri(),
                                  source_fingerprint="messages:max=0",
                                  committed_locator="messages:0",
                                  adapter_version="test")
        r = self.run_sink()
        self.assertEqual(r["skipped"], 1)
        self.assertEqual(self.store.stats()["gaps"], 1)

    def test_row_bytes_exclude_mutable_columns(self) -> None:
        self.add()
        con = sqlite3.connect(self.state)
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM messages").fetchone()
        con.close()
        payload = json.loads(sink.row_bytes(row))
        for col in sink.MUTABLE_COLUMNS:
            self.assertNotIn(col, payload)
        for col in ("id", "session_id", "role", "content", "timestamp"):
            self.assertIn(col, payload)


class TestGroupingAndTime(HermesSinkTestCase):
    def test_conversation_grouped_by_session(self) -> None:
        self.add(session="abc")
        self.add(session="abc", role="assistant")
        self.add(session="other")
        self.run_sink()
        self.assertEqual(len(list(self.store.conversation("hermes:abc"))), 2)

    def test_epoch_timestamp_converted_to_z_suffixed_utc(self) -> None:
        self.add()
        self.run_sink()
        ts = self.store.db.execute("SELECT ts_utc, ts_source FROM event").fetchone()
        self.assertTrue(ts["ts_utc"].endswith("Z"))
        self.assertEqual(ts["ts_source"], "producer")

    def test_bad_timestamp_falls_back_honestly(self) -> None:
        self.add()
        con = sqlite3.connect(self.state)
        con.execute("UPDATE messages SET timestamp=0.0")
        con.commit(); con.close()
        # 0.0 is a valid epoch, so assert the honest-fallback path directly
        stamp, source = sink.to_utc(None)
        self.assertEqual(source, "ingest")
        self.assertTrue(stamp.endswith("Z"))

    def test_raw_payload_round_trips(self) -> None:
        self.add(content="exact ✓ payload")
        self.run_sink()
        eid = self.store.db.execute("SELECT event_id FROM event").fetchone()["event_id"]
        self.assertEqual(json.loads(self.store.raw_for(eid))["content"], "exact ✓ payload")


if __name__ == "__main__":
    unittest.main()
