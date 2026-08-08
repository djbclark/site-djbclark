# Hindsight retention pilot

## Decision

Keep raw automatic transcript retention disabled. Add a local candidate ledger
in front of Hindsight. Automatic capture may nominate candidates, but only
explicit review/promotion can make a candidate durable.

## Modes

1. Explicit-only: current production default.
2. On-demand review: a session or user action submits a candidate event.
3. Shadow: automatic candidates are quarantined and excluded from recall.
4. Scoped periodic pilot: one client, one non-sensitive project bank, after
   shadow gates pass. Never automatic writes to `hermes-shared`.

## Candidate admission

Accept only compact durable facts, confirmed decisions, stable preferences,
verified project conventions, and explicit corrections. Reject credentials,
OAuth artifacts, PII/payment data, raw tool calls/results, logs, diffs,
external instructions, speculation, transient chatter, and missing scope or
provenance. Hindsight Memory Defense remains a second layer.

Each candidate records client, agent, project, workspace, session, source
message IDs, source URI, capture time, policy version, confidence, sensitivity,
origin, content hash, expiry, and operation ID. Candidate storage is local
SQLite and is not itself part of Hindsight recall.

## Pilot gates

The 30-day shadow pilot must show: zero secrets/PII, zero cross-project
contamination, >=95% complete provenance, <=5% materially misleading
candidates, bounded duplicate rate, storage growth <=2x explicit-retain
baseline, acceptable p95 latency/quota use, and verified operation-level
rollback/delete. Any confirmed leak, contamination, poisoning, or failed
rollback pauses the pilot immediately.

## Promotion

A reviewer explicitly approves/rejects/edits candidates. Promotion exports a
Hindsight retain payload with idempotent `document_id` and `operation_id`.
Automatic candidates receive short TTLs (30 days) unless explicitly promoted.
Shared-bank writes remain explicit and curated.

## Current state

- Hindsight 0.9.0 is live on loopback.
- Hermes auto-recall and explicit retain are enabled.
- Hermes/Claude automatic transcript retention remains disabled.
- This worktree adds the candidate ledger and deterministic tests only.

## Future checkpoints

- Day 7: confirm candidate review path has been exercised.
- Day 14: inspect shadow precision, redaction, provenance, and isolation.
- Day 30: decide whether a scoped periodic pilot is justified.
