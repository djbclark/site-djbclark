#!/usr/bin/env python3
"""Tests for S1 retrieval: fts, trigram, neighbours, and incremental indexing."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import s1_evidence as s1  # noqa: E402
import s1_search as search  # noqa: E402


class SearchTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.store = s1.EvidenceStore(root / "s1.sqlite3", root / "cas")
        self.index = search.SearchIndex(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def add(
        self,
        text: str,
        *,
        locator: str | None = None,
        seq: int | None = None,
        conversation: str | None = None,
        json_payload: bool = True,
        **kw,
    ):
        raw = json.dumps({"content": text}).encode() if json_payload else text.encode()
        n = seq if seq is not None else self.store.stats()["events"]
        params = dict(
            producer="claude-code",
            source_uri="file:///t.jsonl",
            source_locator=locator or f"l{n}#{n}",
            raw=raw,
            ts_utc=f"2026-08-23T20:00:{n:02d}Z",
            role="user",
            origin="human",
            source_seq=n,
        )
        params.update(kw)
        eid, _ = self.store.put_event(**params)
        if conversation:
            self.store.assign_conversation(eid, conversation)
        return eid


class TestProjection(SearchTestCase):
    def test_json_is_flattened_to_values(self) -> None:
        body = search.project(
            json.dumps({"role": "user", "content": "needle here"}).encode()
        )
        self.assertIn("needle here", body)
        self.assertNotIn("content", body, "JSON keys should not be indexed as content")

    def test_non_json_falls_back_to_text(self) -> None:
        self.assertIn("plain text", search.project(b"plain text payload"))

    def test_projection_is_bounded(self) -> None:
        body = search.project(json.dumps({"c": "x" * 50000}).encode())
        self.assertLessEqual(len(body), search.PROJECTION_CHARS)

    def test_noncharacters_become_replacement_character(self) -> None:
        body = search.project(json.dumps({"c": "a￾b￿c"}).encode())
        self.assertEqual(body, "a�b�c")

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
        self.store.pack_db.execute(
            "DELETE FROM obj WHERE sha=?", (bytes.fromhex(digest),)
        )
        self.store.pack_db.commit()
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


class TestTrigramLiterals(SearchTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.add("deploy ops_release now")
        self.add("deploy opsXrelease now")
        self.add("save 50% today")
        self.add("save 50x today")
        self.add("au café noir")
        self.add("AU CAFÉ NOIR")
        self.add("plain cafe here")
        self.index.build()

    def bodies(self, query: str) -> set[str]:
        return {
            json.loads(self.store.raw_for(r["event_id"]))["content"]
            for r in self.index.search(query, mode="trigram")
        }

    def test_underscore_is_literal(self) -> None:
        self.assertEqual(self.bodies("ops_rel"), {"deploy ops_release now"})

    def test_percent_is_literal(self) -> None:
        self.assertEqual(self.bodies("50%"), {"save 50% today"})

    def test_non_ascii_case_folds(self) -> None:
        both = {"au café noir", "AU CAFÉ NOIR"}
        self.assertEqual(self.bodies("CAFÉ"), both)
        self.assertEqual(self.bodies("café"), both)
        self.assertEqual(self.bodies("Café N"), both)

    def test_ascii_case_folds(self) -> None:
        self.assertEqual(self.bodies("OPS_RELEASE"), {"deploy ops_release now"})

    def test_short_queries_find_nothing(self) -> None:
        for query in ("", "a", "50", "%%", "__"):
            self.assertEqual(self.index.search(query, mode="trigram"), [], query)

    def test_snippet_present(self) -> None:
        hits = self.index.search("ops_release", mode="trigram")
        self.assertIn("[", hits[0]["snip"])


class TestExternalContent(SearchTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.ids = [
            self.add("original wording alpha"),
            self.add("original wording beta"),
        ]
        self.index.build()

    def test_fresh_store_is_current_layout_and_consistent(self) -> None:
        st = self.index.stats(check=True)
        self.assertEqual(st["search_layout"], search.SEARCH_LAYOUT)
        self.assertEqual(st["text_rows"], 2)
        self.assertTrue(st["healthy"], st)

    def test_reindex_replaces_text_and_index_entries(self) -> None:
        with (
            mock.patch.object(search, "INDEX_VERSION", search.INDEX_VERSION + 1),
            mock.patch.object(
                search, "project", lambda payload: "rewritten zebra " + payload.decode()
            ),
        ):
            self.assertEqual(self.index.pending(), 2)
            self.assertEqual(self.index.build()["indexed"], 2)
            self.assertEqual(
                self.index.stats(check=True)["integrity_check"],
                {"event_fts": "ok", "event_trigram": "ok"},
            )
        self.assertEqual(self.index.stats()["text_rows"], 2)
        self.assertEqual(len(self.index.search("zebra", mode="fts")), 2)
        self.assertEqual(len(self.index.search("rewritten zeb", mode="trigram")), 2)
        # A second re-index drops every earlier word; any hit on one would be
        # a stale index entry that the 'delete' command failed to remove.
        with (
            mock.patch.object(search, "INDEX_VERSION", search.INDEX_VERSION + 2),
            mock.patch.object(search, "project", lambda payload: "only giraffe"),
        ):
            self.index.build()
            self.assertEqual(self.index.search("zebra", mode="fts"), [])
            self.assertEqual(self.index.search("wording", mode="fts"), [])
            self.assertEqual(self.index.search("ebra", mode="trigram"), [])
            self.assertEqual(len(self.index.search("giraffe", mode="fts")), 2)
            self.assertTrue(self.index.stats(check=True)["healthy"])

    def test_check_detects_text_changed_behind_the_index(self) -> None:
        self.store.db.execute(
            "UPDATE event_text SET body='something else' WHERE event_id=?",
            (self.ids[0],),
        )
        self.store.db.commit()
        st = self.index.stats(check=True)
        self.assertFalse(st["healthy"])
        self.assertNotEqual(st["integrity_check"]["event_fts"], "ok")


OLD_LAYOUT_DDL = """
CREATE VIRTUAL TABLE event_fts USING fts5(event_id UNINDEXED, body, tokenize='unicode61');
CREATE VIRTUAL TABLE event_trigram USING fts5(event_id UNINDEXED, body, tokenize='trigram');
CREATE TABLE search_indexed (
  event_id   TEXT PRIMARY KEY REFERENCES event(event_id) ON DELETE CASCADE,
  indexed_at TEXT NOT NULL,
  version    INTEGER NOT NULL
);
"""


class TestMigration(unittest.TestCase):
    """A layout-1 store, written the way the old build() wrote it."""

    TEXTS = [
        "the quick brown fox",
        "deploy_ops_release.py syncs memory",
        "AU CAFÉ NOIR",
        "unrelated words here",
        "odd￿byte",
    ]

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.db_path, self.cas = root / "s1.sqlite3", root / "cas"
        self.store = s1.EvidenceStore(self.db_path, self.cas)
        self.store.db.executescript(OLD_LAYOUT_DDL)
        self.ids = []
        for n, text in enumerate(self.TEXTS):
            eid, _ = self.store.put_event(
                producer="claude-code",
                source_uri="file:///t.jsonl",
                source_locator=f"l{n}",
                raw=json.dumps({"content": text}).encode(),
                ts_utc=f"2026-08-23T20:00:{n:02d}Z",
                role="user",
                origin="human",
                source_seq=n,
            )
            self.ids.append(eid)
            # The old project() kept U+FFFF; reproduce what it stored.
            body = search._project(self.store.raw_for(eid))
            for table in ("event_fts", "event_trigram"):
                self.store.db.execute(
                    f"INSERT INTO {table} (event_id, body) VALUES (?,?)", (eid, body)
                )
            self.store.db.execute(
                "INSERT INTO search_indexed VALUES (?,?,1)", (eid, s1.now_iso())
            )
        self.store.db.commit()

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def cli(self, *args: str) -> int:
        with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            return search.main(
                ["--db", str(self.db_path), "--cas", str(self.cas), *args]
            )

    def test_old_layout_is_refused_not_mixed(self) -> None:
        self.assertEqual(search.store_layout(self.store.db), 1)
        with self.assertRaises(search.LayoutError):
            search.SearchIndex(self.store)
        self.assertIsNotNone(
            self.store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='event_fts_content'"
            ).fetchone()
        )
        self.assertIsNone(
            self.store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='event_text'"
            ).fetchone()
        )

    def test_migrate_keeps_results_and_is_idempotent(self) -> None:
        r = search.migrate_layout(self.store.db)
        self.assertTrue(r["migrated"])
        self.assertEqual(r["text_rows"], len(self.TEXTS))
        self.assertEqual(r["reset_indexed"], 0)
        self.assertEqual(r["noncharacters_replaced"], 1)
        self.assertEqual(
            self.store.db.execute(
                "SELECT body FROM event_text WHERE event_id=?", (self.ids[4],)
            ).fetchone()[0],
            "odd�byte",
            "migrated text must equal what project() now returns",
        )
        names = {
            row[0] for row in self.store.db.execute("SELECT name FROM sqlite_master")
        }
        self.assertNotIn("event_fts_content", names)
        self.assertNotIn("event_trigram_content", names)
        self.assertFalse(search.migrate_layout(self.store.db)["migrated"])

        index = search.SearchIndex(self.store)
        st = index.stats(check=True)
        self.assertTrue(st["healthy"], st)
        self.assertEqual((st["indexed"], st["pending"], st["text_rows"]), (5, 0, 5))
        self.assertEqual(
            [r["event_id"] for r in index.search("brown", mode="fts")], [self.ids[0]]
        )
        self.assertEqual(
            [r["event_id"] for r in index.search("ops_rel", mode="trigram")],
            [self.ids[1]],
        )
        self.assertEqual(
            [r["event_id"] for r in index.search("café", mode="trigram")], [self.ids[2]]
        )
        # New events after the migration go through the new write path.
        eid, _ = self.store.put_event(
            producer="claude-code",
            source_uri="file:///t.jsonl",
            source_locator="l9",
            raw=json.dumps({"content": "fresh brown bear"}).encode(),
            ts_utc="2026-08-23T20:00:09Z",
            role="user",
            origin="human",
            source_seq=9,
        )
        self.assertEqual(index.build()["indexed"], 1)
        self.assertEqual(len(index.search("brown", mode="fts")), 2)
        self.assertTrue(index.stats(check=True)["healthy"])

    def test_damaged_old_index_needs_explicit_opt_in(self) -> None:
        # Make the old trigram index disagree with its own content table.
        self.store.db.execute(
            "UPDATE event_trigram_content SET c1='tampered' WHERE id=1"
        )
        self.store.db.commit()
        with self.assertRaisesRegex(search.LayoutError, "--ignore-old-index-errors"):
            search.migrate_layout(self.store.db)
        self.assertEqual(search.store_layout(self.store.db), 1)
        r = search.migrate_layout(self.store.db, ignore_old_index_errors=True)
        self.assertEqual(len(r["ignored_old_index_errors"]), 1)
        self.assertIn("event_trigram", r["ignored_old_index_errors"][0])
        # event_text comes from event_fts_content, which was not touched.
        index = search.SearchIndex(self.store)
        self.assertTrue(index.stats(check=True)["healthy"])
        self.assertEqual(len(index.search("quick brown", mode="trigram")), 1)

    def test_only_old_index_errors_are_tolerable(self) -> None:
        ok = search._OLD_INDEX_ERROR.fullmatch
        self.assertTrue(ok('fts5: checksum mismatch for table "event_fts"'))
        self.assertTrue(ok("malformed inside FTS5 table main.event_trigram"))
        self.assertTrue(ok("malformed inverted index for FTS5 table main.event_fts"))
        self.assertFalse(ok("row 7 missing from index event_ts_idx"))
        self.assertFalse(ok('fts5: checksum mismatch for table "other_fts"'))
        self.assertFalse(ok("malformed inside FTS5 table main.event_fts_extra"))

    def test_cli_refuses_while_another_connection_is_open(self) -> None:
        self.assertTrue(search.other_writer_files(self.db_path), "WAL file expected")
        self.assertEqual(self.cli("migrate"), 2)
        self.assertEqual(search.store_layout(self.store.db), 1)

    def test_cli_migrate_then_vacuum(self) -> None:
        self.store.close()
        self.assertEqual(search.other_writer_files(self.db_path), [])
        self.assertEqual(self.cli("migrate"), 0)
        self.assertEqual(self.cli("migrate"), 0)
        self.assertEqual(self.cli("stats", "--check"), 0)
        into = Path(self._tmp.name) / "compact.sqlite3"
        self.assertEqual(self.cli("vacuum", "--into", str(into)), 0)
        self.assertEqual(self.cli("vacuum", "--into", str(into)), 2, "never overwrites")
        self.assertEqual(self.cli("vacuum"), 0)
        self.store = s1.EvidenceStore(into, self.cas)
        self.assertEqual(search.store_layout(self.store.db), search.SEARCH_LAYOUT)
        self.assertEqual(
            len(search.SearchIndex(self.store).search("quick", mode="fts")), 1
        )


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
