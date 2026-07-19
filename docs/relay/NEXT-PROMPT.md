# NEXT: D8 — one-device-first edge otelcol rollout (difficulty 60/100)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md`). Quality bar:
**correctness/safety must-fix only**; architecture/style findings may be
deferred to the ledger for M1. No human gates — the old plan row's
**OPERATOR GATE** is replaced by extra self-verification per PROTOCOL.md.

**Recommended AI** (rows from `docs/reference/available-ai-models.md`;
quota basis: step2 plan §1.2 snapshot 2026-07-19 post-D6 — operator steer:
prefer Codex/Cursor/Antigravity, spare Grok, hold Claude for escalations):

- **Primary —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol · `gpt-5.6-sol`
  · Light, Medium, High, Extra High, Max, Ultra · _Flagship; complex coding,
  computer use, research, cybersecurity_ — effort **High**. D8 combines a
  new deployment role with one-device-first live validation and benefits from
  a flagship that can carry the full verification chain.
- **Alt —** Cursor (GUI) · Cursor / SpaceXAI · Grok 4.5 · Grok 4.5 · High,
  Medium, Low · _Joint Cursor + SpaceXAI flagship_ — effort **High**; use the
  Cursor pool before the already-heavily-used direct Grok TUI pool.
- **Escalation —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
  Auto) · _Next-gen long-running agents_ — **new second-Pro account**, effort
  **High**, only if binary/ABI selection, persistent checkpoints, or the live
  offline/reconnect test diverges from the decided design.

**Working dir:** `/Users/djbclark/ops/stayturgid` (implementation; branch +
PR + merge-your-own per PROTOCOL) + `/Users/djbclark/ops/site-djbclark`
(relay/evidence; straight to master).

---

You are executing **D8** (step2 plan row D8 = stayturgid roadmap P4): deploy
an edge `otelcol-contrib` collector that tails the existing device JSONL logs
and exports OTLP HTTP to the Mac's site-owned Vector. **One-device-first is a
hard, non-deviatable rule.** Devices are frequently offline: complete and test
the Mac-side/cache/config half first, then deploy to exactly one reachable
pilot (prefer `s24` if online). Skip unreachable devices with explicit pending
notes; never broaden the first apply to an inventory loop.

## Read first (absolute paths)

1. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` — end-of-session
   ritual, merge your own stayturgid PR, print + `pbcopy` next baton.
2. `/Users/djbclark/ops/site-djbclark/docs/relay/LEDGER.md` — especially D7:
   the dashboard/fleet-health/access-monitor and `just health` remain because
   pre-D8 observability does not yet provide equivalent signal.
3. `/Users/djbclark/ops/site-djbclark/docs/design/phase-d-adapter-design-notes.md`
   §3 (decided rollout order) and §4 (deviation protocol). Do not edit this
   design baseline.
4. Step2 plan §§0–2 + Phase D row D8:
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`.
5. `/Users/djbclark/ops/stayturgid/AGENTS.md`, `docs/handoff.md`, and
   `docs/operations/plans/logging/{01-implementation-plan.md,02-implementation-plan.md}`.
6. Existing `termux_userland` role, its boot scripts, architecture facts,
   `device/termux/py/stayturgid_repair.py`, `device/autojs6/lib/log.js`, and
   their tests. Reuse the already-deployed dual-write paths; do not redo D9.
7. Site inventory/group vars and live Mac endpoints only as needed. Never copy
   live identity or secrets into the public repository.

## Task (step2 row D8, FUND-B-amended)

1. **Mac-side first, no device contact:** choose and pin a real
   `otelcol-contrib` release plus SHA-256 for the supported device ABI; add a
   Mac-side download/cache path so fleet deploys do not redownload per device.
   Fail closed on checksum or architecture mismatch. Verify site-owned Vector
   is listening on `0.0.0.0:4318` and OpenObserve health on `127.0.0.1:5080`
   before any device apply.
