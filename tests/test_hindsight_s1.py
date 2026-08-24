#!/usr/bin/env python3
"""Tests for the S1 evidence store.

These target the Phase B exit gate directly: exact source spans are
recoverable, repeated ingestion creates no duplicates, interrupted ingestion
resumes, and a snapshot restore passes integrity/foreign-key/hash/retrieval
checks.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import hindsight_s1 as s1  # noqa: E402


class S1TestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.store = s1.EvidenceStore(root / "candidates.sqlite3", root / "cas")
        self.root = root

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def ingest(self, raw: bytes = b"hello", locator: str = "0:5#0", **kw):
        params = dict(
            producer="claude-code",
            source_uri="file:///transcript.jsonl",
            source_locator=locator,
            raw=raw,
            ts_utc="2026-08-23T20:00:00Z",
            role="user",
            origin="human",
        )
        params.update(kw)
        return self.store.put_event(**params)


class TestIdentity(S1TestCase):
    def test_event_id_is_deterministic_and_coordinate_derived(self) -> None:
        a = s1.derive_event_id("p", "uri", "loc", "abc")
        b = s1.derive_event_id("p", "uri", "loc", "abc")
        self.assertEqual(a, b)
        # any coordinate change changes identity
        self.assertNotEqual(a, s1.derive_event_id("p2", "uri", "loc", "abc"))
        self.assertNotEqual(a, s1.derive_event_id("p", "uri2", "loc", "abc"))
        self.assertNotEqual(a, s1.derive_event_id("p", "uri", "loc2", "abc"))
        self.assertNotEqual(a, s1.derive_event_id("p", "uri", "loc", "abd"))

    def test_separator_prevents_concatenation_collisions(self) -> None:
        # Without a separator these two would hash the same input.
        self.assertNotEqual(
            s1.derive_event_id("ab", "c", "d", "e"),
            s1.derive_event_id("a", "bc", "d", "e"),
        )

    def test_session_id_is_evidence_not_identity(self) -> None:
        first, created = self.ingest(producer_session_id="s1")
        self.assertTrue(created)
        # same coordinates and bytes, different native session id -> same event
        second, created2 = self.ingest(producer_session_id="s2")
        self.assertEqual(first, second)
        self.assertFalse(created2)


class TestIdempotence(S1TestCase):
    def test_reingesting_identical_source_creates_no_duplicate(self) -> None:
        first, created = self.ingest()
        self.assertTrue(created)
        for _ in range(3):
            again, created_again = self.ingest()
            self.assertEqual(first, again)
            self.assertFalse(created_again)
        self.assertEqual(self.store.stats()["events"], 1)

    def test_mutated_source_is_refused_not_silently_overwritten(self) -> None:
        self.ingest(raw=b"original")
        with self.assertRaises(s1.SourceMutated):
            self.ingest(raw=b"tampered")
        # the original evidence survives intact
        self.assertEqual(self.store.stats()["events"], 1)

    def test_identical_bytes_at_different_coordinates_are_distinct_events(self) -> None:
        a, _ = self.ingest(raw=b"same", locator="0:4#0")
        b, _ = self.ingest(raw=b"same", locator="4:8#1")
        self.assertNotEqual(a, b)
        # ...but the CAS stores the bytes once
        self.assertEqual(self.store.stats()["objects"], 1)
        self.assertEqual(self.store.stats()["events"], 2)

    def test_ingest_lsn_is_unique_and_monotonic(self) -> None:
        ids = [self.ingest(raw=f"m{i}".encode(), locator=f"{i}#{i}")[0] for i in range(5)]
        lsns = [self.store.get_event(i)["ingest_lsn"] for i in ids]
        self.assertEqual(lsns, sorted(lsns))
        self.assertEqual(len(set(lsns)), len(lsns))


class TestExactRecovery(S1TestCase):
    def test_raw_bytes_round_trip_exactly(self) -> None:
        # bytes that would not survive naive text normalization
        raw = b"line1\r\n\ttrailing spaces   \n\x00\xff binary \xe2\x9c\x93"
        event_id, _ = self.ingest(raw=raw)
        self.assertEqual(self.store.raw_for(event_id), raw)

    def test_corrupted_cas_object_is_detected_not_returned(self) -> None:
        event_id, _ = self.ingest(raw=b"trustworthy")
        digest = self.store.get_event(event_id)["raw_sha256"]
        self.store.cas_path(digest).write_bytes(b"corrupted")
        with self.assertRaises(s1.SourceMutated):
            self.store.raw_for(event_id)

    def test_exact_search_finds_stored_span(self) -> None:
        self.ingest(raw=b"the needle is in here", locator="a#0")
        self.ingest(raw=b"unrelated payload", locator="b#1")
        hits = self.store.search("needle")
        self.assertEqual(len(hits), 1)


class TestConversations(S1TestCase):
    def test_conversation_order_is_deterministic(self) -> None:
        # inserted out of chronological order on purpose
        for seq, ts in ((2, "2026-08-23T20:00:02Z"), (0, "2026-08-23T20:00:00Z"),
                        (1, "2026-08-23T20:00:01Z")):
            eid, _ = self.ingest(raw=f"turn{seq}".encode(), locator=f"loc{seq}",
                                 source_seq=seq, ts_utc=ts)
            self.store.assign_conversation(eid, "conv-1")
        order = [r["source_seq"] for r in self.store.conversation("conv-1")]
        self.assertEqual(order, [0, 1, 2])

    def test_reassignment_is_revisable(self) -> None:
        eid, _ = self.ingest()
        self.store.assign_conversation(eid, "conv-a", confidence=0.4)
        self.store.assign_conversation(eid, "conv-a", confidence=0.9)
        rows = list(self.store.conversation("conv-a"))
        self.assertEqual(len(rows), 1)


class TestResumeAndGaps(S1TestCase):
    def test_checkpoint_records_and_resumes_position(self) -> None:
        self.ingest(raw=b"first", locator="0#0")
        self.store.set_checkpoint("claude-code", "file:///transcript.jsonl",
                                  source_fingerprint="fp1", committed_locator="0#0",
                                  adapter_version="v1")
        cp = self.store.checkpoint("claude-code", "file:///transcript.jsonl")
        self.assertEqual(cp["committed_locator"], "0#0")

        # a second pass resumes from the checkpoint and does not duplicate
        self.ingest(raw=b"first", locator="0#0")
        self.ingest(raw=b"second", locator="1#1")
        self.store.set_checkpoint("claude-code", "file:///transcript.jsonl",
                                  source_fingerprint="fp1", committed_locator="1#1",
                                  adapter_version="v1")
        self.assertEqual(self.store.stats()["events"], 2)
        self.assertEqual(
            self.store.checkpoint("claude-code", "file:///transcript.jsonl")["committed_locator"],
            "1#1",
        )

    def test_gaps_are_recorded_rather_than_assumed_lossless(self) -> None:
        self.store.record_gap("claude-code", "file:///gone.jsonl",
                              "session transcript garbage-collected before ingest")
        self.assertEqual(self.store.stats()["gaps"], 1)


class TestIntegrityAndRestore(S1TestCase):
    def test_verify_passes_on_healthy_store(self) -> None:
        for i in range(3):
            self.ingest(raw=f"payload{i}".encode(), locator=f"l{i}#{i}")
        report = self.store.verify()
        self.assertTrue(report["healthy"], report)
        self.assertEqual(report["hash_ok"], 3)

    def test_verify_flags_missing_cas_object(self) -> None:
        event_id, _ = self.ingest(raw=b"vanishing")
        digest = self.store.get_event(event_id)["raw_sha256"]
        self.store.cas_path(digest).unlink()
        report = self.store.verify()
        self.assertFalse(report["healthy"])
        self.assertIn(event_id, report["hash_missing"])

    def test_verify_flags_hash_mismatch(self) -> None:
        event_id, _ = self.ingest(raw=b"authentic")
        digest = self.store.get_event(event_id)["raw_sha256"]
        self.store.cas_path(digest).write_bytes(b"swapped!!")
        report = self.store.verify()
        self.assertFalse(report["healthy"])
        self.assertIn(event_id, report["hash_mismatched"])

    def test_snapshot_restore_drill(self) -> None:
        """The Phase B exit gate: snapshot, reopen, verify, retrieve."""
        payloads = [f"evidence-{i}".encode() for i in range(4)]
        ids = [self.ingest(raw=p, locator=f"s{i}#{i}")[0] for i, p in enumerate(payloads)]
        for eid in ids:
            self.store.assign_conversation(eid, "conv-restore")

        snap = self.store.snapshot(self.root / "snap.sqlite3")
        self.assertTrue(snap.exists())

        # restore into a fresh store pointed at the same CAS
        restored = s1.EvidenceStore(snap, self.root / "cas")
        try:
            report = restored.verify()
            self.assertTrue(report["healthy"], report)
            self.assertEqual(report["events"], 4)
            # exact spans still recoverable after restore
            for eid, payload in zip(ids, payloads):
                self.assertEqual(restored.raw_for(eid), payload)
            # and retrieval still works
            self.assertEqual(len(list(restored.conversation("conv-restore"))), 4)
            self.assertEqual(len(restored.search("evidence-2")), 1)
        finally:
            restored.close()


class TestValidation(S1TestCase):
    def test_rejects_out_of_vocabulary_fields(self) -> None:
        for bad in ({"role": "narrator"}, {"origin": "vibes"}, {"ts_source": "guess"}):
            with self.assertRaises(ValueError):
                self.ingest(**bad)

    def test_timestamps_use_z_suffix(self) -> None:
        self.assertTrue(s1.now_iso().endswith("Z"))


if __name__ == "__main__":
    unittest.main()
