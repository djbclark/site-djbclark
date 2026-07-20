# NEXT: FINAL-REVIEW — Project-level final review (difficulty 80/100)

**Funding plan context:** FUND-B Phase D, REVIEW-1, Phase E (E1–E4 live),
Phase F (F1–F4), and REVIEW-EF are closed with zero must-fix findings
(`docs/relay/reviews/REVIEW-EF-findings.md`). All three original residual
gates are now closed:

- **F2** — closed 2026-07-20 (operator sign-off + mechanical keep/kill;
  ledger `RESIDUAL-EF-F2`).
- **F3 / Immich** — closed 2026-07-20 by **full retirement**, not restore
  (ledger `IMMICH-RETIRE`). No Immich role/playbook remains; any Immich
  reference outside `docs/relay/` historical records is a bug.
- **E5** — closed 2026-07-20 by **operator skip** (ledger
  `RESIDUAL-EF-E5-SKIP`). `mac-mini-intel` and `vps-primary` stay
  `site_host_status: offline_unprovisioned` in inventory; do **not** treat
  offline placeholders or untested Linux LiteLLM path as must-fix — they
  are intentional deferred deploy surface.

There is **no further residual triage baton**. This session is the
**project-level final review** mandated by step2 plan §10.

**Recommended AI** (full rows from `docs/reference/available-ai-models.md`;
quota snapshot taken 2026-07-20T17:45Z via `cswap list --json` +
`codexbar usage --format json --provider <name>` — **recheck live**, do not
trust this snapshot):

- **Primary —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort (default High on Claude
  Code/API) · _Default for most plans_ — use **`cswap` account 2
  (djbclark@mit.edu)** (active; 5h **0%** after window reset, 7d **23%**,
  7d reset Jul 25 ~05:00 local). Run at **`xhigh` effort** (or Claude Code
  `/code-review ultra` if available in your surface). This is a frontier
  senior whole-project pass — not a low-effort triage. Original gmail
  account: 5h **0%**, 7d **70%** (reset Jul 24 ~06:00) — alternate Claude
  pool if mit.edu is busy. **Do not use Claude Fable 5** (not on either
  monthly plan; expensive per-use as of 2026-07-20) unless nothing else
  will work.
- **Alternate —** Cursor (GUI) · Cursor · Composer 2.5 · Composer 2.5 ·
  Agent Thinking · _Native agentic coding_ — use **`/code-review ultra`**
  per repo when available. Cursor Pro primary ~**59%** monthly used
  (secondary ~52%, tertiary 100%); provider cost $1.47/$2; resets Aug 2
  ~7:22pm.
- **Escalation / second opinion —** Grok 0.2.106 (TUI) · xAI / SpaceXAI ·
  Grok 4.5 · `grok-4.5` · Low, Medium, High (default High) · _Flagship for
  code + agentic work_ — SuperGrok weekly **71%** used, reset Jul 23
  ~2:41am ET (`2026-07-23T06:41:20Z`). Use High effort if primary dies
  mid-review; write a continuation file before switching.
- **Avoid —** Codex 0.144.6 (oauth) · GPT-5.6 Sol · weekly **100%** used
  until Jul 25 ~5:17pm ET.

**Quota-check procedure (carry forward verbatim in substance):**

- CodexBar does **not** hang; it can take a long time to reply. Give every
  invocation a hard **two-minute timeout**. Query relevant non-Claude
  providers separately, background output to files, and never pipe it
  through `head`, e.g.:
  `timeout 120 codexbar usage --format json --provider grok > /tmp/grok-usage.json`.
- **Ignore everything CodexBar says about Claude.** Two Claude accounts are
  managed by `cswap`; use **`cswap list --json`** as the authority for both
  accounts' usage and name the selected account in any recommendation.
- Recheck live rather than trusting this snapshot. Checkpoint if the 5h
  meter climbs hard mid-review.

**Working dirs:**

```bash
cd /Users/djbclark/ops/site-djbclark
git fetch origin --prune && git pull --ff-only origin master

cd /Users/djbclark/ops/stayturgid
git fetch origin --prune && git pull --ff-only origin master
```

Required reading (in order):

