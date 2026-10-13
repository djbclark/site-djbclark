#!/usr/bin/env python3
"""Tests for the OpenCode-family read-only SQLite adapter."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import s1_evidence as s1  # noqa: E402
import s1_opencode as adapter  # noqa: E402

SCHEMA = """
CREATE TABLE session (
  id TEXT PRIMARY KEY, project_id TEXT, workspace_id TEXT, parent_id TEXT,
  slug TEXT, directory TEXT, path TEXT, title TEXT, version TEXT,
  time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL,
  cost REAL DEFAULT 0, tokens_input INTEGER DEFAULT 0
);
CREATE TABLE session_v2 (
  id TEXT PRIMARY KEY, project_id TEXT, workspace_id TEXT, parent_id TEXT,
  fork_session_id TEXT, fork_boundary TEXT, slug TEXT, directory TEXT,
  path TEXT, title TEXT, version TEXT, time_created INTEGER NOT NULL,
  time_updated INTEGER NOT NULL, cost REAL DEFAULT 0
);
CREATE TABLE message (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, time_created INTEGER NOT NULL,
  time_updated INTEGER NOT NULL, data TEXT NOT NULL
);
CREATE TABLE part (
  id TEXT PRIMARY KEY, message_id TEXT NOT NULL, session_id TEXT NOT NULL,
  time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, data TEXT NOT NULL
);
CREATE TABLE session_message (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, type TEXT NOT NULL,
  seq INTEGER NOT NULL, time_created INTEGER NOT NULL,
  time_updated INTEGER NOT NULL, data TEXT NOT NULL
);
CREATE TABLE credential (id TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE account (id TEXT PRIMARY KEY, access_token TEXT NOT NULL);
"""


class SQLiteAdapterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = s1.EvidenceStore(self.root / "s1.sqlite3", self.root / "cas")
        self.source = self.root / "opencode.db"
        con = sqlite3.connect(self.source)
        con.executescript(SCHEMA)
        con.execute(
            "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "s1",
                "p1",
                None,
                None,
                "slug",
                "/workspace",
                None,
                "fixture",
                "test",
                1_780_000_000_000,
                1_780_000_000_000,
                0,
                0,
            ),
        )
        con.execute(
            "INSERT INTO session_v2 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "s2",
                "p1",
                None,
                None,
                None,
                None,
                "slug2",
                "/workspace",
                None,
                "fixture2",
                "test",
                1_780_000_000_100,
                1_780_000_000_100,
                0,
            ),
        )
        con.execute(
            "INSERT INTO message VALUES (?,?,?,?,?)",
            (
                "m1",
                "s1",
                1_780_000_000_200,
                1_780_000_000_200,
                json.dumps({"role": "user", "content": "synthetic user fixture"}),
            ),
        )
        con.execute(
            "INSERT INTO part VALUES (?,?,?,?,?,?)",
            (
                "p1",
                "m1",
                "s1",
                1_780_000_000_300,
                1_780_000_000_300,
                json.dumps({"type": "tool", "tool": "FixtureTool", "callID": "call-1"}),
            ),
        )
        con.execute(
            "INSERT INTO session_message VALUES (?,?,?,?,?,?,?)",
            (
                "sm1",
                "s2",
                "message",
                1,
                1_780_000_000_400,
                1_780_000_000_400,
                json.dumps({"role": "assistant", "content": []}),
            ),
        )
        con.execute("INSERT INTO credential VALUES (?,?)", ("cred", "fixture-secret"))
        con.execute("INSERT INTO account VALUES (?,?)", ("account", "fixture-token"))
        con.commit()
        con.close()

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def sink(self, **kwargs):
        return adapter.sink(self.store, self.source, **kwargs)

    def table_checkpoint(self, table: str):
        return self.store.checkpoint(
            adapter.PRODUCER, adapter.checkpoint_uri(adapter.PRODUCER, table)
        )


class TestSQLiteIngest(SQLiteAdapterTestCase):
    def test_ingests_v1_and_v2_content_tables(self) -> None:
        result = self.sink()
        self.assertEqual((result["read"], result["created"]), (5, 5))
        self.assertEqual(self.store.stats()["events"], 5)
        row = self.store.db.execute(
            "SELECT role,origin,tool_name,tool_call_id,sensitivity,redaction_state "
            "FROM event WHERE event_type='part.tool'"
        ).fetchone()
        self.assertEqual((row["role"], row["origin"]), ("assistant", "model"))
        self.assertEqual(
            (row["tool_name"], row["tool_call_id"]), ("FixtureTool", "call-1")
        )
        self.assertEqual(row["sensitivity"], "sensitive")
        self.assertEqual(row["redaction_state"], "none")

    def test_unchanged_rerun_is_idempotent(self) -> None:
        self.sink()
        result = self.sink()
        self.assertEqual((result["read"], result["created"]), (0, 0))
        self.assertEqual(self.store.stats()["events"], 5)

    def test_resume_after_append(self) -> None:
        self.sink()
        con = sqlite3.connect(self.source)
        con.execute(
            "INSERT INTO part VALUES (?,?,?,?,?,?)",
            (
                "p2",
                "m1",
                "s1",
                1_780_000_000_500,
                1_780_000_000_500,
                json.dumps({"type": "text", "text": "synthetic append"}),
            ),
        )
        con.commit()
        con.close()
        result = self.sink()
        self.assertEqual((result["read"], result["created"]), (1, 1))
        self.assertEqual(self.store.stats()["events"], 6)

    def test_mutable_columns_do_not_change_evidence(self) -> None:
        self.sink()
        con = sqlite3.connect(self.source)
        con.execute("UPDATE part SET time_updated=time_updated+1")
        con.execute(
            "UPDATE session SET time_updated=time_updated+1,cost=9,tokens_input=99"
        )
        con.commit()
        con.close()
        result = self.sink()
        self.assertEqual((result["read"], result["created"], result["gaps"]), (0, 0, 0))

    def test_changed_high_water_content_is_new_evidence_and_gap(self) -> None:
        self.sink()
        con = sqlite3.connect(self.source)
        con.execute(
            "UPDATE part SET data=? WHERE id='p1'",
            (json.dumps({"type": "text", "text": "revised"}),),
        )
        con.commit()
        con.close()
        result = self.sink()
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["gaps"], 1)
        self.assertEqual(self.store.stats()["events"], 6)
        self.assertEqual(self.sink()["created"], 0)

    def test_allow_list_never_opens_credentials_or_secret_sibling_files(self) -> None:
        siblings = {
            "auth.json": '{"token":"SIBLING_AUTH_SENTINEL"}',
            "token.txt": "SIBLING_TOKEN_SENTINEL",
            "credentials.toml": 'key = "SIBLING_CREDENTIAL_SENTINEL"',
        }
        for name, content in siblings.items():
            (self.root / name).write_text(content)
        real_connect = sqlite3.connect
        opened = []

        def tracked_connect(database, *args, **kwargs):
            opened.append(str(database))
            return real_connect(database, *args, **kwargs)

        with patch.object(adapter.sqlite3, "connect", side_effect=tracked_connect):
            result = self.sink()
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(opened), 1)
        self.assertIn("opencode.db", opened[0])
        payloads = [
            self.store.get_bytes(row[0])
            for row in self.store.db.execute("SELECT sha256 FROM raw_object")
        ]
        combined = b"\n".join(payloads)
        for sentinel in (
            "SIBLING_AUTH_SENTINEL",
            "SIBLING_TOKEN_SENTINEL",
            "SIBLING_CREDENTIAL_SENTINEL",
            "fixture-secret",
            "fixture-token",
        ):
            self.assertNotIn(sentinel.encode(), combined)

    def test_missing_source_records_gap_and_preserves_checkpoint(self) -> None:
        self.sink()
        before = self.table_checkpoint("part")["committed_locator"]
        self.source.unlink()
        result = self.sink()
        after = self.table_checkpoint("part")["committed_locator"]
        self.assertEqual((result["failed"], result["gaps"]), (1, 1))
        self.assertEqual(before, after)

    def test_truncated_source_records_gap_without_advancing_checkpoint(self) -> None:
        self.sink()
        before = self.table_checkpoint("part")["committed_locator"]
        self.source.write_bytes(self.source.read_bytes()[:64])
        result = self.sink()
        after = self.table_checkpoint("part")["committed_locator"]
        self.assertEqual(result["failed"], 1)
        self.assertGreaterEqual(result["gaps"], 1)
        self.assertEqual(before, after)

    def test_dry_run_does_not_write_events_or_checkpoints(self) -> None:
        result = self.sink(dry_run=True)
        self.assertEqual(result["read"], 5)
        self.assertEqual(result["created"], 0)
        self.assertEqual(self.store.stats()["events"], 0)
        self.assertIsNone(self.table_checkpoint("part"))


if __name__ == "__main__":
    unittest.main()
