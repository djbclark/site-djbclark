# NEXT: F1 — system-state-backup + hibernate-disk-check → site roles (difficulty 30/100)

**Funding plan context:** FUND-B Phase D recovery and REVIEW-1 are closed.
Phase E **E1–E5** are complete (LiteLLM loopback + Goose + MCP research +
SecretSpec keys + multi-host role/inventory). This baton is **Phase F step
F1 only** — adopt the two unmanaged `com.djbclark.*` LaunchAgents into site
roles. **Do not start F2 brew-services audit, F3 Immich, or re-open E5
deploy to offline mini/VPS.** E1–E5 join the **next review slot** when that
baton is written (not a separate gate in this session).

**Recommended AI** (full rows from
`docs/reference/available-ai-models.md`; quota snapshot taken
2026-07-20T15:05Z):

- **Primary —** Cursor (GUI) · Cursor · Composer 2.5 · Composer 2.5 ·
  Agent Thinking · _Native agentic coding_ — Cursor Pro primary pool
  ~**59%** monthly used (secondary ~52%; tertiary 100%); provider cost
  $1.47/$2; resets Aug 2 ~7:22pm. Good fit for mechanical adopt + templating
  (difficulty 30).
- **Alternate —** Grok 0.2.106 (TUI) · xAI / SpaceXAI · Grok 4.5 ·
  `grok-4.5` · Low, Medium, High (default High) · _Flagship for code +
  agentic work_ — SuperGrok weekly **68%** used, reset Jul 23 ~2:41am ET.
  Prefer Low/Medium for this band if Cursor is busy.
  **Also viable:** DeepSeek (api) · DeepSeek · DeepSeek-V4-Flash ·
  `deepseek-v4-flash` · Thinking Mode + reasoning_effort · _Fast high-volume_
  for draft roles/docs.
- **Escalation —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort · _Default for most plans_
  — use **`cswap` account 2 (djbclark@mit.edu)** if needed (active; 5h
  **23%**, 7d **20%**, 7d reset Jul 25 ~05:00 local). Original gmail Pro 7d
  **70%** — reserve Fable. **Codex 0.144.6 (oauth) · GPT-5.6 Sol · weekly
  100% used until Jul 25 ~5:17pm ET — avoid.** Plan named Codex (low) for
  F1 but pool is empty; use Cursor/Grok instead.

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
- step2 ground rules/risk register and §7 Phase F (F1 row):
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
- Live unmanaged agents (adopt, do not invent new behavior):
  - Script: `/Users/djbclark/.local/bin/system-state-backup.sh`
  - Script: `/Users/djbclark/.local/bin/hibernate-disk-check`
  - Plist: `~/Library/LaunchAgents/com.djbclark.system-state-backup.plist`
  - Plist: `~/Library/LaunchAgents/com.djbclark.hibernate-disk-check.plist`
- Path/port registry before new claims:
  `/Users/djbclark/ops/site-djbclark/registry/paths.yml`
  `/Users/djbclark/ops/site-djbclark/registry/ports.yml`
- E5 multi-host Homebrew prefix pattern (scripts currently hardcode
  `/opt/homebrew` — fix while adopting):
  `roles/litellm` + stayturgid `stayturgid_homebrew_prefix`

---

You are implementing **F1: adopt system-state-backup + hibernate-disk-check**
(difficulty 30).

## Live facts (do not re-litigate)

- Both agents already run under `com.djbclark.*` labels (site namespace).
- `system-state-backup.sh`: daily noon calendar; writes
  `/opt/homebrew/var/system-state` + mirror `~/system-state`; log under
  `/opt/homebrew/var/log/system-state-backup.log`. **Hardcodes Apple Silicon
  Homebrew paths** — must become prefix-aware (E5 lesson).
- `hibernate-disk-check`: StartInterval 1800; notifies via `osascript` when
  free GB on `/` &lt; threshold (default 25); state file
  `~/.local/state/hibernate-disk-check.last`.
- E5 LiteLLM multi-host is inventory/role ready; mini + `vps-primary` remain
  `offline_unprovisioned` (not on tailnet). Do not deploy them in F1.
- REVIEW-1: OliveTin/VM unauthenticated on single-user tailnet — do not widen.
- LiteLLM cold start ~30–90s; missing-key storms can wedge the process.

## Decided constraints

- Files into **this** site repo as roles (or one role with two agents); plists
  templated; scripts versioned in-repo and installed to `~/.local/bin` (or
  documented install path) — replace hand-managed copies without dual-running
  conflicting labels.
- Use `com.{{ site_ns }}.*` labels (already `djbclark`).
- Homebrew prefix: arm64 → `/opt/homebrew`, Intel → `/usr/local` (same as
  LiteLLM / stayturgid). Do not leave `/opt/homebrew` only.
- No new ports (neither agent listens). Update `registry/paths.yml` if new
  prefixes appear; lint with `bin/registry_lint.py`.
- just recipes: apply/check/status (or documented).
- Do not start F2/F3/F4. Do not re-template Goose/LiteLLM except path-prefix
  consistency if a shared var is natural.

## Task

1. Capture current live scripts + plists into the site repo (roles + templates).
2. Ansible role(s) install scripts (mode 0755) and render LaunchAgents
   (bootstrap/kickstart semantics consistent with other site agents).
3. Apply on m1-air; second apply changed=0; both labels running / scheduled.
4. Manual one-shot run of each script (or dry verification) without destroying
   useful `~/system-state` history — prefer additive/overwrite-on-success
   behavior already in the script.
5. Document operator notes in role README; rollback = bootout site label and
   note that pre-F1 hand copies may be gone after apply (keep a recovery path:
   git checkout of scripts + bootstrap).

## Carry-forward

- After F1, rewrite `NEXT-PROMPT.md` for **F2** (brew-services audit) per
  step2 §7, difficulty 40 — unless a review baton for E1–E5 is inserted first.
- Preserve REVIEW-1 OliveTin/VM note.
- Carry the AI quota procedure into every next baton.
- E5 residual: mini/VPS LiteLLM still planned until hosts join tailnet and
  operator sets `ansible_host` + `site_host_status: online`.

## End of session

Follow `docs/relay/PROTOCOL.md`: record verification evidence, append exactly
one `F1` ledger row, rewrite the baton for the next step with full catalog AI
rows and fresh quota data, commit/push site straight to master, print the new
baton, and copy it with:

```bash
pbcopy < docs/relay/NEXT-PROMPT.md
```
