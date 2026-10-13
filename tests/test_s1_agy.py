"""Synthetic Antigravity S1 tests; no real transcript text or stores."""

from __future__ import annotations

import builtins
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import s1_agy as adapter
import s1_evidence as s1
import s1_search

STEPS_SCHEMA = """CREATE TABLE steps (
    idx INTEGER PRIMARY KEY,
    step_type INTEGER,
    status INTEGER,
    has_subtrajectory NUMERIC,
    metadata BLOB,
    error_details BLOB,
    permissions BLOB,
    task_details BLOB,
    render_info BLOB,
    step_payload BLOB,
    step_format INTEGER
)"""
TABLE_SCHEMA = (
    STEPS_SCHEMA,
    "CREATE TABLE gen_metadata(idx INTEGER PRIMARY KEY, data BLOB, size INTEGER)",
    "CREATE TABLE executor_metadata(idx INTEGER PRIMARY KEY, data BLOB)",
    "CREATE TABLE parent_references(idx INTEGER PRIMARY KEY, data BLOB)",
    "CREATE TABLE trajectory_meta(trajectory_id TEXT PRIMARY KEY, cascade_id TEXT, trajectory_type INTEGER, source INTEGER)",
    "CREATE TABLE trajectory_metadata_blob(id TEXT PRIMARY KEY, data BLOB)",
    "CREATE TABLE battle_mode_infos(idx INTEGER PRIMARY KEY, data BLOB)",
)


def varint(value: int) -> bytes:
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def length_field(number: int, value: bytes) -> bytes:
    return varint((number << 3) | 2) + varint(len(value)) + value


def make_proto(text: bytes = b"synthetic prompt searchable") -> bytes:
    nested = length_field(1, text)
    return b"".join(
        (
            varint((1 << 3) | 0) + varint(150),  # varint
            varint((2 << 3) | 1) + b"12345678",  # fixed64
            length_field(3, nested),  # nested length-delimited message
            length_field(4, b"\xff\xfe\xfd"),  # invalid UTF-8
            varint((5 << 3) | 5) + b"abcd",  # fixed32
            length_field(6, b"synthetic tool output"),
        )
    )


class AgyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = s1.EvidenceStore(self.root / "s1.sqlite3", self.root / "cas")
        self.roots = {
            name: self.root / name / "conversations" for name in adapter.STORE_ROOTS
        }
        for path in self.roots.values():
            path.mkdir(parents=True)
        self.session_id = str(uuid.uuid4())
        self.session = self.make_session("cli", self.session_id)

    def tearDown(self) -> None:
        writer = getattr(self, "_wal_writer", None)
        if writer is not None:
            writer.close()
        self.store.close()
        self.temporary.cleanup()

    def make_session(self, store_name: str, session_id: str) -> adapter.Session:
        root = self.roots[store_name]
        db_path = root / f"{session_id}.db"
        session = adapter.Session(store_name, session_id, root, db_path, None)
        self.create_db(db_path)
        return session

    def create_db(self, path: Path, *, wal: bool = False) -> None:
        con = sqlite3.connect(path)
        if wal:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA wal_autocheckpoint=0")
        for ddl in TABLE_SCHEMA:
            con.execute(ddl)
        raw = make_proto()
        con.execute(
            "INSERT INTO steps VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (7, 1, 3, 0, b"\x0a\x05meta1", None, b"", b"\x10\x01", b"\x18\x02", raw, 1),
        )
        con.execute(
            "INSERT INTO gen_metadata VALUES(?,?,?)", (1, b"\x0a\x07generate", 7)
        )
        con.execute("INSERT INTO executor_metadata VALUES(?,?)", (1, b"\x0a\x06execfx"))
        con.execute("INSERT INTO parent_references VALUES(?,?)", (1, b"\x0a\x06parent"))
        con.execute(
            "INSERT INTO trajectory_meta VALUES(?,?,?,?)",
            ("traj-fixture", "cascade-fixture", 1, 2),
        )
        con.execute(
            "INSERT INTO trajectory_metadata_blob VALUES(?,?)",
            ("trajectory-fixture", b"\x0a\x05graph"),
        )
        con.execute("INSERT INTO battle_mode_infos VALUES(?,?)", (1, b"\x0a\x06battle"))
        con.commit()
        if not wal:
            con.close()
        else:
            self._wal_writer = con

    def scan(self, **kwargs):
        return adapter.scan(
            self.store,
            roots=self.roots,
            batch="synthetic-test",
            **kwargs,
        )


