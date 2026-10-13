"""Synthetic Cursor IDE state.vscdb adapter tests; no real transcript text."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import s1_cursor_ide as adapter
import s1_evidence as s1
import s1_search

TABLE_SCHEMA = (
    "CREATE TABLE cursorDiskKV (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)",
    "CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)",
    "CREATE TABLE composerHeaders (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)",
)


class CursorIdeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = s1.EvidenceStore(self.root / "s1.sqlite3", self.root / "cas")
        self.profile_root = self.root / "profiles"
        self.workspace_root = self.root / "workspaceStorage"
        self.profile_root.mkdir()
        self.workspace_root.mkdir()
        self.workspace_id = "workspace-fixture"
        self.workspace_dir = self.workspace_root / self.workspace_id
        self.workspace_dir.mkdir()
        self.db_path = self.workspace_dir / "state.vscdb"
        self.workspace_json = self.workspace_dir / "workspace.json"
        self.workspace_json.write_text(
            '{"folder":"/synthetic/project"}', encoding="utf-8"
        )
        self.create_db(self.db_path)
        self.source = adapter.DatabaseSource(
            "workspace", self.workspace_id, self.db_path, self.workspace_json
        )
        self.roots = {
            "global": self.root / "global" / "state.vscdb",
            "profile": self.profile_root,
            "workspace": self.workspace_root,
        }

    def tearDown(self) -> None:
        writer = getattr(self, "_wal_writer", None)
        if writer is not None:
            writer.close()
        self.store.close()
        self.temporary.cleanup()

    def create_db(self, path: Path, *, wal: bool = False) -> None:
        con = sqlite3.connect(path)
        if wal:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA wal_autocheckpoint=0")
        for statement in TABLE_SCHEMA:
            con.execute(statement)
        con.executemany(
            "INSERT INTO cursorDiskKV(key,value) VALUES(?,?)",
            [
                ("agentKv:blob:fixture", b"\x0a\x1dsynthetic binary response"),
                (
                    "bubbleId:fixture",
                    json.dumps(
                        {
                            "bubble": {
                                "text": "synthetic assistant response",
                                "tool": {"args": "synthetic command arguments"},
                            }
                        }
                    ),
                ),
                ("composerData:fixture", '{"prompt":"synthetic composer prompt"}'),
                ("checkpointId:fixture", b'{"result":"synthetic checkpoint result"}'),
                ("composer.content.fixture", "PLANTED_UNVERIFIED_COMPOSER_CONTENT"),
                ("composerDraft:fixture", '{"text":"synthetic draft prompt"}'),
                ("bubbleId:null-fixture", None),
                ("cursorAuth/accessToken", "PLANTED_CURSOR_AUTH_ACCESS_TOKEN"),
                ("some-secret-marker", "PLANTED_SECRET_VALUE"),
                ("unknownPrefix:fixture", "PLANTED_UNKNOWN_PREFIX_VALUE"),
            ],
        )
        con.executemany(
            "INSERT INTO ItemTable(key,value) VALUES(?,?)",
            [
                ("aiService.prompts", '[{"text":"synthetic recent prompt"}]'),
                (
                    "aiService.generations",
                    '[{"textDescription":"synthetic generated result"}]',
                ),
                ("cursorAuth/refreshToken", "PLANTED_ITEM_AUTH_REFRESH"),
                ("extension.secret.value", "PLANTED_ITEM_SECRET_VALUE"),
                ("unknownChatLikeKey", "PLANTED_ITEM_UNKNOWN_VALUE"),
            ],
        )
        con.commit()
        if wal:
            self._wal_writer = con
        else:
            con.close()

    def scan(self, **kwargs):
        return adapter.scan_source(
            self.store,
            self.source,
            batch="synthetic-cursor-test",
            **kwargs,
        )


class TestCursorIdeIngest(CursorIdeTestCase):
    def test_typed_round_trip_search_projection_and_allow_lists(self) -> None:
        result = self.scan()
        self.assertEqual(result["created"], 9)  # eight rows plus workspace.json
        events = self.store.db.execute(
            "SELECT event_id, source_locator FROM event WHERE producer=? ORDER BY ingest_lsn",
            (adapter.PRODUCER,),
        ).fetchall()
        self.assertEqual(len(events), 9)
        decoded_by_key = {}
        for event in events:
            raw = self.store.raw_for(event["event_id"])
            if event["source_locator"].startswith("file:"):
                self.assertEqual(raw, self.workspace_json.read_bytes())
                continue
            db_kind, table, key, value = adapter.decode_row(raw)
            self.assertEqual(db_kind, "workspace:workspace-fixture")
            decoded_by_key[key] = (table, value, raw)
        self.assertEqual(
            decoded_by_key["bubbleId:fixture"][1],
            '{"bubble": {"text": "synthetic assistant response", "tool": {"args": "synthetic command arguments"}}}',
        )
        self.assertEqual(
            decoded_by_key["agentKv:blob:fixture"][1],
            b"\x0a\x1dsynthetic binary response",
        )
        self.assertIsNone(decoded_by_key["bubbleId:null-fixture"][1])
        self.assertIn(
            "synthetic assistant response",
            s1_search.project(decoded_by_key["bubbleId:fixture"][2]),
        )
        self.assertIn(
            "synthetic generated result",
            s1_search.project(decoded_by_key["aiService.generations"][2]),
        )
        self.assertFalse(
            any(
                "PLANTED" in self.store.raw_for(row[0]).decode("utf-8", "ignore")
                for row in self.store.db.execute(
                    "SELECT event_id FROM event WHERE producer=?",
                    (adapter.PRODUCER,),
                )
            )
        )

    def test_unchanged_rescan_is_noop_and_mutation_keeps_old_event(self) -> None:
        first = self.scan()
        event_count = self.store.stats()["events"]
        second = self.scan()
        self.assertGreater(first["created"], 0)
        self.assertEqual(second["created"], 0)
        self.assertEqual(self.store.stats()["events"], event_count)
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "UPDATE cursorDiskKV SET value=? WHERE key=?",
                ('{"text":"synthetic revised bubble"}', "bubbleId:fixture"),
            )
            con.commit()
        finally:
            con.close()
        changed = self.scan()
        self.assertEqual(changed["created"], 1)
        rows = []
        for row in self.store.db.execute(
            "SELECT event_id, event_type FROM event WHERE producer=? ORDER BY ingest_lsn",
            (adapter.PRODUCER,),
        ):
            if (
                row[1] == "cursorDiskKV.row"
                and adapter.decode_row(self.store.raw_for(row[0]))[2]
                == "bubbleId:fixture"
            ):
                rows.append(row)
        self.assertEqual(len(rows), 2)
        values = [adapter.decode_row(self.store.raw_for(row[0]))[3] for row in rows]
        self.assertIn("synthetic assistant response", values[0])
        self.assertEqual(values[1], '{"text":"synthetic revised bubble"}')

    def test_wal_resident_rows_are_visible(self) -> None:
        wal_path = self.root / "wal" / "state.vscdb"
        wal_path.parent.mkdir()
        self.create_db(wal_path, wal=True)
        source = adapter.DatabaseSource("workspace", "wal-fixture", wal_path)
        self.assertTrue(wal_path.with_name("state.vscdb-wal").exists())
        with adapter.open_database_readonly(source) as reader:
            count = reader.execute("SELECT COUNT(*) FROM cursorDiskKV").fetchone()[0]
        self.assertEqual(count, 10)
        result = adapter.scan_source(self.store, source, batch="wal-test")
        self.assertGreater(result["created"], 0)

    def test_dry_run_writes_no_events_gaps_or_checkpoints(self) -> None:
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

    def test_corrupt_database_records_gap(self) -> None:
        self.db_path.write_bytes(b"synthetic corrupt sqlite")
        result = self.scan()
        self.assertEqual(result["failed"], 1)
        self.assertGreaterEqual(result["gaps"], 1)
        self.assertGreaterEqual(self.store.stats()["gaps"], 1)

    def test_shrink_records_gap_without_deleting_old_evidence(self) -> None:
        self.scan()
        before = self.store.stats()["events"]
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("DELETE FROM cursorDiskKV WHERE key=?", ("bubbleId:fixture",))
            con.commit()
        finally:
            con.close()
        result = self.scan()
        self.assertGreaterEqual(result["gaps"], 1)
        self.assertEqual(self.store.stats()["events"], before)

    def test_deleting_an_excluded_key_name_is_still_a_source_shrink_gap(self) -> None:
        self.scan()
        before = self.store.stats()["events"]
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "DELETE FROM cursorDiskKV WHERE key=?", ("unknownPrefix:fixture",)
            )
            con.commit()
        finally:
            con.close()
        result = self.scan()
        self.assertGreaterEqual(result["gaps"], 1)
        self.assertEqual(result["created"], 0)
        self.assertEqual(self.store.stats()["events"], before)

    def test_value_selects_never_include_blocked_key_names(self) -> None:
        statements: list[str] = []
        original = adapter._readonly_connection

        def traced(path: Path) -> sqlite3.Connection:
            con = original(path)
            con.set_trace_callback(statements.append)
            return con

        with mock.patch.object(adapter, "_readonly_connection", traced):
            self.scan()
        value_selects = [
            statement for statement in statements if "CAST(value AS BLOB)" in statement
        ]
        self.assertTrue(value_selects)
        text = "\n".join(value_selects)
        for blocked in (
            "cursorAuth/accessToken",
            "some-secret-marker",
            "unknownPrefix:fixture",
            "cursorAuth/refreshToken",
            "extension.secret.value",
            "unknownChatLikeKey",
            "composer.content.fixture",
        ):
            self.assertNotIn(blocked, text)

    def test_allowed_value_queries_are_chunked_under_sqlite_bind_limits(self) -> None:
        with mock.patch.object(adapter, "KEY_QUERY_BATCH", 2):
            result = self.scan()
        self.assertEqual(result["created"], 9)
        self.assertEqual(result["rows_read"], 8)

    def test_large_blob_round_trips_and_stays_out_of_search_projection(self) -> None:
        payload = b"L" * (2 * 1024 * 1024)
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE sample(key TEXT, value BLOB)")
        con.execute("INSERT INTO sample VALUES(?,?)", ("agentKv:blob:large", payload))
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT CAST(key AS BLOB) key_bytes,typeof(value) value_type,CAST(value AS BLOB) value_bytes FROM sample"
        ).fetchone()
        encoded = adapter.encode_row(
            "workspace:large",
            "cursorDiskKV",
            row["key_bytes"],
            row["value_type"],
            row["value_bytes"],
            "",
        )
        con.close()
        self.assertEqual(adapter.decode_row(encoded)[3], payload)
        self.assertEqual(s1_search.project(encoded), "")
        self.assertGreater(len(encoded), len(payload))


class TestCursorIdeProjectionAndDiscovery(unittest.TestCase):
    def test_json_walk_extracts_chat_tool_and_code_text_without_hash_noise(
        self,
    ) -> None:
        value = {
            "prompt": "synthetic user prompt",
            "response": "synthetic assistant response",
            "toolCall": {
                "args": "synthetic tool arguments",
                "result": "synthetic tool result",
            },
            "codeBlock": "print('synthetic code block')",
            "contentHash": "a" * 64,
            "binary": "A" * 80 + "9",
        }
        projection, kind = adapter.extract_search_text(
            "text", json.dumps(value).encode("utf-8")
        )
        self.assertEqual(kind, "json")
        for text in (
            "synthetic user prompt",
            "synthetic assistant response",
            "synthetic tool arguments",
            "synthetic tool result",
            "synthetic code block",
        ):
            self.assertIn(text, projection)
        self.assertNotIn("a" * 64, projection)
        self.assertNotIn("A" * 80, projection)

    def test_prefix_and_item_key_allow_lists_are_explicit(self) -> None:
        for prefix in adapter.CURSOR_KV_PREFIXES:
            self.assertTrue(adapter._allowed_key("cursorDiskKV", prefix + "fixture"))
        for key in (
            "cursorAuth/accessToken",
            "sample.secret",
            "unknownPrefix:chat",
            "composer.content.unverified",
        ):
            self.assertFalse(adapter._allowed_key("cursorDiskKV", key))
        self.assertTrue(adapter._allowed_key("ItemTable", "aiService.prompts"))
        self.assertTrue(adapter._allowed_key("ItemTable", "aiService.generations"))
        for key in (
            "cursorAuth/accessToken",
            "composer.secret",
            "some.chat.history",
            "unknownPrefix",
        ):
            self.assertFalse(adapter._allowed_key("ItemTable", key))

    def test_discovery_only_finds_three_documented_store_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            global_db = root / "global" / "state.vscdb"
            global_db.parent.mkdir()
            global_db.touch()
            profiles = root / "profiles"
            profile_dir = profiles / "profile-1"
            (profile_dir / "globalStorage").mkdir(parents=True)
            profile_db = profile_dir / "globalStorage" / "state.vscdb"
            profile_db.touch()
            workspaces = root / "workspaces"
            workspace_dir = workspaces / "abc123"
            workspace_dir.mkdir(parents=True)
            workspace_db = workspace_dir / "state.vscdb"
            workspace_db.touch()
            (workspace_dir / "workspace.json").write_text("{}", encoding="utf-8")
            (workspace_dir / "state.vscdb.backup").touch()
            roots = {"global": global_db, "profile": profiles, "workspace": workspaces}
            sources = adapter.discover_sources(roots)
            self.assertEqual(
                [s.kind for s in sources], ["global", "profile", "workspace"]
            )
            self.assertEqual(
                sources[-1].workspace_json, workspace_dir / "workspace.json"
            )


if __name__ == "__main__":
    unittest.main()
