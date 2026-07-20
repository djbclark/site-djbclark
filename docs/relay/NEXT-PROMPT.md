# NEXT: REVIEW-1 — Whole-repo code review + fix (difficulty 60/100)

**Funding plan context:** Operator re-org 2026-07-19: **E1 (LiteLLM) is
DEFERRED, not cancelled** — this slot is a whole-repo general code review +
fix, sized to spend the operator's remaining Fable 5 allowance inside the
current Claude session window. The previously mandated carry-forward review
(stayturgid#29/#30/#31/#32, AutoJs6#1 + debug17, D7-ROUTES-E) is the deep-dive
core; the sweep widens to whole-repo. **Do not start E1/E2/E3.** The prior E1
baton text is preserved at git `8436cb3:docs/relay/NEXT-PROMPT.md`.

**Recommended AI** (full rows from `docs/reference/available-ai-models.md`;
quotas verified 2026-07-20T02:24Z via per-provider codexbar — NOTE
`codexbar usage --provider all` is currently broken: the Gemini CLI OAuth
probe fails and the whole command exits 1 with empty stdout; call
per-provider instead, backgrounded to a file, never piped through `head`):

- **Primary —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
  Auto) · _Next-gen long-running agents_ — effort **High**. Caveat: the
  lower-left yellow "Auto" control is a separate setting, not the thinking
  level — leave it alone. Quota at write time: Fable-only weekly 26% used
  (resets Jul 25 ~4:59am ET); 5h session 68% used, resets Jul 20 12:29am ET,
  pace projected empty ~1h23m — **the session meter, not Fable weekly, is the
  binding constraint; checkpoint accordingly.**
- **Continuation (if session/Fable dies mid-review) —** Grok 0.2.103 (TUI) ·
  xAI / SpaceXAI · Grok 4.5 · `grok-4.5` · Low, Medium, High (default High) ·
  _Flagship for code + agentic work_ — 64% weekly used, resets Jul 23. Feed it
  `docs/relay/reviews/REVIEW-1-CONTINUATION.md`.
- **Not available —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol ·
  `gpt-5.6-sol` · Light, Medium, High, Extra High, Max, Ultra · _Flagship;
  complex coding, computer use, research, cybersecurity_ — weekly window
  **100% used** until Jul 25 ~5:17pm ET (118.8 credits remain; do not burn
  credits on review work).

**Working dirs:** `~/ops/stayturgid`, `~/ops/site-djbclark`, `~/src/AutoJs6`.
`git fetch origin --prune && git pull --ff-only` in each before starting.
Required reading: `docs/relay/PROTOCOL.md`, tail of `docs/relay/LEDGER.md`
(~15 rows), this baton.

---

You are running **REVIEW-1: whole-repo code review + fix** across the three
repos above.

## Budget & checkpoint discipline (operator-mandated)

- Pace with `ccusage blocks --active` at every phase boundary; recheck Claude
  quota with `codexbar usage --format json --provider claude` (background to a
  file).
- **Checkpoint constantly:** commit at every phase boundary and after each
  fix batch; never hold more than ~20 minutes of uncommitted work. An
  out-of-tokens death must lose almost nothing.
- Create `docs/relay/reviews/REVIEW-1-CONTINUATION.md` (site repo) **in
  Phase 0, before reviewing anything**, and update + commit it at every
  checkpoint. Format it as a paste-able prompt for a successor AI (any
  model): what's done (with commit hashes), findings not yet fixed, exact
  next actions, and the end-of-session obligations (ledger line, E1 baton
  restore). If tokens die mid-run, this file is the recovery point that lets
  the next AI finish the review and continue with the batons.

## Phases

**Phase 0 — preflight.** Pull all three repos; create the continuation file;
`ccusage` baseline; start the per-provider codexbar background call (codex,
claude, grok) for the wrap-up baton.

**Phase 1 — mandated carry-forward review (deep).** These interlock — the
sticky-a11y state machine spans repos (detect in stayturgid monitors, degrade
in comonitor.js, rebind in the AutoJs6 app) and must agree end-to-end:

