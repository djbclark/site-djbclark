# NEXT: D6 — inventory→fragments projections (difficulty 60/100)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md`). Quality bar:
**correctness/safety must-fix only**; architecture/style findings may be
deferred to the ledger for M1. No human gates — self-verify per PROTOCOL.md.

**Recommended AI** (rows from `docs/reference/available-ai-models.md`):

- **Primary —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
  Auto) · _Next-gen long-running agents_ — **new second-Pro account**, Medium+
  effort. D6 inventory→projection blast radius wants Fable 5 judgment (step2
  plan + FUND-B Plan B reserved Fable capacity for D6).
- **Alt —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 · `grok-4.5` ·
  Low, Medium, High (default High) · _Flagship for code + agentic work_ —
  effort **High**. Self-passoff from D5 allowed if Fable weekly is exhausted
  and D5 adapter pattern is still the right tool (pure projections, closed
  write set).
- **Alt2 —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol · `gpt-5.6-sol` ·
  Light, Medium, High, Extra High, Max, Ultra · _Flagship; complex coding,
  computer use, research, cybersecurity_ — use while Codex quota lasts.
- **Escalation:** Claude Fable 5 (new second-Pro) if projection purity /
  OliveTin single-writer merge fights the closed write set.

**Working dir:** `/Users/djbclark/ops/stayturgid` (implementation; branch +
PR + merge-your-own per PROTOCOL) + `/Users/djbclark/ops/site-djbclark`
(registry/inventory + relay; straight to master).

---

You are executing **D6**: inventory→fragments projections under site-sync
(design §2). D5 already seeded fragment dirs and shippable scaffolding; D6
owns **purity** of projections and the OliveTin single-writer merge. Do not
re-decide architecture — D0 design notes + D5 live adapters settle the
surfaces.

## Read first (absolute paths)

1. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` (end-of-session
   ritual; merge your own stayturgid PR; print + `pbcopy` next baton).
2. `/Users/djbclark/ops/site-djbclark/docs/design/phase-d-adapter-design-notes.md`
   §2 (projections: pure functions of inventory+registry; closed write set;
   OliveTin single-writer merge; Grafana pinned UIDs / panel ids from sorted
   host index), §1.6 fragment layout, §4 deviations.
3. Step2 plan §§0–2 + Phase D row D6:
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
4. stayturgid: `docs/architecture/site-contract.md` §5 (olivetin projection
   row); `control/site_contract/site_sync.py` + `sync_manifest.yml`; existing
   D5 fragments under `sync_templates/fragments/{grafana,olivetin,caddy}/`.
5. Site: `inventory/` (hosts + group_vars), `registry/ports.yml`,
   `docs/relay/LEDGER.md` D5 line, live OliveTin config at
   `~/.config/djbclark/olivetin/config.yaml` (D5 empty-actions bootstrap).

## Task (step2 plan row D6)

1. **Projections are pure:** same (inventory, registry) ⇒ byte-identical
   outputs; no live probes; hosts sorted by name; stable YAML/JSON key order;
   no timestamps in file bodies (sync time = lockfile only).
2. **Closed write set:** a D6 sync may only create/overwrite/delete files in
   `generated/stayturgid/fragments/{caddy,grafana,olivetin}/` plus the
   lockfile. Anything else = stop (projection bug).
3. **Caddy fragment:** inventory-driven product routes as needed (do not
   break D1 front door; ports from registry only, StrictUndefined).
4. **Grafana:** fleet dashboard / panels may grow host-derived blocks (panel
   ids from sorted host index; datasource UID `stayturgid-victoriametrics`
   pinned). Keep scope honest if metrics are thin pre-D8.
5. **OliveTin single-writer merge:** project live
   `~/.config/<site_ns>/olivetin/config.yaml` from
   `fragments/olivetin/stayturgid_actions.yaml` + optional site
   `olivetin/user-actions.yaml`. Action ids `stayturgid_*` vs `user_*` —
   collisions exit 1. **Shell env propagation** for `just` recipes (PATH,
   Homebrew, venvs) per ovgo plan warning. Do not invent a parallel config
   surface; site-sync (or a dedicated projection step invoked by it) is the
   only writer of the live file.
6. Wire tests proving: pure re-render no-op; closed write set refuse; host
   add/remove rewrites only the closed set; OliveTin id collision → exit 1.
7. Site: `site-sync` apply; second apply no-op; do not break D1–D5 daemons
   (verify health after).

## Constraints

- Do **not** touch serverapp own-mode roles except if projection activation
  requires a thin hook; prefer site-sync as the fragment writer.
- Do **not** set `*_enabled: false` that deletes D7 rollback plists.
- No secrets in commits; broken venv → `rm -rf` + `just test-venv`.
- Pre-health siblings before and after: caddy / vector / openobserve /
  landing / victoriametrics / grafana / olivetin.

## Verification (self-verify, record evidence in ledger)

- Focused tests + `just check` green; full `just test` if Python behavior
  changed; `bin/registry_lint.py` OK.
- `just site-sync mode=apply` then second apply all-skip / lockfile stable.
- Live: OliveTin UI shows projected `stayturgid_` actions (or honest partial
  with ledger note); Grafana dashboard still loads; siblings 200.
- stayturgid PR merged, branch deleted, checkout on pulled master, CI green.

## End of session

Follow PROTOCOL.md: ledger line `D6`; rewrite `NEXT-PROMPT.md` as the **D7
baton** (retire legacy monitors once O-V-G-O coverage is adequate — extra
self-verification, not a human gate per FUND-B); commit/push site to master;
print baton and `pbcopy < docs/relay/NEXT-PROMPT.md`.
