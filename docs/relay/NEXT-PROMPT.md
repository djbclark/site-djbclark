# NEXT: C5 — Entangled site-contract wiring (difficulty 55/100)

**Recommended AI:** Grok 4 (thinking)
alt: Gemini 3 Pro; use Codex (low) for CI wiring if useful
escalate to: Codex (high) if bidirectional tangling or CI parity semantics get subtle

**Working dir:** `/Users/djbclark/ops/stayturgid`
**Operator gate:** none

---

You are executing **step C5** of the two-repository Ansible split. The public
product repo is `/Users/djbclark/ops/stayturgid`; the private reference site
overlay is `/Users/djbclark/ops/site-djbclark`. Implement the accepted
Site Contract v1 literate layout with Entangled: add the product's
`SITE-CONTRACT.md` as the human-readable contract source, tangle its fenced
blocks into the completed C1 scaffold templates, and make CI fail when the
document and tangled output drift.

Keep the step narrow. Do **not** re-initialize the reference site (C6), build
serverapp adapters (Phase D), alter site-map semantics, or turn product roles
and internal code into literate sources. If the accepted spec cannot be
implemented without a new architecture decision, stop and report the conflict
rather than improvising.

## Read first

1. `/Users/djbclark/ops/stayturgid/AGENTS.md` and all applicable files under
   `/Users/djbclark/ops/stayturgid/.cursor/rules/`.
2. Ground rules, model routing, risk register, and the Phase C C5 row in
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
   §§0–2 and §4.
3. **Authoritative specification:**
   `/Users/djbclark/ops/stayturgid/docs/architecture/site-contract.md`,
   especially §2 docs mode, §3 scaffold layout, **§7 literate layout**, and
   §8 acceptance tests 1, 2, and 6. Follow it exactly; deviations require
   operator approval.
