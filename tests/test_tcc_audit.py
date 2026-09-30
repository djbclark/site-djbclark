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
    " auth_value INTEGER NOT NULL, csreq BLOB, last_modified INTEGER NOT NULL DEFAULT 0,"
    " indirect_object_identifier TEXT NOT NULL DEFAULT 'UNUSED',"
    " PRIMARY KEY (service, client, client_type, indirect_object_identifier))"
)
FDA = "kTCCServiceSystemPolicyAllFiles"


class TccAuditTest(unittest.TestCase):
    def make_db(self, rows):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        db = str(Path(d) / "TCC.db")
        con = sqlite3.connect(db)
        con.execute(SCHEMA)
        con.executemany(
            "INSERT INTO access (service, client, client_type, auth_value, csreq, last_modified,"
            " indirect_object_identifier) VALUES (?,?,?,?,?,7,?)",
            [tuple(r) + ("UNUSED",) if len(r) == 5 else tuple(r) for r in rows],
        )
        con.commit()
        con.close()
        return db

    def run_audit(self, rows, existing, satisfied):
        """existing: paths that exist; satisfied: paths whose csreq check passes."""
        db = self.make_db(rows)
        with mock.patch.object(tcc, "path_exists", lambda p: p in existing), \
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
        kinds = {v["client"]: v["kind"] for v in problems.values()}
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

    def test_cleanup_script_handles_apostrophes(self):
        db = self.make_db([(FDA, "/it's/gone", 1, 2, b"x")])
        with mock.patch.object(tcc, "csreq_text", lambda b: "req"), \
             mock.patch.object(tcc, "path_exists", lambda p: False), \
             mock.patch.object(tcc, "missing_expected", lambda rows: []):
            _, problems = tcc.gather([db])
        r = self.run_script(tcc.cleanup_script(problems, False, False))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.db_clients(db), [])

    # -- generated script behaviour: run it for real against a temp database ------------------

    def run_script(self, script):
        import subprocess as sp
        body = "\n".join(l for l in script.splitlines() if "id -u" not in l)
        return sp.run(["bash", "-c", body], capture_output=True, text=True)

    def db_clients(self, db):
        con = sqlite3.connect(db)
        try:
            return sorted(r[0] for r in con.execute("SELECT client FROM access"))
        finally:
            con.close()

    def test_hostile_client_strings_cannot_run_commands(self):
        marker = Path(tempfile.mkdtemp()) / "pwned"
        evil = f"/x/$(touch {marker})/`touch {marker}`/'q\"\ntouch {marker}\n#"
        db = self.make_db([(FDA, evil, 1, 2, b"x"), (FDA, "/keep", 1, 2, b"x")])
        with mock.patch.object(tcc.os.path, "exists", lambda p: True), \
             mock.patch.object(tcc, "csreq_text", lambda b: "req"), \
             mock.patch.object(tcc, "satisfies", lambda p, r: p == "/keep"), \
             mock.patch.object(tcc, "path_exists", lambda p: p == "/keep"), \
             mock.patch.object(tcc, "missing_expected", lambda rows: []):
            _, problems = tcc.gather([db])
        script = tcc.cleanup_script(problems, False, False)
        r = self.run_script(script)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(marker.exists(), "hostile client string executed a command")
        self.assertEqual(self.db_clients(db), ["/keep"])

    def test_delete_matches_full_primary_key(self):
        db = self.make_db([(FDA, "/gone", 1, 2, b"x")])
        con = sqlite3.connect(db)
        con.execute("INSERT INTO access VALUES (?,?,?,?,?,7,?)", (FDA, "/gone", 1, 2, b"x", "com.other.app"))
        con.commit(); con.close()
        rows_before = 2
        with mock.patch.object(tcc, "csreq_text", lambda b: "req"), \
             mock.patch.object(tcc, "path_exists", lambda p: False), \
             mock.patch.object(tcc, "missing_expected", lambda rows: []):
            _, problems = tcc.gather([db])
        self.assertEqual(len(problems), rows_before)  # distinct keys, not collapsed
        # keep only the UNUSED row's problem: the other target must survive
        only = {k: v for k, v in problems.items() if v["ioi"] == "UNUSED"}
        self.assertEqual(self.run_script(tcc.cleanup_script(only, False, False)).returncode, 0)
        con = sqlite3.connect(db)
        left = con.execute("SELECT indirect_object_identifier FROM access").fetchall()
        con.close()
        self.assertEqual(left, [("com.other.app",)])

    def test_row_changed_since_audit_is_not_deleted(self):
        db = self.make_db([(FDA, "/gone", 1, 2, b"x")])
        with mock.patch.object(tcc, "csreq_text", lambda b: "req"), \
             mock.patch.object(tcc, "path_exists", lambda p: False), \
             mock.patch.object(tcc, "missing_expected", lambda rows: []):
            _, problems = tcc.gather([db])
        script = tcc.cleanup_script(problems, False, False)
        con = sqlite3.connect(db)  # the user re-granted while the script sat in review
        con.execute("UPDATE access SET csreq=X'aa', last_modified=99")
        con.commit(); con.close()
        r = self.run_script(script)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.db_clients(db), ["/gone"])
        self.assertIn("deleted 0 of 1", r.stdout)

    def test_failed_delete_rolls_back_everything_and_backup_is_valid(self):
        db = self.make_db([(FDA, "/gone1", 1, 2, b"x"), (FDA, "/gone2", 1, 2, b"x")])
        con = sqlite3.connect(db)
        con.execute("CREATE TRIGGER nope BEFORE DELETE ON access WHEN old.client='/gone2' "
                    "BEGIN SELECT RAISE(ABORT,'no'); END")
        con.commit(); con.close()
        with mock.patch.object(tcc, "csreq_text", lambda b: "req"), \
             mock.patch.object(tcc, "path_exists", lambda p: False), \
             mock.patch.object(tcc, "missing_expected", lambda rows: []):
            _, problems = tcc.gather([db])
        r = self.run_script(tcc.cleanup_script(problems, False, False))
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.db_clients(db), ["/gone1", "/gone2"])  # all-or-nothing
        backups = list(Path(db).parent.glob("TCC.db.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.db_clients(str(backups[0])), ["/gone1", "/gone2"])

    def test_uncertain_evidence_is_unknown_not_stale_or_orphan(self):
        row = dict(client="/a", client_type=1, csreq=b"x")
        with mock.patch.object(tcc, "path_exists", lambda p: True), \
             mock.patch.object(tcc, "csreq_text", lambda b: "req"):
            with mock.patch.object(tcc, "satisfies", lambda p, r: None):
                self.assertEqual(tcc.classify(row)[0], "unknown")
            with mock.patch.object(tcc, "csreq_text", lambda b: None):
                self.assertEqual(tcc.classify(row)[0], "unknown")
        # two installed copies: one conclusively fails, one cannot be judged -> not stale
        app = dict(client="com.x.App", client_type=0, csreq=b"x")
        with mock.patch.object(tcc, "bundle_paths", lambda b: ["/A.app", "/B.app"]), \
             mock.patch.object(tcc, "path_exists", lambda p: True), \
             mock.patch.object(tcc, "csreq_text", lambda b: "req"), \
             mock.patch.object(tcc, "satisfies", lambda p, r: False if p == "/A.app" else None):
            self.assertEqual(tcc.classify(app)[0], "unknown")
        # LaunchServices unreadable -> unknown, never "app not installed"
        with mock.patch.object(tcc, "bundle_paths", side_effect=RuntimeError("lsregister failed")):
            self.assertEqual(tcc.classify(app)[0], "unknown")

    def test_permission_denied_is_not_a_missing_path(self):
        with mock.patch.object(tcc.os, "lstat", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                tcc.path_exists("/private/other-user/bin/x")
        row = dict(client="/private/other-user/bin/x", client_type=1, csreq=b"x")
        with mock.patch.object(tcc.os, "lstat", side_effect=PermissionError("denied")):
            self.assertEqual(tcc.classify(row)[0], "unknown")

    def test_unreadable_db_is_reported_not_silent(self):
        with mock.patch.object(tcc, "missing_expected", lambda rows: []):  # ignore the real expected.json
            _, problems = tcc.gather(["/nonexistent-dir/TCC.db"])  # missing db is skipped, not an error
            self.assertEqual(problems, {})
            with mock.patch.object(tcc, "read_rows", side_effect=sqlite3.OperationalError("authorization denied")), \
                 mock.patch.object(tcc.os.path, "exists", lambda p: True):
                _, problems = tcc.gather(["/x/TCC.db"])
        self.assertEqual([p["kind"] for p in problems.values()], ["health"])


if __name__ == "__main__":
    unittest.main()
