# NEXT: D2 — vector adapter (clone the D1 pattern) (difficulty 45/100)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md`). Quality bar:
**correctness/safety must-fix only**; architecture/style findings may be
deferred to the ledger for M1. No human gates — self-verify per PROTOCOL.md.

**Recommended AI** (rows from `docs/reference/available-ai-models.md`):

- **Primary —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 · `grok-4.5` ·
  Low, Medium, High (default High) · _Flagship for code + agentic work_ —
  effort **Medium/High** (FUND-B Plan B row for D2–D4).
- **Alt —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol · `gpt-5.6-sol` ·
  Light, Medium, High, Extra High, Max, Ultra · _Flagship; complex coding,
  computer use, research, cybersecurity_ — use while Codex quota lasts.
- **Escalation:** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
  Auto) · _Next-gen long-running agents_ — **new second-Pro account**, only
  if the vector adapter diverges from the design notes' pattern.

**Working dir:** `/Users/djbclark/ops/stayturgid` (implementation; branch +
PR + merge-your-own per PROTOCOL) + `/Users/djbclark/ops/site-djbclark`
(registry/inventory edits + relay; straight to master).

---

You are executing **D2**: the vector serverapp adapter, cloning the reviewed
D1 caddy pattern. Do not re-decide architecture — D0 design notes + the R1
review already settled the shape.

## Read first (absolute paths)

1. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` (end-of-session
   ritual; merge your own stayturgid PR; print + `pbcopy` next baton).
2. `/Users/djbclark/ops/site-djbclark/docs/design/phase-d-adapter-design-notes.md`
   §§0–1 (adapter pattern; §1.9 now includes the R1-amended persistent-disable
   step and rollback), §4 (deviation protocol — ledger any deviation).
3. `/Users/djbclark/ops/site-djbclark/docs/relay/reviews/r1-d1-adapter-review.md`
   — R1 findings; §"Clone-safety for D2" lists exactly what to copy vs
   caddy-specific; carry S-2/A-2 notes into your implementation choices.
4. Step2 plan §§0–2 + Phase D row D2:
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
5. stayturgid: `docs/architecture/site-contract.md` §5 (vector row of §5.3);
   `ansible/roles/control_node/tasks/observability.yml` +
   `templates/vector.yaml.j2` (current com.stayturgid.vector management —
   your starting material); `control/site_contract/serverapps.py` +
   `sync_manifest.yml` + `tests/python/test_serverapps.py` (D1 template);
   `ansible/roles/serverapp_caddy/` (role shape incl. legacy bootout +
   persistent-disable tasks — clone both).
6. Site: `registry/ports.yml` (4318 fleet-ingest note; vector ports),
   `inventory/group_vars/all.yml` (`site_ns: djbclark`),
   `docs/relay/LEDGER.md` D1/G1/R1 rows.

## Task (step2 plan row D2)

Vector adapter: start from the merged `observability.yml` + `vector.yaml.j2`
(already Ansible-managed under `com.stayturgid.vector`); split into
product-prefixed fragment components (`stayturgid_*` ids) rendered by
site-sync into `generated/stayturgid/fragments/vector/` (sources/sinks files
per design §1.6); new role `serverapp_vector` (extracted from
observability.yml) relabels to `com.<site_ns>.vector`, own-mode unit passes
extra `--config` args globbing the committed generated fragments (§1.3 — no
copy step), `vector validate` before activate, legacy
`com.stayturgid.vector` bootout **+ persistent `launchctl disable`** (R1
MF-1 pattern — clone it), health check, plist retained until D7. Extend
`serverapps.py`: add `vector` to `KNOWN_APPS` with per-app dispatch (inject
mode per §5.3: standalone fragment files + `--config` args; foreign detect =
existing vector.yaml/vector.toml service config). Site: update
`registry/ports.yml` vector-port ownership → site (0.0.0.0:4318 binding
stays — fleet ingest, registry documents why); run `bin/registry_lint.py`.

Constraints carried from R1/G1:

- Keep the F4-accepted pattern: second own-mode apply re-runs the ansible
  ensure (file actions skip; ansible no-op) — that is the healing/verify path.
- If cheap, use a typed refusal kind instead of `"drifted"` substring gating
  (R1 S-2) in any new refusal paths; otherwise keep the D1 shape and ledger it.
- Do not touch `com.stayturgid.caddy` / caddy paths; do not set
  `stayturgid_caddy_enabled: false` (deletes the rollback plist — D7's job).
- paths.yml stays step1 schema (note only); no secrets in commits; uv-shebang:
  broken venv → `rm -rf` + `just test-venv`, never hand-edit.
- Migration is §1.9 steps 1–7 with vector's health check (old/new labels
  cannot share the 4318 bind): validate → pre-health → bootout+disable old →
  bootstrap `com.djbclark.vector` → verify (health + `launchctl print`
  state=running + one fleet-ingest smoke if reachable, else note pending) →
  rollback documented (`bootout` new + `enable` + `bootstrap` old plist).

## Verification (self-verify, record evidence in ledger)

- Focused serverapps/vector tests + `just check` green; full `just test` if
  Python behavior changed; `bin/registry_lint.py` OK if registry touched.
- Live: `com.djbclark.vector` running; legacy label booted out **and**
  `launchctl print-disabled gui/501` shows `com.stayturgid.vector` disabled;
  legacy plist still on disk; vector health endpoint answering; second
  `just site-serverapps mode=apply apps=vector` exit 0 all-skip file actions.
- Caddy untouched: /health 200 + HTTPS front door 200 after your changes.
- stayturgid PR merged, branch deleted, checkout on pulled master, CI green.

## End of session

Follow PROTOCOL.md exactly: ledger line `D2` (commits/PR, deviations,
anything deferred); rewrite `NEXT-PROMPT.md` as the **D3 baton** (openobserve
adapter per step2 row D3; recommended AI per FUND-B — Grok 4.5 or Codex;
self-passoff allowed if quota holds); commit/push site to master; print the
new baton and `pbcopy < docs/relay/NEXT-PROMPT.md`.
