import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess

import pytest

from bin.hindsight_memory_candidates import CandidateLedger


def event(**overrides):
    value = {
        "content": "Hindsight runs loopback-only on the Mac.",
        "kind": "fact",
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


def test_rejected_candidate_can_be_reapproved_after_safety_recheck(tmp_path: Path):
    ledger = CandidateLedger(tmp_path / "c.sqlite")
    candidate = ledger.propose(event(content="safe durable fact"))
    rejected = ledger.review(candidate["id"], "rejected")
    assert rejected["status"] == "rejected"

    approved = ledger.review(candidate["id"], "approved")

    assert approved["status"] == "approved"
    assert ledger.payload(candidate["id"])["content"] == "safe durable fact"
    ledger.close()


def test_reapproval_reruns_admission_and_preserves_rejected_state_on_failure(tmp_path: Path):
    ledger = CandidateLedger(tmp_path / "c.sqlite")
    candidate = ledger.propose(event(content="safe durable fact"))
    ledger.review(candidate["id"], "rejected")

    with pytest.raises(ValueError, match="failed admission"):
        ledger.review(candidate["id"], "approved", "password: secret")

    assert ledger.list("approved") == []
    assert [row["id"] for row in ledger.list("rejected")] == [candidate["id"]]
    ledger.close()


def test_review_state_guards_reject_repeated_or_post_promotion_reviews(tmp_path: Path):
    ledger = CandidateLedger(tmp_path / "c.sqlite")
    candidate = ledger.propose(event())
    ledger.review(candidate["id"], "approved")
    with pytest.raises(ValueError, match="already approved"):
        ledger.review(candidate["id"], "rejected")
    ledger.mark_promoted(candidate["id"], "op-1")
    with pytest.raises(ValueError, match="already promoted"):
        ledger.review(candidate["id"], "approved")
    ledger.close()


def test_ids_are_monotonic_and_never_reused_after_deletion(tmp_path: Path):
    ledger = CandidateLedger(tmp_path / "c.sqlite")
    first = ledger.propose(event(content="first fact"))
    ledger.db.execute("DELETE FROM candidates WHERE id=?", (first["id"],))
    ledger.db.commit()
    second = ledger.propose(event(content="second fact"))
    assert (first["id"], second["id"]) == (1, 2)
    ledger.close()


def test_existing_database_migrates_promotion_columns_and_sequence(tmp_path: Path):
    db_path = tmp_path / "legacy.sqlite"
    db = sqlite3.connect(db_path)
    db.execute(
        "CREATE TABLE candidates (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, "
        "content TEXT NOT NULL, content_hash TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, "
        "scope TEXT NOT NULL, client TEXT NOT NULL, agent TEXT NOT NULL, project TEXT NOT NULL, "
        "workspace TEXT, session_id TEXT NOT NULL, source_message_ids TEXT NOT NULL, "
        "source_uri TEXT, captured_at TEXT NOT NULL, policy_version TEXT NOT NULL, "
        "confidence REAL NOT NULL, sensitivity TEXT NOT NULL, origin TEXT NOT NULL, "
        "operation_id TEXT NOT NULL, expires_at TEXT, rejection_reason TEXT, reviewed_at TEXT)"
    )
    db.execute(
        "INSERT INTO candidates (id,status,content,content_hash,kind,scope,client,agent,project,"
        "session_id,source_message_ids,captured_at,policy_version,confidence,sensitivity,origin,operation_id) "
        "VALUES (7,'pending','legacy','legacy-hash','fact','scope','c','a','p','s','[]','t','v',0.9,'i','o','op')"
    )
    db.commit()
    db.close()

    ledger = CandidateLedger(db_path)
    columns = {row[1] for row in ledger.db.execute("PRAGMA table_info(candidates)")}
    assert {"promoted_at", "promotion_operation_id"} <= columns
    assert ledger.propose(event(content="post migration"))["id"] == 8
    ledger.close()


def test_reclassify_validates_kind_and_reports_previous_kind(tmp_path: Path):
    ledger = CandidateLedger(tmp_path / "c.sqlite")
    candidate = ledger.propose(event(kind="fact"))
    changed = ledger.reclassify(candidate["id"], "lesson", "operator correction")
    assert changed["kind"] == "lesson"
    assert changed["_old_kind"] == "fact"
    assert changed["_note"] == "operator correction"
    with pytest.raises(ValueError, match="kind must be one of"):
        ledger.reclassify(candidate["id"], "taxonomy-to-memorize")
    ledger.close()


def test_mark_promoted_is_idempotent_and_blocks_repromotion_payload(tmp_path: Path):
    ledger = CandidateLedger(tmp_path / "c.sqlite")
    candidate = ledger.propose(event())
    ledger.review(candidate["id"], "approved")
    promoted = ledger.mark_promoted(candidate["id"], "operation-1")
    assert promoted["status"] == "promoted"
    assert promoted["promotion_operation_id"] == "operation-1"
    assert ledger.mark_promoted(candidate["id"], "operation-2")["promotion_operation_id"] == "operation-1"
    with pytest.raises(ValueError, match="already promoted"):
        ledger.payload(candidate["id"])
    ledger.close()


def test_hindsight_role_installs_the_canonical_candidate_ledger():
    repo = Path(__file__).resolve().parents[1]
    tasks = (repo / "roles/hindsight/tasks/main.yml").read_text()
    defaults = (repo / "roles/hindsight/defaults/main.yml").read_text()

    assert 'hindsight_candidate_ledger_dir: "{{ hindsight_home }}/.hindsight/bin"' in defaults
    assert 'hindsight_candidate_ledger_path: "{{ hindsight_candidate_ledger_dir }}/hindsight_memory_candidates.py"' in defaults
    assert 'src: "{{ role_path }}/../../bin/hindsight_memory_candidates.py"' in tasks
    assert 'dest: "{{ hindsight_candidate_ledger_path }}"' in tasks
    assert 'mode: "0700"' in tasks


def test_hindsight_role_deploys_exact_ledger_idempotently(tmp_path: Path):
    ansible = shutil.which("ansible-playbook")
    if not ansible:
        pytest.skip("ansible-playbook is not installed")
    repo = Path(__file__).resolve().parents[1]
    command = [
        ansible,
        "-i", "site_hindsight,",
        "-c", "local",
        "--tags", "hindsight_candidate_ledger",
        "-e", f"hindsight_home={tmp_path}",
        "playbooks/hindsight.yml",
    ]
    first = subprocess.run(command, cwd=repo, text=True, capture_output=True, check=True)
    deployed = tmp_path / ".hindsight/bin/hindsight_memory_candidates.py"
    source = repo / "bin/hindsight_memory_candidates.py"
    assert deployed.is_file()
    assert stat.S_IMODE(deployed.stat().st_mode) == 0o700
    assert hashlib.sha256(deployed.read_bytes()).digest() == hashlib.sha256(source.read_bytes()).digest()
    assert "changed=2" in first.stdout

    second = subprocess.run(command, cwd=repo, text=True, capture_output=True, check=True)
    assert "changed=0" in second.stdout
