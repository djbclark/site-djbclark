# NEXT: D7 — retire legacy monitors + old-label close-out (difficulty 50/100)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md`). Quality bar:
**correctness/safety must-fix only**; architecture/style findings may be
deferred to the ledger for M1. No human gates — the old plan row's
**OPERATOR GATE** is replaced by extra self-verification per PROTOCOL.md
(before/after health, tested rollback, never delete old path in the session
that stood up the new one).

**Recommended AI** (rows from `docs/reference/available-ai-models.md`):

- **Primary —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 · `grok-4.5` ·
  Low, Medium, High (default High) · _Flagship for code + agentic work_ —
  effort **High**. Self-passoff pattern from D2–D5 fits: mechanical
  retirement with a clear coverage checklist; deletion of working monitors
  wants High, not Medium.
- **Alt —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort (default High on Claude
  Code/API) · _Default for most plans_ — **original account
  (djbclark@gmail.com)**, use if Grok weekly is exhausted.
- **Escalation:** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
  Auto) · _Next-gen long-running agents_ — **new second-Pro account**, if
  coverage adequacy or launchd retirement ordering turns out to need
  judgment calls beyond the checklist.

**Working dir:** `/Users/djbclark/ops/stayturgid` (implementation; branch +
PR + merge-your-own per PROTOCOL) + `/Users/djbclark/ops/site-djbclark`
(registry + relay; straight to master).

---

You are executing **D7** (step2 plan row D7 = stayturgid roadmap P5): retire
the legacy monitoring stack now that O-V-G-O is site-owned (D1–D6), plus the
deferred old-label launchd close-out from D1–D4. Retirement is **coverage-
gated, not calendar-gated**: for each thing you delete, first record in the
session what covers it now; if coverage is genuinely missing (much is thin
pre-D8), retire what IS covered and defer the rest with an explicit ledger
note — do not delete uncovered monitors to "finish the step".

## Read first (absolute paths)

1. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` (end-of-session
   ritual; merge your own stayturgid PR; print + `pbcopy` next baton).
2. `/Users/djbclark/ops/site-djbclark/docs/relay/LEDGER.md` — D1–D6 lines:
   every "retained until D7" / "control_node can re-render legacy plist"
   note is your worklist.
3. `/Users/djbclark/ops/site-djbclark/docs/design/phase-d-adapter-design-notes.md`
   §1.9 (no-cutover rule: old plists retained + persistently disabled since
   R1 MF-1; step 7 = this session), §4 deviation protocol.
4. Step2 plan §§0–2 + Phase D row D7:
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
5. stayturgid: `control/bin/dashboard.py`, `control/bin/fleet_health_monitor.py`,
   `control/bin/access_monitor.py`, `control/bin/check_fleet_health.py`
   (`just health`), `ansible/roles/control_node/tasks/observability.yml` +
   `agents.yml` (legacy plist re-render residual), `just/fleet.just`.
6. Site: `registry/ports.yml` (4097 fleet-dashboard row), live LaunchAgents:
   `ls ~/Library/LaunchAgents/com.stayturgid.*` and
   `launchctl print-disabled gui/501`.

## Task (step2 plan row D7, FUND-B-amended)

1. **Coverage audit first (written into the session + ledger):** for each of
   `dashboard.py` (4097), `fleet_health_monitor.py`, `access_monitor.py` —
   what does it check/serve, and which O-V-G-O surface covers it now
   (Grafana Fleet Control Room panels are thin pre-D8; OliveTin
   `stayturgid_fleet_health` action wraps `just health`; OpenObserve has
   logs only from Mac vector sources). Retire only the covered ones.
2. **Legacy monitor retirement (covered ones):** bootout + disable their
   launchd agents, remove plists, retire the code paths per roadmap P5;
   `registry/ports.yml`: mark 4097 retired if dashboard.py goes. Landing
   page links to retired UIs must go too (`landing-discover` will flag).
3. **`just health` repoint:** only if VictoriaMetrics/Grafana actually carry
   equivalent signal today — otherwise keep `check_fleet_health.py` and
   ledger-defer the repoint to post-D8 (likely outcome; be honest).
4. **Old-label launchd close-out (D1–D4 deferral, design §1.9 step 7):**
   caddy/vector/openobserve/landing/landing-discover/olivetin (if legacy
   olivetin plist exists — check) have run under `com.djbclark.*` since
   2026-07-19 with legacy `com.stayturgid.*` plists retained on disk and
   persistently disabled (R1 MF-1). Delete the legacy plists **only after**
   verifying each site label is running + healthy in this session, and keep
   the documented rollback possible: before deleting each plist, copy it to
   `~/.config/djbclark/retired-plists/` (git-ignored operator archive) so
   the two-command rollback can be restored by hand if a site label fails
   later. Remove the `control_node` tasks that can re-render legacy
   observability/caddy plists (D2/D3/D5 ledger residual) in the same PR.
5. **§11 #9 (Caddy route naming) with operator:** FUND-B removed human
   gates; treat as: adopt the existing route scheme as-is, document it in
   the site README or registry note, ledger the decision for M1 review.
6. Do not touch D8 scope (edge otelcol) or delete anything a pre-D8 device
   pipeline will need.

## Constraints

- stayturgid conventions: fetch/pull master first, branch + PR, pre-commit
  green, merge your own PR, end on pulled master.
- No secrets in commits; broken venv → `rm -rf` + `just test-venv`.
- Pre/post health both times: caddy(8080) / vector(8686) / openobserve(5080)
  / landing(8088) / victoriametrics(8428) / grafana(3000) / olivetin(1337)
  + HTTPS `https://mac.greyhound-sidemirror.ts.net/`.
- After removing legacy plists: `launchctl print gui/501/com.djbclark.<app>`
  still running for every app, and a login-survivability note (disabled DB
  entries for deleted plists may be cleaned with `launchctl enable` — record
  what you did).

## Verification (self-verify, record evidence in ledger)

- Coverage table (monitor → covering surface | DEFERRED) in the ledger note.
- Focused tests + `just check` green; full `just test` if Python changed;
  `bin/registry_lint.py` OK (run with stayturgid `.venv-test` python).
- All 7 sibling health checks + HTTPS 200 before and after; retired
  listeners actually gone (`lsof -iTCP:4097 -sTCP:LISTEN` empty if retired).
- `ls ~/Library/LaunchAgents/com.stayturgid.*` empty (or each survivor
  ledger-justified); archive copies present under
  `~/.config/djbclark/retired-plists/`.
- stayturgid PR merged, branch deleted, checkout on pulled master, CI green.

## End of session

Follow PROTOCOL.md: ledger line `D7`; rewrite `NEXT-PROMPT.md` as the **D8
baton** (edge otelcol rollout per design notes §3 — one-device-first is a
hard rule; devices frequently offline, do Mac-side first). Commit/push site
to master; print baton and `pbcopy < docs/relay/NEXT-PROMPT.md`.
