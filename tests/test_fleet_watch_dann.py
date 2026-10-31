"""Hermetic Dann checks: real watcher, fake SSH and remote systemd."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "bin/fleet-watch"


class DannWatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        ping = self.home / ".local/bin/hermes-ping"
        ping.parent.mkdir(parents=True)
        self.write(ping, '#!/bin/bash\nprintf "%s\\n" "$*" >> "$HOME/pings"\n')
        self.write(self.bin / "ssh", '#!/bin/bash\nif [[ -n "$RECORD" ]]; then printf "%s\\n" "$RECORD"; else bash -c "${!#}"; fi\n')
        self.write(self.bin / "systemctl", '#!/bin/bash\ncase "$1" in --failed) :;; is-active) echo inactive; exit 3;; show) case "$*" in *Result*) echo success;; *) echo inactive;; esac;; esac\n')
        self.write(self.bin / "cat", '#!/bin/bash\ncase "$1" in /var/lib/pool-verify/last.exit) echo 0;; *) /bin/cat "$@";; esac\n')
        self.write(self.bin / "stat", '#!/bin/bash\necho 99940\n')
        for name in ("date", "gdate"):
            self.write(self.bin / name, '#!/bin/bash\necho 100000\n')

    def write(self, path, text):
        path.write_text(text)
        path.chmod(0o755)

    def watch(self, record=""):
        env = dict(os.environ, HOME=str(self.home), PATH=f"{self.bin}:" + os.environ["PATH"], RECORD=record)
        r = subprocess.run(["bash", str(SCRIPT), "dann"], env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def pings(self):
        p = self.home / "pings"
        return p.read_text() if p.exists() else ""

    def test_malicious_numeric_field_never_executes(self):
        marker = self.home / "executed"
        for record in (f'0 a[$(touch${{IFS}}{marker})] 0 active success inactive',
                       f'a[$(touch${{IFS}}{marker})] 60 0 active success inactive'):
            self.assertEqual(self.watch(record), "dann=probe-invalid")
            self.assertFalse(marker.exists())
        self.assertIn("invalid", self.pings())

    def test_invalid_record_fields(self):
        for record in ("0 60 0 active success", "0 60 0 active success inactive extra",
                       "0 60 nope active success inactive", "0 60 0 bogus success inactive",
                       "0 60 0 active bogus inactive", "0 60 0 active success bogus",
                       "0 -1 0 active success inactive", "0 60 0 active success inactive\nextra"):
            self.assertEqual(self.watch(record), "dann=probe-invalid", record)

    def test_missing_report_does_not_hide_failed_units(self):
        self.assertEqual(self.watch("none 100000 1 active success inactive"), "dann=units-failed")
        self.assertIn("failed systemd", self.pings())

    def test_missing_report_does_not_hide_failed_upgrade(self):
        self.assertEqual(self.watch("none 100000 0 active exit-code failed"), "dann=upgrade-failed")
        self.assertIn("nixos-upgrade failed", self.pings())

    def test_missing_report_does_not_hide_gateway_outage(self):
        self.assertEqual(self.watch("none 100000 0 inactive success inactive"), "dann=gateway-down")
        self.assertIn("is inactive", self.pings())

    def test_healthy_first_deploy_is_quiet_then_expires(self):
        self.assertEqual(self.watch("none 100000 0 active success inactive"), "dann=verify-pending")
        self.assertEqual(self.pings(), "")
        (self.home / ".local/state/fleet-watch/dann-noreport").write_text("0")
        self.assertEqual(self.watch("none 100000 0 active success inactive"), "dann=verify-never-ran")

    def test_inactive_gateway_producer_preserves_record(self):
        self.assertEqual(self.watch(), "dann=gateway-down")
        self.assertIn("is inactive;", self.pings())

    def test_zero_age_is_a_fresh_report(self):
        self.assertEqual(self.watch("0 0 0 active success inactive"), "dann=ok")

    def test_decimal_leading_zero_and_staleness(self):
        self.assertEqual(self.watch("0 000008 000 active success inactive"), "dann=ok")
        self.assertEqual(self.watch("0 129601 0 active success inactive"), "dann=verify-stale")
