# NEXT: R2 — D2–D4 adapter clone review (difficulty review / FUND-B)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md`). Quality bar:
**correctness/safety must-fix only**; architecture/style findings may be
deferred to the ledger for M1. No human gates — self-verify per PROTOCOL.md.

**Recommended AI** (rows from `docs/reference/available-ai-models.md`;
FUND-B Plan B R2 row prefers Grok 4.5 High; Plan A row was Sonnet 5):

- **Primary —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 · `grok-4.5` ·
  Low, Medium, High (default High) · _Flagship for code + agentic work_ —
  effort **High** (FUND-B Plan B R2). Self-passoff from D4 allowed if quota
  holds.
- **Alt —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort (default High) · _Default
  for most plans_ — **original** Claude Pro account (djbclark@gmail.com), not
  the second-Pro Fable pool.
- **Escalation:** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
  Auto) · _Next-gen long-running agents_ — **new second-Pro account**, only
  if a correctness/safety must-fix needs deep design judgment.

**Working dir:** `/Users/djbclark/ops/stayturgid` (read + must-fix PRs) +
`/Users/djbclark/ops/site-djbclark` (ledger/baton; straight to master).

---

You are executing **R2**: architecture/correctness review of adapters D2–D4
(vector, openobserve, landing) against the D1 template and design notes.
This is a **review baton** (PROTOCOL.md § Review batons).

## Read first (absolute paths)

1. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` (review baton
   rules; end-of-session ritual; print + `pbcopy`).
2. `/Users/djbclark/ops/site-djbclark/docs/design/phase-d-adapter-design-notes.md`
   §§0–1, §4 (deviation protocol).
3. `/Users/djbclark/ops/site-djbclark/docs/relay/reviews/r1-d1-adapter-review.md`
   — R1 findings; MF-1/F4/F5 dispositions; clone-safety notes. Do not re-litigate
   accepted F4 (second-apply ansible ensure).
4. `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-phase-d-funding-plans-v1.md`
   § Review checkpoints (R2 scope: D2–D4 + landing fix).
5. stayturgid masters since R1: PRs #20 (D2 vector), #21 (D3 openobserve),
   #22 (D4 landing) → current master. Roles:
   `ansible/roles/serverapp_{vector,openobserve,landing}/`,
   `control/site_contract/serverapps.py`, landing port default in
   `control/landing/landing.py`, discover registry drift in
   `control/landing/discover.py`.
6. Site ledger D2/D3/D4 lines + live labels: `com.djbclark.{caddy,vector,openobserve,landing,landing-discover}`.

## Task

1. Review D2–D4 against design §1 and site-contract §5 for **correctness and
   safety** only (must-fix). Architecture/style → ledger defer to M1.
2. Especially verify:
   - R1 MF-1 pattern cloned (bootout **+** persistent disable) for every
     migrated app; rollback commands documented.
   - No dual-bind races (4317/4318, 5080/5081, 8088).
   - Landing PORT default is 8088 (not 8080).
   - OpenObserve data dir not re-homed.
   - Inject semantics: vector multi-config; openobserve zero writes; landing
     inject refused.
   - Live: all site labels running; legacy labels disabled; sibling health.
3. **Must-fix:** open PR(s), apply live, merge, CI green — same as R1 MF-1.
4. Write findings to
   `docs/relay/reviews/r2-d2-d4-adapter-review.md` (mirror R1 structure).
5. Do **not** re-run full green suites except where code changed (R1 handoff
   style). Spot-check live health.

## Verification (self-verify)

- Review file committed on site master.
- Any must-fix stayturgid PR merged, branch deleted, checkout on master, CI
  green.
- Live: caddy /health 200 + HTTPS 200; vector :8686/health 200; openobserve
  /healthz 200; landing :8088/health 200; print-disabled shows all four
  legacy `com.stayturgid.{caddy,vector,openobserve,landing,landing-discover}`
  disabled (as applicable).

## End of session

Follow PROTOCOL.md: ledger line `R2`; rewrite `NEXT-PROMPT.md` as the **D5
baton** (O-V-G-O completion per step2 row D5; FUND-B: Grok 4.5 High; self-passoff
allowed); commit/push site to master; print baton and
`pbcopy < docs/relay/NEXT-PROMPT.md`.