4. The accepted Entangled scope and rationale in
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step1-segmentation-architecture-v1.md`
   §6, plus site-contract purpose in §5.
5. Completed C1–C4 under
   `/Users/djbclark/ops/stayturgid/control/site_contract/`, especially
   `templates/`, `site_init.py`, `site_sync.py`, `site_map.py`, registry seed
   generation, and the three focused test modules under `tests/python/`.
6. Current CI and dependency wiring in
   `/Users/djbclark/ops/stayturgid/.github/workflows/test.yml`,
   `tests/python/requirements.txt`, `pyproject.toml`, `.pre-commit-config.yaml`,
   `just/tests.just`, and `just/site.just`.
7. Relay rules:
   `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md`.

## Current state and carry-forward gotchas

- Phase B and C1–C4 are complete. stayturgid is clean on pulled `master` at
  merge commit `9fc611b`.
- C1: templates + source-driven registry seed generator (`982a4b0`).
- CI baseline repairs from PR #11 remain required (`3091d10`): preserve pinned
  Lychee/dotenv installers, job-wide generic Ansible selection, the named test
  environment, collection installation, and deterministic tests.
- C2: `site-init` apply/dry-run/docs and exit codes 0/1/2 (`1e3c727`).
- C3: `site-sync`, plan-then-act lockfile/drift/force/delete semantics
  (`488dd39`). Generated headers use product version/commit, not wall-clock;
  `synced` is lockfile-only so a second apply remains a true no-op.
- C4: fail-closed `site-map.yml` / `map=` support (`9fc611b`). Contract path
  keys currently used are `inventory`, `registry_ports`, and `registry_paths`.
  Unknown keys, escapes, generated-area targets, and path collisions exit 1.
  Serverapp entries are validated only; Phase D behavior remains deferred.
- The current C1 template tree includes Jinja templates, copied YAML/text
  files, dotfiles, and empty `.gitkeep` files. Preserve exact bytes and paths.
- Registry seeds remain single-authority: `registry_sources.yml` contains
  selectors, not copied port/path literals. Do not make the literate document
  a second authority for generated registry values or bypass the stale-output
  check.
- Scope discipline is explicit: only the site contract document and its
  scaffold outputs are literate. Do not tangle `site_init.py`, `site_sync.py`,
  `site_map.py`, roles, playbooks, adapters, or unrelated docs.
- Entangled behavior and install commands are version-sensitive. Verify the
  current official Entangled documentation/package before wiring commands;
  pin or constrain dependencies consistently with the project's existing CI
  conventions. Do not substitute another tangling tool.

## Exact task

1. Inspect status, then run
   `git fetch origin --prune && git pull --ff-only origin master` before edits.
   Create a focused C5 branch and preserve unrelated user changes.
2. Add product-root `SITE-CONTRACT.md` as the human-readable Site Contract v1
   literate source. It must:
   - explain the contract coherently for a user who refuses automation;
   - contain Entangled-compatible fenced blocks for the C1 scaffold outputs
     under `control/site_contract/templates/`;
   - preserve every existing template path and exact rendered source bytes,
     including dotfiles and empty `.gitkeep` files;
   - keep product-derived registry values single-authority. If generated seed
     files cannot be represented without duplicating authority, use the
     accepted spec and existing generator/check to define the safe wiring; do
     not hand-copy a second set of literals.
3. Add the minimal Entangled project/dependency configuration required for
   deterministic local and CI use. The checked-in templates must equal the
   tangled output exactly after a normal tangle.
4. Add a check that fails closed when `SITE-CONTRACT.md` and its tangled C1
   outputs drift. Wire it into the existing local check/test surface and hosted
   CI without weakening or undoing the repaired CI baseline.
5. Reconcile `site-init mode=docs` with Site Contract §§2 and 7. Docs output
   must remain deterministic, self-contained, generic-only, and write nothing.
   Do not leak the current site, operator home, production inventory, or live
   registry values. Keep apply/dry-run behavior and exit codes unchanged.
6. Add focused tests for:
   - a clean Entangled parity check;
   - a deliberately drifted document or tangled output failing the check;
   - all existing C1 scaffold templates still present and byte-correct;
   - `mode=docs` rendering the accepted generic contract with no writes or
     private identity;
   - full C1–C4 regression, including site-map and C3 lockfile semantics.
7. Do not initialize Git, contact devices, create secrets, re-init the private
   site, implement C6, or add any Phase D adapter behavior.

## Verification

- Run the Entangled tangle/check commands from a clean tree and prove a planted
  drift fails, then restore it and prove the check passes.
- Run the C1–C5 focused suite with `.venv-test/bin/python`.
- Run the registry seed stale-output check with the same interpreter.
- Run `SITE_INIT_PYTHON=.venv-test/bin/python just site-init sitename=example mode=docs`
  and scan the output for generic-only values and no writes.
- Run
  `STAYTURGID_SITE_DIR=/Users/djbclark/ops/site-djbclark just check`, plus
  `just test` and relevant lint/pre-commit hooks.
- Run strict identity validation with the active overlay and separately with
  the upstream-only example inventory. Both must report zero drift and no
  secret-shaped strings.
- Run `git diff --check` and hosted CI.
- Confirm the public PR diff contains no production inventory, addresses,
  serials, operator home path, credentials, or secret values.
- Create a branch and PR. Present the checklist below with evidence and wait
  for human confirmation before merging. After confirmation, merge with
  `gh pr merge <n> --merge --delete-branch`, return to pulled `master`, and
  rerun relevant checks.

## Human-verification checklist

- [ ] `SITE-CONTRACT.md` is the coherent human-readable contract and Entangled
      source for the complete C1 scaffold template set
- [ ] clean tangle/check passes; planted document/output drift fails closed
- [ ] registry values remain source-driven with no duplicated literal authority
- [ ] `site-init mode=docs` is deterministic, generic-only, and write-free
- [ ] C1–C4 apply/dry-run/exit-code/map/lockfile regressions remain green
- [ ] no product roles, adapters, or unrelated internals were made literate
- [ ] no production identity or secrets in the public PR diff
- [ ] focused tests, registry check, `just check`, `just test`, strict
      overlay/upstream identity, pre-commit, and hosted CI pass
- [ ] PR merged, branch deleted, checkout on pulled `master`

## End of session

Follow `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` exactly.
After C5 is human-confirmed and merged, append its ledger entry, prepare the
C6 baton from the execution-plan row, commit/push the site repo, and print the
new `NEXT-PROMPT.md` contents in chat.
