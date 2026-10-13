#!/usr/bin/env python3
"""Tests for zcode's opencode-shaped SQLite source adapter."""

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
import s1_opencode  # noqa: E402
import s1_zcode as adapter  # noqa: E402

SCHEMA = """
CREATE TABLE session (
  id TEXT PRIMARY KEY, project_id TEXT, workspace_id TEXT, parent_id TEXT,
  slug TEXT, directory TEXT, path TEXT, title TEXT, version TEXT,
  time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL,
  task_type TEXT, status TEXT
);
CREATE TABLE message (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, time_created INTEGER NOT NULL,
  time_updated INTEGER NOT NULL, data TEXT NOT NULL, sequence INTEGER
);
CREATE TABLE part (
  id TEXT PRIMARY KEY, message_id TEXT NOT NULL, session_id TEXT NOT NULL,
  time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL,
  data TEXT NOT NULL, sequence INTEGER
);
CREATE TABLE credential (id TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE local_setting (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class ZcodeAdapterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = s1.EvidenceStore(self.root / "s1.sqlite3", self.root / "cas")
        self.source = self.root / "db.sqlite"
        con = sqlite3.connect(self.source)
        con.executescript(SCHEMA)
        con.execute(
            "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "zs1",
                "zp1",
                None,
                None,
                "slug",
                "/fixture",
                None,
                "fixture",
                "test",
                1_780_000_000_000,
                1_780_000_000_000,
                "interactive",
                "active",
            ),
        )
        con.execute(
            "INSERT INTO message VALUES (?,?,?,?,?,?)",
            (
                "zm1",
                "zs1",
                1_780_000_000_100,
                1_780_000_000_100,
                json.dumps({"role": "user", "content": "synthetic prompt"}),
                1,
            ),
        )
        con.execute(
            "INSERT INTO part VALUES (?,?,?,?,?,?,?)",
            (
                "zp1",
                "zm1",
                "zs1",
                1_780_000_000_200,
                1_780_000_000_200,
                json.dumps({"type": "tool", "tool": "FixtureTool", "callID": "z-call"}),
                2,
            ),
        )
        con.execute("INSERT INTO credential VALUES (?,?)", ("cred", "fixture-secret"))
        con.execute(
            "INSERT INTO local_setting VALUES (?,?)", ("token", "fixture-token")
        )
        con.commit()
        con.close()

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def sink(self, **kwargs):
        return adapter.sink(self.store, self.source, **kwargs)

    def checkpoint(self, table: str):
        return self.store.checkpoint(
            adapter.PRODUCER, s1_opencode.checkpoint_uri(adapter.PRODUCER, table)
        )


class TestZcodeSink(ZcodeAdapterTestCase):
    def test_reuses_reader_with_distinct_producer(self) -> None:
        self.assertEqual(adapter.PRODUCER, "zcode")
        first = self.sink()
        self.assertEqual((first["read"], first["created"]), (3, 3))
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM event WHERE producer='zcode'"
            ).fetchone()[0],
            3,
        )
        second = self.sink()
        self.assertEqual((second["read"], second["created"]), (0, 0))

    def test_resume_after_append(self) -> None:
        self.sink()
        con = sqlite3.connect(self.source)
        con.execute(
            "INSERT INTO part VALUES (?,?,?,?,?,?,?)",
            (
                "zp2",
                "zm1",
                "zs1",
                1_780_000_000_300,
                1_780_000_000_300,
                json.dumps({"type": "text", "text": "synthetic append"}),
                3,
            ),
        )
        con.commit()
        con.close()
        result = self.sink()
        self.assertEqual((result["read"], result["created"]), (1, 1))

    def test_mutable_time_and_status_columns_are_excluded(self) -> None:
        self.sink()
        con = sqlite3.connect(self.source)
        con.execute("UPDATE part SET time_updated=time_updated+1")
        con.execute(
            "UPDATE session SET status='complete',task_type='workflow',time_updated=time_updated+1"
        )
        con.commit()
        con.close()
        result = self.sink()
        self.assertEqual((result["read"], result["created"], result["gaps"]), (0, 0, 0))

    def test_allow_list_does_not_read_credential_files_or_tables(self) -> None:
        for name, text in {
            "auth.json": '{"token":"ZCODE_AUTH_SENTINEL"}',
            "token.txt": "ZCODE_TOKEN_SENTINEL",
            "credentials.json": '{"key":"ZCODE_CREDENTIAL_SENTINEL"}',
        }.items():
            (self.root / name).write_text(text)
        real_connect = sqlite3.connect
        opened = []

        def tracked_connect(database, *args, **kwargs):
            opened.append(str(database))
            return real_connect(database, *args, **kwargs)

        with patch.object(s1_opencode.sqlite3, "connect", side_effect=tracked_connect):
            self.sink()
            rejected = adapter.sink(self.store, self.root / "credentials.json")
            rejected_opencode = s1_opencode.sink(
                self.store, self.root / "auth.json", producer="opencode"
            )
        self.assertEqual((rejected["failed"], rejected["gaps"]), (1, 1))
        self.assertEqual(
            (rejected_opencode["failed"], rejected_opencode["gaps"]), (1, 1)
        )
        self.assertEqual(len(opened), 1)
        self.assertIn("db.sqlite", opened[0])
        payloads = [
            self.store.get_bytes(row[0])
            for row in self.store.db.execute("SELECT sha256 FROM raw_object")
        ]
        combined = b"\n".join(payloads)
        for sentinel in (
            "ZCODE_AUTH_SENTINEL",
            "ZCODE_TOKEN_SENTINEL",
            "ZCODE_CREDENTIAL_SENTINEL",
            "fixture-secret",
            "fixture-token",
        ):
            self.assertNotIn(sentinel.encode(), combined)

    def test_truncated_database_records_gap_and_keeps_checkpoint(self) -> None:
        self.sink()
        before = self.checkpoint("part")["committed_locator"]
        self.source.write_bytes(self.source.read_bytes()[:64])
        result = self.sink()
        self.assertEqual(result["failed"], 1)
        self.assertGreaterEqual(result["gaps"], 1)
        self.assertEqual(self.checkpoint("part")["committed_locator"], before)

    def test_missing_source_records_gap_and_keeps_checkpoint(self) -> None:
        self.sink()
        before = self.checkpoint("part")["committed_locator"]
        self.source.unlink()
        result = self.sink()
        self.assertEqual((result["failed"], result["gaps"]), (1, 1))
        self.assertEqual(self.checkpoint("part")["committed_locator"], before)


if __name__ == "__main__":
    unittest.main()
