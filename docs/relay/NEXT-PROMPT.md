# NEXT: D3 — openobserve adapter (clone D1/D2 pattern) (difficulty 40/100)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md`). Quality bar:
**correctness/safety must-fix only**; architecture/style findings may be
deferred to the ledger for M1. No human gates — self-verify per PROTOCOL.md.

**Recommended AI** (rows from `docs/reference/available-ai-models.md`):

- **Primary —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 · `grok-4.5` ·
  Low, Medium, High (default High) · _Flagship for code + agentic work_ —
  effort **Medium/High** (FUND-B Plan B row for D2–D4). Self-passoff from D2
  allowed if quota holds.
- **Alt —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol · `gpt-5.6-sol` ·
  Light, Medium, High, Extra High, Max, Ultra · _Flagship; complex coding,
  computer use, research, cybersecurity_ — use while Codex quota lasts.
- **Escalation:** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
  Auto) · _Next-gen long-running agents_ — **new second-Pro account**, only
  if openobserve diverges from the single-owner §5.3 pattern.

**Working dir:** `/Users/djbclark/ops/stayturgid` (implementation; branch +
PR + merge-your-own per PROTOCOL) + `/Users/djbclark/ops/site-djbclark`
(registry/inventory edits + relay; straight to master).

---

You are executing **D3**: the openobserve serverapp adapter, cloning the
reviewed D1 caddy + D2 vector pattern. Do not re-decide architecture — D0
design notes + R1 already settled the shape. OpenObserve is a
**single-owner** daemon (site-contract §5.3): inject mode means "reuse
endpoint from registry only" — **zero file writes** in inject.

## Read first (absolute paths)

1. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` (end-of-session
   ritual; merge your own stayturgid PR; print + `pbcopy` next baton).
2. `/Users/djbclark/ops/site-djbclark/docs/design/phase-d-adapter-design-notes.md`
   §§0–1 (adapter pattern; §1.9 migration + R1 persistent-disable rollback),
   §4 (deviation protocol — ledger any deviation).
3. `/Users/djbclark/ops/site-djbclark/docs/relay/reviews/r1-d1-adapter-review.md`
   — R1 findings; clone-safety notes; MF-1 bootout+disable pattern;
   F4 second-apply ansible ensure accepted; F5 do not delete rollback plists
   before D7.
4. Step2 plan §§0–2 + Phase D row D3:
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
5. stayturgid: `docs/architecture/site-contract.md` §5 (openobserve /
   victoriametrics row of §5.3 — single-owner; inject = reuse endpoint only);
   `ansible/roles/control_node/tasks/observability.yml` +
   `templates/openobserve.plist.j2` (current com.stayturgid.openobserve
   management — starting material); `control/site_contract/serverapps.py` +
   `sync_manifest.yml` + `tests/python/test_serverapps.py` (D1/D2 template);
   `ansible/roles/serverapp_caddy/` + `ansible/roles/serverapp_vector/` (role
   shape incl. legacy bootout + persistent-disable — clone both).
6. Site: `registry/ports.yml` (5080/5081 openobserve ports — move owner →
   site), `inventory/group_vars/all.yml` (`site_ns: djbclark`,
   `openobserve_root_email` already set for D2 vector sink),
   `docs/relay/LEDGER.md` D1/D2/R1 rows.

## Task (step2 plan row D3)

OpenObserve adapter: start from merged `observability.yml` +
`openobserve.plist.j2` (already Ansible-managed under
`com.stayturgid.openobserve`); new role `serverapp_openobserve` extracted
from observability.yml vector/OO split (D2 left vector tasks in
observability — same residual as caddy; leave OO render residual for D7,
do not set any `*_enabled: false` that deletes the rollback plist).

- Relabel to `com.<site_ns>.openobserve`.
- **Data dir migration:** keep parquet/data path unchanged
  (`~/.local/share/openobserve/data` or current live path) so existing
  data is not re-ingested or lost — verify path before cutover.
- secretspec already declares `OPENOBSERVE_ROOT_PASSWORD`; password only
  via env / secretspec providers — never commit secrets.
- Binary install path: today control_node downloads OpenObserve EE when
  missing — preserve that pattern in the role (brew-if-absent style: never
  re-download if binary present; never upgrade by default).
- Health: `http://127.0.0.1:5080/healthz` (registry `openobserve-http`).
- Legacy `com.stayturgid.openobserve` bootout **+ persistent
  `launchctl disable`** (R1 MF-1 — clone vector/caddy).
- Plist retained until D7.
- Extend `serverapps.py`: add `openobserve` to `KNOWN_APPS` with per-app
  dispatch. Modes: own / inject / off. Inject = zero file writes, just
  confirm registry endpoint is reachable (or document as noop-verify).
- Site: update `registry/ports.yml` 5080/5081 owner → site; run
  `bin/registry_lint.py`.

Constraints carried from R1/G1/D2:

- Keep F4-accepted pattern: second own-mode apply re-runs ansible ensure
  (file actions skip; ansible no-op) — healing/verify path.
- Typed refusal kinds already in serverapps.py (R1 S-2 fixed in D2) — use
  them for any new refusals.
- Do not touch `com.djbclark.caddy` / `com.djbclark.vector` paths; do not
  set `stayturgid_caddy_enabled: false` or disable observability wholesale
  (breaks OO/vector residual plists before D7).
- paths.yml stays step1 schema (note only); no secrets in commits; uv-shebang:
  broken venv → `rm -rf` + `just test-venv`, never hand-edit.
- Migration is §1.9 steps 1–7 with openobserve health (old/new labels
  cannot share 5080/5081): validate/pre-render → pre-health →
  bootout+disable old → bootstrap `com.djbclark.openobserve` → verify
  (healthz 200 + `launchctl print` state=running + one OO API smoke if
  creds available, else note pending) → rollback documented
  (`bootout` new + `enable` + `bootstrap` old plist).

## Verification (self-verify, record evidence in ledger)

- Focused serverapps/openobserve tests + `just check` green; full `just
  test` if Python behavior changed; `bin/registry_lint.py` OK if registry
  touched.
- Live: `com.djbclark.openobserve` running; legacy label booted out **and**
  `launchctl print-disabled gui/501` shows `com.stayturgid.openobserve`
  disabled; legacy plist still on disk; data dir path unchanged; healthz
  200; second `just site-serverapps mode=apply apps=openobserve` exit 0
  all-skip file actions.
- Caddy + vector untouched: caddy /health 200 + HTTPS 200; vector
  `com.djbclark.vector` still running + `http://127.0.0.1:8686/health` 200.
- stayturgid PR merged, branch deleted, checkout on pulled master, CI green.

## End of session

Follow PROTOCOL.md exactly: ledger line `D3` (commits/PR, deviations,
anything deferred); rewrite `NEXT-PROMPT.md` as the **D4 baton** (landing
adapter per step2 row D4; recommended AI per FUND-B — Grok 4.5 or Codex;
self-passoff allowed if quota holds); commit/push site to master; print the
new baton and `pbcopy < docs/relay/NEXT-PROMPT.md`.
