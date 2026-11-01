"""Tests for bin/s1_archive.py (ArchiveStore). Synthetic data in temp dirs only."""

from __future__ import annotations

import base64
import calendar
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from compression import zstd
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import s1_archive as arc  # noqa: E402

TS = "2026-10-01T00:00:00Z"


def records_of(path: Path) -> list[dict]:
    text = zstd.decompress(path.read_bytes())
    return [json.loads(line) for line in text.split(b"\n") if line]


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="s1arc-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "root"
        self.stores: list[arc.ArchiveStore] = []

    def store(self, **kw) -> arc.ArchiveStore:
        s = arc.ArchiveStore(self.root, **kw)
        self.stores.append(s)
        return s

    @staticmethod
    def put(s, uri="/src/a.jsonl", loc="1", raw=b"x", producer="prod", **kw):
        kw.setdefault("ts_utc", TS)
        return s.put_event(
            producer=producer, source_uri=uri, source_locator=loc, raw=raw, **kw
        )

    def file_of(self, s, uri="/src/a.jsonl", producer="prod") -> Path:
        return s.source_path(producer, uri)


class TestIdempotency(Base):
    def test_reput_is_noop_and_mutation_raises(self):
        s = self.store()
        eid, created = self.put(s, raw=b"one")
        self.assertTrue(created)
        s.flush()
        path = self.file_of(s)
        before = path.read_bytes()
        # same process, then a fresh process-like store loaded from disk
        for store in (s, self.store()):
            self.assertEqual(self.put(store, raw=b"one"), (eid, False))
            store.flush()
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(arc.SourceMutated):
                self.put(store, raw=b"two")
        self.assertEqual(path.read_bytes(), before)

    def test_validation_errors_match_evidence_store(self):
        s = self.store()
        with self.assertRaisesRegex(ValueError, "ts_source must be one of"):
            self.put(s, ts_source="bogus")
        with self.assertRaisesRegex(ValueError, "role must be one of"):
            self.put(s, role="bogus")
        with self.assertRaisesRegex(ValueError, "origin must be one of"):
            self.put(s, origin="bogus")

    def test_event_id_is_stable_derivation(self):
        s = self.store()
        eid, _ = self.put(s, raw=b"abc", loc="9")
        digest = hashlib.sha256(b"abc").hexdigest()
        joined = "\x1f".join(("prod", "/src/a.jsonl", "9", digest))
        self.assertEqual(eid, hashlib.sha256(joined.encode()).hexdigest())


