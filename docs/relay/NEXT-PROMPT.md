# NEXT: E4 — First-run + SecretSpec / provider keys (difficulty 25/100)

**Funding plan context:** FUND-B Phase D recovery and REVIEW-1 are closed.
Phase E **E1** (LiteLLM loopback), **E2** (Goose + local provider), and
**E3** (MCP research + Goose extension templates) are complete on the M1 Air
control node. This baton is **Phase E step E4 only** — first-run human
checklist plus SecretSpec/provider key wiring so LiteLLM completions and
Fieldy OAuth can succeed. **Do not start E5 multi-host LiteLLM, invent MCP
packages, or re-research Shortwave/Saner (already reported: no Goose-facing
MCP).**

**Recommended AI** (full rows from
`docs/reference/available-ai-models.md`; quota snapshot taken
2026-07-20T14:31Z):

- **Primary —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 ·
  `grok-4.5` · Low, Medium, High (default High) · _Flagship for code +
  agentic work_ — use **Medium** (or Low) for checklist + SecretSpec scaffolding;
  live CodexBar saw Grok **0.2.106**, **66%** weekly used, reset Jul 23
  ~2:41am ET.
- **Alternate —** DeepSeek (api) · DeepSeek · DeepSeek-V4-Flash ·
  `deepseek-v4-flash` · Thinking Mode (Enabled/Disabled) + reasoning_effort ·
  _Fast high-volume_ — good for doc-heavy E4 if Grok weekly is tight.
  **Also viable:** Cursor (GUI) · Cursor · Composer 2.5 · Composer 2.5 ·
  Agent Thinking · _Native agentic coding_ — Cursor Pro ~59% monthly used
  (provider cost $1.47/$2), resets Aug 2 ~7:22pm.
- **Escalation —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol ·
  `gpt-5.6-sol` · Light, Medium, High, Extra High, Max, Ultra · _Flagship;
  complex coding, computer use, research, cybersecurity_ — weekly **100%**
  used until Jul 25 ~5:17pm ET; **avoid unless necessary**.

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

**Working dir:** `/Users/djbclark/ops/site-djbclark` (SecretSpec + roles/litellm
+ roles/goose docs). Start with:

```bash
cd /Users/djbclark/ops/site-djbclark
git fetch origin --prune
git pull --ff-only origin master
```

Required reading:

- `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md`
- step2 ground rules/risk register and §6 Phase E (E4 row):
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
- step0 secrets + post-Ansible human steps (§5 / §7):
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step0-plan-v1.md`
- E1 LiteLLM role:
  `/Users/djbclark/ops/site-djbclark/roles/litellm/README.md`
- E2/E3 Goose role (MCP research + Fieldy OAuth notes):
  `/Users/djbclark/ops/site-djbclark/roles/goose/README.md`
- Declared secrets (no values in git):
  `/Users/djbclark/ops/site-djbclark/secretspec.toml`

---

You are implementing **E4: First-run + SecretSpec / provider keys** on the
M1 Air control node.

## Live E1–E3 facts (do not re-litigate)

- LiteLLM `1.94.0rc1` as `gui/501/com.djbclark.litellm` on `127.0.0.1:4000`;
  `/v1/models` returns tiers + `smart-router`. Completions fail with missing
  credentials until keys are injected (expected).
- SecretSpec is **declared** (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc. in
  `secretspec.toml`) but **not operational** for LiteLLM launchd — no provider
  profile/aliases configured for the litellm apply path.
- Goose **1.43.0** with site-managed:
  - `~/.config/goose/config.yaml` — provider `litellm-local` / `smart-router`
    plus E3 `extensions:` (filesystem **enabled**, fieldy **disabled**,
    Shortwave/Saner **comment stubs only**)
  - `~/.config/goose/custom_providers/litellm-local.json`
- E3 research (committed in `roles/goose/README.md`):
  - **filesystem** — real: `npx -y @modelcontextprotocol/server-filesystem`
  - **Fieldy** — real remote MCP `https://api.fieldy.ai/mcp` (streamable HTTP;
    browser OAuth on first use)
  - **Shortwave** — MCP *client only*; no Goose-facing server (npm 404)
  - **Saner.ai** — no MCP found (npm 404)
- D7 front-door routes `/grafana/`, `/oo/`, `/olivetin/`, `/vm/` are live;
  OliveTin/VictoriaMetrics intentionally unauthenticated on single-user
  tailnet (REVIEW-1) — revisit before widening services or adding tailnet users.
- E1–E3 join the **next review slot** scope (not a separate gate in this baton).

## Decided constraints

- Scope: SecretSpec configuration path + human checklist so operator can enter
  provider keys and complete Fieldy OAuth. Prefer `secretspec run -- … just
  litellm-apply` pattern already documented in `roles/litellm/README.md`.
- **Never commit API keys or OAuth tokens.** Do not paste secrets into chat,
  ledger, or git.
- Do not widen LiteLLM beyond loopback (E5). Do not invent MCP packages.
- Do not re-template Goose extensions except to flip
  `goose_ext_fieldy_enabled: true` **after** documenting OAuth first-run, if
  that is part of the checklist (default remains false until operator is ready).
- Preserve E1–E3 daemons and managed configs.

## Task

1. Document the **API Keys – Human Step** checklist (step0 §5/§7) in an
   appropriate site doc (role README and/or `human/` handoff) covering at
   least:
   - SecretSpec provider init/profile so `OPENAI_API_KEY` and
     `ANTHROPIC_API_KEY` resolve for LiteLLM apply/restart
   - `secretspec run --reason "…" -- just litellm-apply` (or equivalent kickstart)
   - Verify completions: SIMPLE and REASONING prompts route differently
     (LiteLLM decision log) without inventing keys yourself
   - Fieldy: enable extension + browser OAuth first connect
   - Explicit note: Shortwave/Saner have no Goose MCP — out of scope
2. Make SecretSpec **operational for LiteLLM** in the least-privilege way the
   local secretspec setup allows (config init / provider / profile as needed).
   If a step requires the human to paste a key into a secret store UI/CLI,
   stop at that boundary, leave a clear checklist item, and verify everything
   that does not need the secret.
3. After keys are present (operator may complete mid-session if present),
   restart LiteLLM with injected env and prove:
   - `/v1/models` still 200
   - a completion returns 200 (not missing-credential)
   - Goose `goose run` reaches a real model response (or document remaining
     hang cause if keys only partial)
4. Verify standing health: D7 grafana/oo/olivetin/vm 200; goose config still
   0600/0700; `just lint`, inventory, ansible syntax/lint, check mode as
   touched by any role/doc changes.
5. Do **not** start E5 in this session.

## Carry-forward

- After E4, rewrite `NEXT-PROMPT.md` for **E5 multi-host LiteLLM** (difficulty
  60) per step2 plan §6.
- E1–E3 (and E4 when done) join the next review slot's scope.
- Preserve REVIEW-1: OliveTin/VM unauthenticated on single-user tailnet.
- Carry the AI quota procedure into every next baton.
- Note from E3: LiteLLM can become unresponsive under repeated missing-key
  completion retries (12MB+ stderr); heal with launchd bootout/bootstrap and
  rotate logs if needed — cold start under launchd can take ~30–60s.

## End of session

Follow `docs/relay/PROTOCOL.md`: record verification evidence, append exactly
one `E4` ledger row, rewrite the baton for E5 with full catalog AI rows and
fresh quota data, commit/push site straight to master, print the new baton,
and copy it with:

```bash
pbcopy < docs/relay/NEXT-PROMPT.md
```
