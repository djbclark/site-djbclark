import json
from pathlib import Path

from bin.hindsight_memory_candidates import CandidateLedger


def event(**overrides):
    value = {
        "content": "Hindsight runs loopback-only on the Mac.",
        "kind": "project_fact",
        "scope": "site-djbclark",
        "client": "hermes",
        "agent": "hermes",
        "project": "site-djbclark",
        "workspace": "/tmp/site-djbclark",
        "session_id": "s-1",
        "source_message_ids": ["m-1"],
        "source_uri": "session://s-1/m-1",
        "confidence": 0.95,
    }
    value.update(overrides)
    return value


def test_propose_attaches_provenance_and_ttl(tmp_path: Path):
    ledger = CandidateLedger(tmp_path / "c.sqlite")
    result = ledger.propose(event())
    assert result["status"] == "pending"
    assert result["policy_version"] == "hindsight-retention-v1"
    assert result["expires_at"]
    assert json.loads(result["source_message_ids"]) == ["m-1"]
    ledger.close()


def test_secrets_and_tool_content_are_rejected(tmp_path: Path):
    ledger = CandidateLedger(tmp_path / "c.sqlite")
    assert ledger.propose(event(content="api_key=supersecret"))["status"] == "rejected"
    assert ledger.propose(event(tool_output=True))["status"] == "rejected"
    ledger.close()


def test_transient_language_is_rejected_and_duplicates_are_idempotent(tmp_path: Path):
    ledger = CandidateLedger(tmp_path / "c.sqlite")
    assert ledger.propose(event(content="Maybe we should use this later."))["status"] == "rejected"
    first = ledger.propose(event())
    duplicate = ledger.propose(event())
    assert first["status"] == "pending"
    assert duplicate["status"] == "duplicate"
    assert duplicate["id"] == first["id"]
    ledger.close()


def test_review_then_payload_requires_explicit_approval(tmp_path: Path):
    ledger = CandidateLedger(tmp_path / "c.sqlite")
    first = ledger.propose(event())
    try:
        ledger.payload(first["id"])
        assert False, "pending candidate was promotable"
    except ValueError:
        pass
    approved = ledger.review(first["id"], "approved")
    payload = ledger.payload(approved["id"])
    assert payload["bank_id"] == "site-djbclark"
    assert payload["metadata"]["source_uri"] == "session://s-1/m-1"
    ledger.close()
