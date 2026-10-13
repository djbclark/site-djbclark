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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import s1_evidence as s1  # noqa: E402


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
        ids = [
            self.ingest(raw=f"m{i}".encode(), locator=f"{i}#{i}")[0] for i in range(5)
        ]
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
        self.store.pack_db.execute(
            "UPDATE obj SET data=? WHERE sha=?", (b"corrupted", bytes.fromhex(digest))
        )
        self.store.pack_db.commit()
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
        for seq, ts in (
            (2, "2026-08-23T20:00:02Z"),
            (0, "2026-08-23T20:00:00Z"),
            (1, "2026-08-23T20:00:01Z"),
        ):
            eid, _ = self.ingest(
                raw=f"turn{seq}".encode(),
                locator=f"loc{seq}",
                source_seq=seq,
                ts_utc=ts,
            )
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
        self.store.set_checkpoint(
            "claude-code",
            "file:///transcript.jsonl",
            source_fingerprint="fp1",
            committed_locator="0#0",
            adapter_version="v1",
        )
        cp = self.store.checkpoint("claude-code", "file:///transcript.jsonl")
        self.assertEqual(cp["committed_locator"], "0#0")

        # a second pass resumes from the checkpoint and does not duplicate
        self.ingest(raw=b"first", locator="0#0")
        self.ingest(raw=b"second", locator="1#1")
        self.store.set_checkpoint(
            "claude-code",
            "file:///transcript.jsonl",
            source_fingerprint="fp1",
            committed_locator="1#1",
            adapter_version="v1",
        )
        self.assertEqual(self.store.stats()["events"], 2)
        self.assertEqual(
            self.store.checkpoint("claude-code", "file:///transcript.jsonl")[
                "committed_locator"
            ],
            "1#1",
        )

    def test_gaps_are_recorded_rather_than_assumed_lossless(self) -> None:
        self.store.record_gap(
            "claude-code",
            "file:///gone.jsonl",
            "session transcript garbage-collected before ingest",
        )
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
        self.store.pack_db.execute(
            "DELETE FROM obj WHERE sha=?", (bytes.fromhex(digest),)
        )
        self.store.pack_db.commit()
        report = self.store.verify()
        self.assertFalse(report["healthy"])
        self.assertIn(event_id, report["hash_missing"])
        self.assertIn(digest, report["pack_hash_missing"])

    def test_verify_flags_hash_mismatch(self) -> None:
        event_id, _ = self.ingest(raw=b"authentic")
        digest = self.store.get_event(event_id)["raw_sha256"]
        self.store.pack_db.execute(
            "UPDATE obj SET data=? WHERE sha=?", (b"swapped!!", bytes.fromhex(digest))
        )
        self.store.pack_db.commit()
        report = self.store.verify()
        self.assertFalse(report["healthy"])
        self.assertIn(event_id, report["hash_mismatched"])

    def test_snapshot_restore_drill(self) -> None:
        """The Phase B exit gate: snapshot, reopen, verify, retrieve."""
        payloads = [f"evidence-{i}".encode() for i in range(4)]
        ids = [
            self.ingest(raw=p, locator=f"s{i}#{i}")[0] for i, p in enumerate(payloads)
        ]
        for eid in ids:
            self.store.assign_conversation(eid, "conv-restore")

        snap = self.store.snapshot(self.root / "snap.sqlite3")
        self.assertTrue(snap.exists())

        # restore into a fresh store pointed at the same CAS
        restored = s1.EvidenceStore(
            snap, self.root / "cas", snap.with_name(f"{snap.stem}.cas-pack.sqlite3")
        )
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


