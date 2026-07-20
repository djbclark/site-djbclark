# NEXT: E5 — Multi-host LiteLLM (difficulty 60/100)

**Funding plan context:** FUND-B Phase D recovery and REVIEW-1 are closed.
Phase E **E1–E4** are complete on the M1 Air control node (LiteLLM loopback,
Goose + local provider, MCP research/templates, SecretSpec + first-run keys).
This baton is **Phase E step E5 only** — extend LiteLLM beyond the Air to the
Intel Mac mini and VPSs. **Do not invent MCP packages, re-open Shortwave/Saner
research, or start Phase F.**

**Recommended AI** (full rows from
`docs/reference/available-ai-models.md`; quota snapshot taken
2026-07-20T14:50Z):

- **Primary —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 ·
  `grok-4.5` · Low, Medium, High (default High) · _Flagship for code +
  agentic work_ — use **High** for cross-platform launchd/systemd refactor;
  live CodexBar saw Grok **0.2.106**, **67%** weekly used, reset Jul 23
  ~2:41am ET.
- **Alternate —** Cursor (GUI) · Cursor · Composer 2.5 · Composer 2.5 ·
  Agent Thinking · _Native agentic coding_ — Cursor Pro ~**59%** monthly used
  (provider cost $1.47/$2), resets Aug 2 ~7:22pm.
  **Also viable:** DeepSeek (api) · DeepSeek · DeepSeek-V4-Flash ·
  `deepseek-v4-flash` · Thinking Mode (Enabled/Disabled) + reasoning_effort ·
  _Fast high-volume_ — for drafting systemd unit templates / docs if Grok
  weekly tightens.
- **Escalation —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra · _Next-gen
  long-running agents_ — use **`cswap` account 2 (djbclark@mit.edu)** if
  judgment on multi-host trust/bind/auth is needed (active; 5h **23%**, 7d
  **20%**, 7d reset Jul 25 ~05:00 local). Original gmail Pro 7d **70%** —
  reserve. **Codex 0.144.6 (oauth) · GPT-5.6 Sol · weekly 100% used until
  Jul 25 ~5:17pm ET — avoid unless necessary.**

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

**Working dir:** `/Users/djbclark/ops/site-djbclark` (LiteLLM role + inventory +
registry). Start with:

```bash
cd /Users/djbclark/ops/site-djbclark
git fetch origin --prune
git pull --ff-only origin master
```

Required reading:

- `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md`
- step2 ground rules/risk register and §6 Phase E (E5 row):
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
- E1 LiteLLM role (loopback baseline to extend):
  `/Users/djbclark/ops/site-djbclark/roles/litellm/README.md`
- E4 human keys checklist (do not regress SecretSpec path):
  `/Users/djbclark/ops/site-djbclark/human/API-KEYS-E4.md`
- Inventory + registry before new hosts/ports:
  `/Users/djbclark/ops/site-djbclark/inventory/hosts.yml`
  `/Users/djbclark/ops/site-djbclark/registry/ports.yml`
  `/Users/djbclark/ops/site-djbclark/registry/paths.yml`
- stayturgid Homebrew prefix pattern (Intel mini `/usr/local` vs Apple Silicon
  `/opt/homebrew`): search `stayturgid_homebrew_prefix` under
  `/Users/djbclark/ops/stayturgid`

---

You are implementing **E5: multi-host LiteLLM** (difficulty 60).

## Live E1–E4 facts (do not re-litigate)

- LiteLLM `1.94.0rc1` as `gui/501/com.djbclark.litellm` on **Air only**,
  `127.0.0.1:4000`; Auto Router v2 tiers + `smart-router`.
- SecretSpec **operational** for LiteLLM on Air: user config
  `~/.config/secretspec/config.toml` uses `[defaults]` `provider=dotenv`
  `profile=default`; site `.env` 0600 gitignored; apply via
  `secretspec run --reason "…" -- just litellm-apply` (or
  `just litellm-apply-secrets`). Values render only into mode-0600 LaunchAgent.
- E4 proven: `/v1/models` 200; Anthropic completions 200; smart-router decision
  log shows different tiers (SIMPLE→gpt-4o-mini, multi-step→gpt-4o/MEDIUM);
  OpenAI-tier primary fails without `OPENAI_API_KEY` but **fallbacks** to
  claude-sonnet-5 when Anthropic is present; `goose run` returned real PONG.
- Goose 1.43.0: `litellm-local` / `smart-router`; filesystem MCP enabled;
  Fieldy disabled until operator OAuth (`human/API-KEYS-E4.md` §4).
- Shortwave/Saner: no Goose-facing MCP (E3) — out of scope.
- D7 routes `/grafana/` `/oo/` `/olivetin/` `/vm/` live; OliveTin/VM
  unauthenticated on single-user tailnet (REVIEW-1) — revisit before widening
  services or adding tailnet users.
- E1–E4 join the **next review slot** scope (not a separate gate in this baton).

## Decided constraints

- New hosts enter `inventory/` + `registry/ports.yml` (and paths if needed)
  **first**; lint with `bin/registry_lint.py`.
- Intel Mac mini: Homebrew prefix `/usr/local` (stayturgid
  `stayturgid_homebrew_prefix` pattern) — do not hardcode only `/opt/homebrew`.
- VPSs: **systemd user units** instead of launchd; no root-only surprise
  network binds without auth plan.
- Loopback-only remains the default bind until multi-host design explicitly
  chooses Tailscale-only or authenticated bind. **No public bind without a
  master key / auth story.** Preserve REVIEW-1: do not casually open OliveTin/VM.
- Prefer extending `roles/litellm` (vars + templates + OS family branches)
  over a second copy-paste role.
- Never commit API keys. Reuse E4 SecretSpec inject pattern on each host that
  needs provider keys.
- Do not start Phase F. Do not re-template Goose MCP packages.

## Task

1. Inventory + registry: declare Mac mini and VPS targets as needed for
   LiteLLM; allocate ports/paths without colliding with existing claims.
2. Refactor `roles/litellm` for multi-host:
   - Darwin Apple Silicon vs Intel Homebrew prefix
   - Linux: systemd user unit equivalent of `com.djbclark.litellm`
   - Keep Auto Router v2 config + disk cache semantics
3. Apply/check/status paths that work from the site justfile (or documented
   per-host recipes) without breaking Air loopback.
4. Verify on each touched host you can reach: process up, models endpoint 200
   (or honest skip if host offline — document), and that Air E4 path still
   works after the refactor.
5. Document operator steps for keys on new hosts (link/extend
   `human/API-KEYS-E4.md` only as needed).

## Carry-forward

- After E5, rewrite `NEXT-PROMPT.md` for **Phase F F1** (system-state-backup +
  hibernate-disk-check) per step2 plan §7, difficulty 30 — unless the plan
  inserts a review slot first (E1–E4 + E5 join next review when that baton is
  written).
- Preserve REVIEW-1: OliveTin/VM unauthenticated on single-user tailnet.
- Carry the AI quota procedure into every next baton.
- LiteLLM cold start under launchd can take ~30–90s; missing-key completion
  storms can wedge the process (heal with bootout/bootstrap + log rotate).

## End of session

Follow `docs/relay/PROTOCOL.md`: record verification evidence, append exactly
one `E5` ledger row, rewrite the baton for the next step with full catalog AI
rows and fresh quota data, commit/push site straight to master, print the new
baton, and copy it with:

```bash
pbcopy < docs/relay/NEXT-PROMPT.md
```
