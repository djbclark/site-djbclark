"""Synthetic Cline S1 adapter tests; no real chat content or stores."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import s1_cline as adapter
import s1_evidence as s1
import s1_search


class ClineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "data"
        self.sessions = self.root / "sessions" / "session-fixture"
        self.sessions.mkdir(parents=True)
        self.session_file = self.sessions / "session-fixture.json"
        self.messages_file = self.sessions / "session-fixture.messages.json"
        self.db = self.root / "db" / "hub-events-hub-production.db"
        self.db.parent.mkdir(parents=True)
        self.store = s1.EvidenceStore(
            Path(self.temp.name) / "s1.db", Path(self.temp.name) / "cas"
        )
        self.create_db(
            [
                (
                    1,
                    "reasoning.delta",
                    "session-fixture",
                    '{"text":"synthetic reasoning phrase"}',
                    1000,
                ),
                (
                    2,
                    "assistant.delta",
                    "session-fixture",
                    '{"text":"synthetic assistant phrase"}',
                    1001,
                ),
            ]
        )

    def tearDown(self) -> None:
        writer = getattr(self, "writer", None)
        if writer is not None:
            writer.close()
        self.store.close()
        self.temp.cleanup()

    def create_db(self, rows, *, wal: bool = False) -> None:
        con = sqlite3.connect(self.db)
        if wal:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA wal_autocheckpoint=0")
        con.execute(
            "CREATE TABLE hub_events(sequence INTEGER PRIMARY KEY, event TEXT, session_id TEXT, envelope_json TEXT, created_at INTEGER)"
        )
        con.executemany("INSERT INTO hub_events VALUES(?,?,?,?,?)", rows)
        con.commit()
        if wal:
            self.writer = con
        else:
            con.close()

    def scan(self, **kwargs):
        return adapter.scan(
            self.store, data_root=self.root, batch="cline-test", **kwargs
        )

    def test_session_files_capture_exact_bytes_with_content_hash_identity(self) -> None:
        original = (
            b'{"messages":[{"role":"user","text":"synthetic original phrase"}]}\n'
        )
        messages = (
            b'{"blocks":[{"type":"thinking","text":"synthetic thinking phrase"}]}\n'
        )
        self.session_file.write_bytes(original)
        self.messages_file.write_bytes(messages)
        one = adapter.ingest_session_file(
            self.store, self.session_file, root=self.root, batch="one"
        )
        two = adapter.ingest_session_file(
            self.store, self.messages_file, root=self.root, batch="one"
        )
        self.assertEqual((one["created"], two["created"]), (1, 1))
        unchanged = adapter.ingest_session_file(
            self.store, self.session_file, root=self.root, batch="two"
        )
        self.assertEqual(unchanged["created"], 0)
        self.assertEqual(unchanged["skipped"], 1)
        row = self.store.db.execute(
            "SELECT event_id FROM event WHERE event_type='session.snapshot'"
        ).fetchone()
        stored = self.store.raw_for(row["event_id"])
        self.assertEqual(adapter.decode_source_file(stored), original)
        self.assertIn("synthetic original phrase", s1_search.project(stored))

        self.session_file.write_bytes(
            b'{"messages":[{"text":"synthetic changed phrase"}]}\n'
        )
        changed = adapter.ingest_session_file(
            self.store, self.session_file, root=self.root, batch="three"
        )
        self.assertEqual(changed["created"], 1)
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM event WHERE event_type='session.snapshot'"
            ).fetchone()[0],
            2,
        )

    def test_hub_rows_round_trip_search_and_second_scan_is_empty(self) -> None:
        self.session_file.write_text('{"text":"synthetic session file"}')
        self.messages_file.write_text('{"text":"synthetic messages file"}')
        first = self.scan()
        self.assertEqual(first["rows_read"], 2)
        self.assertEqual(first["created"], 4)
        second = self.scan()
        self.assertEqual(second["rows_read"], 0)
        self.assertEqual(second["created"], 0)

        row = self.store.db.execute(
            "SELECT event_id, source_seq FROM event WHERE event_type='reasoning.delta'"
        ).fetchone()
        table, decoded = adapter.decode_row(self.store.raw_for(row["event_id"]))
        self.assertEqual(table, "hub_events")
        self.assertEqual(decoded["sequence"], row["source_seq"])
        self.assertIn(
            "synthetic reasoning phrase",
            s1_search.project(self.store.raw_for(row["event_id"])),
        )
        source = sqlite3.connect(self.db.resolve().as_uri() + "?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        actual = dict(
            source.execute("SELECT * FROM hub_events WHERE sequence=1").fetchone()
        )
        source.close()
        self.assertEqual(decoded, actual)

    def test_hub_database_reads_rows_from_live_wal(self) -> None:
        self.db.unlink()
        self.create_db(
            [
                (
                    9,
                    "tool.updated",
                    "session-fixture",
                    '{"result":"synthetic wal phrase"}',
                    1009,
                )
            ],
            wal=True,
        )
        result = adapter.ingest_hub_events(self.store, data_root=self.root, batch="wal")
        self.assertEqual(result["created"], 1)
        self.assertTrue(self.db.with_name(self.db.name + "-wal").exists())

    def test_rolling_window_gap_is_recorded_and_new_rows_are_captured(self) -> None:
        adapter.ingest_hub_events(self.store, data_root=self.root, batch="first")
        con = sqlite3.connect(self.db)
        try:
            with con:
                con.execute("DELETE FROM hub_events WHERE sequence < 3")
                con.executemany(
                    "INSERT INTO hub_events VALUES(?,?,?,?,?)",
                    [
                        (
                            5,
                            "tool.updated",
                            "session-fixture",
                            '{"text":"synthetic five"}',
                            1005,
                        ),
                        (
                            6,
                            "capability.resolved",
                            "session-fixture",
                            '{"text":"synthetic six"}',
                            1006,
                        ),
                    ],
                )
        finally:
            con.close()
        result = adapter.ingest_hub_events(
            self.store, data_root=self.root, batch="second"
        )
        self.assertGreaterEqual(result["gaps"], 1)
        self.assertEqual(result["created"], 2)
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM event WHERE producer='cline'"
            ).fetchone()[0],
            4,
        )

    def test_dry_run_writes_no_events_gaps_or_checkpoints(self) -> None:
        self.session_file.write_text('{"text":"synthetic dry run"}')
        self.messages_file.write_text('{"text":"synthetic dry run"}')
        before = (
            self.store.stats()["events"],
            self.store.stats()["gaps"],
            self.store.db.execute("SELECT COUNT(*) FROM ingest_checkpoint").fetchone()[
                0
            ],
        )
        result = self.scan(dry_run=True)
        after = (
            self.store.stats()["events"],
            self.store.stats()["gaps"],
            self.store.db.execute("SELECT COUNT(*) FROM ingest_checkpoint").fetchone()[
                0
            ],
        )
        self.assertEqual(result["created"], 0)
        self.assertEqual(after, before)

    def test_strict_file_allow_list_ignores_control_plane_and_symlinks(self) -> None:
        self.session_file.write_text('{"text":"synthetic allowed"}')
        (self.root / "sessions.db").write_text("synthetic control plane")
        (self.root / "logs").mkdir()
        (self.root / "logs" / "hub-daemon.log").write_text("synthetic log")
        external = Path(self.temp.name) / "external.json"
        external.write_text('{"text":"synthetic forbidden"}')
        (self.sessions / "other.json").symlink_to(external)
        self.assertEqual(adapter.session_paths(self.root), [self.session_file])

    def test_bad_json_is_still_raw_captured_and_projection_failure_is_nonfatal(
        self,
    ) -> None:
        self.session_file.write_bytes(b"{not json\n")
        result = adapter.ingest_session_file(
            self.store, self.session_file, root=self.root, batch="bad"
        )
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["unparsed"], 1)
        row = self.store.db.execute(
            "SELECT event_id FROM event WHERE producer='cline'"
        ).fetchone()
        self.assertEqual(
            adapter.decode_source_file(self.store.raw_for(row["event_id"])),
            b"{not json\n",
        )


if __name__ == "__main__":
    unittest.main()
