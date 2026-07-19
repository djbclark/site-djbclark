# NEXT: D5 — O-V-G-O completion under site ownership (difficulty 55/100)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md`). Quality bar:
**correctness/safety must-fix only**; architecture/style findings may be
deferred to the ledger for M1. No human gates — self-verify per PROTOCOL.md.

**Recommended AI** (rows from `docs/reference/available-ai-models.md`):

- **Primary —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 · `grok-4.5` ·
  Low, Medium, High (default High) · _Flagship for code + agentic work_ —
  effort **High** (FUND-B Plan B post-R2). Self-passoff from R2 allowed if
  quota holds.
- **Alt —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol · `gpt-5.6-sol` ·
  Light, Medium, High, Extra High, Max, Ultra · _Flagship; complex coding,
  computer use, research, cybersecurity_ — use while Codex quota lasts.
  Grafana provisioning YAML is fiddly — DeepSeek R1 / V4 Pro is fine for
  drafting dashboards (step2 D5 notes).
- **Escalation:** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
  Auto) · _Next-gen long-running agents_ — **new second-Pro account**, only
  if multi-app cutover fights the D1–D4 pattern.

**Working dir:** `/Users/djbclark/ops/stayturgid` (implementation; branch +
PR + merge-your-own per PROTOCOL) + `/Users/djbclark/ops/site-djbclark`
(registry/inventory + relay; straight to master).

---

You are executing **D5**: complete O-V-G-O under **site** ownership (ADR 005
— not `com.stayturgid.*` labels). OpenObserve is already site-owned (D3).
Install VictoriaMetrics (8428), Grafana (3000), OliveTin (1337) via
serverapp adapters; provision Grafana datasources from registry endpoints;
ship a "Fleet Control Room" dashboard. Do not re-decide architecture — D0
design notes + R1/R2 settle the adapter pattern.

## Read first (absolute paths)

1. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` (end-of-session
   ritual; merge your own stayturgid PR; print + `pbcopy` next baton).
2. `/Users/djbclark/ops/site-djbclark/docs/design/phase-d-adapter-design-notes.md`
   §§0–1 (adapter pattern; §1.9 migration + MF-1 disable), §2 (D6 projections
   — D5 may seed fragment dirs but D6 owns inventory→projection purity), §4
   deviations.
3. `/Users/djbclark/ops/site-djbclark/docs/relay/reviews/r1-d1-adapter-review.md`
   and `docs/relay/reviews/r2-d2-d4-adapter-review.md` — MF-1, F4/F5, inject
   semantics, deferred A-* items (do not re-open F4).
4. Step2 plan §§0–2 + Phase D row D5:
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
5. stayturgid: `docs/architecture/site-contract.md` §5 (grafana /
   victoriametrics / olivetin rows); existing roles
   `serverapp_{caddy,vector,openobserve,landing}/` + `serverapps.py` as
   templates; any prior OVGO plans under `docs/operations/plans/` if present.
6. Site: `registry/ports.yml` (3000 grafana, 8428 victoriametrics, 1337
   olivetin — already planned/site-owned), `inventory/group_vars/all.yml`
   (`site_ns: djbclark`), `docs/relay/LEDGER.md` D3/D4/R2.

## Task (step2 plan row D5)

1. **VictoriaMetrics** own-mode adapter (`serverapp_victoriametrics`): brew
   if absent (never upgrade), config under `~/.config/<site_ns>/…`, label
   `com.<site_ns>.victoriametrics`, health on registry port 8428, MF-1 N/A
   if no legacy product label (new install) — if a foreign unit exists,
   inject = reuse endpoint only (same as openobserve §5.3).
2. **Grafana** own-mode adapter (`serverapp_grafana`): brew if absent;
   provisioning dirs for datasources + dashboards under product fragment
   layout (`generated/stayturgid/fragments/grafana/…` per design §1.6);
   label `com.<site_ns>.grafana`; health 3000; datasources point at
   registry endpoints (openobserve / victoriametrics — **ports from
   registry only**, StrictUndefined).
3. **OliveTin** own-mode adapter: config is a **projection** (§5.3) — may
   land a minimal own unit + empty/actions placeholder; full inventory→
   actions projection is D6. Do not invent a parallel config surface.
4. **Fleet Control Room** Grafana dashboard JSON (product fragment) covering
   enough of fleet health that D7 can later retire legacy monitors — keep
   scope honest if data is thin.
5. Extend `serverapps.py` `KNOWN_APPS` + per-app dispatch + tests.
6. Site: activate ports 3000/8428/1337 as active when listening; registry_lint;
   do not break D1–D4 daemons (verify health after).

Constraints:

- Clone MF-1 disable for any legacy product labels you replace; retain plists
  until D7.
- F4 second-apply ansible ensure accepted.
- Typed refusals already in serverapps.py.
- Do **not** touch caddy/vector/openobserve/landing paths except health
  verification; do not set `*_enabled: false` that deletes rollback plists.
- No secrets in commits; broken venv → `rm -rf` + `just test-venv`.
- New installs (no port conflict) skip migration steps 2–3 of §1.9 — just
  bootstrap site labels. Pre-health siblings before and after.

## Verification (self-verify, record evidence in ledger)

- Focused tests + `just check` green; full `just test` if Python behavior
  changed; `bin/registry_lint.py` OK.
- Live: `com.djbclark.{victoriametrics,grafana,olivetin}` running (or
  honest partial with ledger note); health endpoints 200; Grafana UI loads
  datasources; second apply exit 0 for new apps.
- Siblings untouched: caddy /health + HTTPS 200; vector health 200;
  openobserve healthz 200; landing /health 200.
- stayturgid PR merged, branch deleted, checkout on pulled master, CI green.

## End of session

Follow PROTOCOL.md: ledger line `D5`; rewrite `NEXT-PROMPT.md` as the **D6
baton** (inventory→fragments projections; FUND-B may want Fable 5 judgment —
quote full catalog rows; self-passoff only if still the right tool);
commit/push site to master; print baton and
`pbcopy < docs/relay/NEXT-PROMPT.md`.
