# NEXT: REVIEW-EF — Phase E + Phase F close-out review (difficulty 55/100)

**Funding plan context:** FUND-B Phase D recovery and REVIEW-1 are closed.
**Phase E (E1–E5)** and **Phase F (F1–F4)** are complete. This baton is the
**combined Phase E/F code review** before any remaining operator-gated
residuals or a later project-level final review. Scope is site-djbclark
commits from E1 through F4 (and linked docs/registry/roles only). Do **not**
execute F2 keep/kill stops, do **not** reinstall Immich app, do **not** deploy
to offline mini/VPS. Correctness/safety findings must be fixed in-session;
architecture/style may be deferred to the ledger (FUND-B quality bar).

**Recommended AI** (full rows from
`docs/reference/available-ai-models.md`; quota snapshot taken
2026-07-20T15:47Z — recheck live):

- **Primary —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low/Medium · use **`cswap` account 2 (djbclark@mit.edu)**
  (active; 5h **23%**, 7d **20%**, 7d reset Jul 25 ~05:00 local). Prefer
  **Medium** for review (reading-heavy). Original gmail Pro 7d **70%** /
  5h **2%** — reserve gmail weekly for other work.
- **Alternate —** Grok 0.2.106 (TUI) · xAI / SpaceXAI · Grok 4.5 ·
  `grok-4.5` · Low, Medium, High (default High) · _Flagship for code +
  agentic work_ — SuperGrok weekly **70%** used, reset Jul 23 ~2:41am ET
  (`2026-07-23T06:41:20Z`). Prefer **High** if Fable unavailable; self-passoff
  from F4 is fine if pool allows.
- **Escalation —** Cursor (GUI) · Cursor · Composer 2.5 · Composer 2.5 ·
  Agent Thinking · _Native agentic coding_ — Cursor Pro primary pool
  ~**59%** monthly used (secondary ~52%; tertiary 100%); provider cost
  $1.47/$2; resets Aug 2 ~7:22pm. **Codex 0.144.6 (oauth) · GPT-5.6 Sol ·
  weekly 100% used until Jul 25 ~5:17pm ET — avoid.**

**Quota-check procedure — operator update 2026-07-20 (carry forward
verbatim in substance):**

- CodexBar does **not** hang; it can take a long time to reply. Give every
  invocation a hard **two-minute timeout**. Query relevant non-Claude
  providers separately, background output to files, and never pipe it through
  `head`, for example:
  `timeout 120 codexbar usage --format json --provider cursor > /tmp/cursor-usage.json`.
- **Ignore everything CodexBar says about Claude.** There are two Claude
  accounts managed by `cswap`; use **`cswap list --json`** as the authority
  for both accounts' usage and name the selected account in any recommendation.
- Recheck live rather than trusting any snapshot.

**Working dir:** `/Users/djbclark/ops/site-djbclark`

```bash
cd /Users/djbclark/ops/site-djbclark
git fetch origin --prune
git pull --ff-only origin master
```

Required reading:

- `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md`
- step2 ground rules/risk register + §6 Phase E + §7 Phase F:
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
- step1 coordination contracts (ports/paths/brew §4):
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step1-segmentation-architecture-v1.md`
- Funding quality bar (correctness/safety must-fix; style deferrable):
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-phase-d-funding-plans-v1.md`
- Ledger (E1–F4 rows):
  `/Users/djbclark/ops/site-djbclark/docs/relay/LEDGER.md`
- Audits:
  `/Users/djbclark/ops/site-djbclark/docs/relay/audits/F2-brew-services-audit.md`
  `/Users/djbclark/ops/site-djbclark/docs/relay/audits/F3-immich-adoption.md`
  `/Users/djbclark/ops/site-djbclark/docs/relay/audits/F4-merged-brewfile.md`
- Prior review carry-forward (do not re-open resolved items without cause):
  `/Users/djbclark/ops/site-djbclark/docs/relay/reviews/REVIEW-1-findings.md`
- Registry:
  `/Users/djbclark/ops/site-djbclark/registry/ports.yml`
  `/Users/djbclark/ops/site-djbclark/registry/paths.yml`

---

You are performing **REVIEW-EF: Phase E + Phase F close-out review**.

## Live facts (do not re-litigate)

- **E1–E5:** LiteLLM role (loopback :4000, Auto Router v2, launchd/systemd);
  Goose + researched MCP (filesystem real; Fieldy disabled pending OAuth;
  Shortwave/Saner not inventable); SecretSpec dotenv path; multi-host inventory
  with mini+VPS `offline_unprovisioned`.
- **F1:** `roles/site_agents` — system-state-backup + hibernate-disk-check.
- **F2:** brew-services audit only; kills wait on
  `human/F2-BREW-SERVICES-DECISIONS.md` (do not execute).
- **F3:** Immich LaunchDaemons site-managed under `com.immich.*`, **disabled**
  while `/opt/services/immich/app` missing; ports 3001–3003 planned.
- **F4:** Merged-Brewfile from `brew/fragments` → `generated/Merged-Brewfile`;
  `bin/brew_flock.py` serializes brew-touching just recipes; no mass cleanup.
- **REVIEW-1:** OliveTin/VM unauthenticated on single-user tailnet — do not
  widen unauthenticated surfaces.
- LiteLLM cold start ~30–90s; missing-key storms can wedge the process.

## Review scope

1. Walk site commits / ledger rows **E1 → F4** (roles, playbooks, justfile,
   registry, human docs, generated Merged-Brewfile, brew fragments).
2. Re-run standing checks that are mechanical:
   - `bin/registry_lint.py`
   - `just brew-project && just brew-diff` (expect exit 0; read-only)
   - `just litellm-status` / `just goose-status` / `just site-agents-status` /
     `just immich-status` (document actual state; Immich may be disabled)
   - Spot-check D7 health endpoints if still relevant (grafana/oo/olivetin/vm)
3. Hunt correctness/safety: secrets in git, public binds without auth,
   destructive brew/uninstall paths without gates, launchd system-domain
   mistakes, race conditions around brew flock, registry collisions.
4. Fix must-fix findings in this session with evidence. Defer architecture
   polish to ledger with `DEFERRED` notes.
5. Write findings to
   `docs/relay/reviews/REVIEW-EF-findings.md` (or equivalent under
   `docs/relay/reviews/`).

## Out of scope

- F2 redis/pg@14/et-user-agent destructive stops (operator file only).
- Immich app restore / enable while app missing.
- E5 deploy to mini/VPS until hosts online + inventory flipped.
- stayturgid product deep rewrite (site-only unless a site bug requires a
  tiny product fix — then PR+merge per PROTOCOL).

## End of session

Follow `docs/relay/PROTOCOL.md`: record verification evidence, append exactly
one `REVIEW-EF` ledger row, rewrite the baton for the **next** step:

- If must-fix work remains unfinished → same REVIEW-EF escalated, or
- If clean → project-level closeout / residual operator baton (F2 sign-off
  reminder + F3 restore + E5 host-online) **or** end the chain with an
  explicit “phases E/F complete; residuals are operator-scheduled” baton
  per step2 §10 (project-level final review is separate and may wait).

Include full catalog AI rows and fresh quota data. Commit/push site straight
to master, print the new baton, and copy it with:

```bash
pbcopy < docs/relay/NEXT-PROMPT.md
```
