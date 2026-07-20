# NEXT: F3 — Immich LaunchDaemon → site role (difficulty 55/100)

**Funding plan context:** FUND-B Phase D recovery and REVIEW-1 are closed.
Phase E **E1–E5** are complete (LiteLLM + Goose + MCP research + SecretSpec +
multi-host inventory). Phase F **F1** (site_agents) and **F2** (brew-services
audit) are complete. This baton is **Phase F step F3 only** — adopt Immich
system-domain LaunchDaemon into a site role. **Do not start F4 Brewfile flock,
re-open E5 offline mini/VPS deploy, or execute F2 keep/kill stops** (those wait
on operator sign-off in `human/F2-BREW-SERVICES-DECISIONS.md`). E1–E5 join the
**next review slot** when that baton is written (not a separate gate here).

**Recommended AI** (full rows from
`docs/reference/available-ai-models.md`; quota snapshot taken
2026-07-20T15:25Z — recheck live):

- **Primary —** Grok 0.2.106 (TUI) · xAI / SpaceXAI · Grok 4.5 ·
  `grok-4.5` · Low, Medium, High (default High) · _Flagship for code +
  agentic work_ — SuperGrok weekly **69%** used, reset Jul 23 ~2:41am ET.
  Prefer **High** for difficulty 55 (system-domain launchd + service user).
  Self-passoff from F2 is fine if pool allows.
- **Alternate —** Cursor (GUI) · Cursor · Composer 2.5 · Composer 2.5 ·
  Agent Thinking · _Native agentic coding_ — Cursor Pro primary pool
  ~**59%** monthly used (secondary ~52%; tertiary 100%); provider cost
  $1.47/$2; resets Aug 2 ~7:22pm.
- **Escalation —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low/Medium (system launchd judgment) · use **`cswap`
  account 2 (djbclark@mit.edu)** (active; 5h **23%**, 7d **20%**, 7d reset
  Jul 25 ~05:00 local). Original gmail Pro 7d **70%** — reserve for other
  work. **Codex 0.144.6 (oauth) · GPT-5.6 Sol · weekly 100% used until
  Jul 25 ~5:17pm ET — avoid.**

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
- step2 ground rules/risk register and §7 Phase F (F3 row):
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
- F2 audit (do not re-litigate; operator kills still open):
  `/Users/djbclark/ops/site-djbclark/docs/relay/audits/F2-brew-services-audit.md`
- Registry:
  `/Users/djbclark/ops/site-djbclark/registry/paths.yml`
  `/Users/djbclark/ops/site-djbclark/registry/ports.yml`
- Live Immich state (do not trust from memory):
  `launchctl print system/com.immich.*` (and any related labels),
  `/Library/LaunchDaemons/com.immich*`, `/opt/services/immich` if present,
  listening ports via `lsof`/`nc`

---

You are implementing **F3: Immich LaunchDaemon → site role** (difficulty 55).

## Live facts (do not re-litigate)

- Immich is currently an **unmanaged** system-domain LaunchDaemon (paths.yml
  known_gaps: `com.immich.*` among LaunchDaemons). Target shape from step2:
  dedicated user under `/opt/services/immich`, site-owned role, **port
  registration** for Immich web in `registry/ports.yml`.
- Site pattern for user-domain agents: `roles/litellm`, `roles/site_agents`
  (LaunchAgent bootstrap/bootout/kickstart). Immich is **system domain** —
  different privileges, service user, and failure modes. R1 MF-1 style
  disable-on-retire applies if replacing labels.
- E5 mini + `vps-primary` remain `offline_unprovisioned` — F3 is control-node
  (m1-air) only unless operator expands scope.
- REVIEW-1: OliveTin/VM unauthenticated on single-user tailnet — do not widen
  Immich to public/Tailscale without an auth story.
- LiteLLM cold start ~30–90s; missing-key storms can wedge the process.
- F2 defaults (not executed): remove orphaned `postgresql@14` agent; stop+uninstall
  redis if unused; leave mariadb stopped; herdr/omlx claimed site; et system keep.

## Decided constraints

- Prefer idempotent Ansible role under `roles/` + playbook + just recipes matching
  existing site patterns (`site-agents-*`, `litellm-*`).
- Register Immich listen port(s) in `registry/ports.yml` **before** claiming them
  live; lint with `bin/registry_lint.py`.
- Update `registry/paths.yml` for Immich paths / LaunchDaemon labels under `site`.
- System-domain work needs careful verification: before/after `launchctl print`,
  HTTP health to Immich web, rollback command documented (bootout site label +
  restore prior plist if any — do not delete the old path in the same session
  that stands up the new one if both exist).
- No secrets in git. Service user / data dir ownership must be correct.
- Do not start F4. Do not execute F2 destructive stops without operator decisions
  file updates.

## Task

1. Survey live Immich: LaunchDaemon plists, service user, data dir, ports, version,
   how it was installed (docker? binary? brew?).
2. Design + implement site role that owns the daemon under site namespace or
   documents intentional keep of `com.immich.*` labels with site-managed
   content (pick one approach; record deviation if needed).
3. Port/path registry claims; README + just status/apply/check; live apply with
   second-apply idempotence; health checks before and after.
4. Record rollback command in role README and ledger.

## Carry-forward

- After F3, rewrite `NEXT-PROMPT.md` for **F4** (Merged-Brewfile + flock) per
  step2 §7, difficulty 45 — unless a review baton for E1–E5/F is inserted first.
- Preserve REVIEW-1 OliveTin/VM note.
- Carry the AI quota procedure into every next baton.
- F2 residual: operator sign-off on redis remove, postgres@14 agent bootout,
  user-domain et agent cleanup (`human/F2-BREW-SERVICES-DECISIONS.md`).
- E5 residual: mini/VPS LiteLLM planned until hosts join tailnet and operator
  sets `ansible_host` + `site_host_status: online`.

## End of session

Follow `docs/relay/PROTOCOL.md`: record verification evidence, append exactly
one `F3` ledger row, rewrite the baton for the next step with full catalog AI
rows and fresh quota data, commit/push site straight to master, print the new
baton, and copy it with:

```bash
pbcopy < docs/relay/NEXT-PROMPT.md
```
