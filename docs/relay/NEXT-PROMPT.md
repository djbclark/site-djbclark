# NEXT: D1 — caddy adapter + migrate to com.djbclark.caddy (difficulty 60/100)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md`). No human gates —
self-verify per PROTOCOL.md. The former OPERATOR GATE on public-facing 443 is
replaced by the extra-verification + rollback rules below.

**Recommended AI** (rows from `docs/reference/available-ai-models.md`):

- **Primary —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 · `grok-4.5` ·
  Low, Medium, High (default High) · _Flagship for code + agentic work._ Use
  **High**; ~75% weekly remaining. Self-passoff applies if Grok is already the
  runner.
- **Alt —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol · `gpt-5.6-sol` ·
  Light, Medium, High, Extra High, Max, Ultra · _Flagship; complex coding,
  computer use, research, cybersecurity._ Codex burn is operator-authorized
  (29% weekly); when it empties, fall back to OpenRouter (api) · OpenAI ·
  GPT-5.6 Sol · various incl. Pro · Light–Ultra · _Full family_ ($18.90).
- **Escalation:** implementation trouble → the Codex/OpenRouter alt at higher
  effort. If the DESIGN itself seems architecturally wrong, do not redesign —
  stop, ledger `ESCALATED` with findings per PROTOCOL.md §B; R1 (Fable 5) is
  two sessions away and will judge it.

**Working dir:** `/Users/djbclark/ops/stayturgid` (implementation; branch +
PR) + `/Users/djbclark/ops/site-djbclark` (site facts, registry, relay).

---

You are executing **step D1** of Phase D: implement the caddy serverapp
adapter and migrate the live instance from `com.stayturgid.caddy` to
`com.djbclark.caddy`. This is the template adapter D2–D5 will clone.

## Your spec (do not re-decide architecture)

`/Users/djbclark/ops/site-djbclark/docs/design/phase-d-adapter-design-notes.md`
— Fable-5-authored. Implement §1 (all of it) for caddy. §4 defines what you
may deviate on: awkward details yes (ledger `DEVIATION: <what> — <why>`),
but never exit-code meanings, never-touch-user-content, the no-cutover +
rollback rule (§1.9), or the closed write set.

## Read first (absolute paths)

1. The design notes above — your primary spec.
2. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` (self-verify;
   merge-your-own-PR rule; end-of-session ritual).
3. Ground rules + risk register:
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
   §§0–2, and the D1 row in §5.
4. `/Users/djbclark/ops/stayturgid/docs/architecture/site-contract.md` §5 and
   acceptance test 5 (caddy own + inject behavior — you must ship it).
5. Existing code to extend:
   `/Users/djbclark/ops/stayturgid/control/site_contract/site_sync.py`,
   `site_map.py`, `sync_manifest.yml`;
   `/Users/djbclark/ops/stayturgid/ansible/roles/control_node/tasks/observability.yml`
   - `launchd_ensure.yml` (lifecycle pattern to clone);
     current live config `~/.config/stayturgid/Caddyfile` (no import line today).
6. Site registry: `/Users/djbclark/ops/site-djbclark/registry/ports.yml`
   (caddy 80/443/8080 rows; run `bin/registry_lint.py` after edits).

## Task (per design §1; caddy only this session)

1. stayturgid: fragment template + `sync_manifest.yml` entry for
   `generated/stayturgid/fragments/caddy/stayturgid.caddy` (routes for the
   product UIs currently in the live Caddyfile), generated header per §1.7;
   extend `_site_render_context` with `ports` + `inventory_hosts` (§1.8).
2. stayturgid: `control/site_contract/serverapps.py` + `just site-serverapps`
   (mode resolution §1.2, own/inject/off behavior §1.3, exit codes §1.4,
   plan-then-act, dry-run). Ansible role `ansible/roles/serverapp_caddy/`
   (base config with import line at `~/.config/<site_ns>/caddy/Caddyfile`,
   plist `com.<site_ns>.caddy`, validate-before-activate). Tests: mode
   resolution, exit-2 paths, idempotent re-run, acceptance test 5.
3. site repo: add `site_ns: djbclark` to `inventory/group_vars/all.yml`;
   update `registry/ports.yml` caddy rows' Phase-D notes (owner → site).
4. Migrate per design §1.9 exactly: validate → pre-health-check → bootout
   old → bootstrap new → verify (health curl + one real HTTPS request through
   the Tailscale front door + `launchctl print` state=running; paste all
   three into ledger/PR). **Old plist and old Caddyfile stay on disk until
   D7.** Rollback (keep working, record in ledger):
   `launchctl bootout gui/501/com.djbclark.caddy && launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.stayturgid.caddy.plist`

## Carry-forward gotchas (C6/FUND-B — do not rediscover)

- Site justfile wrappers must export `STAYTURGID_SITE_DIR`; the C6 session
  left the site justfile without that helper — add/fix it when you touch the
  wrappers, don't work around it.
- `site-example` was deleted upstream; CI creates a generic example inventory
  itself — don't reference a checked-in example site.
- Site `registry/paths.yml` still uses the step1 schema, not the product seed
  format — don't "fix" it drive-by; note it if it blocks you.
- uv-shebang lint: never hand-edit venv shebangs; broken venv → `rm -rf` +
  `just test-venv`.
- Devices frequently offline — D1 needs no device contact; keep it that way.

## Verification (self-verify; evidence into ledger + PR)

- `just check` + full `just test` green in stayturgid; focused adapter tests
  pass; pre-commit clean; overlay + upstream-only strict identity clean.
- Acceptance test 5 shipped and passing (own on clean prefix; inject exit 2
  without import line).
- Second `just site-serverapps` run is a no-op (exit 0, all skip).
- Live: `com.djbclark.caddy` running, health + TLS verified, old label
  booted out but plist retained; rollback command recorded.
- `registry_lint.py` passes; no secrets in any commit.

## End of session

Follow PROTOCOL.md exactly: stayturgid branch + PR, record evidence, **merge
your own PR, delete branch, end on pulled green master**; site repo straight
to master. Append the `D1` ledger line (including any `DEVIATION:` notes).
Then rewrite `NEXT-PROMPT.md` as the **G1 gate-debt retro-verification
baton** (funding-plans doc § Gate-debt remediation): recommended AI = Claude
2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 · `claude-sonnet-5` ·
Adaptive Thinking + Effort (default High on Claude Code/API) · _Default for
most plans_ — **original account (djbclark@gmail.com)**, effort Medium/Low
(mechanical command-running, not judgment); scope = ALL ledger stages to date
(B1–B6, B-review, C1–C6, D0-design, D1): re-run every mechanically checkable
checklist claim, output `docs/relay/reviews/gate-debt-audit.md` (one row per
claim: verified-now / failed / not-mechanically-checkable). G1's own
end-of-session must route to the **R1 review baton**: Claude 2.1.205 (Mac
GUI) · Anthropic · Claude Fable 5 · `claude-fable-5` · Low, Medium, High,
Extra, Max, Ultra (GUI picker; no Auto) · _Next-gen long-running agents_ —
**new second-Pro account**, effort **Medium**, judging G1's failures/flags
plus the D1 architecture review proper against the design notes
(correctness/safety must-fix; architecture/style deferred to ledger).
Commit/push, print the new baton in chat, and
`pbcopy < docs/relay/NEXT-PROMPT.md`.
