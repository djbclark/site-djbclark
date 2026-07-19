# NEXT: C4 — `site-map.yml` support (difficulty 45/100)

**Recommended AI:** OpenAI Codex GPT-5.x (medium)
alt: Copilot premium (Sonnet-class) / Cursor composer
escalate to: Codex (high) or Grok 4 (thinking) if fail-closed key
validation or remapped path semantics get subtle

**Working dir:** `/Users/djbclark/ops/stayturgid`
**Operator gate:** none

---

You are executing **step C4** of the two-repository Ansible split. The public
product repo is `/Users/djbclark/ops/stayturgid`; the private reference site
overlay is `/Users/djbclark/ops/site-djbclark`. Implement optional
`site-map.yml` support so an existing non-default site layout can remap the
paths the product expects, with **fail-closed** unknown keys, per the accepted
Site Contract v1 specification.

Keep the step narrow. Do **not** implement Entangled wiring (C5), serverapp
adapters (Phase D), or re-init of the reference site as a consumer (C6). Do
not invent inject-mode writes outside paths declared in the map. If the
accepted spec cannot be followed without making a later-step architecture
decision, stop and report the conflict rather than improvising.

## Read first

1. `/Users/djbclark/ops/stayturgid/AGENTS.md` and applicable files under
   `/Users/djbclark/ops/stayturgid/.cursor/rules/`.
2. Ground rules, model routing, risk register, and the Phase C C4 row in
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
   §§0–2 and §4.
3. **Authoritative specification:**
   `/Users/djbclark/ops/stayturgid/docs/architecture/site-contract.md`,
   especially §§1–2, **§6 (site-map.yml)**, §4 (sync still owns generated/),
   and §8 acceptance test **4**. Follow it exactly; deviations require
   operator approval.
