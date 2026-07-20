# NEXT: E2 — Goose role + local LiteLLM provider (difficulty 40/100)

**Funding plan context:** FUND-B Phase D recovery and REVIEW-1 are closed.
Phase E E1 is complete: the site-owned LiteLLM proxy is live and healthy at
`127.0.0.1:4000`. This baton is **Phase E step E2 only** — install/configure
Goose against the local proxy. **Do not start MCP research/configuration (E3),
configure the SecretSpec backend or provider API keys (E4), or widen LiteLLM
beyond loopback (E5).**

**Recommended AI** (full rows from
`docs/reference/available-ai-models.md`; quota snapshot taken
2026-07-20T13:45Z):

- **Primary —** Cursor (GUI) · Cursor · Composer 2.5 · `Composer 2.5` ·
  Agent Thinking · _Native agentic coding_ — main monthly pools were 57.9%
  and 50.9% used (third pool exhausted), resetting Aug 2 ~7:22pm ET. The E2
  plan row says Copilot premium, and Copilot was only 11.3% used, but the
  operator-maintained AI catalog contains no full GitHub Copilot model row;
  relay protocol therefore cannot make it the formal recommendation without
  an operator catalog edit.
- **Alternate —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 ·
  `grok-4.5` · Low, Medium, High (default High) · _Flagship for code +
  agentic work_ — use **Medium**; live CodexBar saw installed Grok 0.2.106,
  65% weekly used, reset Jul 23 ~2:41am ET.
- **Escalation —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort (default High on Claude
  Code/API) · _Default for most plans_ — use **original Gmail account**,
  Medium, only if the installed Goose configuration format cannot be
  reconciled with current official docs. At snapshot: original Gmail was 2%
  of its five-hour window and 70% weekly (Fable 100%); the newer MIT account
  was 23% five-hour, 20% weekly, and 35% Fable weekly. Preserve the newer
  account's Fable pool for reviews/design/escalations.

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
- Snapshot context only: Codex weekly was 100% used until Jul 25 ~5:17pm ET
  (118.8 credits remain); avoid burning credits before reset. Recheck live
  rather than trusting this snapshot.

**Working dir:** `/Users/djbclark/ops/site-djbclark` (Goose role incubates
here as `roles/goose`). Start with:

```bash
cd /Users/djbclark/ops/site-djbclark
git fetch origin --prune
git pull --ff-only origin master
```

Required reading:

- `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md`
- step2 ground rules/risk register and §6 Phase E:
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
- step0 plan as amended, especially Goose provider config and verification:
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step0-plan-v1.md`
- step1 §9 role-location revisions:
  `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step1-segmentation-architecture-v1.md`
- completed E1 role and runtime notes:
  `/Users/djbclark/ops/site-djbclark/roles/litellm/README.md`
- current Goose official docs for the **installed version**; do not rely on a
  remembered config path or format.

---

You are implementing **E2: Goose desktop/CLI and local LiteLLM provider** on
the M1 Air control node.

## Live E1 facts (do not re-litigate)

- LiteLLM `1.94.0rc1` is running as
  `gui/501/com.djbclark.litellm`, bound only to `127.0.0.1:4000`.
- PyPI stable was still 1.93.0 on 2026-07-20; Auto Router v2 first existed in
  the 1.94 train. The E1 role uses
  `litellm[proxy,caching]>=1.94.0rc1,<2`; the `caching` extra is required for
  disk cache. Do not downgrade it or rewrite its v2 config.
- `curl -fsS http://127.0.0.1:4000/v1/models` returns `gpt-4o-mini`,
  `gpt-4o`, `claude-sonnet-5`, `gpt-5.5`, and `smart-router`.
- No master key is configured because the proxy is loopback-only.
- **SecretSpec is declared but not operational:**
  `secretspec config show` reports provider `(none)`, profile `(none)`, and
  no aliases. The operator explicitly chose not to configure it during E1.
  Provider completions therefore fail with missing credentials until E4.
- Auto Router itself is proven: SIMPLE routed to `gpt-4o-mini`; REASONING
  routed to `gpt-5.5`. Do not claim a real provider completion in E2.
- E1 rollback (do not perform):
  `launchctl bootout gui/$(id -u)/com.djbclark.litellm`; config/cache/plist
  remain for re-bootstrap.

## Decided constraints

