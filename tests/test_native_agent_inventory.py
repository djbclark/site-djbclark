"""Site desired-state guards for native-agent peer redundancy."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEVICES_DIR = ROOT / "inventory" / "devices.d"


def _load_device_vars(alias: str) -> dict:
    data = yaml.safe_load((DEVICES_DIR / f"{alias}.yml").read_text(encoding="utf-8"))
    return data["all"]["children"]["stayturgid"]["hosts"][alias]


class NativeAgentInventoryTest(unittest.TestCase):
    """Keep peer redundancy in the normal fleet-deploy source of truth."""

    def test_phone_peers_converge_hd8_assignment_via_normal_deploy(self):
        s24 = _load_device_vars("s24")
        p7a = _load_device_vars("p7a")
        hd8 = _load_device_vars("hd8")

        hd8_address = hd8.get("ansible_host")
        self.assertTrue(hd8_address)
        expected_target = f"{hd8_address}:5555"

        self.assertIn(
            expected_target, s24.get("stayturgid_native_agent_peer_targets", [])
        )
        self.assertIn(
            expected_target, p7a.get("stayturgid_native_agent_peer_targets", [])
        )
        self.assertNotIn("stayturgid_native_agent_peer_targets", hd8)
        self.assertIs(hd8.get("device_usb_heal"), False)
