"""Synthetic Cursor project transcript tests; no real transcript text."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import s1_cursor_transcripts as adapter
import s1_evidence as s1


class CursorTranscriptTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "projects"
        self.root.mkdir()
        self.store = s1.EvidenceStore(
            Path(self.temp.name) / "s1.db", Path(self.temp.name) / "cas"
        )
        self.session_id = str(uuid.uuid4())
        self.path = self.make_transcript("project-fixture", self.session_id)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def make_transcript(self, project: str, session_id: str) -> Path:
        directory = self.root / project / "agent-transcripts" / session_id
        directory.mkdir(parents=True)
        return directory / f"{session_id}.jsonl"

    @staticmethod
    def line(role: str, text: str) -> bytes:
        return (json.dumps({"role": role, "message": {"content": text}}) + "\n").encode(
            "utf-8"
        )

    def scan(self, **kwargs):
        return adapter.scan(
            self.store, root=self.root, batch="cursor-transcript-test", **kwargs
        )

    def test_exact_bytes_idempotency_and_sensitivity(self) -> None:
        first_line = self.line("user", "synthetic user text")
        second_line = self.line("assistant", "synthetic assistant text")
        self.path.write_bytes(first_line + second_line)

        first = self.scan()
        second = self.scan()

        self.assertEqual((first["read"], first["created"]), (2, 2))
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["read"], 0)
        rows = list(
            self.store.db.execute(
                "SELECT event_id,role,sensitivity FROM event WHERE producer=? ORDER BY source_seq",
                (adapter.PRODUCER,),
            )
        )
        self.assertEqual([row["role"] for row in rows], ["user", "assistant"])
        self.assertEqual({row["sensitivity"] for row in rows}, {"sensitive"})
        self.assertEqual(
            [self.store.raw_for(row["event_id"]) for row in rows],
            [first_line, second_line],
        )

    def test_partial_tail_is_deferred_then_resumed(self) -> None:
        complete = self.line("user", "synthetic complete")
        partial = b'{"role":"assistant","message":{"content":"synthetic partial"}'
        self.path.write_bytes(complete + partial)

        first = adapter.ingest_file(
            self.store, self.path, root=self.root, batch="first"
        )
        self.assertEqual((first["read"], first["created"]), (1, 1))
        self.path.write_bytes(
            complete + partial + b"}\n" + self.line("assistant", "synthetic next")
        )
        second = adapter.ingest_file(
            self.store, self.path, root=self.root, batch="second"
        )
        self.assertEqual((second["read"], second["created"]), (2, 2))
        self.assertEqual(self.store.stats()["events"], 3)

    def test_shrunk_source_records_gap_and_keeps_prior_events(self) -> None:
        self.path.write_bytes(
            self.line("user", "synthetic original one")
            + self.line("assistant", "synthetic original two")
        )
        self.scan()
        prior_events = self.store.stats()["events"]
        self.path.write_bytes(self.line("user", "synthetic replacement"))

        result = self.scan()

        self.assertEqual(result["created"], 1)
        self.assertGreaterEqual(result["gaps"], 1)
        self.assertEqual(self.store.stats()["events"], prior_events + 1)

    def test_dry_run_does_not_write_events_gaps_or_checkpoints(self) -> None:
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

    def test_allow_list_excludes_neighboring_project_state_and_symlinks(self) -> None:
        self.path.write_bytes(self.line("user", "synthetic allowed"))
        project = self.root / "project-fixture"
        (project / "worker.log").write_text("sentinel", encoding="utf-8")
        (project / "mcp-auth.json").write_text("sentinel", encoding="utf-8")
        outside = Path(self.temp.name) / "outside.jsonl"
        outside.write_bytes(self.line("user", "synthetic outside"))
        linked_session = str(uuid.uuid4())
        linked = project / "agent-transcripts" / linked_session
        linked.mkdir()
        (linked / f"{linked_session}.jsonl").symlink_to(outside)

        self.assertEqual(adapter.transcript_paths(self.root), [self.path])
        result = self.scan()
        self.assertEqual(result["created"], 1)

    def test_malformed_complete_line_is_preserved_and_counted(self) -> None:
        raw = b"{synthetic-invalid-json\n"
        self.path.write_bytes(raw)

        result = self.scan()

        self.assertEqual((result["created"], result["unparsed"]), (1, 1))
        row = self.store.db.execute("SELECT event_id FROM event").fetchone()
        self.assertEqual(self.store.raw_for(row["event_id"]), raw)

    def test_same_uuid_in_another_project_has_distinct_source_identity(self) -> None:
        duplicate = self.make_transcript("other-project", self.session_id)
        self.path.write_bytes(self.line("user", "synthetic first project"))
        duplicate.write_bytes(self.line("user", "synthetic other project"))

        result = self.scan()

        self.assertEqual(result["created"], 2)
        uris = {
            row[0]
            for row in self.store.db.execute(
                "SELECT DISTINCT source_uri FROM event WHERE producer=?",
                (adapter.PRODUCER,),
            )
        }
        self.assertEqual(len(uris), 2)

    def test_vanished_previously_captured_transcript_records_gap(self) -> None:
        self.path.write_bytes(self.line("user", "synthetic retained"))
        self.scan()
        self.path.unlink()

        result = self.scan()

        self.assertGreaterEqual(result["gaps"], 1)
        self.assertEqual(self.store.stats()["events"], 1)


if __name__ == "__main__":
    unittest.main()
