# NEXT: F2 — brew-services audit (difficulty 40/100)

**Funding plan context:** FUND-B Phase D recovery and REVIEW-1 are closed.
Phase E **E1–E5** are complete (LiteLLM loopback + Goose + MCP research +
SecretSpec keys + multi-host role/inventory). Phase F **F1** is complete
(system-state-backup + hibernate-disk-check → `roles/site_agents`). This baton
is **Phase F step F2 only** — audit unmanaged `homebrew.mxcl.*` services and
decide adopt vs remove per service. **Do not start F3 Immich, F4 Brewfile
flock, or re-open E5 deploy to offline mini/VPS.** E1–E5 join the **next
review slot** when that baton is written (not a separate gate in this session).

**Recommended AI** (full rows from
`docs/reference/available-ai-models.md`; quota snapshot taken
2026-07-20T15:17Z):

- **Primary —** Grok 0.2.106 (TUI) · xAI / SpaceXAI · Grok 4.5 ·
  `grok-4.5` · Low, Medium, High (default High) · _Flagship for code +
  agentic work_ — SuperGrok weekly **69%** used, reset Jul 23 ~2:41am ET.
  Good fit for structured audit doc + registry updates (difficulty 40).
  Prefer Medium for this band.
- **Alternate —** Cursor (GUI) · Cursor · Composer 2.5 · Composer 2.5 ·
  Agent Thinking · _Native agentic coding_ — Cursor Pro primary pool
  ~**59%** monthly used (secondary ~52%; tertiary 100%); provider cost
  $1.47/$2; resets Aug 2 ~7:22pm.
  **Also viable:** DeepSeek (api) · DeepSeek · DeepSeek-V4-Flash ·
  `deepseek-v4-flash` · Thinking Mode + reasoning_effort · _Fast high-volume_
  for draft audit tables.
- **Escalation —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort · _Default for most plans_
  — use **`cswap` account 2 (djbclark@mit.edu)** if needed (active; 5h
  **23%**, 7d **20%**, 7d reset Jul 25 ~05:00 local). Original gmail Pro 7d
  **70%** — reserve Fable. **Codex 0.144.6 (oauth) · GPT-5.6 Sol · weekly
  100% used until Jul 25 ~5:17pm ET — avoid.**

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
- step2 ground rules/risk register and §7 Phase F (F2 row):
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
- Current brew-services registry claims:
  `/Users/djbclark/ops/site-djbclark/registry/paths.yml` (`brew_services` section)
- Live inventory snapshot (do not trust from memory):
  `/opt/homebrew/var/system-state/brew-services.txt` and/or
  `brew services list`
- F1 baseline (recent captures):
  `~/system-state/brew-services.txt`

---

You are implementing **F2: brew-services audit** (difficulty 40).

## Live facts (do not re-litigate)

- `registry/paths.yml` `brew_services` lists: `homebrew.mxcl.et` and
  `homebrew.mxcl.ui-tars` → stayturgid; **unmanaged** candidates:
  `postgresql@14` (exit 78 / failing), `redis` (6379), `herdr`, `omlx`.
  Step2 also names **mariadb** — verify whether it exists on this host.
- F1 `roles/site_agents` now captures `brew-services.txt` daily; use it as
  evidence, but re-run live `brew services list` at session start.
- E5 mini + `vps-primary` remain `offline_unprovisioned` — audit is control-node
  (m1-air) only unless operator expands scope.
- REVIEW-1: OliveTin/VM unauthenticated on single-user tailnet — do not widen.
- LiteLLM cold start ~30–90s; missing-key storms can wedge the process.

## Decided constraints

- Produce an audit artifact (role README section, `docs/`, or
  `human/` checklist) with per-service: running?, needed?, port conflict?,
  **recommendation** (adopt into site/stayturgid role vs `brew services stop`
  + remove vs defer).
- Each keep/kill is an **operator decision** — document evidence and a default
  recommendation; do not silently stop production services without recording
  the choice in the ledger. Self-verify with before/after `brew services list`.
- Adopted services update `registry/paths.yml` `brew_services.claimed_by` and
  lint with `bin/registry_lint.py`. No port claims without `registry/ports.yml`.
- just recipes for audit helpers if useful (`brew-services-audit`, etc.).
- Do not start F3/F4. Do not re-deploy offline LiteLLM hosts.

## Task

1. Live survey: `brew services list`, `brew list --formula` for postgres/redis/
   mariadb/herdr/omlx; note exit codes, plist paths, listening ports.
2. Cross-check against registry, ports.yml, stayturgid roles, and F1 snapshot.
3. Write audit doc with per-service table + recommended action; implement only
   **uncontroversial** fixes (e.g. document failing postgres@14, update registry
   notes) — defer destructive stops to explicit operator sign-off recorded in
   ledger.
4. If adopting a service into a role, stop at design + registry claim unless
   the step2 row explicitly includes implementation (F2 is audit-first).

## Carry-forward

- After F2, rewrite `NEXT-PROMPT.md` for **F3** (Immich LaunchDaemon) per
  step2 §7, difficulty 55 — unless a review baton for E1–E5 is inserted first.
- Preserve REVIEW-1 OliveTin/VM note.
- Carry the AI quota procedure into every next baton.
- E5 residual: mini/VPS LiteLLM still planned until hosts join tailnet and
  operator sets `ansible_host` + `site_host_status: online`.

## End of session

Follow `docs/relay/PROTOCOL.md`: record verification evidence, append exactly
one `F2` ledger row, rewrite the baton for the next step with full catalog AI
rows and fresh quota data, commit/push site straight to master, print the new
baton, and copy it with:

```bash
pbcopy < docs/relay/NEXT-PROMPT.md
```
