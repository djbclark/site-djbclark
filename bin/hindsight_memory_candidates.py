#!/usr/bin/env python3
"""Quarantine and review ledger for Hindsight memory candidates.

This module deliberately does not call Hindsight. Promotion emits a payload
for an explicit, separately audited retain operation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

POLICY_VERSION = "hindsight-retention-v1"
SECRET_PATTERNS = [
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|secret|password|private[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"\b(?:sk|ghp|github_pat|xox[baprs]-)[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
]
TRANSIENT_PATTERNS = [
    re.compile(r"(?i)\b(todo|maybe|i think|probably|brainstorm|temporary|scratch)\b"),
]
ALLOWED_KINDS = {"preference", "decision", "project_fact", "convention", "correction", "lesson"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def redact_or_reject(text: str) -> tuple[str | None, list[str]]:
    reasons: list[str] = []
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            reasons.append("secret_or_sensitive_pattern")
    if reasons:
        return None, reasons
    for pattern in TRANSIENT_PATTERNS:
        if pattern.search(text):
            reasons.append("transient_or_uncertain_language")
    return text.strip(), reasons


def fingerprint(text: str) -> str:
    normalized = " ".join(text.casefold().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


class CandidateLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS candidates (
          id INTEGER PRIMARY KEY,
          status TEXT NOT NULL,
          content TEXT NOT NULL,
          content_hash TEXT NOT NULL UNIQUE,
          kind TEXT NOT NULL,
          scope TEXT NOT NULL,
          client TEXT NOT NULL,
          agent TEXT NOT NULL,
          project TEXT NOT NULL,
          workspace TEXT,
          session_id TEXT NOT NULL,
          source_message_ids TEXT NOT NULL,
          source_uri TEXT,
          captured_at TEXT NOT NULL,
          policy_version TEXT NOT NULL,
          confidence REAL NOT NULL,
          sensitivity TEXT NOT NULL,
          origin TEXT NOT NULL,
          operation_id TEXT NOT NULL,
          expires_at TEXT,
          rejection_reason TEXT,
          reviewed_at TEXT,
          UNIQUE(operation_id, content_hash)
        )""")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def propose(self, event: dict[str, Any]) -> dict[str, Any]:
        required = ["content", "kind", "scope", "client", "agent", "project", "session_id"]
        missing = [key for key in required if not event.get(key)]
        if missing:
            return {"status": "rejected", "reasons": [f"missing:{key}" for key in missing]}
        if event.get("kind") not in ALLOWED_KINDS:
            return {"status": "rejected", "reasons": ["kind_not_allowlisted"]}
        if event.get("tool_call") or event.get("tool_output"):
            return {"status": "rejected", "reasons": ["tool_content_excluded"]}
        content, reasons = redact_or_reject(str(event["content"]))
        if content is None:
            return {"status": "rejected", "reasons": reasons}
        if "transient_or_uncertain_language" in reasons:
            return {"status": "rejected", "reasons": reasons}
        operation_id = str(event.get("operation_id") or f"candidate-{fingerprint(content)[:16]}")
        expires = event.get("expires_at") or (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0).isoformat()
        row = {
            "status": "pending", "content": content, "content_hash": fingerprint(content),
            "kind": event["kind"], "scope": event["scope"], "client": event["client"],
            "agent": event["agent"], "project": event["project"], "workspace": event.get("workspace"),
            "session_id": event["session_id"], "source_message_ids": json.dumps(event.get("source_message_ids", [])),
            "source_uri": event.get("source_uri"), "captured_at": event.get("captured_at", now_iso()),
            "policy_version": POLICY_VERSION, "confidence": float(event.get("confidence", 0.0)),
            "sensitivity": event.get("sensitivity", "internal"), "origin": event.get("origin", "candidate"),
            "operation_id": operation_id, "expires_at": expires,
        }
        try:
            cur = self.db.execute("INSERT INTO candidates (status,content,content_hash,kind,scope,client,agent,project,workspace,session_id,source_message_ids,source_uri,captured_at,policy_version,confidence,sensitivity,origin,operation_id,expires_at) VALUES (:status,:content,:content_hash,:kind,:scope,:client,:agent,:project,:workspace,:session_id,:source_message_ids,:source_uri,:captured_at,:policy_version,:confidence,:sensitivity,:origin,:operation_id,:expires_at)", row)
            self.db.commit()
            row["id"] = cur.lastrowid
            return row
        except sqlite3.IntegrityError:
            existing = self.db.execute("SELECT id,status,content_hash FROM candidates WHERE content_hash=?", (row["content_hash"],)).fetchone()
            return {"status": "duplicate", "id": existing["id"], "content_hash": existing["content_hash"]}

    def list(self, status: str = "pending") -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM candidates WHERE status=? ORDER BY id", (status,)).fetchall()
        return [dict(row) for row in rows]

    def review(self, candidate_id: int, decision: str, edited_content: str | None = None) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        row = self.db.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        content = edited_content.strip() if edited_content else row["content"]
        if decision == "approved":
            safe, reasons = redact_or_reject(content)
            if safe is None or reasons:
                raise ValueError("edited content failed admission: " + ",".join(reasons))
            content = safe
        self.db.execute("UPDATE candidates SET status=?, content=?, reviewed_at=? WHERE id=?", (decision, content, now_iso(), candidate_id))
        self.db.commit()
        return dict(self.db.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone())

    def payload(self, candidate_id: int) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM candidates WHERE id=? AND status='approved'", (candidate_id,)).fetchone()
        if row is None:
            raise ValueError("candidate must be approved before promotion")
        return {
            "content": row["content"], "bank_id": row["scope"], "document_id": f"candidate-{row['id']}-{row['content_hash'][:12]}",
            "operation_id": row["operation_id"], "context": "approved-memory-candidate",
            "metadata": {"client": row["client"], "agent": row["agent"], "project": row["project"], "session_id": row["session_id"], "source_uri": row["source_uri"], "policy_version": row["policy_version"], "origin": row["origin"], "expires_at": row["expires_at"]},
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="~/.hindsight/candidates.sqlite3")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("propose")
    ls = sub.add_parser("list"); ls.add_argument("--status", default="pending")
    rv = sub.add_parser("review"); rv.add_argument("id", type=int); rv.add_argument("decision", choices=["approved", "rejected"]); rv.add_argument("--content")
    pl = sub.add_parser("payload"); pl.add_argument("id", type=int)
    args = parser.parse_args(); ledger = CandidateLedger(args.db)
    try:
        if args.command == "propose": result = ledger.propose(json.load(sys.stdin))
        elif args.command == "list": result = ledger.list(args.status)
        elif args.command == "review": result = ledger.review(args.id, args.decision, args.content)
        else: result = ledger.payload(args.id)
        print(json.dumps(result, indent=2, sort_keys=True, default=str)); return 0
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)})); return 2
    finally: ledger.close()

if __name__ == "__main__":
    raise SystemExit(main())