- **Role home:** `site-djbclark/roles/goose`; add a site-local playbook and
  `just` apply/check/status recipes matching E1's operator ergonomics.
- **Install:** native Homebrew only, no Docker. Install Goose Desktop cask
  `block-goose` and Goose CLI formula `block-goose-cli` if absent; never
  upgrade already-present packages as an incidental apply.
- **Provider:** configure Goose's custom OpenAI-compatible provider to
  `http://127.0.0.1:4000` with model `smart-router`. Because E1 has no master
  key, do not invent or commit a Goose API key; if current Goose requires a
  nonempty placeholder for an OpenAI-compatible endpoint, verify and document
  the least-secret local value its official docs permit.
- **Config path/format:** inspect the actually installed Goose 1.43.x (or
  current) CLI/help and current official docs before templating. The old plan's
  `~/.config/goose/config.yaml` vs profiles YAML/JSON warning is real. Record
  the discovered path and schema; do not force an old example onto a new
  release.
- **Secrets:** do not run `secretspec config init`, select a provider backend,
  enter API keys, or render keys. That is E4.
- **Scope:** provider configuration only. Do **not** add guessed or real MCP
  extensions/packages; Shortwave/Saner.ai/Fieldy/filesystem research is E3.
- Preserve LiteLLM, D7 routes, and O-V-G-O daemons. Goose need not expose a
  listener or receive a Caddy route.

## Task

1. Inspect pre-state: Homebrew cask/formula presence, any existing Goose app,
   CLI, and user config. Preserve any unrelated user config; if a managed-file
   collision exists, stop and record it rather than overwrite blindly.
2. Verify the installed/current Goose documentation for its configuration
   path and custom OpenAI-compatible provider schema.
3. Author an idempotent `roles/goose` plus local playbook/wrappers that:
   - requires Homebrew;
   - installs `block-goose` and `block-goose-cli` only when absent;
   - creates the correct config directory with private permissions;
   - renders or safely manages the provider pointing at local LiteLLM;
   - reports the discovered Goose version/config path.
4. Document apply, check/status, configuration ownership, the expected
   keyless-provider limitation until E4, and a non-destructive rollback.
5. Verify live without pretending E4 is complete:
   - Goose app is installed in `/Applications` (or the cask's actual path);
   - `goose --version` succeeds;
   - Goose recognizes/loads the local provider and `smart-router` using an
     official CLI/config inspection command if available;
   - config file exists at the version-correct path and is mode 0600 (parent
     private as appropriate);
   - LiteLLM `/v1/models` still returns 200;
   - a second full apply reports zero changes;
   - `just lint`, inventory, Ansible syntax/lint, and check mode pass;
   - D7 front-door paths `/grafana/`, `/oo/`, `/olivetin/`, `/vm/` remain 200.
6. If Goose can issue a prompt without interactive first-run setup, a missing
   provider credential is the expected E4 boundary. Record it; do not work
   around it with ad-hoc keys or configure SecretSpec.

## Rollback expectation

Document how to remove or disable the managed Goose provider configuration
without touching LiteLLM or user-owned config. Homebrew package removal is not
part of ordinary rollback unless the install itself prevents Goose from
starting; prefer leaving installed artifacts and restoring the prior config.

## Carry-forward

- After E2, rewrite `NEXT-PROMPT.md` for **E3 MCP server research + Goose
  extension config** (difficulty 55). E3 must verify real vendor offerings and
  must never install a guessed package name. Do not start E3 in this session.
- SecretSpec backend selection, provider API keys, first-run auth, and real
  provider completions remain **E4**.
- E1 and E2 join the next review slot's scope. Preserve REVIEW-1 notes:
  OliveTin/VictoriaMetrics are intentionally unauthenticated on a single-user
  tailnet; revisit before widening any service or adding tailnet users.
- The AI quota procedure at the top of this baton must be carried into every
  next baton: CodexBar timeout 120 seconds; Claude usage only from
  `cswap list --json` across both accounts.

## End of session

Follow `docs/relay/PROTOCOL.md`: record verification evidence, append exactly
one `E2` ledger row, rewrite the baton for E3 with full catalog AI rows and
fresh quota data using the corrected procedure, commit/push site straight to
master, print the new baton, and copy it with:

```bash
pbcopy < docs/relay/NEXT-PROMPT.md
```
