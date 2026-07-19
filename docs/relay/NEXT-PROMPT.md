# NEXT: D1 — Caddy serverapp adapter + label migration (difficulty 60/100)

**Recommended AI** (rows from `docs/reference/available-ai-models.md`; quote the
whole row, not a bare name):

- **Primary —** Grok 0.2.103 (grok-web) · xAI / SpaceXAI · Grok 4.5 · `grok-4.5`
  · Low, Medium, High (default High) · _Flagship for code + agentic work._ Run
  at **High**. Caveat: same model is also reachable via Cursor (row 22) or
  OpenRouter/Poe (rows 64, 106) if the grok-web quota is empty.
- **Alt —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol · `gpt-5.6-sol` ·
  Light, Medium, High, Extra High, Max, Ultra · _Flagship; complex coding,
  computer use, research, cybersecurity._ Run at **High**. Good for the launchd
  plist / brew adapter work. Caveat (quota, 2026-07-19): pool is at 29% weekly —
  operator has authorized burning the remainder; when it empties, switch to the
  same model via OpenRouter (api) · OpenAI · GPT-5.6 Sol · various incl. Pro ·
  Light…Ultra · _Full family_ ($18.90 balance) until the Codex weekly resets.
- **Alt (templating subtasks) —** Cursor (web) · Cursor · Composer 2.5 ·
  Composer 2.5 · Agent Thinking · _Native agentic coding._ Caveats: "Copilot
  premium" from the old baton is **not** in the catalog — use this row instead.
  Cursor's **API pool is at 0%** this cycle, so only native Composer/Auto rows
  (19–21) work; Cursor rows 22–32 are unavailable until it resets.
- **Escalate to —** Claude 2.1.205 (web) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Adaptive Thinking (always on) · _Next-gen long-running
  agents._ Use if own/inject mode selection or the TLS cutover needs judgment.
  Caveat: the web variant has no separate effort dial (thinking is always on);
  the Cursor API-pool variant with an Effort dial (row 24) is **unavailable**
  this cycle (API pool 0%), so accept always-on thinking here.

**Working dir:** `/Users/djbclark/ops/stayturgid` (product PR) + `/Users/djbclark/ops/site-djbclark` (site overlay)
**Operator gate:** **public-facing 443** — operator must approve TLS cutover before retiring `com.stayturgid.caddy`; keep old launchd label until new one serves TLS

---

You are executing **step D1** of Phase D (shared-infra handover / serverapp
adapters). Phase C is complete: the reference site at
`/Users/djbclark/ops/site-djbclark` consumes the site contract
(`generated/stayturgid/` + lockfile @ product 2.7 / commit `240f7ee`); a
post-C review landed site `73b559a` (justfile pins `STAYTURGID_SITE_DIR`). D1
implements the **first serverapp adapter** — Caddy — per the site contract spec.

Keep the step narrow. Do **not** migrate vector/openobserve/landing (D2–D4),
implement O-V-G-O (D5), tenant fragments (D6), retire legacy monitors (D7),
edge otelcol (D8), or re-open Phase C contract work. If adapter design requires
a decision not in the specs, stop and report.

## Read first

1. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md`.
2. Ground rules, model routing, risk register, and Phase D **D1** row in
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
   §§0–2 and §5.
3. Site contract spec (product):
   `/Users/djbclark/ops/stayturgid/docs/architecture/site-contract.md`
   §§5.1–5.4 (adapter modes, detection, include mechanisms, invariants).
4. ADR 005 two-repo topology:
   `/Users/djbclark/ops/stayturgid/docs/architecture/adr/005-two-repo-topology.md`.
5. Current Caddy state: live Caddyfile location, existing `com.stayturgid.caddy`
   (or equivalent) launchd label, registry port claims in site
   `registry/ports.yml`, and any hand-managed route fragments.
6. Relay ledger C6 line for carry-forward gotchas.

## Current state and carry-forward gotchas

- stayturgid master at `240f7ee` (C1–C5 merged). Site master at `73b559a`
  (C6 `755e5b0` + review fix): `generated/stayturgid/` adopted; live
  inventory/registries untouched.
- Site `justfile` is site-owned (has `dryrun-termux`, `lint`) and now exports
  `STAYTURGID_SITE_DIR` in every product wrapper and provides
  `just site-sync [mode=dry-run]` — use those instead of setting env by hand.
- `~/ops/site-example` (a C6 test scaffold) was deleted post-review, so
  product site-* auto-discovery resolves to this site — but still prefer the
  site justfile wrappers or explicit `dir=` / `STAYTURGID_SITE_DIR`.
- Site `registry/paths.yml` uses step1 architecture schema (`base_dir`,
  `prefixes`); product registry seeds use contract v1 format — site registry
  remains authoritative; do not overwrite with product seeds.
- `site-map.yml` support (C4, `control/site_contract/site_map.py`) already
  validates `serverapps.caddy.{mode,config,fragment_dir}` with modes
  own/inject/off — D1 must **consume** that existing surface for mode
  selection, not invent a new config key.
- Site `bin/registry_lint.py` is a uv script (`#!/usr/bin/env -S uv run`) —
  run it as `just lint` or `bin/registry_lint.py`, not `python3 bin/...`.