class TestAgyEncodingAndIngest(AgyTestCase):
    def test_all_allowlisted_tables_round_trip_and_capture_every_steps_column(
        self,
    ) -> None:
        (self.session.root / f"{self.session_id}.meta").write_bytes(
            b'{"cwd":"/synthetic/project","mode_id":"fixture"}'
        )
        self.session = adapter.Session(
            "cli",
            self.session_id,
            self.session.root,
            self.session.db_path,
            self.session.root / f"{self.session_id}.meta",
        )
        result = self.scan()
        self.assertEqual(result["created"], 8)  # seven table rows and .meta
        rows = self.store.db.execute(
            "SELECT event_id, source_locator FROM event WHERE producer='agy' AND event_type='steps.row'"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        table, decoded = adapter.decode_row(self.store.raw_for(rows[0]["event_id"]))
        self.assertEqual(table, "steps")
        self.assertEqual(
            list(decoded),
            [
                "idx",
                "step_type",
                "status",
                "has_subtrajectory",
                "metadata",
                "error_details",
                "permissions",
                "task_details",
                "render_info",
                "step_payload",
                "step_format",
            ],
        )
        source = sqlite3.connect(
            self.session.db_path.resolve().as_uri() + "?mode=ro", uri=True
        )
        source.row_factory = sqlite3.Row
        original = dict(source.execute("SELECT * FROM steps WHERE idx=7").fetchone())
        source.close()
        self.assertEqual(decoded, original)
        self.assertIn("sha256:", rows[0]["source_locator"])
        self.assertIn(
            "synthetic prompt searchable",
            s1_search.project(self.store.raw_for(rows[0]["event_id"])),
        )

    def test_unchanged_rescan_creates_zero_events_and_changed_row_keeps_history(
        self,
    ) -> None:
        first = self.scan()
        original_events = self.store.stats()["events"]
        second = self.scan()
        self.assertGreater(first["created"], 0)
        self.assertEqual(second["created"], 0)
        self.assertEqual(self.store.stats()["events"], original_events)

        with sqlite3.connect(self.session.db_path) as con:
            con.execute("UPDATE steps SET status=4 WHERE idx=7")
        changed = self.scan()
        self.assertEqual(changed["created"], 1)
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM event WHERE event_type='steps.row'"
            ).fetchone()[0],
            2,
        )
        statuses = []
        for row in self.store.db.execute(
            "SELECT event_id FROM event WHERE event_type='steps.row' ORDER BY ingest_lsn"
        ):
            statuses.append(adapter.decode_row(self.store.raw_for(row[0]))[1]["status"])
        self.assertEqual(statuses, [3, 4])

    def test_wal_resident_rows_are_visible_without_immutable_mode(self) -> None:
        session_id = str(uuid.uuid4())
        db_path = self.roots["ide"] / f"{session_id}.db"
        self.create_db(db_path, wal=True)
        self.assertTrue(db_path.with_name(db_path.name + "-wal").exists())
        session = adapter.Session("ide", session_id, self.roots["ide"], db_path, None)
        with adapter.open_store_readonly(session) as reader:
            self.assertEqual(
                reader.execute("SELECT COUNT(*) FROM steps").fetchone()[0], 1
            )
        result = adapter.scan_session(self.store, session, batch="wal-test")
        self.assertEqual(result["created"], 7)

    def test_duplicate_uuid_across_stores_has_distinct_sources(self) -> None:
        other = self.make_session("acp", self.session_id)
        first = self.scan(store_filter="cli")
        self.assertEqual(first["created"], 7)
        result = adapter.scan_session(self.store, other, batch="duplicate-uuid")
        self.assertEqual(result["created"], 7)
        uris = {
            row[0]
            for row in self.store.db.execute(
                "SELECT DISTINCT source_uri FROM event WHERE producer='agy'"
            )
        }
        self.assertEqual(
            uris, {f"agy://cli/{self.session_id}", f"agy://acp/{self.session_id}"}
        )

    def test_dry_run_does_not_write_events_gaps_or_checkpoints(self) -> None:
        before = {
            "events": self.store.stats()["events"],
            "gaps": self.store.stats()["gaps"],
            "checkpoints": self.store.db.execute(
                "SELECT COUNT(*) FROM ingest_checkpoint"
            ).fetchone()[0],
        }
        result = self.scan(dry_run=True)
        after = {
            "events": self.store.stats()["events"],
            "gaps": self.store.stats()["gaps"],
            "checkpoints": self.store.db.execute(
                "SELECT COUNT(*) FROM ingest_checkpoint"
            ).fetchone()[0],
        }
        self.assertEqual(result["created"], 0)
        self.assertEqual(after, before)

    def test_corrupt_database_records_gap_and_failure(self) -> None:
        self.session.db_path.write_bytes(b"synthetic invalid sqlite")
        result = self.scan()
        self.assertGreaterEqual(result["gaps"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertGreaterEqual(self.store.stats()["gaps"], 1)

    def test_steps_shrink_records_gap_without_deleting_events(self) -> None:
        self.scan()
        event_count = self.store.stats()["events"]
        with sqlite3.connect(self.session.db_path) as con:
            con.execute("DELETE FROM steps WHERE idx=7")
        result = self.scan()
        self.assertGreaterEqual(result["gaps"], 1)
        self.assertEqual(self.store.stats()["events"], event_count)


class TestAgyAllowLists(AgyTestCase):
    def test_planted_token_file_next_to_store_is_never_opened(self) -> None:
        token_path = self.roots["acp"].parent / "acp_token.json"
        token_path.write_text('{"synthetic":"must-not-open"}', encoding="utf-8")
        original_open = Path.open
        original_builtin_open = builtins.open
        opened: list[Path] = []

        def tracked_open(path: Path, *args, **kwargs):
            opened.append(path)
            return original_open(path, *args, **kwargs)

        def tracked_builtin_open(file, *args, **kwargs):
            try:
                opened.append(Path(file))
            except TypeError:
                pass
            return original_builtin_open(file, *args, **kwargs)

        with (
            mock.patch.object(Path, "open", tracked_open),
            mock.patch.object(builtins, "open", tracked_builtin_open),
        ):
            self.scan()
        self.assertNotIn(token_path, opened)

    def test_brain_extension_size_and_sensitive_name_allow_list(self) -> None:
        brain = self.session.brain_root
        brain.mkdir(parents=True)
        (brain / "notes.md").write_bytes(b"synthetic brain note")
        (brain / "data.json").write_bytes(b'{"kind":"synthetic"}')
        (brain / "skip.bin").write_bytes(b"not allowed")
        (brain / "auth-notes.yaml").write_bytes(b"must not be read")
        (brain / "large.txt").write_bytes(b"x" * (adapter.MAX_BRAIN_FILE_BYTES + 1))
        result = self.scan()
        self.assertEqual(result["brain_files"], 2)
        self.assertGreaterEqual(result["gaps"], 1)
        locators = {
            row[0]
            for row in self.store.db.execute(
                "SELECT source_locator FROM event WHERE producer='agy'"
            )
        }
        self.assertTrue(any(value.startswith("brain:notes.md:") for value in locators))
        self.assertFalse(
            any("skip.bin" in value or "auth-notes" in value for value in locators)
        )


class TestProtobufProjection(unittest.TestCase):
    def test_wire_extraction_nested_invalid_utf8_and_fixed_fields(self) -> None:
        parsed, strings = adapter.extract_protobuf_text(make_proto())
        self.assertTrue(parsed)
        self.assertIn("synthetic prompt searchable", strings)
        self.assertIn("synthetic tool output", strings)
        self.assertFalse(any("\ufffd" in text for text in strings))
        self.assertTrue(adapter.looks_like_protobuf(make_proto()))
        self.assertFalse(adapter.looks_like_protobuf(b"\xff\xff"))

    def test_indexer_uses_projection_instead_of_base64_hash_noise(self) -> None:
        proto = make_proto()
        columns = ["payload"]
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE sample(payload BLOB)")
        con.execute("INSERT INTO sample VALUES(?)", (proto,))
        row = con.execute("SELECT * FROM sample").fetchone()
        raw = adapter.encode_row("sample", columns, row, "synthetic searchable phrase")
        projected = s1_search.project(raw)
        self.assertEqual(projected, "synthetic searchable phrase")
        self.assertNotIn("base64", projected)

        large_row = sqlite3.connect(":memory:")
        large_row.row_factory = sqlite3.Row
        large_row.execute("CREATE TABLE sample(payload BLOB)")
        large_row.execute("INSERT INTO sample VALUES(?)", (b"x" * 30_000,))
        large_raw = adapter.encode_row(
            "sample",
            columns,
            large_row.execute("SELECT * FROM sample").fetchone(),
            "synthetic projection beyond the search window",
        )
        self.assertGreater(len(large_raw), s1_search.PROJECTION_CHARS * 2)
        self.assertEqual(
            s1_search.project(large_raw),
            "synthetic projection beyond the search window",
        )


if __name__ == "__main__":
    unittest.main()