class TestCasPack(S1TestCase):
    def add_loose(self, payload: bytes, *, name_digest: str | None = None) -> str:
        digest = name_digest or s1.sha256_bytes(payload)
        path = self.store.cas_path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return digest

    def test_new_event_writes_to_pack_not_loose_files(self) -> None:
        event_id, _ = self.ingest(raw=b"new packed evidence")
        digest = self.store.get_event(event_id)["raw_sha256"]
        packed = self.store.pack_db.execute(
            "SELECT sha FROM obj WHERE sha=?", (bytes.fromhex(digest),)
        ).fetchone()
        self.assertIsNotNone(packed)
        self.assertFalse(self.store.cas_path(digest).exists())
        self.assertEqual(self.store.raw_for(event_id), b"new packed evidence")

    def test_new_write_repairs_a_corrupt_existing_pack_row(self) -> None:
        first, _ = self.ingest(raw=b"repairable object", locator="before")
        digest = self.store.get_event(first)["raw_sha256"]
        self.store.pack_db.execute(
            "UPDATE obj SET data=? WHERE sha=?", (b"bad", bytes.fromhex(digest))
        )
        self.store.pack_db.commit()
        second, created = self.ingest(raw=b"repairable object", locator="after")
        self.assertTrue(created)
        self.assertEqual(self.store.raw_for(first), b"repairable object")
        self.assertEqual(self.store.raw_for(second), b"repairable object")

    def test_zstd_object_round_trips_exactly(self) -> None:
        payload = b'{"role":"assistant","content":"repeated evidence payload"}' * 200
        event_id, _ = self.ingest(raw=payload, locator="compressed")
        digest = self.store.get_event(event_id)["raw_sha256"]
        row = self.store.pack_db.execute(
            "SELECT codec,dict_id FROM obj WHERE sha=?", (bytes.fromhex(digest),)
        ).fetchone()
        self.assertEqual(row["codec"], 1)
        self.assertEqual(self.store.raw_for(event_id), payload)

    def test_reads_packed_and_loose_objects_during_half_migration(self) -> None:
        packed_event, _ = self.ingest(raw=b"packed object", locator="packed")
        loose_payload = b"legacy loose object"
        loose_event, _ = self.ingest(raw=loose_payload, locator="loose")
        loose_digest = self.store.get_event(loose_event)["raw_sha256"]
        self.store.pack_db.execute(
            "DELETE FROM obj WHERE sha=?", (bytes.fromhex(loose_digest),)
        )
        self.store.pack_db.commit()
        loose_path = self.store.cas_path(loose_digest)
        loose_path.parent.mkdir(parents=True, exist_ok=True)
        loose_path.write_bytes(loose_payload)
        self.assertEqual(self.store.raw_for(packed_event), b"packed object")
        self.assertEqual(self.store.raw_for(loose_event), loose_payload)
        report = self.store.verify()
        self.assertTrue(report["healthy"], report)

    def test_cas_pack_resumes_after_a_committed_batch(self) -> None:
        for i in range(5):
            self.add_loose(f"loose-object-{i}".encode())
        original = self.store._write_pack_batch
        calls = 0

        def interrupt_after_commit(batch):
            nonlocal calls
            result = original(batch)
            calls += 1
            if calls == 1:
                raise RuntimeError("simulated process interruption after commit")
            return result

        self.store._write_pack_batch = interrupt_after_commit
        with self.assertRaisesRegex(RuntimeError, "simulated process interruption"):
            self.store.cas_pack(batch_size=2)
        self.store._write_pack_batch = original
        report = self.store.cas_pack(batch_size=2)
        self.assertEqual(report["files_seen"], 5)
        self.assertEqual(report["packed"], 3)
        self.assertEqual(report["already_packed"], 2)
        self.assertEqual(report["hash_mismatched"], [])
        self.assertEqual(
            self.store.pack_db.execute("SELECT COUNT(*) FROM obj").fetchone()[0], 5
        )

    def test_interrupted_mid_batch_rolls_back_and_can_resume(self) -> None:
        payloads = [b"loose-a", b"loose-b", b"loose-c"]
        digests = [self.add_loose(payload) for payload in payloads]
        first = (digests[0], len(payloads[0]), payloads[0], 0, 0)
        invalid = ("not-a-digest", 1, b"x", 0, 0)
        with self.assertRaises(ValueError):
            self.store._write_pack_batch([first, invalid])
        self.assertEqual(
            self.store.pack_db.execute("SELECT COUNT(*) FROM obj").fetchone()[0], 0
        )

        report = self.store.cas_pack(batch_size=3)
        self.assertEqual(report["packed"], 3)
        self.assertEqual(report["hash_mismatched"], [])
        self.assertEqual(
            self.store.pack_db.execute("SELECT COUNT(*) FROM obj").fetchone()[0], 3
        )

    def test_bad_loose_hash_is_reported_and_not_packed(self) -> None:
        digest = self.add_loose(
            b"bytes that do not match the filename", name_digest="a" * 64
        )
        report = self.store.cas_pack()
        self.assertIn(digest, report["hash_mismatched"])
        self.assertIsNone(
            self.store.pack_db.execute(
                "SELECT 1 FROM obj WHERE sha=?", (bytes.fromhex(digest),)
            ).fetchone()
        )

    def test_prune_requires_lock_and_keeps_unverified_objects(self) -> None:
        event_id, _ = self.ingest(raw=b"prune candidate")
        digest = self.store.get_event(event_id)["raw_sha256"]
        path = self.store.cas_path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"prune candidate")
        with self.assertRaisesRegex(RuntimeError, "without .*maintenance.lock"):
            self.store.cas_prune_loose()

        self.store.maintenance_lock.touch()
        self.store.pack_db.execute(
            "UPDATE obj SET data=? WHERE sha=?", (b"corrupt", bytes.fromhex(digest))
        )
        self.store.pack_db.commit()
        report = self.store.cas_prune_loose()
        self.assertTrue(any(item.startswith(digest) for item in report["unverified"]))
        self.assertTrue(path.exists())

    def test_dry_run_and_prune_only_remove_verified_copies(self) -> None:
        event_id, _ = self.ingest(raw=b"verified prune candidate")
        digest = self.store.get_event(event_id)["raw_sha256"]
        path = self.store.cas_path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"verified prune candidate")
        self.store.maintenance_lock.touch()
        preview = self.store.cas_prune_loose(dry_run=True)
        self.assertEqual(preview["would_prune"], 1)
        self.assertEqual(preview["pruned"], 0)
        self.assertTrue(path.exists())
        actual = self.store.cas_prune_loose()
        self.assertEqual(actual["pruned"], 1)
        self.assertFalse(path.exists())

    def test_verify_detects_corrupt_packed_row(self) -> None:
        event_id, _ = self.ingest(raw=b"packed verification")
        digest = self.store.get_event(event_id)["raw_sha256"]
        self.store.pack_db.execute(
            "UPDATE obj SET data=? WHERE sha=?",
            (b"broken payload", bytes.fromhex(digest)),
        )
        self.store.pack_db.commit()
        report = self.store.verify(sample=10)
        self.assertEqual(report["pack_integrity_check"], "ok")
        self.assertIn(digest, report["pack_hash_mismatched"])
        self.assertFalse(report["healthy"])

    def test_wal_reader_remains_available_while_writer_commits(self) -> None:
        event_id, _ = self.ingest(raw=b"stable reader object")
        digest = self.store.get_event(event_id)["raw_sha256"]
        reader = s1.EvidenceStore(
            self.store.path, self.store.cas_root, self.store.pack_path
        )
        try:
            reader.pack_db.execute("BEGIN")
            self.assertEqual(reader.get_bytes(digest), b"stable reader object")

            def write_event() -> tuple[str, bool]:
                writer_store = s1.EvidenceStore(
                    self.store.path, self.store.cas_root, self.store.pack_path
                )
                try:
                    return writer_store.put_event(
                        producer="claude-code",
                        source_uri="file:///transcript.jsonl",
                        source_locator="writer",
                        raw=b"concurrent writer payload",
                        ts_utc="2026-08-23T20:00:00Z",
                        role="user",
                        origin="human",
                    )
                finally:
                    writer_store.close()

            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(write_event).result(timeout=5)
            self.assertTrue(result[1])
            self.assertEqual(reader.get_bytes(digest), b"stable reader object")
            reader.pack_db.execute("COMMIT")
            new_digest = s1.sha256_bytes(b"concurrent writer payload")
            self.assertEqual(reader.get_bytes(new_digest), b"concurrent writer payload")
        finally:
            reader.close()


