# NEXT: D4 — landing adapter + port default 8080→8088 (difficulty 45/100)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md`). Quality bar:
**correctness/safety must-fix only**; architecture/style findings may be
deferred to the ledger for M1. No human gates — self-verify per PROTOCOL.md.

**Recommended AI** (rows from `docs/reference/available-ai-models.md`):

- **Primary —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 · `grok-4.5` ·
  Low, Medium, High (default High) · _Flagship for code + agentic work_ —
  effort **Medium/High** (FUND-B Plan B row for D2–D4). Self-passoff from D3
  allowed if quota holds.
- **Alt —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol · `gpt-5.6-sol` ·
  Light, Medium, High, Extra High, Max, Ultra · _Flagship; complex coding,
  computer use, research, cybersecurity_ — use while Codex quota lasts.
- **Escalation:** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
  Auto) · _Next-gen long-running agents_ — **new second-Pro account**, only
  if landing plists diverge badly from the D1–D3 pattern.

**Working dir:** `/Users/djbclark/ops/stayturgid` (implementation; branch +
PR + merge-your-own per PROTOCOL) + `/Users/djbclark/ops/site-djbclark`
(registry/inventory edits + relay; straight to master).

---

You are executing **D4**: landing serverapp adapter + close the 8080 footgun.
Do not re-decide architecture — D0 design notes + R1 + D1–D3 patterns settle
the shape. Landing is product-internal today (two hand-managed plists); D4
makes them Ansible-managed under the site namespace.

## Read first (absolute paths)

1. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` (end-of-session
   ritual; merge your own stayturgid PR; print + `pbcopy` next baton).
2. `/Users/djbclark/ops/site-djbclark/docs/design/phase-d-adapter-design-notes.md`
   §§0–1 (adapter pattern; §1.9 migration + R1 persistent-disable), §4
   (deviation protocol).
3. `/Users/djbclark/ops/site-djbclark/docs/relay/reviews/r1-d1-adapter-review.md`
   — MF-1 bootout+disable; F4 second-apply ensure accepted; F5 do not delete
   rollback plists before D7.
4. Step2 plan §§0–2 + Phase D row D4:
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
5. stayturgid: `docs/architecture/site-contract.md` §5 (landing row);
   `control/landing/` (landing.py code default port is still 8080 — **must
   become 8088**; plists already pass 8088); existing hand-managed landing
   plists under `~/Library/LaunchAgents/` (find `*landing*`);
   `control/site_contract/serverapps.py` + roles `serverapp_caddy`,
   `serverapp_vector`, `serverapp_openobserve` (clone shape);
   `tests/python/test_serverapps.py`.
6. Site: `registry/ports.yml` (landing 8088, caddy-health 8080 notes),
   `inventory/group_vars/all.yml` (`site_ns: djbclark`),
   `docs/relay/LEDGER.md` D1–D3 rows.

## Task (step2 plan row D4)

1. **Port footgun:** change `landing.py` code default from 8080 → 8088
   (risk register + registry note). Plists that already pass `--port 8088`
   stay correct; bare runs no longer collide with caddy health.
2. **Ansible-manage both landing plists** under site namespace
   `com.<site_ns>.landing` (and any second landing agent if two exist —
   inventory them first). New role `serverapp_landing` (or extend pattern):
   brew/deps if any, dirs, plist(s), bootstrap, health curl to 8088.
3. **Legacy:** bootout + **persistent disable** of old `com.stayturgid.*`
   landing labels (R1 MF-1); retain plists until D7.
4. **Registry drift check** on `landing-discover` (or equivalent): diff live
   scan vs `registry/ports.yml`, badge/report unregistered listeners.
5. Extend `serverapps.py`: add `landing` to `KNOWN_APPS` with per-app
   dispatch. Modes own/inject/off as appropriate for product-internal app
   (likely own-only or own+off; inject may be n/a — follow §5.3).
6. Site: update `registry/ports.yml` landing owner → site if not already;
   run `bin/registry_lint.py`.

Constraints:

- F4: second own-mode apply re-runs ansible ensure (accepted).
- Typed refusals already in serverapps.py (R1 S-2) — use them.
- Do **not** touch `com.djbclark.caddy` / `vector` / `openobserve` except
  health verification; do not set `*_enabled: false` that deletes rollback
  plists before D7.
- No secrets in commits; broken venv → `rm -rf` + `just test-venv`.
- Migration §1.9 with landing health (8088). Note: 8080 is caddy health —
  do not steal it.

## Verification (self-verify, record evidence in ledger)

- Focused tests + `just check` green; full `just test` if Python behavior
  changed; `bin/registry_lint.py` OK if registry touched.
- Live: site-namespace landing running on 8088; legacy disabled + unloaded;
  legacy plists retained; health/landing URL 200; second apply exit 0.
- Caddy /health 200 + HTTPS 200; vector health 200; openobserve healthz 200.
- landing.py default is 8088 (grep/tests prove it).
- stayturgid PR merged, branch deleted, checkout on pulled master, CI green.

## End of session

Follow PROTOCOL.md exactly: ledger line `D4`; rewrite `NEXT-PROMPT.md` as
the **R2 review baton** (funding-plans § Review checkpoints: R2 after D4 —
scope D2–D4 adapter clones + landing fix; correctness/safety must-fix;
recommended AI per FUND-B Plan B: Grok 4.5 High or Claude Sonnet 5); then
R2 rewrites to D5. Commit/push site to master; print the new baton and
`pbcopy < docs/relay/NEXT-PROMPT.md`.
