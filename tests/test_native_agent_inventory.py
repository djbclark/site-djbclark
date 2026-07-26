"""Site desired-state guards for native-agent peer redundancy."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_phone_peers_converge_hd8_assignment_via_normal_deploy():
    inventory = yaml.safe_load(
        (ROOT / "inventory/hosts.yml").read_text(encoding="utf-8")
    )
    hosts = inventory["all"]["children"]["stayturgid"]["hosts"]
    expected = ["100.124.55.39:5555"]
    assert hosts["s24"]["stayturgid_native_agent_peer_targets"] == expected
    assert hosts["p7a"]["stayturgid_native_agent_peer_targets"] == expected
    assert "stayturgid_native_agent_peer_targets" not in hosts["hd8"]