- stayturgid #29 (merge `199ea20`): `control/bin/dashboard.py`,
  `control/bin/fleet_health_monitor.py`, `control/lib/fleet_health.py`,
  `device/autojs6/lib/comonitor.js`, `device/autojs6/lib/guard.js`,
  `device/termux/py/stayturgid_repair.py`, tests (`comonitor.test.js`,
  `test_fleet_health.py`). Themes: sticky-a11y detect, catastrophic 2h
  window, Fire skip-catastrophic.
- stayturgid #31 (merge `0053f00`): comonitor.js sticky → degraded-not-FAILED.
- AutoJs6 `4c2c3522..3a0f0696` (PR #1 + debug17):
  `AccessibilityBridgeImpl.java`, `AccessibilityTool.kt`,
  `AccessibilityService.kt` (+ strings/bools/version bumps).
- stayturgid #30 (merge `c5e52e1`): `autojs6_deploy_util.py` ASCII-only paths
  + `test_ascii_paths.py`.
- stayturgid #32 (`ab329a5`): serverapp_grafana/openobserve defaults +
  templates, `control/site_contract/{serverapps.py,site_sync.py}`,
  `control/landing/discover.py`, fragments `caddy/stayturgid.caddy.j2` +
  `vector/stayturgid_sinks.yaml.j2` — check against live site
  `registry/ports.yml`.
- site-djbclark D7-ROUTES-E (`HEAD~3..HEAD` at `8436cb3`): the generated
  caddy/vector fragments are **renders of #32's templates — verify parity
  only**, don't re-review logic; the rest is docs/ledger.

**Phase 2 — whole-repo sweep.** Prioritize by blast radius:

1. stayturgid `control/` (health monitors, repair loops, landing,
   site_contract), `device/` (comonitor/guard/termux py), `ansible/` roles +
   module_utils.
2. site-djbclark `bin/registry_lint.py`, `registry/*.yml` consistency,
   `secretspec.toml` declarations, justfile delegation, `generated/` vs
   lockfile.
3. AutoJs6: **fleet-patch surface only** (files changed by the fleet commits
   vs upstream) — do not review the upstream app wholesale.

Lenses: correctness, error handling, security (front-door route auth, secrets
handling, launchd/daemon templates), dead code, test gaps. Log findings to the
continuation file as you go.

**Phase 3 — fix + merge (operator-approved policy).** stayturgid + AutoJs6:
PR branches, merge autonomously only when tests are green — stayturgid:
`just syntax && just check && just test && just lint` + CI; AutoJs6: compile
check only if sources touched. site: direct to master, `just lint` green.
ASCII-only path policy (#30) applies to anything new. Risky or judgment-heavy
findings: document in the review notes, do NOT fix. Do not change behavior
contracts shipped in #29–#32 without evidence of a real bug.

**Phase 4 — leftover budget: deeper passes.** Repeat adversarial passes
(security lens, failure-mode lens, test-coverage-gap lens) over the Phase 1
scope until the session budget is spent. Keep checkpointing.

**Phase 5 — wrap-up (per PROTOCOL.md).**

- Review notes → `docs/relay/reviews/REVIEW-1-findings.md` (what was
  reviewed, findings, fixed vs flagged, evidence).
- One ledger line `REVIEW-1` in `docs/relay/LEDGER.md`.
- **Restore the E1 baton:** rewrite `docs/relay/NEXT-PROMPT.md` for E1
  LiteLLM — recover the text via
  `git show 8436cb3:docs/relay/NEXT-PROMPT.md`, drop its "next project code
  review MUST include" mandate (done by this session), append any
  flagged-not-fixed findings as E-phase notes, and refresh its Recommended AI
  quotas from the fresh codexbar output.
- Commit/push all touched repos; verify front-door
  `https://mac.greyhound-sidemirror.ts.net/{grafana,oo,olivetin,vm}/` curl
  matrix still 200 and O-V-G-O daemons up; mark the continuation file
  COMPLETE.
- Print the new E1 baton and `pbcopy < docs/relay/NEXT-PROMPT.md`.

## Constraints

- **Do not start E1** (no LiteLLM install), E2 Goose, or E3 MCP research.
- Don't break D7-ROUTES-E Caddy routes or O-V-G-O daemons; fleet devices
  (s24/p7a/hd8) read-only.
- No secrets in commits. No Docker. No new ports without `registry/ports.yml`.
- If a fix's tests can't be made green inside the budget, revert the fix,
  flag the finding in the notes, move on.
