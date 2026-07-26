"""Site desired-state guards for native-agent peer redundancy."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeAgentInventoryTest(unittest.TestCase):
    """Keep peer redundancy in the normal fleet-deploy source of truth."""

    def test_phone_peers_converge_hd8_assignment_via_normal_deploy(self):
        inventory = (ROOT / "inventory/hosts.yml").read_text(encoding="utf-8")
        s24_block = inventory.split("        s24:\n", 1)[1].split(
            "        p7a:\n", 1
        )[0]
        p7a_block = inventory.split("        p7a:\n", 1)[1].split(
            "        hd8:\n", 1
        )[0]
        hd8_block = inventory.split("        hd8:\n", 1)[1].split(
            "      vars:\n", 1
        )[0]
        peer_assignment = (
            "stayturgid_native_agent_peer_targets:\n"
            '            - "100.124.55.39:5555"'
        )

        self.assertIn(peer_assignment, s24_block)
        self.assertIn(peer_assignment, p7a_block)
        self.assertNotIn("stayturgid_native_agent_peer_targets", hd8_block)
