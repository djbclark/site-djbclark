from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "tcc_audit.py"
SPEC = importlib.util.spec_from_file_location("tcc_audit", SCRIPT)
assert SPEC and SPEC.loader
tcc = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tcc
SPEC.loader.exec_module(tcc)

SCHEMA = (
    "CREATE TABLE access (service TEXT NOT NULL, client TEXT NOT NULL, client_type INTEGER NOT NULL,"
    " auth_value INTEGER NOT NULL, csreq BLOB, last_modified INTEGER NOT NULL DEFAULT 0)"
)
FDA = "kTCCServiceSystemPolicyAllFiles"


class TccAuditTest(unittest.TestCase):
    def make_db(self, rows):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        db = str(Path(d) / "TCC.db")
        con = sqlite3.connect(db)
        con.execute(SCHEMA)
        con.executemany("INSERT INTO access VALUES (?,?,?,?,?,0)", rows)
        con.commit()
        con.close()
        return db

    def run_audit(self, rows, existing, satisfied):
        """existing: paths that exist; satisfied: paths whose csreq check passes."""
        db = self.make_db(rows)
        with mock.patch.object(tcc.os.path, "lexists", lambda p: p in existing), \
             mock.patch.object(tcc, "csreq_text", lambda b: "req" if b else None), \
             mock.patch.object(tcc, "satisfies", lambda p, r: p in satisfied), \
             mock.patch.object(tcc, "bundle_paths", lambda b: [p for p in existing if p.endswith(f"/{b}.app")]), \
             mock.patch.object(tcc, "missing_expected", lambda rows: []):
            return tcc.gather([db])

    def test_classifies_ok_stale_orphan(self):
        rows = [
            (FDA, "/bin/ok", 1, 2, b"x"),
            (FDA, "/bin/resigned", 1, 2, b"x"),
            (FDA, "/opt/homebrew/Cellar/foo/1.0/bin/foo", 1, 2, b"x"),
            (FDA, "com.gone.App", 0, 2, b"x"),
            (FDA, "/bin/denied", 1, 0, b"x"),  # denied rows are ignored
        ]
        _, problems = self.run_audit(rows, {"/bin/ok", "/bin/resigned", "/bin/denied"}, {"/bin/ok"})
        kinds = {k.split("|", 2)[2]: v["kind"] for k, v in problems.items()}
        self.assertEqual(kinds, {
            "/bin/resigned": "stale",
            "/opt/homebrew/Cellar/foo/1.0/bin/foo": "orphan",
            "com.gone.App": "orphan",
        })

    def test_bundle_client_satisfied_by_any_copy(self):
        rows = [(FDA, "com.x.App", 0, 2, b"x")]
        _, problems = self.run_audit(
            rows, {"/A/com.x.App.app", "/B/com.x.App.app"}, {"/B/com.x.App.app"})
        self.assertEqual(problems, {})

    def test_cleanup_script_is_conservative_by_default(self):
        rows = [
            (FDA, "/bin/resigned", 1, 2, b"x"),
            (FDA, "/old/path", 1, 2, b"x"),
            (FDA, "com.gone.App", 0, 2, b"x"),
        ]
        _, problems = self.run_audit(rows, {"/bin/resigned"}, set())
        default = tcc.cleanup_script(problems, False, False)
        self.assertIn("/old/path", default)
        self.assertNotIn("/bin/resigned", default)
        self.assertNotIn("com.gone.App", default)
        full = tcc.cleanup_script(problems, True, True)
        self.assertIn("/bin/resigned", full)
        self.assertIn("com.gone.App", full)

    def test_cleanup_script_escapes_quotes(self):
        rows = [(FDA, "/it's/gone", 1, 2, b"x")]
        _, problems = self.run_audit(rows, set(), set())
        self.assertIn("'/it''s/gone'", tcc.cleanup_script(problems, False, False))

    def test_unreadable_db_is_reported_not_silent(self):
        _, problems = tcc.gather(["/nonexistent-dir/TCC.db"])  # missing db is skipped, not an error
        self.assertEqual(problems, {})
        with mock.patch.object(tcc, "read_rows", side_effect=sqlite3.OperationalError("authorization denied")), \
             mock.patch.object(tcc.os.path, "exists", lambda p: True):
            _, problems = tcc.gather(["/x/TCC.db"])
        self.assertEqual([p["kind"] for p in problems.values()], ["health"])


if __name__ == "__main__":
    unittest.main()
