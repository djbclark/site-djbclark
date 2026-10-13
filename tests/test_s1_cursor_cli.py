#!/usr/bin/env python3
"""Synthetic tests for the Cursor CLI S1 adapter; no real transcript text."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import s1_cursor_cli as adapter
import s1_evidence as s1


class CursorCliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = s1.EvidenceStore(self.root / "s1.sqlite3", self.root / "cas")
        self.chats = self.root / "chats"
        self.acp = self.root / "acp-sessions"
        self.config = self.root / "config-chats"
        self.chats.mkdir()
        self.acp.mkdir()
        self.config.mkdir()
        self.session_id = str(uuid.uuid4())
        self.session = self.make_session(self.chats, self.session_id, "chats")

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def make_session(self, root: Path, session_id: str, layout: str) -> adapter.Session:
        if layout in ("chats", "config-chats"):
            bucket = hashlib.md5(
                b"/workspace/project", usedforsecurity=False
            ).hexdigest()
            directory = root / bucket / session_id
        else:
            directory = root / session_id
        directory.mkdir(parents=True, exist_ok=True)
        return adapter.Session(session_id, directory, layout)

    def create_db(self, session: adapter.Session, *, meta: str = "hex") -> None:
        con = sqlite3.connect(session.store)
        con.executescript(
            "CREATE TABLE blobs(id TEXT PRIMARY KEY, data BLOB); CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);"
        )
        value = json.dumps(
            {"agentId": "fixture", "latestRootBlobId": "root"}, separators=(",", ":")
        )
        if meta == "hex":
            value = value.encode().hex()
        con.execute("INSERT INTO meta(key,value) VALUES('0',?)", (value,))
        con.commit()
        con.close()
        (session.directory / "meta.json").write_text(
            '{"schemaVersion":1}', encoding="utf-8"
        )
        (session.directory / "prompt_history.json").write_text(
            '["synthetic prompt"]', encoding="utf-8"
        )

    def add_blob(self, session: adapter.Session, payload: bytes) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        con = sqlite3.connect(session.store)
        con.execute("INSERT INTO blobs(id,data) VALUES(?,?)", (digest, payload))
        con.commit()
        con.close()
        return digest

    def run_scan(self, **kw):
        return adapter.scan(
            self.store,
            chats=self.chats,
            acp_sessions=self.acp,
            config_chats=self.config,
            batch="test",
            **kw,
        )


class TestCursorIngest(CursorCliTestCase):
    def test_json_tool_call_result_protobuf_and_unparsed_are_preserved(self) -> None:
        self.create_db(self.session)
        user = json.dumps(
            {"role": "user", "content": "fixture", "createdAt": 1787500000000}
        ).encode()
        call = json.dumps(
            {
                "role": "assistant",
                "content": [{"type": "tool-call", "toolName": "FakeTool", "args": {}}],
            }
        ).encode()
        result = json.dumps(
            {
                "role": "tool",
                "content": [
                    {
                        "type": "tool-result",
                        "toolCallId": "call-1",
                        "toolName": "FakeTool",
                        "result": "ok",
                        "isError": False,
                    }
                ],
            }
        ).encode()
        proto = b"\x22\x03abc"  # valid generic protobuf field 4, length-delimited
        malformed = b"\xff\xff"
        ids = [
            self.add_blob(self.session, raw)
            for raw in (user, call, result, proto, malformed)
        ]
        totals = self.run_scan()
        self.assertEqual(
            (
                totals["blobs_read"],
                totals["json_parsed"],
                totals["graph_raw"],
                totals["unparsed"],
            ),
            (5, 3, 1, 1),
        )
        self.assertEqual(
            self.store.stats()["events"], 8
        )  # five blobs + three metadata values
        call_row = self.store.db.execute(
            "SELECT * FROM event WHERE tool_name='FakeTool' AND event_type='tool_call'"
        ).fetchone()
        self.assertEqual(call_row["tool_call_id"], f"{self.session_id}:2:0:FakeTool")
        result_row = self.store.db.execute(
            "SELECT * FROM event WHERE event_type='tool_result'"
        ).fetchone()
        self.assertEqual(result_row["tool_call_id"], "call-1")
        self.assertEqual(result_row["source_seq"], 3)
        for digest in ids:
            row = self.store.db.execute(
                "SELECT event_id FROM event WHERE raw_sha256=?", (digest,)
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(
                hashlib.sha256(self.store.raw_for(row["event_id"])).hexdigest(), digest
            )
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM event WHERE event_type='unknown'"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM event WHERE sensitivity='sensitive'"
            ).fetchone()[0],
            8,
        )

    def test_plain_json_meta_row_is_ingested(self) -> None:
        self.create_db(self.session, meta="plain")
        self.add_blob(self.session, b'{"role":"user","content":"fixture"}')
        self.run_scan()
        raw = json.dumps(
            {"agentId": "fixture", "latestRootBlobId": "root"}, separators=(",", ":")
        ).encode()
        self.assertIsNotNone(
            self.store.db.execute(
                "SELECT 1 FROM event WHERE raw_sha256=?",
                (hashlib.sha256(raw).hexdigest(),),
            ).fetchone()
        )

    def test_json_object_without_message_role_is_preserved_as_unknown(self) -> None:
        self.create_db(self.session)
        self.add_blob(self.session, b'{"fixtureField":"synthetic"}')
        result = self.run_scan()
        row = self.store.db.execute(
            "SELECT role,event_type FROM event WHERE event_type='unknown'"
        ).fetchone()
        self.assertEqual((row["role"], row["event_type"]), ("unknown", "unknown"))
        self.assertEqual(result["json_parsed"], 1)

    def test_rerun_is_idempotent(self) -> None:
        self.create_db(self.session)
        self.add_blob(self.session, b'{"role":"user","content":"fixture"}')
        first = self.run_scan()
        count = self.store.stats()["events"]
        second = self.run_scan()
        self.assertEqual(first["created"], 4)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["blobs_read"], 0)
        self.assertEqual(self.store.stats()["events"], count)

    def test_resume_after_appended_blob_reads_only_new_row(self) -> None:
        self.create_db(self.session)
        self.add_blob(self.session, b'{"role":"user","content":"one"}')
        self.run_scan()
        self.add_blob(self.session, b'{"role":"assistant","content":"two"}')
        result = self.run_scan()
        self.assertEqual(result["blobs_read"], 1)
        self.assertEqual(result["created"], 1)

    def test_hex_and_plain_json_meta_rows_both_ingest(self) -> None:
        self.create_db(self.session, meta="hex")
        other_id = str(uuid.uuid4())
        other = self.make_session(self.acp, other_id, "acp-sessions")
        self.create_db(other, meta="plain")
        self.run_scan()
        values = list(
            self.store.db.execute(
                "SELECT raw_sha256 FROM event WHERE event_type='session_meta_row'"
            )
        )
        self.assertEqual(len(values), 2)

    def test_corrupt_store_records_gap_and_does_not_crash(self) -> None:
        (self.session.directory / "store.db").write_bytes(b"not sqlite")
        result = self.run_scan()
        self.assertGreaterEqual(result["gaps"], 1)
        self.assertTrue(result["failed"])
        self.assertGreaterEqual(self.store.stats()["gaps"], 1)

    def test_empty_session_directory_is_not_a_missing_source(self) -> None:
        result = self.run_scan()
        self.assertEqual(result["sessions"], 0)
        self.assertEqual(result["gaps"], 0)

    def test_wal_is_read_without_immutable_mode(self) -> None:
        con = sqlite3.connect(self.session.store)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA wal_autocheckpoint=0")
        con.executescript(
            "CREATE TABLE blobs(id TEXT PRIMARY KEY, data BLOB); CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);"
        )
        con.execute("INSERT INTO meta(key,value) VALUES('0','{}')")
        raw = b'{"role":"user","content":"wal fixture"}'
        con.execute(
            "INSERT INTO blobs(id,data) VALUES(?,?)",
            (hashlib.sha256(raw).hexdigest(), raw),
        )
        con.commit()
        self.assertTrue(self.session.store.with_name("store.db-wal").exists())
        with adapter.open_store_readonly(self.session) as reader:
            self.assertEqual(
                reader.execute("SELECT COUNT(*) FROM blobs").fetchone()[0], 1
            )
        con.close()
        result = adapter.scan_session(self.store, self.session, batch="wal-test")
        self.assertEqual(result["blobs_read"], 1)

    def test_allow_list_refuses_auth_and_token_siblings(self) -> None:
        self.create_db(self.session)
        for name in ("auth.json", "token.txt", "credentials.toml"):
            (self.session.directory / name).write_text(
                "fixture-only-sentinel", encoding="utf-8"
            )
            with self.assertRaises(PermissionError):
                adapter.read_allowed_file(self.session, name)
        self.add_blob(self.session, b'{"role":"user","content":"fixture"}')
        result = self.run_scan()
        self.assertEqual(self.store.stats()["events"], 4)
        self.assertEqual(result["created"], 4)

    def test_symlinked_store_is_refused(self) -> None:
        self.create_db(self.session)
        alternate = self.root / "outside.db"
        alternate.write_bytes(self.session.store.read_bytes())
        self.session.store.unlink()
        self.session.store.symlink_to(alternate)
        with (
            self.assertRaises(PermissionError),
            adapter.open_store_readonly(self.session),
        ):
            pass

    def test_missing_previously_checkpointed_source_records_gap(self) -> None:
        self.create_db(self.session)
        self.add_blob(self.session, b'{"role":"user","content":"fixture"}')
        self.run_scan()
        self.session.store.unlink()
        result = self.run_scan()
        self.assertGreaterEqual(result["gaps"], 1)
        self.assertGreaterEqual(self.store.stats()["gaps"], 1)

    def test_duplicate_session_copies_do_not_fight_or_fail(self) -> None:
        """One UUID in several buckets: each real store keeps its own checkpoint,
        and an emptied leftover copy is not a missing store."""
        other = self.chats / hashlib.md5(b"/workspace/other", usedforsecurity=False).hexdigest()
        copy = adapter.Session(self.session_id, other / self.session_id, "chats")
        copy.directory.mkdir(parents=True)
        empty_bucket = self.chats / hashlib.md5(b"/workspace/gone", usedforsecurity=False).hexdigest()
        leftover = empty_bucket / self.session_id
        leftover.mkdir(parents=True)
        (leftover / "prompt_history.json").write_text('["old"]', encoding="utf-8")
        self.create_db(self.session)
        self.create_db(copy)
        self.add_blob(self.session, b'{"role":"user","content":"first copy"}')
        self.add_blob(copy, b'{"role":"user","content":"second copy"}')
        self.add_blob(copy, b'{"role":"assistant","content":"second copy more"}')
        first = self.run_scan()
        self.assertFalse(first["failed"])
        second = self.run_scan()
        self.assertFalse(second["failed"])
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["gaps"], 0)
        uris = {
            row[0]
            for row in self.store.db.execute(
                "SELECT DISTINCT source_uri FROM event WHERE producer='cursor-cli'"
            )
        }
        self.assertGreaterEqual(len(uris), 2)

    def test_store_shrink_records_gap_and_rescans(self) -> None:
        self.create_db(self.session)
        self.add_blob(self.session, b'{"role":"user","content":"one"}')
        self.add_blob(self.session, b'{"role":"assistant","content":"two"}')
        self.run_scan()
        con = sqlite3.connect(self.session.store)
        con.execute("DELETE FROM blobs WHERE rowid=2")
        con.commit()
        con.execute("VACUUM")
        con.close()
        result = self.run_scan()
        self.assertGreaterEqual(result["gaps"], 1)
        self.assertEqual(result["blobs_read"], 1)


if __name__ == "__main__":
    unittest.main()