class TestValidation(S1TestCase):
    def test_rejects_out_of_vocabulary_fields(self) -> None:
        for bad in ({"role": "narrator"}, {"origin": "vibes"}, {"ts_source": "guess"}):
            with self.assertRaises(ValueError):
                self.ingest(**bad)

    def test_timestamps_use_z_suffix(self) -> None:
        self.assertTrue(s1.now_iso().endswith("Z"))


class TestFreshness(S1TestCase):
    NOW = 1_787_536_800  # 2026-08-24T02:00:00Z

    def test_newest_event_per_producer_with_age(self) -> None:
        self.ingest(b"a", "1", ts_utc="2026-08-23T20:00:00Z")
        self.ingest(b"b", "2", ts_utc="2026-08-24T01:13:00Z")
        self.ingest(b"c", "1", producer="hermes", ts_utc="2026-08-24T01:59:30.123Z")
        self.ingest(
            b"d", "1", producer="hindsight", ts_utc="2026-07-01T00:00:00.198631Z"
        )
        newest = self.store.newest_by_producer(now=self.NOW)
        self.assertEqual(sorted(newest), ["claude-code", "hermes", "hindsight"])
        self.assertEqual(
            newest["claude-code"],
            {
                "newest_ts_utc": "2026-08-24T01:13:00Z",
                "age_seconds": 2820,
                "age": "47m",
            },
        )
        self.assertEqual(newest["hermes"]["age"], "30s")
        self.assertEqual(newest["hindsight"]["age"], "54d2h")

    def test_stats_adds_ages_and_keeps_existing_keys(self) -> None:
        self.ingest()
        stats = self.store.stats()
        for key in (
            "db",
            "cas",
            "events",
            "raw_bytes",
            "producers",
            "sessions",
            "objects",
            "conversations",
            "gaps",
            "schema_version",
        ):
            self.assertIn(key, stats)
        self.assertEqual(list(stats["newest_by_producer"]), ["claude-code"])
        self.assertIsInstance(
            stats["newest_by_producer"]["claude-code"]["age_seconds"], int
        )

    def test_empty_store_has_no_producers(self) -> None:
        self.assertEqual(self.store.stats()["newest_by_producer"], {})

    def test_format_age(self) -> None:
        cases = {
            0: "0s",
            59: "59s",
            60: "1m",
            3599: "59m",
            3600: "1h0m",
            7 * 3600 + 125: "7h2m",
            86400: "1d0h",
            49 * 86400 + 3 * 3600 + 59: "49d3h",
            -5: "0s",
        }
        for seconds, want in cases.items():
            self.assertEqual(s1.format_age(seconds), want, seconds)


if __name__ == "__main__":
    unittest.main()