2. **Role + config:** extend the appropriate collection role to install the
   cached collector binary, render `otel-config.yaml`, and manage
   `start-otelcol.sh` through the existing Termux boot/supervision pattern.
   Required config: filelog tails `repair.jsonl` and `watchdog.jsonl`;
   `memory_limiter` limit 100 MiB; batch timeout 30 s; `otlphttp` exporter to
   the Mac control-node address on port 4318; `file_storage` extension with a
   checkpoint directory under the app's Termux data dir. Preserve offline
   buffering and do not ingest secrets.
3. **Device-free tests first:** cover template structure, SHA/checksum failure,
   ABI selection, idempotence, boot integration, persistent file-storage
   checkpoints, and rollback. `just check`, `just test`, and pre-commit must be
   green before device contact.
4. **Reachability probe:** announce device use before contact. Probe the fleet
   without changing it. Select exactly one online pilot, preferring `s24`.
   If none is online, finish the Mac-side implementation, ledger every device
   as pending, and do not fabricate live validation.
5. **Pilot deploy only:** deploy to the named pilot and verify the collector
   process/config/checkpoint storage. Do not deploy to a second device until
   both pilot proofs pass:
   - live path: append a unique marker to `repair.jsonl`; find that marker in
     OpenObserve within 60 seconds;
   - offline/reconnect: stop the collector or isolate its network, append a
     second unique marker, restore it, and find the marker in OpenObserve
     within 60 seconds. Confirm offsets persist without replay storms.
6. **Remaining fleet, one at a time:** only after both pilot proofs, deploy to
   each other reachable device separately and verify one live marker each.
   Skip offline devices without failing D8 and record them pending for the next
   contact. Never run overlapping Ansible operations against one device.
7. **Rollback:** prove on the pilot that removing `start-otelcol.sh` from the
   boot integration and stopping the collector disables only edge collection;
   Vector/OpenObserve remain healthy. Restore the pilot after the proof.
8. Do not retire the D7-deferred dashboard, monitors, or `just health` in this
   session. Record whether D8 now supplies enough telemetry for a later
   coverage audit; D8's scope is the collector rollout.

## Constraints

- Fetch/pull master first, then stayturgid branch + PR. Merge your own PR,
  delete the branch, and finish on pulled master. Site relay changes go
  straight to master.
- No secrets in commits. Use the private site inventory only through the
  established resolver. Broken venv: remove/rebuild with `just test-venv`.
- Announce every device interaction in the repository's required format.
  Accessibility remains detection-only; use existing screen-control safety
  if any UI interaction unexpectedly becomes necessary.
- The collector must not block the existing repair/watchdog writers or delete
  legacy `.log`/`.jsonl` files. D9 owns dual-write/state close-out.
- Offline devices are an expected partial result, not permission to weaken the
  pilot proof or deploy fleet-wide first.

## Verification (record exact evidence in the ledger)

- Pinned version, source URL, SHA-256, cache path, and supported ABI evidence.
- Focused tests + `just check` + full `just test` + pre-commit green.
- Pre/post Mac health: Vector 8686, OTLP 4318 listening, OpenObserve 5080, and
  the other six D7 sibling endpoints plus HTTPS all healthy.
- One named pilot, announced before use; live marker and offline/reconnect
  marker visible in OpenObserve with timestamps and ≤60 s latency.
- `file_storage` checkpoint survives collector restart; no duplicate replay
  storm; role second apply is a no-op.
- Per-device outcome table: deployed+verified or pending-offline. Rollback
  tested on pilot and restored.
- stayturgid PR CI green, merged, branch deleted, checkout on pulled master.

## End of session

Follow `PROTOCOL.md`: append ledger line `D8`, then choose the next review or
recovery baton exactly from the FUND-B review-checkpoint sequencing (R3 is the
D5–D8/whole-Phase-D close-out and may be deferred to M1 per the funding plan).
Commit/push site master, print the complete new baton in chat, and run
`pbcopy < docs/relay/NEXT-PROMPT.md`.
