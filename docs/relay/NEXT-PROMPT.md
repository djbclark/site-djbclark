# NEXT: D9 — Logging Phase-2 close-out verification (difficulty 30/100)

**Funding plan context:** FUND-B revised
(`docs/plans/site-djbclark-phase-d-funding-plans-v1.md`). The recovery month
is complete: M1-R ✓, M1-F ✓, M1-Q ✓, R3 ✓ — **R3 closed Phase D**
(`docs/relay/reviews/r3-phase-d-closeout-review.md`). D9 is the one step the
step2 plan lists in Phase D (§5, difficulty 30) that FUND-B's sequencing
never scheduled (it stops at D8). It is cheap verification work, the last
Phase D box, and the natural next session.

**Recommended AI** (full rows from `docs/reference/available-ai-models.md`;
quota snapshot 2026-07-19 CodexBar: Codex weekly **100% used**, resets
~Jul 25 · Grok 45% used, resets ~Jul 23 · Claude original-acct weekly ~8%
used — recheck with `codexbar usage --format json --provider all`
(slow; run to a file in the background, never pipe through `head`) before
starting):

- **Primary —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 · `grok-4.5` ·
  Low, Medium, High (default High) · _Flagship for code + agentic work_ —
  effort **Medium** (verification + small fixes; the step2 row's "Codex
  (low)" pick is unavailable — Codex weekly is exhausted until ~Jul 25).
- **Alternate —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort (default High on Claude
  Code/API) · _Default for most plans_ — **original account**, Medium.
- **Escalation —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol ·
  `gpt-5.6-sol` · Light, Medium, High, Extra High, Max, Ultra · _Flagship;
  complex coding, computer use, research, cybersecurity_ — Light/Medium,
  **only after the ~Jul 25 weekly reset**.

**Working dir:** `/Users/djbclark/ops/stayturgid` (verification + small
fixes; branch + PR if any code changes) and
`/Users/djbclark/ops/site-djbclark` (ledger/baton; straight to master).
`git fetch origin --prune && git pull --ff-only origin master` in both
before starting. Required reading: `docs/relay/PROTOCOL.md`, step2 plan §0
ground rules + §2 risk register
(`docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`), and the D9
row in that plan's §5.

---

You are running **D9 — Logging Phase-2 close-out** per the step2 plan §5:
verify dual-write (`*.log` + `*.jsonl`) and `state.json` behavior on-device;
confirm `scrape_errors` parses both formats; record any Fire OS path
deviations. Mostly verification; the tests are already merged — your job is
to prove the live fleet matches them and fix only what's small.

## Task

1. On each reachable device (s24, p7a, hd8 — via `ssh s24` etc. over
   Tailscale, `bash -s` per the shell rules): verify repair/watchdog write
   BOTH `*.log` and `*.jsonl` forms under `/sdcard/stayturgid/logs/` (or the
   Fire-OS-deviant path on hd8 — record any deviation), and that
   `state.json` updates correctly across a repair cycle.
2. On the Mac: confirm `scrape_errors` parses both formats (unit evidence +
   a live `just health` error-summary run).
3. Record any Fire OS path deviations in the D9 ledger note (and in the
   design §5 deviation log ONLY if it contradicts a decided rule).
4. Small fixes only; anything larger goes to the ledger as deferred with a
   proposed owner.

## Known state you inherit (from R3 — don't rediscover)

- **p7a**: ssh on 8022 refused as of R3, but the device is alive and
  reporting (fleet-health 7 min, OpenObserve records current). Known
  device-side AutoJs6/a11y issue (`autojs6_a11y_missing`, port
  CLOSED_NO_SHELL — see `~/.config/stayturgid/logs/fleet-health.log`). If
  ssh is still refused, verify p7a's logging via OpenObserve + fleet-health
  evidence instead, note it, and do NOT attempt destructive recovery.
- **hd8**: edge otelcol disabled persistently
  (`stayturgid_otelcol_enabled: false`, pending-incompatible-runtime — see
  M1-R review §D8 for the OCB recovery plan). D9's dual-write check still
  applies on hd8; only the otelcol shipping leg is absent there.
- **Live own-mode config headers** for caddy/vector/grafana/olivetin/VM
  still show pre-M1-Q placeholder headers; the first credentialed
  `site-serverapps mode=apply` will rewrite them (S-3) and restart those
  daemons via the M1-F reload paths — expected, not drift. OpenObserve
  creds come from `~/ops/stayturgid/.env` via secretspec (now 0600; keep it
  that way).
- Verification baseline: full `just test` = 497 passed 1 skipped, suites
  43/11/20/7/15/7; site repo has NO hosted CI (stayturgid CI + registry
  lint are the gates).

## Operator decision owed (not this session's work)

**D7 route scheme (§11 #9)** — Caddy route naming + whether the O-V-G-O UIs
(grafana/OO/olivetin) get front-door routes. Open since D7, forwarded
through R1→M1-R→M1-Q→R3; R3 was the last checkpoint that forwards it.
Operator: decide and either queue a small implementation baton or record
"accepted as-is" in the ledger.

## End of session

Per `docs/relay/PROTOCOL.md`: self-verify with recorded evidence (suites,
identity, lint, health endpoints, device evidence), one `D9` ledger line,
rewrite `NEXT-PROMPT.md` for the next step (Phase E per step2 plan §6, or
the route-scheme implementation if the operator has decided), commit/push
both repos (stayturgid via branch+PR merged same-session if code changed;
both repos end on pulled master, no open PRs/branches), print the new
baton in chat and `pbcopy < docs/relay/NEXT-PROMPT.md`.
