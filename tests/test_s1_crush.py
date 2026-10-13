"""Synthetic Crush S1 adapter tests; no real transcript text or stores."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import s1_crush as adapter
import s1_evidence as s1
import s1_search

SCHEMA = """
CREATE TABLE sessions (
  id TEXT PRIMARY KEY, parent_session_id TEXT, title TEXT, message_count INTEGER,
  prompt_tokens INTEGER, completion_tokens INTEGER, cost REAL, updated_at INTEGER,
  created_at INTEGER, summary_message_id TEXT, todos TEXT, channel TEXT
);
CREATE TABLE messages (
  id TEXT PRIMARY KEY, session_id TEXT, role TEXT, parts TEXT, model TEXT,
  created_at INTEGER, updated_at INTEGER, finished_at INTEGER, provider TEXT,
  is_summary_message INTEGER, prism_model_id TEXT, prism_model_name TEXT,
  prism_hypercredit_savings REAL, prism_dollar_savings REAL
);
CREATE TABLE files (
  id TEXT PRIMARY KEY, session_id TEXT, path TEXT, content TEXT, version INTEGER,
  created_at INTEGER, updated_at INTEGER
);
CREATE TABLE read_files (
  session_id TEXT, path TEXT, read_at INTEGER, PRIMARY KEY(session_id, path)
);
CREATE TABLE goose_db_version (
  id INTEGER PRIMARY KEY, version_id INTEGER, is_applied INTEGER, tstamp TIMESTAMP
);
CREATE TABLE mcp_enabled_servers(name TEXT PRIMARY KEY);
CREATE TABLE mcp_disabled_servers(name TEXT PRIMARY KEY);
CREATE TABLE provider_tokens(name TEXT PRIMARY KEY, access_token TEXT);
"""


class CrushTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = s1.EvidenceStore(self.root / "s1.sqlite3", self.root / "cas")
        self.projects = self.root / "projects"
        self.projects.mkdir()
        self.project = self.projects / "synthetic-project"
        self.project.mkdir()
        self.database = self.make_db(self.project)
        self.registry = self.root / "crush" / "projects.json"
        self.registry.parent.mkdir()
        self.write_registry([str(self.project)])

    def tearDown(self) -> None:
        writer = getattr(self, "_wal_writer", None)
        if writer is not None:
            writer.close()
        self.store.close()
        self.temporary.cleanup()

    def write_registry(self, project_paths: list[str]) -> None:
        self.registry.write_text(
            json.dumps(
                {
                    "projects": [
                        {"path": path, "data_dir": "ignored"} for path in project_paths
                    ]
                }
            ),
            encoding="utf-8",
        )

    def make_db(self, project: Path, *, wal: bool = False) -> Path:
        crush_dir = project / ".crush"
        crush_dir.mkdir(parents=True, exist_ok=True)
        path = crush_dir / "crush.db"
        connection = sqlite3.connect(path)
        if wal:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA wal_autocheckpoint=0")
            self._wal_writer = connection
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "session-1",
                None,
                "synthetic session title",
                1,
                2,
                3,
                0.5,
                4,
                3,
                None,
                "[]",
                "chat",
            ),
        )
        connection.execute(
            "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "message-1",
                "session-1",
                "user",
                json.dumps([{"type": "text", "text": "synthetic searchable phrase"}]),
                "fixture-model",
                10,
                11,
                12,
                "fixture-provider",
                0,
                None,
                None,
                0.0,
                0.0,
            ),
        )
        connection.execute(
            "INSERT INTO files VALUES (?,?,?,?,?,?,?)",
            (
                "file-1",
                "session-1",
                "src/fixture.py",
                "synthetic file content",
                1,
                9,
                10,
            ),
        )
        connection.execute(
            "INSERT INTO read_files VALUES (?,?,?)", ("session-1", "src/fixture.py", 10)
        )
        connection.execute("INSERT INTO goose_db_version VALUES (1,2,1,'synthetic')")
        connection.execute(
            "INSERT INTO provider_tokens VALUES (?,?)", ("fixture", "MUST_NOT_CAPTURE")
        )
        connection.commit()
        if not wal:
            connection.close()
        return path

    def scan(self, **kwargs):
        return adapter.scan(
            self.store,
            registry_paths=[self.registry],
            global_db=None,
            batch="synthetic-crush-test",
            **kwargs,
        )

    def events(self):
        return list(
            self.store.db.execute(
                "SELECT event_id, source_uri, source_locator, event_type FROM event "
                "WHERE producer=? ORDER BY ingest_lsn",
                (adapter.PRODUCER,),
            )
        )


class TestCrushIngest(CrushTestCase):
    def test_typed_rows_round_trip_exactly_and_credentials_table_is_skipped(
        self,
    ) -> None:
        result = self.scan()
        self.assertEqual(result["created"], 5)
        self.assertEqual(result["skipped_table_names"], ["provider_tokens"])
        self.assertEqual(result["tables_skipped"], 1)
        event = self.store.db.execute(
            "SELECT event_id, source_locator FROM event WHERE producer=? AND event_type='message.user'",
            (adapter.PRODUCER,),
        ).fetchone()
        table, values = adapter.decode_row(self.store.raw_for(event["event_id"]))
        self.assertEqual(table, "messages")
        source = sqlite3.connect(
            self.database.resolve().as_uri() + "?mode=ro", uri=True
        )
        source.row_factory = sqlite3.Row
        original = dict(
            source.execute("SELECT * FROM messages WHERE id='message-1'").fetchone()
        )
        source.close()
        self.assertEqual(values, original)
        self.assertIn("sha256:", event["source_locator"])
        self.assertIn("project:", event["source_locator"])
        raw_events = b"\n".join(
            self.store.raw_for(item["event_id"]) for item in self.events()
        )
        self.assertNotIn(b"MUST_NOT_CAPTURE", raw_events)
        self.assertNotIn(b"provider_tokens", raw_events)

    def test_parts_projection_indexes_text_and_tool_arguments_and_results(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute(
            "UPDATE messages SET parts=? WHERE id='message-1'",
            (
                json.dumps(
                    [
                        {"type": "text", "text": "synthetic searchable phrase"},
                        {
                            "type": "tool_use",
                            "name": "FixtureTool",
                            "input": {"query": "argument phrase"},
                        },
                        {"type": "tool_result", "content": "result phrase"},
                    ]
                ),
            ),
        )
        connection.commit()
        connection.close()
        self.scan()
        event = self.store.db.execute(
            "SELECT event_id FROM event WHERE producer=? AND event_type='message.user' ORDER BY ingest_lsn DESC LIMIT 1",
            (adapter.PRODUCER,),
        ).fetchone()
        projection = s1_search.project(self.store.raw_for(event["event_id"]))
        self.assertIn("synthetic searchable phrase", projection)
        self.assertIn("argument phrase", projection)
        self.assertIn("result phrase", projection)

    def test_second_scan_has_zero_new_events_and_changed_row_is_new_event(self) -> None:
        first = self.scan()
        event_count = self.store.stats()["events"]
        second = self.scan()
        self.assertEqual(first["created"], 5)
        self.assertEqual(second["created"], 0)
        self.assertEqual(self.store.stats()["events"], event_count)
        connection = sqlite3.connect(self.database)
        connection.execute(
            "UPDATE sessions SET title='revised synthetic title' WHERE id='session-1'"
        )
        connection.commit()
        connection.close()
        changed = self.scan()
        self.assertEqual(changed["created"], 1)
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM event WHERE producer=? AND event_type='sessions.row'",
                (adapter.PRODUCER,),
            ).fetchone()[0],
            2,
        )

    def test_table_shrink_is_gap_without_deleting_events(self) -> None:
        self.scan()
        event_count = self.store.stats()["events"]
        connection = sqlite3.connect(self.database)
        connection.execute("DELETE FROM messages WHERE id='message-1'")
        connection.commit()
        connection.close()
        result = self.scan()
        self.assertGreaterEqual(result["gaps"], 1)
        self.assertEqual(self.store.stats()["events"], event_count)

    def test_wal_rows_visible_read_only_without_immutable(self) -> None:
        self.database.unlink()
        self.database = self.make_db(self.project, wal=True)
        self.assertTrue(self.database.with_name("crush.db-wal").exists())
        sources, _ = adapter.discover_sources(
            registry_paths=[self.registry], global_db=None
        )
        connection = adapter.open_source(sources[0])
        try:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1
            )
        finally:
            connection.close()
        result = self.scan()
        self.assertEqual(result["created"], 5)

    def test_dry_run_changes_no_store_state(self) -> None:
        before = (self.store.stats()["events"], self.store.stats()["gaps"])
        result = self.scan(dry_run=True)
        after = (self.store.stats()["events"], self.store.stats()["gaps"])
        self.assertEqual(result["read"], 5)
        self.assertEqual(result["created"], 0)
        self.assertEqual(after, before)
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM ingest_checkpoint").fetchone()[
                0
            ],
            0,
        )

    def test_missing_db_after_checkpoint_records_gap_once(self) -> None:
        self.scan()
        self.database.unlink()
        first = self.scan()
        second = self.scan()
        self.assertEqual(first["gaps"], 1)
        self.assertEqual(second["gaps"], 0)
        self.assertEqual(self.store.stats()["events"], 5)

    def test_vanished_registry_path_gap_is_deduplicated(self) -> None:
        absent = self.root / "already-cleaned-project"
        self.write_registry([str(absent)])
        self.assertEqual(self.scan()["gaps"], 1)
        self.assertEqual(self.scan()["gaps"], 0)

    def test_symlinked_project_is_resolved_and_duplicate_db_is_collapsed(self) -> None:
        alias = self.projects / "alias"
        alias.symlink_to(self.project, target_is_directory=True)
        self.write_registry([str(self.project), str(alias)])
        sources, _ = adapter.discover_sources(
            registry_paths=[self.registry], global_db=None
        )
        self.assertEqual(len(sources), 1)
        self.assertEqual(self.scan()["created"], 5)

    def test_global_database_alias_is_collapsed_with_registered_project(self) -> None:
        sources, _ = adapter.discover_sources(
            registry_paths=[self.registry], global_db=self.database
        )
        self.assertEqual(len(sources), 1)
        self.assertFalse(sources[0].global_store)

    def test_symlinked_db_is_refused_and_reported_as_gap(self) -> None:
        other = self.root / "outside.db"
        other.write_bytes(self.database.read_bytes())
        self.database.unlink()
        self.database.symlink_to(other)
        result = self.scan()
        self.assertEqual(result["files"], 0)
        self.assertEqual(result["gaps"], 1)
        self.assertEqual(self.store.stats()["events"], 0)

    def test_corrupt_source_is_a_gap_but_does_not_fail_other_sources(self) -> None:
        other_project = self.projects / "second"
        other_project.mkdir()
        self.make_db(other_project)
        self.write_registry([str(self.project), str(other_project)])
        self.database.write_bytes(b"synthetic invalid sqlite")
        result = self.scan()
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["files"], 1)
        self.assertEqual(result["created"], 5)
        self.assertEqual(result["gaps"], 1)

    def test_neighboring_auth_files_are_not_opened(self) -> None:
        auth = self.project / "auth.json"
        auth.write_text('{"fixture":"must not open"}', encoding="utf-8")
        original = Path.read_text
        reads: list[Path] = []

        def tracked(path: Path, *args, **kwargs):
            reads.append(path)
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", tracked):
            self.scan()
        self.assertNotIn(auth, reads)

    def test_limit_caps_database_sources(self) -> None:
        second = self.projects / "second"
        second.mkdir()
        self.make_db(second)
        self.write_registry([str(self.project), str(second)])
        result = self.scan(limit=1)
        self.assertEqual(result["files"], 1)
        self.assertEqual(result["created"], 5)


if __name__ == "__main__":
    unittest.main()