4. Site-contract purpose and CLI context in
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step1-segmentation-architecture-v1.md`
   §§5–6.
5. Topology and configuration precedence:
   `/Users/djbclark/ops/stayturgid/docs/architecture/adr/005-two-repo-topology.md`
   and
   `/Users/djbclark/ops/stayturgid/docs/architecture/multi-site-topology.md`
   §4, especially §4.8.
6. Completed C1–C3 under
   `/Users/djbclark/ops/stayturgid/control/site_contract/`:
   templates, `generate_registry_seeds.py`, `site_init.py`, `site_sync.py`,
   `sync_manifest.yml`, `sync_templates/`, and tests
   `test_site_contract_templates.py`, `test_site_init.py`, `test_site_sync.py`.
7. Relay rules:
   `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md`.

## Current state and carry-forward gotchas

- Phase B is complete, including B6. Explicit `ANSIBLE_CONFIG` wins and its
  errors are fatal; otherwise resolution uses `STAYTURGID_SITE_DIR`, then
  exactly one discovered `site-*` checkout under `OPS_ROOT` (default
  `~/ops`). There is no hardcoded production-site fallback.
- C1 merged through stayturgid PR #10 as master commit `982a4b0` (templates +
  registry seed generator).
- C2 merged through stayturgid PR #12 as master commit `1e3c727`
  (`site-init` apply/dry-run/docs, exit codes 0/1/2).
- C3 merged through stayturgid PR #13 as master commit `488dd39`
  (`site-sync` + lockfile, plan-then-act, drift/force-generated/delete).
  Branch deleted; checkout ended clean on pulled `master`.
- C2 still **rejects** any non-empty `map=` until C4 lands. C4 must wire
  `map=` (and auto-discovery of `site-map.yml` at the site root if that is
  what the spec implies — follow §6; do not invent extra config files).
- C3 `site-sync` currently assumes default paths under the site dir
  (`inventory/`, `registry/`, `generated/stayturgid/`). C4 must make
  remapped `paths:` take effect for the locations the product reads/writes
  through the contract, **without** rewriting user-owned content at the
  default location when a remap is active (acceptance test 4).
- Spec §6 example keys under `paths:` include `inventory` and
  `registry_ports` (and similarly other contract paths as needed). Spec
  also shows `serverapps:` with per-app `config` / `fragment_dir` / `mode`.
  **C4 implements path remapping for contract-relevant paths used by
  site-init/site-sync today.** Full serverapp adapter behavior remains
  Phase D — if you must accept `serverapps` keys in the map schema for
  forward-compat, store/validate them fail-closed but do **not** start
  daemons or write inject fragments in C4 unless the acceptance test
  strictly requires it (it does not; test 4 is about remapped inventory
  path read/write).
- **Fail closed on unknown keys** — typos must not silently fall back to
  defaults. Unknown top-level keys, unknown `paths` keys, and unknown
  `serverapps` / per-app keys (if you parse that section) are exit 1 with
  a clear error naming the key.
- Just wrappers prefer `.venv-test/bin/python` (or `SITE_INIT_PYTHON` /
  `SITE_SYNC_PYTHON`) because system `python3` on CI may lack Jinja2/PyYAML.
  Explicit `jinja2` is in `tests/python/requirements.txt`.
- Registry seeds remain single-authority: `registry_sources.yml` holds
  selectors, not copied port/path literals. Preserve that design.
- PR #11 (`3091d10`) repaired the pre-existing GitHub Actions baseline. Do
  not undo its pinned Lychee/dotenv installers, job-wide generic Ansible
  selection, named test environment, or deterministic tests.
- C3 lockfile semantics are sharp: do not break drift detection, force-
  generated scope (generated area only), or plan-then-act no partial writes
  when adding map resolution.
- Generated-file headers use product version/commit (not wall-clock) so
  second apply is a true no-op; `synced` ISO-8601 lives only in the
  lockfile. Preserve that when touching sync code.

## Exact task

1. Inspect status, then run
   `git fetch origin --prune && git pull --ff-only origin master` before
   edits. Create a focused C4 branch. Preserve unrelated or pre-existing
   user changes.
2. Implement `site-map.yml` loading and validation per spec §6:
   - Optional file at the site dir root (and/or explicit `map=` path as
     already accepted by `site-init` CLI shape).
   - Schema: `contract_version: 1`, optional `paths:`, optional
     `serverapps:` (validate structure; do not implement Phase D adapters).
   - **Unknown keys → error (fail closed).**
   - Relative path values resolve relative to the site dir; reject
     escapes / nested-in-product violations (ADR 005) where applicable.
3. Wire remapping into the existing C2/C3 surfaces so that when a map
   remaps e.g. inventory (or other declared path keys the product uses):
   - `site-init` / `site-sync` (as appropriate) **read and write the mapped
     location** and **nothing at the default location** (acceptance test 4).
   - Default layout remains when no map is present (full C1–C3 regression).
4. Keep modes and exit codes unchanged (apply / dry-run / docs; 0 / 1 / 2).
   Invalid maps are exit 1 (precondition/input). Drift still exit 2.
5. Focused tests for acceptance test **4** plus safety:
   - Map with remapped inventory path → tools use mapped path only; default
     path is not created/written by the operation under test.
   - Unknown key in map → exit 1 naming the key.
   - No map → behavior identical to pre-C4 defaults.
   - Existing C1–C3 suite still passes.
   - docs mode remains generic-only if it documents map usage.
6. Do not initialize Git, install brew/Ansible, contact devices, create
   secrets, implement full serverapp adapters, or add Entangled. Do not
   complete C5/C6 as convenience work.

## Verification

- Exercise `map=` / site-map with temporary site dirs (init + sync as needed).
- Run the C1–C4 focused suite with the project test environment.
- Run the registry seed stale-output check with the same interpreter.
- Run
  `STAYTURGID_SITE_DIR=/Users/djbclark/ops/site-djbclark just check`.
- Run strict identity validation with the active overlay and separately with
  the upstream-only example inventory. Both must report zero drift and no
  secret-shaped strings.
- Run `git diff --check`, relevant pre-commit hooks, and hosted CI.
- Confirm the public PR diff contains no production inventory, addresses,
  serials, operator home path, credentials, or secret values.
- Create a branch and PR. Present the checklist below with evidence and wait
  for human confirmation before merging. After confirmation, merge with
  `gh pr merge <n> --merge --delete-branch`, return to pulled `master`, and
  rerun the relevant checks.

## Human-verification checklist

- [ ] `site-map.yml` / `map=` accepted; unknown keys fail closed (exit 1)
- [ ] remapped inventory (or other declared paths) used; default location
      not written when remap is active (acceptance test 4)
- [ ] no map → default layout behavior unchanged (C1–C3 regression green)
- [ ] dry-run/docs still make no writes; docs remain generic-only if updated
- [ ] drift / force-generated / lockfile semantics from C3 still hold
- [ ] no production identity or secrets in the public PR diff
- [ ] focused tests, `just check`, strict overlay/upstream identity
      validation, pre-commit, and hosted CI pass
- [ ] PR merged, branch deleted, checkout on pulled `master`

## End of session

Follow `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` exactly.
After C4 is human-confirmed and merged, append its ledger entry, prepare the
C5 baton from the execution-plan row, commit/push the site repo, and print the
new `NEXT-PROMPT.md` contents in chat.
