# NEXT: E3 — MCP server research + Goose extension config (difficulty 55/100)

**Funding plan context:** FUND-B Phase D recovery and REVIEW-1 are closed.
Phase E E1 (LiteLLM loopback proxy) and **E2 (Goose + local provider)** are
complete on the M1 Air control node. This baton is **Phase E step E3 only** —
research real MCP vendor offerings and template Goose extension configuration.
**Do not configure SecretSpec or provider API keys (E4), widen LiteLLM beyond
loopback (E5), or install guessed MCP package names.**

**Recommended AI** (full rows from
`docs/reference/available-ai-models.md`; quota snapshot taken
2026-07-20T14:18Z):

- **Primary —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 ·
  `grok-4.5` · Low, Medium, High (default High) · _Flagship for code +
  agentic work_ — use **Medium** for vendor/MCP research; live CodexBar saw
  Grok **0.2.106**, **65%** weekly used, reset Jul 23 ~2:41am ET.
- **Alternate —** DeepSeek (api) · DeepSeek · DeepSeek V3.x / R1 series ·
  various · Thinking Mode (Enabled/Disabled) + reasoning_effort · _Prior
  generations_ — use for parallel research if Grok weekly is tight.
- **Escalation —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol ·
  `gpt-5.6-sol` · Light, Medium, High, Extra High, Max, Ultra · _Flagship;
  complex coding, computer use, research, cybersecurity_ — use **High** only
  for templating/idempotent Ansible after research is complete. Codex weekly was
  **100%** used until Jul 25 ~5:17pm ET; avoid unless necessary.

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

**Working dir:** `/Users/djbclark/ops/site-djbclark` (extend
`roles/goose`). Start with:

```bash
cd /Users/djbclark/ops/site-djbclark
git fetch origin --prune
git pull --ff-only origin master
```

Required reading:

- `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md`
- step2 ground rules/risk register and §6 Phase E:
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
- step0 plan MCP/extension sections:
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step0-plan-v1.md`
- completed E2 role and runtime notes:
  `/Users/djbclark/ops/site-djbclark/roles/goose/README.md`
- completed E1 role:
  `/Users/djbclark/ops/site-djbclark/roles/litellm/README.md`
- current Goose official docs for the **installed version** (1.43.x as of E2)

---

You are implementing **E3: MCP server research + Goose extension config** on
the M1 Air control node.

## Live E1/E2 facts (do not re-litigate)

- LiteLLM `1.94.0rc1` runs as `gui/501/com.djbclark.litellm` on
  `127.0.0.1:4000`; `/v1/models` returns all tiers + `smart-router`.
- SecretSpec is declared but **not operational** — provider completions fail
  until E4. Do not configure SecretSpec or ad-hoc API keys in E3.
- Goose **1.43.0** installed via Homebrew (`block-goose` cask +
  `block-goose-cli` formula).
- Goose config (Goose 1.43 schema — **not** legacy flat keys alone):
  - `~/.config/goose/config.yaml` — `active_provider: litellm-local`,
    structured `providers:` block, mode 0600, site-managed marker
  - `~/.config/goose/custom_providers/litellm-local.json` — OpenAI-compatible
    endpoint `http://127.0.0.1:4000/v1`, model `smart-router`,
    `requires_auth: false`, mode 0600
- `goose info -v` shows `litellm-local` / `smart-router`; `goose run` reaches
  LiteLLM then hits the expected missing-credential boundary (E4).
- E2 rollback (do not perform unless reverting E2):
  remove managed files under `~/.config/goose/` per `roles/goose/README.md`.

## Decided constraints

- **Scope:** research + template only for MCP extensions in `roles/goose`.
  Targets from step0/step2: **Shortwave, Saner.ai, Fieldy, filesystem** — but
  you must **verify each vendor's real MCP offering** (package name, install
  method, auth requirements) from official docs or the vendor. **Never install
  a guessed package name.**
- If a vendor has no MCP server or package cannot be verified, **report to the
  operator in the ledger** and template a commented stub or doc-only entry — do
  not invent packages.
- Preserve E2 provider config and LiteLLM/D7 daemons. Goose still needs no
  Caddy route.
- Do not run `secretspec config init`, enter API keys, or claim real provider
  completions.

## Task

1. For each target integration (Shortwave, Saner.ai, Fieldy, filesystem):
   verify whether a real MCP server exists, its official install/run command,
   and auth expectations. Record sources (URLs) in role docs.
2. Extend `roles/goose` to template verified extension entries in Goose 1.43
   `config.yaml` `extensions:` format (stdio/streamable HTTP per vendor docs).
   Use collision-safe managed markers; refuse to overwrite unrelated user
   extension config.
3. Document apply/check/status changes, what remains human/auth-gated for E4,
   and rollback of managed extension blocks only.
4. Verify:
   - `just goose-apply` idempotent (second apply changed=0)
   - `goose info -v` lists configured extensions (enabled/disabled as templated)
   - config permissions still 0600/0700
   - LiteLLM `/v1/models` 200; D7 `/grafana/`, `/oo/`, `/olivetin/`, `/vm/` 200
   - `just lint`, inventory, ansible syntax/lint, check mode pass
5. Do **not** start E4 SecretSpec or E5 multi-host LiteLLM in this session.

## Carry-forward

- After E3, rewrite `NEXT-PROMPT.md` for **E4 first-run + SecretSpec/provider
  keys** (difficulty 25).
- E1–E3 join the next review slot's scope. Preserve REVIEW-1 notes:
  OliveTin/VictoriaMetrics are intentionally unauthenticated on a single-user
  tailnet; revisit before widening any service or adding tailnet users.
- Carry the AI quota procedure into every next baton.

## End of session

Follow `docs/relay/PROTOCOL.md`: record verification evidence, append exactly
one `E3` ledger row, rewrite the baton for E4 with full catalog AI rows and
fresh quota data, commit/push site straight to master, print the new baton,
and copy it with:

```bash
pbcopy < docs/relay/NEXT-PROMPT.md
```