class TestRoundTrip(Base):
    def test_binary_and_unicode_round_trip(self):
        s = self.store()
        binary = bytes(range(256)) + b"\xff\xfe"
        text = 'line1\nline2 "quoted" \x00 NUL 😀 \u2028 \\ end'.encode()
        eb, _ = self.put(s, loc="b", raw=binary)
        et, _ = self.put(s, loc="t", raw=text)
        s.flush()
        recs = {r["id"]: r for r in records_of(self.file_of(s))}
        self.assertIn("raw_b64", recs[eb])
        self.assertNotIn("raw", recs[eb])
        self.assertEqual(base64.b64decode(recs[eb]["raw_b64"]), binary)
        self.assertIn("raw", recs[et])
        self.assertNotIn("raw_b64", recs[et])
        self.assertEqual(recs[et]["raw"].encode(), text)
        for eid, payload in ((eb, binary), (et, text)):
            self.assertEqual(recs[eid]["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(recs[eid]["size"], len(payload))
            self.assertEqual(self.store().raw_for(eid), payload)
        # one physical line per record: JSON escaping, never a raw newline
        decoded = zstd.decompress(self.file_of(s).read_bytes())
        self.assertEqual(decoded.count(b"\n"), 2)
        got = {e["source_locator"]: e["raw"] for e in self.store().iter_source("prod", "/src/a.jsonl")}
        self.assertEqual(got, {"b": binary, "t": text})

    def test_verify_recomputes_hashes(self):
        s = self.store()
        self.put(s, raw=b"ok")
        s.flush()
        self.assertTrue(s.verify()["healthy"])
        path = self.file_of(s)
        rec = records_of(path)[0]
        rec["raw"] = "tampered"
        path.write_bytes(arc._compress_frame(arc._dumps(rec) + b"\n"))
        report = self.store().verify()
        self.assertFalse(report["healthy"])
        self.assertEqual(report["hash_mismatched"], [rec["id"]])


class TestFrames(Base):
    def test_two_flushes_two_frames_readable_as_one_stream(self):
        s = self.store()
        self.put(s, loc="1", raw=b"a")
        s.flush()
        self.put(s, loc="2", raw=b"b")
        s.flush()
        data = self.file_of(s).read_bytes()
        self.assertEqual(arc.count_frames(data), 2)
        lines = zstd.decompress(data).split(b"\n")
        self.assertEqual([json.loads(x)["source_locator"] for x in lines if x], ["1", "2"])

    @unittest.skipUnless(shutil.which("zstd"), "zstd CLI not on PATH")
    def test_zstd_cli_reads_multiframe(self):
        s = self.store()
        for i in range(3):
            self.put(s, loc=str(i), raw=b"v%d" % i)
            s.flush()
        out = subprocess.run(
            ["zstd", "-d", "-c", "-q", str(self.file_of(s))], capture_output=True, check=True
        ).stdout
        self.assertEqual(len([x for x in out.split(b"\n") if x]), 3)

    def test_torn_tail_is_repaired_and_append_continues(self):
        s = self.store()
        e1, _ = self.put(s, loc="1", raw=b"first" * 50)
        s.flush()
        path = self.file_of(s)
        first_frame = path.read_bytes()
        self.put(s, loc="2", raw=b"second" * 50)
        s.flush()
        full = path.read_bytes()
        with open(path, "r+b") as handle:
            handle.truncate(len(full) - 7)  # mid second frame
        s2 = self.store()
        e3, created = self.put(s2, loc="3", raw=b"third")
        self.assertTrue(created)
        _e2, lost_created = self.put(s2, loc="2", raw=b"second" * 50)
        self.assertTrue(lost_created, "the torn frame's event was never durable")
        s2.flush()
        self.assertEqual(len(s2.repairs), 1)
        data = path.read_bytes()
        self.assertTrue(data.startswith(first_frame))
        self.assertEqual(
            [r["source_locator"] for r in records_of(path)], ["1", "3", "2"]
        )
        self.assertEqual(e1, records_of(path)[0]["id"])
        self.assertEqual(arc.count_frames(data), 2)
        self.assertTrue(self.store().verify()["healthy"])

    def test_corrupt_middle_frame_raises_and_file_is_untouched(self):
        s = self.store()
        for i in range(3):
            self.put(s, loc=str(i), raw=(b"payload-%d-" % i) * 40)
            s.flush()
        path = self.file_of(s)
        data = bytearray(path.read_bytes())
        # second frame spans [a, b): flip a byte in the middle of it
        a = len(arc._compress_frame(arc._dumps(records_of(path)[0]) + b"\n"))
        data[a + 40] ^= 0xFF
        path.write_bytes(bytes(data))
        before = path.read_bytes()
        mtime = path.stat().st_mtime_ns
        s2 = self.store()
        with self.assertRaises(arc.ArchiveCorrupt) as ctx:
            self.put(s2, loc="9", raw=b"new")
            s2.flush()
        self.assertIn(str(path), str(ctx.exception))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, mtime)
        report = self.store().verify()
        self.assertFalse(report["healthy"])
        self.assertEqual(len(report["corrupt_files"]), 1)

    def test_partial_frame_followed_by_later_frame_is_corrupt_not_torn(self):
        s = self.store()
        self.put(s, loc="1", raw=b"a" * 200)
        s.flush()
        f1 = self.file_of(s).read_bytes()
        # an incompressible body makes one big raw block: cut inside it, so the decoder
        # reads the next frame's bytes as block data and never errors, only runs out
        f2 = arc._compress_frame(os.urandom(100_000))
        f3 = arc._compress_frame(b'{"v":1,"t":"zzz"}\n')
        self.file_of(s).write_bytes(f1 + f2[:20_000] + f3)
        before = self.file_of(s).read_bytes()
        with self.assertRaises(arc.ArchiveCorrupt):
            self.put(self.store(), loc="2", raw=b"b")
        self.assertEqual(self.file_of(s).read_bytes(), before)


class TestCheckpointOrdering(Base):
    def test_checkpoint_written_only_after_events_are_durable(self):
        s = self.store()
        eid, _ = self.put(s, raw=b"data")
        path = self.file_of(s)
        seen: dict = {}
        real = s._append_state

        def failing(name, record):
            seen["on_disk_when_checkpoint_written"] = (
                [r["id"] for r in records_of(path)] if path.exists() else []
            )
            raise OSError("disk full")

        s._append_state = failing
        with self.assertRaises(OSError):
            s.set_checkpoint(
                "prod", "/src/a.jsonl",
                source_fingerprint="fp", committed_locator="1", adapter_version="v1",
            )
        self.assertEqual(seen["on_disk_when_checkpoint_written"], [eid])
        s._append_state = real
        fresh = self.store()
        self.assertIsNone(fresh.checkpoint("prod", "/src/a.jsonl"))
        self.assertEqual(self.put(fresh, raw=b"data"), (eid, False))

    def test_checkpoint_round_trip_and_skip_unchanged(self):
        s = self.store()
        s.set_checkpoint("prod", "u", source_fingerprint="f1", committed_locator=None, adapter_version="1")
        cp = self.store().checkpoint("prod", "u")
        self.assertEqual(
            {k: cp[k] for k in ("source_fingerprint", "committed_locator", "adapter_version")},
            {"source_fingerprint": "f1", "committed_locator": None, "adapter_version": "1"},
        )
        self.assertRegex(cp["updated_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        log = self.root / "state" / "checkpoints.jsonl"
        size = log.stat().st_size
        s.set_checkpoint("prod", "u", source_fingerprint="f1", committed_locator=None, adapter_version="1")
        self.assertEqual(log.stat().st_size, size)
        s.set_checkpoint("prod", "u", source_fingerprint="f2", committed_locator="9", adapter_version="1")
        self.assertEqual(self.store().checkpoint("prod", "u")["source_fingerprint"], "f2")
        self.assertEqual(self.store().checkpoint_source_uris("prod"), ["u"])
        self.assertEqual(self.store().checkpoint_source_uris("other"), [])

    def test_torn_state_line_is_ignored_and_not_glued(self):
        s = self.store()
        s.set_checkpoint("prod", "u", source_fingerprint="f1", committed_locator="1", adapter_version="1")
        with open(self.root / "state" / "checkpoints.jsonl", "ab") as handle:
            handle.write(b'{"producer":"prod","source_uri":"u","finger')  # crash mid-line
        s2 = self.store()
        self.assertEqual(s2.checkpoint("prod", "u")["source_fingerprint"], "f1")
        s2.set_checkpoint("prod", "u", source_fingerprint="f3", committed_locator="2", adapter_version="1")
        self.assertEqual(self.store().checkpoint("prod", "u")["source_fingerprint"], "f3")

    def test_gaps_idempotent(self):
        s = self.store()
        s.record_gap("prod", "u", "why", from_locator="1", to_locator=None)
        s.record_gap("prod", "u", "why", from_locator="1", to_locator=None)
        s.record_gap("prod", "u", "why")
        self.assertTrue(s.has_gap("prod", "u", "why", "1", None))
        self.assertTrue(s.has_gap("prod", "u", "why", None, None))
        self.assertFalse(s.has_gap("prod", "u", "why", "2", None))
        self.assertFalse(s.has_gap("prod", "u", "other", "1", None))
        lines = (self.root / "state" / "gaps.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 2)
        fresh = self.store()
        self.assertTrue(fresh.has_gap("prod", "u", "why", "1", None))
        self.assertEqual(fresh.stats()["gaps"], 2)


class TestPathSafety(Base):
    HOSTILE = [
        "../../../../etc/passwd",
        "a/../../b",
        "..",
        ".",
        "/",
        "",
        "x\x00y/z\x00",
        "has space/and spaces.jsonl",
        "a" * 2000,
        "/" + "dir/" * 300 + "file.jsonl",
        "日本語/файл.jsonl",
        "file:///a/b.jsonl#table=x;y&z=?",
        "\\..\\..\\windows",
        "..;rm -rf ~;..",
    ]

    def test_paths_stay_inside_sessions(self):
        s = self.store()
        sessions = s.sessions.resolve()
        pattern = re.compile(r"^[A-Za-z0-9._-]{1,48}-[0-9a-f]{12}\.jsonl\.zst$")
        for producer in ("prod", "..", ".", "a/../b", "p\x00q", "日本", "x" * 500):
            for uri in self.HOSTILE:
                with self.subTest(producer=producer[:20], uri=uri[:20]):
                    path = s.source_path(producer, uri)
                    resolved = path.resolve()
                    self.assertTrue(resolved.is_relative_to(sessions), path)
                    rel = path.relative_to(s.sessions)
                    self.assertEqual(len(rel.parts), 3, rel)
                    self.assertNotIn(rel.parts[0], ("", ".", ".."))
                    self.assertRegex(rel.parts[0], r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$")
                    self.assertRegex(rel.parts[1], r"^[0-9a-f]{2}$")
                    self.assertRegex(rel.parts[2], pattern)
        # and writing really lands nothing outside root/{sessions,state}
        for producer in ("..", "a/../b"):
            for uri in self.HOSTILE:
                self.put(s, uri=uri, producer=producer, raw=b"x")
        s.flush()
        for current, _dirs, names in os.walk(self.tmp):
            for name in names:
                p = Path(current, name).resolve()
                self.assertTrue(
                    p.is_relative_to(s.sessions.resolve()) or p.is_relative_to(s.state.resolve()), p
                )

    def test_slug_rules(self):
        s = self.store()
        name = lambda uri: s.source_path("p", uri).name  # noqa: E731
        digest = lambda uri: arc.source_hash("p", uri)[:12]  # noqa: E731
        self.assertEqual(name("/d/file name.jsonl#x"), f"filename.jsonlx-{digest('/d/file name.jsonl#x')}.jsonl.zst")
        self.assertEqual(name("///"), f"session-{digest('///')}.jsonl.zst")
        self.assertEqual(name("/a/b/"), f"b-{digest('/a/b/')}.jsonl.zst")
        long = "/x/" + "n" * 100
        self.assertEqual(name(long), f"{'n' * 48}-{digest(long)}.jsonl.zst")
        # the hash separates sources whose slugs collide
        self.assertNotEqual(name("/a/same.jsonl"), name("/b/same.jsonl"))
        self.assertEqual(s.source_path("p", "/a/b").parent.name, arc.source_hash("p", "/a/b")[:2])


class TestCompaction(Base):
    def make_multiframe(self, s, uri="/src/a.jsonl", n=4, age_hours=7.0):
        for i in range(n):
            self.put(s, uri=uri, loc=str(i), raw=(b"record-%d " % i) * 30)
            s.assign_conversation(
                arc.derive_event_id("prod", uri, str(i), hashlib.sha256((b"record-%d " % i) * 30).hexdigest()),
                "conv-1",
            )
            s.flush()
        path = self.file_of(s, uri)
        old = time.time() - age_hours * 3600
        os.utime(path, (old, old))
        return path

    def test_merges_old_multiframe_files_preserving_records(self):
        s = self.store()
        path = self.make_multiframe(s)
        before_recs = records_of(path)
        self.assertEqual(arc.count_frames(path.read_bytes()), 4)
        report = s.compact()
        self.assertEqual(report["compacted"], 1)
        self.assertEqual(report["errors"], [])
        data = path.read_bytes()
        self.assertEqual(arc.count_frames(data), 1)
        after_recs = records_of(path)
        self.assertEqual(after_recs, before_recs)
        self.assertEqual(
            [r["sha256"] for r in after_recs if r["t"] == "ev"],
            [r["sha256"] for r in before_recs if r["t"] == "ev"],
        )
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(len(list(self.store().conversation("conv-1"))), 4)
        # idempotent: a single frame is left alone
        self.assertEqual(self.store().compact()["compacted"], 0)
        self.assertFalse(list(self.root.rglob("*" + arc.TMP_SUFFIX)))

    def test_young_files_are_never_touched(self):
        s = self.store()
        path = self.make_multiframe(s, age_hours=5.0)
        before = path.read_bytes()
        report = s.compact()
        self.assertEqual((report["compacted"], report["young"]), (0, 1))
        self.assertEqual(path.read_bytes(), before)

    def test_maintenance_lock_blocks_compaction(self):
        for custom in (False, True):
            with self.subTest(custom=custom):
                lock = self.tmp / "custom.lock" if custom else self.root / "maintenance.lock"
                s = arc.ArchiveStore(
                    self.root, maintenance_lock_path=lock if custom else None
                )
                path = self.make_multiframe(s, uri=f"/src/{custom}.jsonl")
                before = path.read_bytes()
                lock.write_text("held")
                try:
                    with self.assertRaises(arc.MaintenanceLocked):
                        s.compact()
                    self.assertEqual(path.read_bytes(), before)
                finally:
                    lock.unlink()
                self.assertEqual(s.compact()["compacted"], 1)

    def test_failed_verification_leaves_original_intact(self):
        s = self.store()
        path = self.make_multiframe(s)
        before = path.read_bytes()
        real = arc._compress_frame

        def lossy(payload, level=arc.APPEND_LEVEL):
            if level == arc.COMPACT_LEVEL:  # drop the last record while "compacting"
                payload = payload[: payload.rstrip(b"\n").rfind(b"\n") + 1]
            return real(payload, level)

        with mock.patch.object(arc, "_compress_frame", lossy):
            report = s.compact()
        self.assertEqual(report["compacted"], 0)
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(list(self.root.rglob("*" + arc.TMP_SUFFIX)))
        self.assertEqual(s.compact()["compacted"], 1)  # and a healthy retry works

    def test_compaction_leaves_corrupt_file_alone(self):
        s = self.store()
        path = self.make_multiframe(s)
        raw = bytearray(path.read_bytes())
        raw[30] ^= 0xFF
        path.write_bytes(bytes(raw))
        os.utime(path, (time.time() - 8 * 3600,) * 2)
        before = path.read_bytes()
        report = s.compact()
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(path.read_bytes(), before)

    def test_writer_after_compaction_appends_to_new_file(self):
        s = self.store()
        path = self.make_multiframe(s)
        s.compact()
        e, created = self.put(s, uri="/src/a.jsonl", loc="late", raw=b"late")
        self.assertTrue(created)
        s.flush()
        self.assertIn(e, [r["id"] for r in records_of(path)])
        self.assertEqual(arc.count_frames(path.read_bytes()), 2)

    def test_compact_state_keeps_last_record_per_key(self):
        s = self.store()
        for i in range(5):
            s.set_checkpoint("prod", "u", source_fingerprint=f"f{i}", committed_locator=str(i), adapter_version="1")
        removed = s.compact_state()
        self.assertEqual(removed["checkpoints.jsonl"], 4)
        fresh = self.store()
        self.assertEqual(fresh.checkpoint("prod", "u")["source_fingerprint"], "f4")
        # a long-lived store notices the rewrite
        s.set_checkpoint("prod", "u", source_fingerprint="f9", committed_locator="9", adapter_version="1")
        self.assertEqual(self.store().checkpoint("prod", "u")["source_fingerprint"], "f9")


class TestQueries(Base):
    def test_conversation_last_wins_and_members(self):
        s = self.store()
        e1, _ = self.put(s, uri="/s/1.jsonl", loc="1", ts_utc="2026-10-01T00:00:02Z", raw=b"one")
        e2, _ = self.put(s, uri="/s/2.jsonl", loc="1", ts_utc="2026-10-01T00:00:01Z", raw=b"two", producer="other")
        e3, _ = self.put(s, uri="/s/1.jsonl", loc="2", ts_utc="2026-10-01T00:00:03Z", raw=b"three")
        s.assign_conversation(e1, "c1", assigned_by="a", confidence=0.5)
        s.assign_conversation(e1, "c1", assigned_by="b", confidence=0.9)
        s.assign_conversation(e2, "c1")
        s.assign_conversation(e3, "c2")
        s.flush()
        fresh = self.store()
        info = fresh._load_source("prod", "/s/1.jsonl")
        self.assertEqual(info.conv[(e1, "c1")], ("b", 0.9))
        convs = [r for r in records_of(self.file_of(s, "/s/1.jsonl")) if r["t"] == "conv"]
        self.assertEqual([(r["assigned_by"], r["confidence"]) for r in convs if r["id"] == e1], [("a", 0.5), ("b", 0.9)])
        size = self.file_of(s, "/s/1.jsonl").stat().st_size
        again = self.store()
        again.put_event(producer="prod", source_uri="/s/1.jsonl", source_locator="1", raw=b"one", ts_utc=TS)
        again.assign_conversation(e1, "c1", assigned_by="b", confidence=0.9)
        again.flush()
        self.assertEqual(self.file_of(s, "/s/1.jsonl").stat().st_size, size)
        for ugrep in (shutil.which("ugrep"), None):
            with self.subTest(ugrep=bool(ugrep)):
                reader = self.store()
                reader._ugrep = ugrep
                rows = list(reader.conversation("c1"))
                self.assertEqual([r["event_id"] for r in rows], [e2, e1])  # ts order
                self.assertEqual(rows[1]["raw"], b"one")
                self.assertEqual([r["event_id"] for r in reader.conversation("c2")], [e3])
                self.assertEqual(list(reader.conversation("nope")), [])

    def test_conversation_ids_needing_json_escapes(self):
        s = self.store()
        e, _ = self.put(s, raw=b"x")
        cid = 'we"ird\\id ünï \u2028'
        s.assign_conversation(e, cid)
        s.flush()
        for ugrep in (shutil.which("ugrep"), None):
            reader = self.store()
            reader._ugrep = ugrep
            self.assertEqual([r["event_id"] for r in reader.conversation(cid)], [e])

    def test_assign_conversation_unknown_event_raises_keyerror(self):
        s = self.store()
        with self.assertRaises(KeyError) as ctx:
            s.assign_conversation("f" * 64, "c")
        self.assertIn("f" * 64, str(ctx.exception))

    def test_event_loaded_from_disk_can_be_assigned(self):
        s = self.store()
        e, _ = self.put(s, raw=b"x")
        s.flush()
        s2 = self.store()
        with self.assertRaises(KeyError):
            s2.assign_conversation(e, "c")  # not loaded in this process
        self.put(s2, raw=b"x")  # loads the source
        s2.assign_conversation(e, "c")
        s2.flush()
        self.assertEqual([r["event_id"] for r in self.store().conversation("c")], [e])

    def test_get_event_and_raw_for_with_and_without_ugrep(self):
        s = self.store()
        ids = [self.put(s, uri=f"/s/{i}.jsonl", loc="1", raw=b"raw-%d" % i)[0] for i in range(5)]
        s.flush()
        for ugrep in (shutil.which("ugrep"), None):
            with self.subTest(ugrep=bool(ugrep)):
                reader = self.store()
                reader._ugrep = ugrep
                row = reader.get_event(ids[3])
                self.assertEqual(row["event_id"], ids[3])
                self.assertEqual(row["source_uri"], "/s/3.jsonl")
                self.assertEqual(row["raw_sha256"], hashlib.sha256(b"raw-3").hexdigest())
                self.assertEqual(row["raw_size"], 5)
                self.assertEqual(reader.raw_for(ids[3]), b"raw-3")
                self.assertIsNone(reader.get_event("0" * 64))
                with self.assertRaises(KeyError):
                    reader.raw_for("0" * 64)

    def test_ugrep_is_called_with_argv_list_and_dashdash(self):
        s = self.store()
        e, _ = self.put(s, raw=b"x")
        s.flush()
        if not shutil.which("ugrep"):
            self.skipTest("ugrep not installed")
        reader = self.store()
        calls = []
        real = subprocess.run

        def spy(argv, **kw):
            calls.append((argv, kw))
            return real(argv, **kw)

        with mock.patch.object(subprocess, "run", spy):
            reader.get_event(e)
        argv, kw = calls[0]
        self.assertIsInstance(argv, list)
        self.assertFalse(kw.get("shell"))
        self.assertEqual(argv[argv.index("-e") + 1], e)
        self.assertEqual(argv[-2], "--")
        self.assertEqual(argv[-1], str(reader.sessions))

    def test_source_queries(self):
        s = self.store()
        self.put(s, uri="/a/one.jsonl#table=t1", loc="row:1", raw=b"1")
        self.put(s, uri="/a/one.jsonl#table=t1", loc="row:2", raw=b"2")
        self.put(s, uri="/a/one.jsonl#table=t2", loc="x:1", raw=b"3")
        self.put(s, uri="/b/two.jsonl", loc="1", raw=b"4")
        self.put(s, uri="/b/two.jsonl", loc="1", raw=b"4", producer="elsewhere")
        s.flush()
        fresh = self.store()
        self.assertEqual(
            fresh.source_uris("prod"),
            ["/a/one.jsonl#table=t1", "/a/one.jsonl#table=t2", "/b/two.jsonl"],
        )
        self.assertEqual(fresh.source_uris("prod", "/a/one.jsonl#table="), ["/a/one.jsonl#table=t1", "/a/one.jsonl#table=t2"])
        self.assertEqual(fresh.source_uris("elsewhere"), ["/b/two.jsonl"])
        self.assertEqual(fresh.source_uris("none"), [])
        self.assertEqual(fresh.source_locators("prod", "/a/one.jsonl#table=t1"), {"row:1", "row:2"})
        self.assertEqual(fresh.source_locators("prod", "/missing"), set())
        self.assertTrue(fresh.has_locator_prefix("prod", "/a/one.jsonl#table=t1", "row:"))
        self.assertFalse(fresh.has_locator_prefix("prod", "/a/one.jsonl#table=t1", "x:"))
        self.assertEqual([e["raw"] for e in fresh.iter_source("prod", "/a/one.jsonl#table=t1")], [b"1", b"2"])
        self.assertEqual(list(fresh.iter_source("prod", "/nope")), [])

    def test_read_your_writes_before_flush(self):
        s = self.store()
        e, _ = self.put(s, raw=b"pending")
        self.assertEqual(s.stats()["events"], 1)  # stats flushes
        e2, _ = self.put(s, loc="2", raw=b"pending2")
        self.assertEqual(s.raw_for(e2), b"pending2")
        self.assertEqual(s.source_locators("prod", "/src/a.jsonl"), {"1", "2"})
        self.assertEqual(e, s.get_event(e)["event_id"])

    def test_stats_heads_and_newest_by_producer(self):
        s = self.store()
        self.put(s, loc="1", ts_utc="2026-10-01T00:00:00Z", raw=b"a")
        self.put(s, loc="2", ts_utc="2026-10-01T01:00:00Z", raw=b"b", producer="zz", producer_session_id="S1")
        self.put(s, loc="3", ts_utc="2026-10-01T00:30:00Z", raw=b"c")
        s.flush()
        heads = json.loads((self.root / "state" / "heads.json").read_text())
        self.assertEqual(heads["prod"]["count"], 2)
        self.assertEqual(heads["prod"]["newest_ts"], "2026-10-01T00:30:00Z")
        self.assertEqual(set(heads["zz"]), {"newest_ts", "count", "last_ingest"})
        now = calendar.timegm(time.strptime("2026-10-01T02:00:00", "%Y-%m-%dT%H:%M:%S"))
        newest = self.store().newest_by_producer(now)
        self.assertEqual(newest["zz"], {"newest_ts_utc": "2026-10-01T01:00:00Z", "age_seconds": 3600, "age": "1h0m"})
        self.assertEqual(newest["prod"]["age_seconds"], 5400)
        st = self.store().stats(full=True)
        self.assertEqual((st["events"], st["producers"], st["gaps"], st["files"]), (3, 2, 0, 1 + 1))
        self.assertEqual((st["raw_bytes"], st["sessions"]), (3, 1))

    def test_rebuild_heads_repairs_drift(self):
        s = self.store()
        for i in range(3):
            self.put(s, loc=str(i), raw=b"%d" % i)
        s.flush()
        (self.root / "state" / "heads.json").write_text("{}")
        report = self.store().verify()
        self.assertTrue(report["healthy"])
        self.assertFalse(report["heads_ok"])
        self.assertTrue(self.store().verify(rebuild_heads=True)["healthy"])
        self.assertTrue(self.store().verify()["heads_ok"])
        self.assertEqual(self.store().stats()["events"], 3)

    def test_context_manager_flushes(self):
        with self.store() as s:
            e, _ = self.put(s, raw=b"cm")
        self.assertEqual(self.store().raw_for(e), b"cm")


class TestModes(Base):
    def test_files_0600_dirs_0700(self):
        old = os.umask(0)
        try:
            s = self.store()
            e, _ = self.put(s, raw=b"secret")
            s.set_checkpoint("prod", "u", source_fingerprint="f", committed_locator="1", adapter_version="1")
            s.record_gap("prod", "u", "r")
            s.flush()
            self.put(s, loc="2", raw=b"more")
            s.flush()
            s.compact(min_age_seconds=-1)
        finally:
            os.umask(old)
        seen = 0
        for current, dirs, names in os.walk(self.root):
            for d in dirs:
                self.assertEqual(stat.S_IMODE(os.stat(Path(current, d)).st_mode), 0o700, Path(current, d))
                seen += 1
            for n in names:
                self.assertEqual(stat.S_IMODE(os.stat(Path(current, n)).st_mode), 0o600, Path(current, n))
                seen += 1
        self.assertEqual(stat.S_IMODE(os.stat(self.root).st_mode), 0o700)
        self.assertGreater(seen, 8)


class TestConcurrency(Base):
    def test_two_stores_same_source_lose_nothing_duplicate_nothing(self):
        n_shared, n_own = 150, 100
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def worker(tag: str) -> None:
            try:
                s = arc.ArchiveStore(self.root)
                barrier.wait()
                for i in range(n_shared):  # both write the same locators and bytes
                    self.put(s, loc=f"shared-{i}", raw=b"shared-%d" % i)
                    if i % 7 == 0:
                        s.flush()
                for i in range(n_own):
                    self.put(s, loc=f"{tag}-{i}", raw=f"{tag}-{i}".encode())
                    if i % 5 == 0:
                        s.flush()
                s.close()
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(errors, [])
        reader = self.store()
        expected = {f"shared-{i}" for i in range(n_shared)}
        expected |= {f"{t}-{i}" for t in ("a", "b") for i in range(n_own)}
        self.assertEqual(reader.source_locators("prod", "/src/a.jsonl"), expected)
        on_disk = [r["source_locator"] for r in records_of(self.file_of(reader)) if r["t"] == "ev"]
        self.assertEqual(len(on_disk), len(set(on_disk)), "duplicate events on disk")
        self.assertEqual(set(on_disk), expected)
        report = reader.verify()
        self.assertTrue(report["healthy"], report)
        self.assertEqual(reader.stats()["events"], len(expected))
        self.assertTrue(report["heads_ok"])


class TestPerformance(Base):
    def test_ten_thousand_events_across_fifty_files(self):
        s = self.store()
        start = time.perf_counter()
        for i in range(10_000):
            self.put(s, uri=f"/perf/{i % 50}.jsonl", loc=str(i), raw=(b'{"n":%d,"t":"hello world"}' % i) * 4)
        s.flush()
        elapsed = time.perf_counter() - start
        print(f"\n[perf] 10,000 events / 50 files appended in {elapsed:.2f}s", file=sys.stderr)
        self.assertEqual(s.stats()["events"], 10_000)
        self.assertLess(elapsed, 30)


class TestCli(Base):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = arc.main(["--root", str(self.root), *args])
        return rc, out.getvalue(), err.getvalue()

    def test_stats_verify_compact(self):
        s = self.store()
        for i in range(3):
            self.put(s, loc=str(i), raw=b"c%d" % i)
            s.flush()
        os.utime(self.file_of(s), (time.time() - 9 * 3600,) * 2)
        rc, out, _ = self.run_cli("stats")
        self.assertEqual((rc, json.loads(out)["events"]), (0, 3))
        rc, out, _ = self.run_cli("verify")
        self.assertEqual((rc, json.loads(out)["healthy"]), (0, True))
        rc, out, _ = self.run_cli("compact")
        self.assertEqual((rc, json.loads(out)["compacted"]), (0, 1))
        (self.root / "maintenance.lock").write_text("x")
        rc, _out, err = self.run_cli("compact")
        self.assertEqual(rc, 2)
        self.assertIn("maintenance.lock", err)
        self.file_of(s).write_bytes(self.file_of(s).read_bytes()[:-3] + b"\x00\x00\x00")
        rc, out, _ = self.run_cli("verify")
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
