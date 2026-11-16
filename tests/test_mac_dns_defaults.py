"""roles/mac_dns defaults: the Tailscale CLI path must be the one that exists."""
from __future__ import annotations

import pathlib
import unittest

import yaml

DEFAULTS = pathlib.Path(__file__).resolve().parents[1] / "roles" / "mac_dns" / "defaults" / "main.yml"


class MacDnsDefaultsTests(unittest.TestCase):
    def test_tailscale_bin_is_the_usr_local_wrapper(self) -> None:
        # 2026-11-16: the default resolved to /opt/homebrew/bin/tailscale, which
        # is not installed, so "Read Tailscale prefs" failed every run.
        data = yaml.safe_load(DEFAULTS.read_text())
        self.assertEqual(data["mac_dns_tailscale_bin"], "/usr/local/bin/tailscale")

    def test_accept_dns_stays_on(self) -> None:
        # 2026-11-16: accept-dns=false with the exit node offline broke public DNS.
        data = yaml.safe_load(DEFAULTS.read_text())
        self.assertIs(data["mac_dns_tailscale_accept_dns"], True)


if __name__ == "__main__":
    unittest.main()
