# NEXT: F4 — Merged-Brewfile + flock (difficulty 45/100)

**Funding plan context:** FUND-B Phase D recovery and REVIEW-1 are closed.
Phase E **E1–E5** are complete (LiteLLM + Goose + MCP research + SecretSpec +
multi-host inventory). Phase F **F1–F3** are complete (site_agents,
brew-services audit, Immich LaunchDaemon site role). This baton is **Phase F
step F4 only** — Merged-Brewfile projection + `flock` serialization wrapper in
the site justfile (step1 §4.3). **Do not re-open F3 Immich app restore, do not
execute F2 keep/kill stops** (those wait on operator sign-off in
`human/F2-BREW-SERVICES-DECISIONS.md`), and do not expand E5 mini/VPS deploy
until hosts are online. E1–E5 join the **next review slot** when that baton is
written (not a separate gate here). After F4, either write a Phase E/F review
baton if the plan calls for one, or end Phase F per step2.

**Recommended AI** (full rows from
`docs/reference/available-ai-models.md`; quota snapshot taken
2026-07-20T15:40Z — recheck live):

- **Primary —** Grok 0.2.106 (TUI) · xAI / SpaceXAI · Grok 4.5 ·
  `grok-4.5` · Low, Medium, High (default High) · _Flagship for code +
  agentic work_ — SuperGrok weekly **70%** used, reset Jul 23 ~2:41am ET
  (`2026-07-23T06:41:20Z`). Prefer **Medium** for difficulty 45 (Brewfile
  projection + flock). Self-passoff from F3 is fine if pool allows.
- **Alternate —** Cursor (GUI) · Cursor · Composer 2.5 · Composer 2.5 ·
  Agent Thinking · _Native agentic coding_ — Cursor Pro primary pool
  ~**59%** monthly used (secondary ~52%; tertiary 100%); provider cost
  $1.47/$2; resets Aug 2 ~7:22pm.
- **Escalation —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low/Medium · use **`cswap` account 2 (djbclark@mit.edu)**
  (active; 5h **23%**, 7d **20%**, 7d reset Jul 25 ~05:00 local). Original
  gmail Pro 7d **70%** — reserve for other work. **Codex 0.144.6 (oauth) ·
  GPT-5.6 Sol · weekly 100% used until Jul 25 ~5:17pm ET — avoid.**

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
- step2 ground rules/risk register and §7 Phase F (F4 row):
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
- step1 §4.3 (Merged-Brewfile + flock) if present:
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step1-segmentation-architecture-v1.md`
- F2 audit (do not re-litigate kills):
  `/Users/djbclark/ops/site-djbclark/docs/relay/audits/F2-brew-services-audit.md`
- F3 Immich adoption note (do not re-open app restore):
  `/Users/djbclark/ops/site-djbclark/docs/relay/audits/F3-immich-adoption.md`
- Live Brewfile snapshot (compare target):
  `~/system-state/Brewfile` and/or `/opt/homebrew/var/system-state/Brewfile`
- Registry:
  `/Users/djbclark/ops/site-djbclark/registry/paths.yml`
  `/Users/djbclark/ops/site-djbclark/registry/ports.yml`

---

You are implementing **F4: Merged-Brewfile projection + flock serialization**
(difficulty 45).

## Live facts (do not re-litigate)

- F1–F3 complete. Immich is site-managed under `com.immich.*` (labels kept;
  **disabled** while `/opt/services/immich/app` is missing). Ports 3001–3003
  planned. App restore is out of band.
- F2 defaults (not executed): remove orphaned `postgresql@14` agent; stop+uninstall
  redis if unused; leave mariadb stopped; herdr/omlx claimed site; et system keep.
- E5 mini + `vps-primary` remain `offline_unprovisioned`.
- REVIEW-1: OliveTin/VM unauthenticated on single-user tailnet — do not widen
  unauthenticated surfaces.
- LiteLLM cold start ~30–90s; missing-key storms can wedge the process.
- system-state-backup already captures Brewfile under Homebrew var + `~/system-state`.

## Decided constraints

- Project a **Merged-Brewfile** (or site-owned Brewfile fragment set) per
  step1 §4.3 — compare against live `Brewfile` snapshot; do not blindly
  `brew bundle` destructive uninstalls without operator gates.
- Serialize concurrent brew operations with **`flock`** in the site justfile
  (wrapper recipes), so two sessions cannot clobber each other.
- Prefer idempotent just recipes + docs; lint registry if you touch it.
- No secrets in git. Do not execute F2 destructive stops. Do not reinstall Immich app.

## Task

1. Read step1 §4.3 and current system-state Brewfile snapshot; inventory how
   brew is invoked today (justfile, roles, ad-hoc).
2. Implement Merged-Brewfile projection (site-owned source of truth for
   intended formulae/casks the site claims) + just recipes to generate/diff
   against live snapshot.
3. Add `flock`-based serialization wrapper for brew-touching just recipes.
4. Verify: generate/diff exit 0; flock prevents concurrent writers (simple
   evidence); second run idempotent; document rollback (remove wrapper /
   generated file path).
5. Do not run mass `brew bundle cleanup` / uninstall without operator sign-off.

## Carry-forward

- Preserve REVIEW-1 OliveTin/VM note.
- Carry the AI quota procedure into every next baton.
- F2 residual: operator sign-off on redis remove, postgres@14 agent bootout,
  user-domain et agent cleanup (`human/F2-BREW-SERVICES-DECISIONS.md`).
- F3 residual: Immich app tree missing; labels disabled; re-apply after restore;
  flip ports planned→active when healthy.
- E5 residual: mini/VPS LiteLLM planned until hosts join tailnet and operator
  sets `ansible_host` + `site_host_status: online`.

## End of session

Follow `docs/relay/PROTOCOL.md`: record verification evidence, append exactly
one `F4` ledger row, rewrite the baton for the next step (or Phase E/F review
if that is the plan's next slot) with full catalog AI rows and fresh quota
data, commit/push site straight to master, print the new baton, and copy it
with:

```bash
pbcopy < docs/relay/NEXT-PROMPT.md
```
