#!/usr/bin/env python3
"""Tests for S1 retrieval: fts, trigram, neighbours, and incremental indexing."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import hindsight_s1 as s1  # noqa: E402
import hindsight_s1_search as search  # noqa: E402


class SearchTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.store = s1.EvidenceStore(root / "s1.sqlite3", root / "cas")
        self.index = search.SearchIndex(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def add(self, text: str, *, locator: str | None = None, seq: int | None = None,
            conversation: str | None = None, json_payload: bool = True, **kw):
        raw = (json.dumps({"content": text}).encode() if json_payload
               else text.encode())
        n = seq if seq is not None else self.store.stats()["events"]
        params = dict(
            producer="claude-code", source_uri="file:///t.jsonl",
            source_locator=locator or f"l{n}#{n}", raw=raw,
            ts_utc=f"2026-08-23T20:00:{n:02d}Z", role="user", origin="human",
            source_seq=n,
        )
        params.update(kw)
        eid, _ = self.store.put_event(**params)
        if conversation:
            self.store.assign_conversation(eid, conversation)
        return eid


class TestProjection(SearchTestCase):
    def test_json_is_flattened_to_values(self) -> None:
        body = search.project(json.dumps({"role": "user", "content": "needle here"}).encode())
        self.assertIn("needle here", body)
        self.assertNotIn("content", body, "JSON keys should not be indexed as content")

    def test_non_json_falls_back_to_text(self) -> None:
        self.assertIn("plain text", search.project(b"plain text payload"))

    def test_projection_is_bounded(self) -> None:
        body = search.project(json.dumps({"c": "x" * 50000}).encode())
        self.assertLessEqual(len(body), search.PROJECTION_CHARS)

    def test_malformed_payload_does_not_raise(self) -> None:
        self.assertIsInstance(search.project(b"\xff\xfe not json"), str)


class TestIndexing(SearchTestCase):
    def test_indexes_pending_events(self) -> None:
        self.add("alpha")
        self.add("beta")
        self.assertEqual(self.index.pending(), 2)
        r = self.index.build()
        self.assertEqual(r["indexed"], 2)
        self.assertEqual(self.index.pending(), 0)

    def test_is_incremental_and_resumable(self) -> None:
        self.add("first")
        self.index.build()
        self.add("second")
        r = self.index.build()
        self.assertEqual(r["indexed"], 1, "only the new event should be indexed")

    def test_limit_leaves_remainder_pending(self) -> None:
        for i in range(5):
            self.add(f"item{i}")
        r = self.index.build(limit=2)
        self.assertEqual(r["indexed"], 2)
        self.assertEqual(r["remaining"], 3)

    def test_missing_cas_object_is_counted_not_fatal(self) -> None:
        eid = self.add("vanishing")
        digest = self.store.get_event(eid)["raw_sha256"]
        self.store.cas_path(digest).unlink()
        r = self.index.build()
        self.assertEqual(r["cas_missing"], 1)
        self.assertEqual(r["indexed"], 0)


class TestSearchModes(SearchTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.add("the quick brown fox jumps")
        self.add("deploy_ops_release.py handles memory sync")
        self.add("completely unrelated content")
        self.index.build()

    def test_fts_finds_words(self) -> None:
        hits = self.index.search("brown", mode="fts")
        self.assertEqual(len(hits), 1)

    def test_fts_finds_phrases(self) -> None:
        self.assertEqual(len(self.index.search('"memory sync"', mode="fts")), 1)

    def test_trigram_finds_substring_inside_a_token(self) -> None:
        # 'ops_release' sits inside a filename; word tokenisers miss it
        hits = self.index.search("ops_release", mode="trigram")
        self.assertGreaterEqual(len(hits), 1)

    def test_trigram_handles_punctuation_without_syntax_error(self) -> None:
        self.index.search("deploy_ops_release.py", mode="trigram")  # must not raise

    def test_exact_mode_still_scans_bytes(self) -> None:
        self.assertEqual(len(self.index.search("brown", mode="exact")), 1)

    def test_no_match_returns_empty(self) -> None:
        self.assertEqual(self.index.search("zzzznotpresent", mode="fts"), [])

    def test_bad_mode_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.index.search("x", mode="semantic")

    def test_limit_is_honoured(self) -> None:
        for i in range(10):
            self.add(f"repeated needle {i}", locator=f"extra{i}", seq=100 + i)
        self.index.build()
        self.assertEqual(len(self.index.search("needle", mode="fts", limit=3)), 3)


class TestNeighbours(SearchTestCase):
    def test_returns_surrounding_turns_in_order(self) -> None:
        ids = [self.add(f"turn {i}", seq=i, conversation="conv-1") for i in range(7)]
        rows = self.index.neighbours(ids[3], window=2)
        self.assertEqual([r["event_id"] for r in rows], ids[1:6])

    def test_window_clamps_at_conversation_start(self) -> None:
        ids = [self.add(f"turn {i}", seq=i, conversation="conv-2") for i in range(4)]
        rows = self.index.neighbours(ids[0], window=3)
        self.assertEqual(rows[0]["event_id"], ids[0])
        self.assertLessEqual(len(rows), 4)

    def test_falls_back_to_session_when_unassigned(self) -> None:
        a = self.add("lonely one", seq=0, producer_session_id="sess-x")
        self.add("lonely two", seq=1, producer_session_id="sess-x")
        rows = self.index.neighbours(a, window=2)
        self.assertGreaterEqual(len(rows), 2, "should fall back to the session")

    def test_unknown_event_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.index.neighbours("nope")


class TestStats(SearchTestCase):
    def test_stats_track_progress(self) -> None:
        self.add("one")
        self.add("two")
        self.index.build(limit=1)
        st = self.index.stats()
        self.assertEqual(st["events"], 2)
        self.assertEqual(st["indexed"], 1)
        self.assertEqual(st["pending"], 1)


if __name__ == "__main__":
    unittest.main()