- Caddy adapter must support **own** and **inject** modes (spec §5.1–5.2):
  mode selection order is site var (`site-map.yml` serverapps.caddy.mode) →
  detect existing → own default.
- **inject** mode: verify `import <dir>/*.caddy` exists; exit 2 with
  instructions if missing (spec §5.3).
- **own** mode: install via brew, render base config, reserve fragment dir,
  manage launchd under site namespace (`com.<site_ns>.caddy`, e.g.
  `com.djbclark.caddy`).
- Port/label values come **only** from site registry/inventory — never hardcode
  production literals in product code.
- Product changes: branch + PR on stayturgid; merge per product protocol after
  human checklist confirmation. Site overlay changes land in site-djbclark.
- Do not contact fleet devices unless operator asks. Do not rotate secrets.

## Exact task

1. `git fetch` / pull both repos from clean master.
2. **Discover** current Caddy deployment on the control node: Caddyfile path,
   fragment/include dirs, launchd label, listening ports (443/80/8080 health).
   Cross-check site `registry/ports.yml` — register any gaps before adapter work.
3. **Implement** the Caddy adapter role in stayturgid (product):
   - own mode: brew install, base Caddyfile template, fragment dir, site-namespace
     launchd plist, import line for product fragments under
     `generated/stayturgid/`.
   - inject mode: detect existing config; write only fragment files; verify import
     line (exit 2 if missing per spec).
   - Rendered files carry generated header (product, template, sync time).
4. Wire adapter into site-sync manifest / sync templates so Caddy route
   fragments land under `generated/stayturgid/` (minimal v1 fragment to prove
   the path; full tenant routes are D6).
5. **Migrate** this site's Caddy instance to `com.djbclark.caddy` under site
   ownership — but **keep the old `com.stayturgid.*` label running** until
   operator confirms the new instance serves TLS on 443 (**OPERATOR GATE**).
6. Dry-run deploy first (`just dryrun-*` / `--check`). Verify health endpoints
   after any launchd change (`curl`, `launchctl list`).
7. Run `just check` / focused tests on the product PR; from product with
   `STAYTURGID_SITE_DIR=/Users/djbclark/ops/site-djbclark` run
   `just validate-identity` (strict); site `bin/registry_lint.py` if registry
   edited.

## Verification

- Caddy adapter role exists with own + inject modes per spec §5.
- inject against pre-existing Caddyfile without import → exit 2 with instructions.
- own mode on clean prefix → daemon under `com.<site_ns>.caddy`, fragment dir
  importable.
- Site-sync renders at least one Caddy fragment under `generated/stayturgid/`;
  lockfile updated; second sync no-op.
- Old label still serves TLS until operator-approved cutover.
- `just check` green on product PR; strict identity clean with site overlay.
- No secret values in commits; no live inventory in public product.

## Human-verification checklist

- [ ] Caddy adapter own/inject modes match spec §5.1–5.4
- [ ] Registry updated for any new port/label claims before deploy
- [ ] Dry-run reviewed; no surprise writes outside generated area + adapter targets
- [ ] New `com.djbclark.caddy` serves routes; old label retained until operator cutover
- [ ] `curl` health/TLS spot-check passed on control node
- [ ] Product PR merged; stayturgid on pulled master; site repo updated if needed
- [ ] Ledger + next baton updated per PROTOCOL.md

## End of session

Follow `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` exactly.
After D1 is human-confirmed and landed, append its ledger entry, prepare the
**D2** baton from the execution-plan row, commit/push both repos as needed,
print the new `NEXT-PROMPT.md` contents in chat, and copy the baton to the
clipboard using pbcopy (`pbcopy < docs/relay/NEXT-PROMPT.md`).

When the D2 baton header names a recommended AI, draw it from
`docs/reference/available-ai-models.md` and quote each option's full table row
(source, vendor, model, variant/ID, thinking levels, notes) plus any caveats.