1. `docs/relay/PROTOCOL.md` (site repo)
2. step2 §0 ground rules + §2 risk register + **§10 final review** —
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
3. step1 architecture —
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step1-segmentation-architecture-v1.md`
4. Prior review baselines (do **not** re-open closed dispositions unless
   still true on HEAD):
   - `docs/relay/reviews/REVIEW-1-findings.md` (+ continuation if present)
   - `docs/relay/reviews/r3-phase-d-closeout-review.md`
   - `docs/relay/reviews/REVIEW-EF-findings.md`
   - Phase B notes under `docs/relay/reviews/phase-b-review-*.md` as needed
5. Tail of `docs/relay/LEDGER.md` (especially `IMMICH-RETIRE`,
   `RESIDUAL-EF-F2`, `RESIDUAL-EF-E5-SKIP`)

---

You are running the **project-level final review** for the stayturgid ↔
site-djbclark segmentation + FUND-B implementation chain (step2 Phases
B–F). This is **not** another residual triage and **not** a re-run of
REVIEW-EF alone.

## Scope

### In scope

**site-djbclark** (`~/ops/site-djbclark`), whole project through HEAD
(architecture since `01f6b7c`, relay implementation through current master).
Emphasize:

- Registries (`registry/ports.yml`, `registry/paths.yml`) +
  `bin/registry_lint.py`
- Live roles still present: `litellm`, `goose`, `site_agents` (and any
  remaining site-owned paths)
- Inventory honesty: online hosts vs `offline_unprovisioned` placeholders
- Secrets handling: `secretspec.toml` declarations only; no key-shaped
  values in git; live secret files mode 0600 where applicable
- Justfile recipes + brew projection/flock (F4) — still read-only projector
- Immich **absence**: no role/playbook/registry claims outside historical
  `docs/relay/` records
- Generated/sync surface consistency with stayturgid site-contract

**stayturgid** (`~/ops/stayturgid`), product side of the contract through
HEAD (current master includes post-REVIEW-1 fixes, e.g. PR #33 identity
drift). Emphasize:

- `control/site_contract/` + serverapp adapters (caddy/vector/OO/grafana/
  olivetin/VM/landing paths as shipped)
- `just check` / full `just test` / identity strict / `just site-contract-check`
- Live D7 front-door + loopback health endpoints (read-only)
- No re-opening of device-fleet AutoJs6 product work unless site-contract
  or Mac control-plane code regressed

### Out of scope / do not treat as defects

- Bringing `mac-mini-intel` / `vps-primary` online (E5 **skipped** by
  operator). Offline inventory rows and untested Linux LiteLLM systemd path
  are known deferred deploy surface.
- Restoring Immich (retired by operator).
- Re-litigating F2 keep/kill decisions already executed.
- Re-reviewing AutoJs6 upstream wholesale (fleet-patch surface only if a
  site/control regression points there).
- Burning session budget re-deriving every closed M1-F / R3 / REVIEW-EF
  finding that still holds — **spot-verify** critical closures; deep-read
  only where HEAD drifted or prior reviews never covered.

## Deliverables

1. **Findings document** at
   `docs/relay/reviews/FINAL-REVIEW-findings.md` (site repo) with:
   - Scope + baselines (commit SHAs for both repos at review start)
   - What was re-verified live (commands + results table)
   - Must-fix findings (correctness / safety) — **fix in this session**
     when safe and local; record rollback notes for any daemon/TLS change
   - Architecture / style / deferred items (may ledger-defer; do not invent
     a new multi-month plan)
   - Explicit verdict: project chain complete / complete-with-deferrals /
     blocked-on-must-fix
2. **Fixes** for must-fix only, per repo rules:
   - site-djbclark → straight to master
   - stayturgid → branch + PR, merge same session when green
     (`just check` + `just test` + CI), end on pulled master, no open step
     branch
3. **Self-verification evidence** in the findings doc and ledger note:
   - site: `bin/registry_lint.py` OK; relevant `just *-status` for daemons
     you touch; `git status` clean
   - stayturgid: `just check`, full `just test` (or record exact subset +
     why), identity/site-contract checks as applicable
   - Live health curl sample for D7 front door / loopback services
     (read-only unless fixing)
4. **End of session** per `docs/relay/PROTOCOL.md`:
   - One ledger row with step id `FINAL-REVIEW`
   - Rewrite `NEXT-PROMPT.md`:
     - If verdict is complete (or complete-with-accepted-deferrals only) →
       write a short **CHAIN-COMPLETE** baton (no more implementation
       steps; optional operator-only notes for future E5 if hosts appear)
     - If must-fix remain after a failed fix attempt → baton for the fix
       follow-up or escalation (not Fable 5)
   - Commit/push; print baton; `pbcopy < docs/relay/NEXT-PROMPT.md`

## Review method (recommended)

1. Pull both masters; record SHAs.
2. Skim step1 + step2 §10 + the three major review docs above.
3. Diff since last whole-repo-ish points rather than re-reading the universe:
   - site: at least post-REVIEW-EF residual commits + any gaps REVIEW-EF
     marked out-of-scope that still matter project-wide
   - stayturgid: `git log` since R3 / REVIEW-1 merge tips through HEAD
4. Live mechanical matrix (registry lint, brew-project/diff if cheap,
   litellm/goose/site-agents status, D7 health endpoints, stayturgid check/test).
5. Security lens: secret modes, loopback binds, no secrets in git, launchd
   plist modes for secret-bearing units.
6. Write findings → fix must-fix → re-verify → ledger + CHAIN-COMPLETE (or
   fix baton).

## Invariants

- Prompts self-contained; no secrets in commits.
- Do not manufacture new residual chains for deferred architecture items
  already accepted in prior reviews unless they are now must-fix.
- Human confirmation is not required for ordinary fixes (FUND-B); for
  hard-to-reverse actions use extra before/after health checks and never
  delete the old path in the same session that stands up the new one.
```
