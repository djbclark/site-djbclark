from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
SPEC = importlib.util.spec_from_file_location("plocate_watch", BIN / "plocate_watch.py")
assert SPEC and SPEC.loader
pw = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pw
SPEC.loader.exec_module(pw)


class PlocateWatchTest(unittest.TestCase):
    def check(self, *, age_h=1.0, info=None, log="", fda=None, db_exists=True):
        d = Path(tempfile.mkdtemp())
        db = d / "plocate.db"
        if db_exists:
            db.write_text("x")
            t = time.time() - age_h * 3600
            os.utime(db, (t, t))
        log_path = d / "updatedb.log"
        log_path.write_text(log)
        info = {"last_exit": "0", "runs": 1} if info is None else info
        with mock.patch.object(pw, "DB", str(db)), mock.patch.object(pw, "LOG", log_path), \
             mock.patch.object(pw, "launchd_info", return_value=info or None), \
             mock.patch.object(pw, "fda_problem", return_value=fda):
            return pw.check(36)

    def test_healthy_is_silent(self):
        self.assertEqual(self.check(), [])

    def test_never_exited_yet_is_fine(self):
        self.assertEqual(self.check(info={"last_exit": "(never exited)", "runs": 0}), [])

    def test_stale_or_missing_database(self):
        self.assertIn("50h old", self.check(age_h=50)[0])
        self.assertIn("missing", self.check(db_exists=False)[0])

    def test_job_not_loaded_and_bad_exit(self):
        with mock.patch.object(pw, "launchd_info", return_value=None):
            pass
        self.assertIn("not loaded", " ".join(self.check(info={})))  # {} -> falsy -> None
        self.assertIn("code 1", " ".join(self.check(info={"last_exit": "1", "runs": 3})))

    def test_permission_errors_and_lapsed_grant_are_reported(self):
        out = self.check(log="scanning\nplocate: /x: Operation not permitted\n", fda="Full Disk Access grant is stale")
        self.assertEqual(len(out), 2)
        self.assertIn("Operation not permitted", out[0])
        self.assertIn("stale", out[1])


if __name__ == "__main__":
    unittest.main()
