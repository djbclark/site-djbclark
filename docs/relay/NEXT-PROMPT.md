# NEXT: E1 — LiteLLM proxy role + launchd (difficulty 50/100)

**Funding plan context:** FUND-B Phase D recovery closed (R3). D9 logging
close-out done. D7-ROUTES-E Choice E front-door routes shipped (stayturgid
#32 → master `ab329a5`). REVIEW-1 whole-repo review complete 2026-07-20
(findings: `docs/relay/reviews/REVIEW-1-findings.md`; fixes merged as
stayturgid #33 `6ca9d31` + site `08409bf`). This baton is **Phase E step E1
only** — LiteLLM proxy under site ownership. **Do not start Goose (E2)** or
MCP research (E3).

**Recommended AI** (full rows from `docs/reference/available-ai-models.md`;
quotas verified 2026-07-20T02:35Z via per-provider codexbar — NOTE
`codexbar usage --provider all` is broken: the Gemini CLI OAuth probe fails
and the whole command exits 1 with empty stdout; call
`codexbar usage --format json --provider <codex|claude|grok>` per provider,
backgrounded to a file, never piped through `head`):

- **Primary —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol ·
  `gpt-5.6-sol` · Light, Medium, High, Extra High, Max, Ultra · _Flagship;
  complex coding, computer use, research, cybersecurity_ — effort **High**
  (verify Auto Router v2 against live LiteLLM docs, not memory; pin ≥1.94).
  **Quota gate:** weekly window was 100% used until Jul 25 ~5:17pm ET
  (118.8 credits remain — do not burn credits). If running E1 before that
  reset, use the Alternate instead.
- **Alternate —** Grok 0.2.106 (TUI) · xAI / SpaceXAI · Grok 4.5 ·
  `grok-4.5` · Low, Medium, High (default High) · _Flagship for code +
  agentic work_ — 64% weekly used at write time, resets Jul 23 ~2:41am ET.
- **Escalation —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort (default High on Claude
  Code/API) · _Default for most plans_ — **original account**, Medium, if
  router config vs docs is ambiguous or secretspec/launchd integration
  needs judgment. (Fable-only weekly on the new account was 16% used,
  resets Jul 25 ~5am ET; its 5h session meter resets 12:30am ET Jul 20 —
  recheck if using that account.)

**Working dir:** `/Users/djbclark/ops/site-djbclark` (roles incubate **here**
per step1 §9 / step2 §6 — `roles/litellm`, not a standalone `~/ai-stack`
tree; branch optional — site often straight to master for ops) and pull
stayturgid only if you need port/registry patterns as reference.
`git fetch origin --prune && git pull --ff-only origin master` before
starting. Required reading:

- `docs/relay/PROTOCOL.md`
- step2 plan §6 Phase E (`docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`)
- step0 plan as **amended** (`docs/plans/site-djbclark-step0-plan-v1.md` —
  header amendment: label `com.djbclark.litellm`, port 4000 in registry,
  secretspec, roles in this repo)
- step1 §9 revisions (`docs/plans/site-djbclark-step1-segmentation-architecture-v1.md`)
- live `registry/ports.yml` (`litellm-proxy` port 4000, status planned)
- live `registry/paths.yml` (`~/.litellm/**`)
- site `secretspec.toml` pattern (declarations only; never commit secrets)
- existing Phase D adapters in stayturgid for launchd/site_ns patterns
  (reference only — LiteLLM is a **site** role, not a stayturgid serverapp
  unless you explicitly decide to promote it later)

---

You are implementing **E1: LiteLLM proxy** for the site control node.

## Decided constraints (do not re-litigate)

- **Role home:** `site-djbclark/roles/litellm` (or `ansible/roles/litellm`
  matching this repo’s layout — inspect existing site ansible structure).
- **Label:** `com.{{ site_ns }}.litellm` → live `com.djbclark.litellm`
  (not `local.litellm`).
- **Bind:** `127.0.0.1:4000` (registry `litellm-proxy`). Widen to Tailscale
  only if mini/other host will consume it later (E5) — default loopback.
- **Install:** `uv tool install "litellm[proxy]"` with pin **≥1.94** (Auto
  Router v2 / `auto_router/complexity_router` shipped 2026-07-14). If config
  is rejected, upgrade LiteLLM — **do not** rewrite config to older syntax.
- **Config:** `~/.litellm/config.yaml` mode 0600; disk cache under
  `~/.litellm/cache`; logs under site or `~/Library/Logs/litellm` as
  patterned in step0.
- **Secrets:** API keys via secretspec / env (`OPENAI_API_KEY`,
  `ANTHROPIC_API_KEY`, etc.) — **never** commit secrets or master keys.
  Template may reference `os.environ/...`; human fills keys (E4 gate) but
  E1 must leave secretspec entries declared and document how keys enter.
- **Router:** model `smart-router` using Auto Router v2 complexity tiers
  (SIMPLE/MEDIUM/COMPLEX/REASONING) per step0 template, **verified against
  current docs.litellm.ai** at implement time. Update stale model IDs
  (step0 still shows `claude-sonnet-4-20250514` — use current IDs).

## Task

1. Author Ansible role + playbook/wrapper so the operator can apply
   LiteLLM idempotently (install if absent, render config + plist, bootstrap
   launchd, health wait). Prefer patterns already used on this Mac
   (site just recipes, `site_ns` from `inventory/group_vars/all.yml`).
2. Render `litellm-config.yaml.j2` with Auto Router v2 + disk cache +
   sensible fallbacks; no secrets in git.
3. Render launchd plist `com.djbclark.litellm` (RunAtLoad + KeepAlive),
   ProgramArguments: litellm binary `--config` `--host 127.0.0.1` `--port 4000`.
4. Declare secretspec keys needed for provider API keys (values operator-
   supplied; empty-ok until E4).
5. Flip registry `litellm-proxy` status from `planned` → `active` when live
   and healthy (or document why still planned).
6. **Verify:**
   - `launchctl print gui/$(id -u)/com.djbclark.litellm` loaded
   - `curl -sS http://127.0.0.1:4000/v1/models` (auth as configured —
     master_key local-only or documented)
   - One **SIMPLE** and one **REASONING** prompt route to different tiers
     (check LiteLLM logs / response headers / `model` field — record
     evidence)
7. Rollback note in ledger: bootout label; keep config on disk for re-bootstrap.

## Constraints

- **Scope:** LiteLLM only. **Do not** install Goose (E2), MCP servers (E3),
  or run the human API-key checklist as if E4 is done (you may document it).
- No Docker. No secrets in commits. Tailscale auth remains the network trust
  model; LiteLLM stays loopback unless explicitly widened.
- Do not break D7-ROUTES-E Caddy routes or O-V-G-O daemons.
- If weekly Codex is reset ~Jul 25 and you are pre-reset, prefer Grok/Claude
  alternate rather than burning Sol Ultra needlessly.

## Carry-forward

- **After this baton → E2 Goose** (step2 §6). Rewrite NEXT-PROMPT for E2
  with full catalog AI rows; do not start MCP research (E3).
- REVIEW-1 (2026-07-20) covered stayturgid#29/#30/#31/#32, AutoJs6#1 +
  debug17, and D7-ROUTES-E — the previously mandated carry-forward review is
  **done**; this E1 role itself joins the next review slot's scope.
  Flagged-not-fixed E-phase notes from REVIEW-1
  (`docs/relay/reviews/REVIEW-1-findings.md`):
  - R1-2: OliveTin + VictoriaMetrics are unauthenticated behind the tailnet
    front door (by D7-ROUTES-E design, single-user tailnet). If E-phase work
    widens any service beyond loopback (e.g. LiteLLM to Tailscale in E5) or
    adds tailnet users, revisit auth on those paths first.
  - R1-1: guard.js still hard-notifies sticky-a11y per watchdog cycle
    (comonitor was softened in #31); only touch with s24 device-log evidence.
  - R1-3 (nit): WATCHDOG_FRESH_SEC 1800 duplicated as a literal in
    stayturgid_repair.py — deliberate (device file can't import control lib).
- Operator GUI available for Accessibility OFF→ON / run main.js if fleet
  work blocks.
- Fleet baseline: health OK on s24/p7a/hd8; main.js auto-running; canonical
  AutoJs6 path only `/sdcard/stayturgid/autojs6`.
- Front door: `https://mac.greyhound-sidemirror.ts.net/{grafana,oo,olivetin,vm}/`
  already live — operators need not use raw ports for those UIs.

## End of session

Per `docs/relay/PROTOCOL.md`: self-verify with recorded evidence (uv install
version ≥1.94, launchctl, curl `/v1/models`, router tier proof, registry
status), one ledger line `E1`, rewrite `NEXT-PROMPT.md` for **E2**,
commit/push site (and stayturgid only if you touched product), print the
new baton and `pbcopy < docs/relay/NEXT-PROMPT.md`.
