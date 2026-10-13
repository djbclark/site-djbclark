"""Synthetic Qwen S1 adapter tests; no real chat content or stores."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import s1_evidence as s1
import s1_qwen as adapter


class QwenTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "projects"
        self.chats = self.root / "project-fixture" / "chats"
        self.chats.mkdir(parents=True)
        self.path = self.chats / "chat-fixture.jsonl"
        self.runtime = self.chats / "chat-fixture.runtime.json"
        self.store = s1.EvidenceStore(
            Path(self.temp.name) / "s1.db", Path(self.temp.name) / "cas"
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def scan(self, **kwargs):
        return adapter.scan(self.store, root=self.root, batch="qwen-test", **kwargs)

    @staticmethod
    def line(kind: str, text: str) -> bytes:
        return (
            json.dumps({"type": kind, "session_id": "session-fixture", "text": text})
            + "\n"
        ).encode()

    def test_exact_jsonl_and_runtime_bytes_and_idempotent_scan(self) -> None:
        lines = self.line("user", "synthetic qwen prompt") + self.line(
            "assistant", "synthetic qwen answer"
        )
        runtime = b'{"state":"synthetic runtime"}\n'
        self.path.write_bytes(lines)
        self.runtime.write_bytes(runtime)

        first = self.scan()
        self.assertEqual(first["created"], 3)
        second = self.scan()
        self.assertEqual(second["created"], 0)
        events = list(
            self.store.db.execute(
                "SELECT event_id, event_type FROM event WHERE producer='qwen'"
            )
        )
        chat_raw = [
            self.store.raw_for(row["event_id"])
            for row in events
            if row["event_type"] in {"user", "assistant"}
        ]
        self.assertEqual(
            chat_raw,
            [lines.splitlines(keepends=True)[0], lines.splitlines(keepends=True)[1]],
        )
        runtime_row = next(
            row for row in events if row["event_type"] == "runtime_snapshot"
        )
        self.assertEqual(self.store.raw_for(runtime_row["event_id"]), runtime)

    def test_partial_tail_then_append_and_checkpoint_resume(self) -> None:
        complete = self.line("user", "synthetic first")
        partial = b'{"type":"assistant","text":"synthetic partial"'
        self.path.write_bytes(complete + partial)
        first = adapter.ingest_chat(self.store, self.path, root=self.root, batch="one")
        self.assertEqual((first["read"], first["created"]), (1, 1))
        self.path.write_bytes(
            complete + partial + b"}\n" + self.line("assistant", "synthetic next")
        )
        second = adapter.ingest_chat(self.store, self.path, root=self.root, batch="two")
        self.assertEqual((second["read"], second["created"]), (2, 2))
        self.assertEqual(self.store.stats()["events"], 3)

    def test_shrink_records_gap_and_rescues_rewritten_content_without_deleting_old(
        self,
    ) -> None:
        self.path.write_bytes(
            self.line("user", "synthetic original one")
            + self.line("assistant", "synthetic original two")
        )
        self.scan()
        old_events = self.store.stats()["events"]
        self.path.write_bytes(self.line("user", "synthetic replacement"))
        result = self.scan()
        self.assertEqual(result["created"], 1)
        self.assertGreaterEqual(result["gaps"], 1)
        self.assertEqual(self.store.stats()["events"], old_events + 1)

    def test_runtime_rewrite_is_a_new_hash_addressed_event(self) -> None:
        self.path.write_bytes(self.line("user", "synthetic content"))
        self.runtime.write_bytes(b'{"state":"first synthetic"}')
        self.scan()
        self.runtime.write_bytes(b'{"state":"second synthetic"}')
        result = self.scan()
        self.assertEqual(result["created"], 1)
        rows = list(
            self.store.db.execute(
                "SELECT event_id FROM event WHERE event_type='runtime_snapshot'"
            )
        )
        self.assertEqual(len(rows), 2)

    def test_missing_previously_captured_runtime_records_gap(self) -> None:
        self.path.write_bytes(self.line("user", "synthetic content"))
        self.runtime.write_bytes(b'{"state":"synthetic runtime"}')
        self.scan()
        self.runtime.unlink()
        result = self.scan()
        self.assertGreaterEqual(result["gaps"], 1)

    def test_dry_run_changes_no_store_state(self) -> None:
        self.path.write_bytes(self.line("user", "synthetic dry run"))
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

    def test_strict_allow_list_ignores_settings_and_symlinked_chat(self) -> None:
        self.path.write_bytes(self.line("user", "synthetic allowed"))
        (self.root / "settings.json").write_text('{"synthetic":"not an input"}')
        outside = Path(self.temp.name) / "outside.jsonl"
        outside.write_bytes(self.line("user", "synthetic forbidden"))
        link = self.chats / "linked.jsonl"
        link.symlink_to(outside)
        self.assertEqual(adapter.chat_paths(self.root), [self.path])
        self.assertEqual(self.scan()["created"], 1)

    def test_malformed_complete_json_is_preserved_and_counted(self) -> None:
        self.path.write_bytes(b"{not valid json\n")
        result = self.scan()
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["unparsed"], 1)
        row = self.store.db.execute("SELECT event_id FROM event").fetchone()
        self.assertEqual(self.store.raw_for(row["event_id"]), b"{not valid json\n")


if __name__ == "__main__":
    unittest.main()
