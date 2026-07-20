# NEXT: D7-ROUTES-E — Caddy Choice E front-door routes (difficulty 35/100)

**Funding plan context:** FUND-B Phase D recovery closed (R3). D9 logging
close-out done. Operator **decided D7 route scheme §11 #9 = Choice E**
(2026-07-19; design notes §6 + ledger). This baton is the **small
implementation** of that decision only — **not** full D7 (do not retire
dashboard.py / fleet-health / 4097 here).

**Recommended AI** (full rows from `docs/reference/available-ai-models.md`;
recheck quotas with `codexbar usage --format json --provider all` to a file
in the background before starting — never pipe through `head`):

- **Primary —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 · `grok-4.5` ·
  Low, Medium, High (default High) · _Flagship for code + agentic work_ —
  effort **Medium** (Caddy fragment + app root_url + landing links + verify).
- **Alternate —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort (default High on Claude
  Code/API) · _Default for most plans_ — **original account**, Medium.
- **Escalation —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol ·
  `gpt-5.6-sol` · Light, Medium, High, Extra High, Max, Ultra · _Flagship_ —
  Medium, after ~Jul 25 weekly reset if stuck on Grafana subpath.

**Working dir:** `/Users/djbclark/ops/stayturgid` (Caddy fragment template +
any Grafana provisioning root_url; branch + PR) and
`/Users/djbclark/ops/site-djbclark` (ledger/baton; landing links if site-owned;
straight to master). `git fetch origin --prune && git pull --ff-only origin
master` in both before starting. Required reading:
`docs/relay/PROTOCOL.md`, step2 plan §0 + §2
(`docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`), design notes
§6 Choice E
(`docs/design/phase-d-adapter-design-notes.md`), live fragment
`generated/stayturgid/fragments/caddy/stayturgid.caddy` and template
`control/site_contract/sync_templates/fragments/caddy/stayturgid.caddy.j2`.

---

You are implementing **Choice E front-door routes** for O-V-G-O UIs.

## Decided scheme (do not re-litigate)

Front door: `https://mac.greyhound-sidemirror.ts.net` (site
`caddy_public_hostname`). Landing stays at `/`. Keep existing
`/dashboard/`, `/opencode/`, `/vlm/`, `/stats/`.

**Add** (Caddy `handle_path`, strip prefix, reverse_proxy to registry ports):

| Path | Service | Port key (registry) |
| --- | --- | --- |
| `/grafana/` | grafana | 3000 / `grafana` |
| `/oo/` | openobserve HTTP | 5080 / `openobserve-http` |
| `/olivetin/` | olivetin | 1337 / `olivetin` |
| `/vm/` | victoriametrics | 8428 / `victoriametrics` |

Port numbers **only** from site `registry/ports.yml` (StrictUndefined).

## Task

1. Extend `stayturgid.caddy.j2` (and re-render via site-sync) so the live
   fragment includes the four routes **before** the catch-all landing
   `handle { … }`.
2. Fix app base-path / `root_url` as required so UIs work under subpaths
   (Grafana is the usual offender: `serve_from_sub_path` / `root_url`).
   OliveTin / OpenObserve / VM: verify; if one app cannot do subpaths,
   document DEVIATION and either fix config or note subdomain follow-up —
   do not abandon Choice E for the others.
3. Update landing / network services directory links to the new HTTPS paths
   (so operators never need raw ports for these UIs).
4. Apply: `just site-sync` / `just site-serverapps` as appropriate so Caddy
   reloads (fragment checksum / M1-F reload paths). **Before/after health:**
   `curl` caddy `/health`, HTTPS front door, and each new path (expect 200
   or app login page, not 502).
5. Rollback note in ledger: revert fragment + re-apply; or bootout/bootstrap
   caddy label path already documented for D1.

## Constraints

- **Scope:** routes + app subpath config + landing links + verify. **Not**
  full D7: do **not** delete `dashboard.py`, fleet-health, access_monitor, or
  retire 4097.
- stayturgid: branch + PR, merge same session when CI green (admin only if
  GitHub 503 flake after local green). site: ledger/baton straight to master.
- No secrets in commits. Tailscale trust remains the auth model (no new
  Caddy basic-auth unless trivial and already patterned).

## Carry-forward

- **After this baton → E1 LiteLLM** (step2 §6). Rewrite NEXT-PROMPT for E1
  with full catalog AI rows; do not start Goose (E2).
- **Next project code review MUST include:** stayturgid#29/#30/#31 (sticky
  a11y, catastrophic 2h window, Fire skip-catastrophic, ASCII paths, sticky
  degraded); AutoJs6#1 + debug17 LeakCanary-off; this D7-ROUTES-E change.
- Operator GUI available for Accessibility OFF→ON / run main.js if fleet
  work blocks.
- Fleet baseline: health OK on s24/p7a/hd8; main.js auto-running; canonical
  AutoJs6 path only `/sdcard/stayturgid/autojs6`.

## End of session

Per `docs/relay/PROTOCOL.md`: self-verify with recorded evidence (curl
matrix, site-sync/apply, commits/PR), one ledger line `D7-ROUTES-E`, rewrite
`NEXT-PROMPT.md` for **E1**, commit/push both repos (stayturgid PR merged +
master pulled; site on master), print the new baton and
`pbcopy < docs/relay/NEXT-PROMPT.md`.
