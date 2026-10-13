"""Tests for roles/site_agents/files/sqlite-vacuum (the weekly Jobber vacuum)."""

import importlib.machinery
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "roles/site_agents/files/sqlite-vacuum"


def load():
    loader = importlib.machinery.SourceFileLoader("sqlite_vacuum", str(SCRIPT))
    spec = importlib.util.spec_from_loader("sqlite_vacuum", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


sv = load()


def make_db(path: Path, *, keep_every: int = 100, rows: int = 4000, wal: bool = False) -> None:
    """A db whose pages are mostly free: fill it, then delete almost everything."""
    conn = sqlite3.connect(path)
    if wal:
        conn.execute("pragma journal_mode=wal")
    conn.execute("create table t (id integer primary key, body text)")
    conn.execute("create table keep (id integer primary key, v text)")
    conn.executemany("insert into t(body) values (?)", [("x" * 2000,)] * rows)
    conn.executemany("insert into keep(v) values (?)", [(str(i),) for i in range(10)])
    conn.commit()
    conn.execute("delete from t where id % ? != 0", (keep_every,))
    conn.commit()
    conn.close()


class TestSqliteVacuum(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_one(self, path, **kw):
        kw.setdefault("min_ratio", 0.3)
        kw.setdefault("min_bytes", 1000)
        kw.setdefault("dry_run", False)
        return sv.process(path, **kw)

    def test_vacuum_shrinks_and_keeps_rows(self):
        db = self.dir / "a.db"
        make_db(db)
        before = db.stat().st_size
        counts = sv.row_counts(db)
        line, ok = self.run_one(db)
        self.assertTrue(ok, line)
        self.assertIn("integrity=ok", line)
        self.assertLess(db.stat().st_size, before / 5)
        self.assertEqual(sv.row_counts(db), counts)
        self.assertEqual(list(self.dir.glob("*clone*")), [])

    def test_wal_database(self):
        db = self.dir / "w.db"
        make_db(db, wal=True)
        counts = sv.row_counts(db)
        line, ok = self.run_one(db)
        self.assertTrue(ok, line)
        self.assertEqual(sv.row_counts(db), counts)
        self.assertEqual(list(self.dir.glob("*clone*")), [])

    def test_open_database_is_skipped(self):
        db = self.dir / "busy.db"
        make_db(db)
        before = db.stat().st_size
        holder = sqlite3.connect(db)
        holder.execute("select 1").fetchone()
        try:
            line, ok = self.run_one(db)
        finally:
            holder.close()
        self.assertTrue(ok)
        self.assertIn("retry next run", line)
        self.assertEqual(db.stat().st_size, before)

    def test_below_threshold_is_skipped(self):
        db = self.dir / "full.db"
        conn = sqlite3.connect(db)
        conn.execute("create table t (id integer primary key, b text)")
        conn.executemany("insert into t(b) values (?)", [("y" * 500,)] * 2000)
        conn.commit()
        conn.close()
        before = db.stat().st_size
        line, ok = self.run_one(db)
        self.assertTrue(ok)
        self.assertIn("below threshold", line)
        self.assertEqual(db.stat().st_size, before)

    def test_min_bytes_threshold(self):
        db = self.dir / "small.db"
        make_db(db)
        line, _ = self.run_one(db, min_bytes=10**12)
        self.assertIn("below threshold", line)

    def test_dry_run_changes_nothing(self):
        db = self.dir / "dry.db"
        make_db(db)
        before = db.stat().st_size
        line, ok = self.run_one(db, dry_run=True)
        self.assertTrue(ok)
        self.assertIn("would vacuum", line)
        self.assertEqual(db.stat().st_size, before)

    def test_not_sqlite_and_absent(self):
        junk = self.dir / "junk.db"
        junk.write_bytes(b"not a database" * 100)
        self.assertIn("not a SQLite file", self.run_one(junk)[0])
        self.assertIn("absent", self.run_one(self.dir / "missing.db")[0])

    def test_expand_globs_and_home_relative(self):
        sub = self.dir / "backups"
        sub.mkdir()
        (sub / "x.sqlite").write_bytes(b"")
        (sub / "x.sqlite.sqlite-vacuum-clone").write_bytes(b"")
        got = sv.expand(["backups/*.sqlite", "backups/x.sqlite"], self.dir)
        self.assertEqual(got, [sub / "x.sqlite"])

    def test_main_exit_code(self):
        db = self.dir / "m.db"
        make_db(db)
        self.assertEqual(sv.main(["--min-bytes", "1000", str(db)]), 0)


if __name__ == "__main__":
    unittest.main()
