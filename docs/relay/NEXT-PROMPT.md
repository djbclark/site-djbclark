# NEXT: C3 — `site-sync` + lockfile (difficulty 65/100)

**Recommended AI:** Grok 4 (thinking)
alt: OpenAI Codex GPT-5.x, reasoning High
escalate to: Claude Fable 5, effort Medium — drift/hash/delete semantics have
sharp edges; schedule after rechecking Claude session/weekly quota if not
urgent, or escalate when genuinely blocked

**Working dir:** `/Users/djbclark/ops/stayturgid`
**Operator gate:** none

---

You are executing **step C3** of the two-repository Ansible split. The public
product repo is `/Users/djbclark/ops/stayturgid`; the private reference site
overlay is `/Users/djbclark/ops/site-djbclark`. Implement `site-sync` with
apply/dry-run/docs modes and the generated-area lockfile semantics defined by
the accepted Site Contract v1 specification.

Keep the step narrow. Do **not** implement full `site-map.yml` remapping (C4),
Entangled wiring (C5), serverapp adapters (Phase D), or re-init of the
reference site as a consumer (C6). If the accepted spec cannot be followed
without making a later-step architecture decision, stop and report the conflict
rather than improvising.

## Read first

1. `/Users/djbclark/ops/stayturgid/AGENTS.md` and applicable files under
   `/Users/djbclark/ops/stayturgid/.cursor/rules/`.
2. Ground rules, model routing, risk register, and the Phase C C3 row in
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
   §§0–2 and §4.
3. **Authoritative specification:**
   `/Users/djbclark/ops/stayturgid/docs/architecture/site-contract.md`,
   especially §§1–2, **§4 (sync model and lockfile)**, and §8 acceptance
   test **3**. Follow it exactly; deviations require operator approval.
4. Site-contract purpose and CLI context in
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step1-segmentation-architecture-v1.md`
   §§5–6.
5. Topology and configuration precedence:
   `/Users/djbclark/ops/stayturgid/docs/architecture/adr/005-two-repo-topology.md`
   and
   `/Users/djbclark/ops/stayturgid/docs/architecture/multi-site-topology.md`
   §4, especially §4.8.
6. Completed C1+C2 under
   `/Users/djbclark/ops/stayturgid/control/site_contract/`:
   templates, `generate_registry_seeds.py`, `site_init.py`, and
   `/Users/djbclark/ops/stayturgid/tests/python/test_site_init.py` +
   `test_site_contract_templates.py`.
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
  (`site-init` apply/dry-run/docs, exit codes 0/1/2). Branch deleted; checkout
  ended clean on pulled `master`.
- C2 `site-init` creates `generated/stayturgid/.gitkeep` only (no lockfile yet).
  Everything outside `generated/stayturgid/` is user-owned after init; never
  overwrite differing user files (exit 2). Second identical apply is a no-op.
- C2 accepts the `map=` CLI parameter but **rejects** any non-empty map until
  C4 (fail-closed). Do not invent partial site-map remapping in C3.
- Just wrapper for site-init prefers `.venv-test/bin/python` (or
  `SITE_INIT_PYTHON`) because system `python3` on CI lacked Jinja2. Follow the
  same pattern for `site-sync` if it needs Jinja2/PyYAML. Explicit `jinja2`
  is now in `tests/python/requirements.txt`; do not assume global packages.
- Registry seeds remain single-authority: `registry_sources.yml` holds
  selectors, not copied port/path literals. Preserve that design.
- PR #11 (`3091d10`) repaired the pre-existing GitHub Actions baseline. Do
  not undo its pinned Lychee/dotenv installers, job-wide generic Ansible
  selection, named test environment, or deterministic tests.
- C3 is difficulty 65: lockfile hash drift, force-generated, and delete of
  files removed from the product manifest are easy to get subtly wrong.
  Prefer a complete plan-then-act model (like C2) so dry-run and apply share
  one action list and exit 2 never partial-writes.

## Exact task

1. Inspect status, then run
   `git fetch origin --prune && git pull --ff-only origin master` before
   edits. Create a focused C3 branch. Preserve unrelated or pre-existing
   user changes.
2. Add Python implementation under `control/site_contract/` and wire the
   product `justfile` surface exactly as specified:

   ```text
   just site-sync [dir=<path>] [mode=apply|dry-run|docs]
   ```

   `mode=apply` is the default. Keep Python behavior directly testable; the
   `just` recipe should remain a thin wrapper (same KEY=VALUE-after-recipe
   pattern as C2 if needed).

3. Implement lockfile at `generated/<product>/.lockfile.yml` per §4:

   ```yaml
   contract_version: 1
   product: stayturgid
   product_version: <version.json version>
   product_commit: <git sha of product checkout at sync time>
   synced: <ISO-8601>
   files:
     - path: generated/stayturgid/...
       sha256: <hash of rendered output>
   ```

4. Sync rules (spec §4 — follow exactly):
   - Re-render every file in the **product manifest** from the currently
     checked-out product version, using site facts from `inventory/` and
     `registry/` as required by the templates you introduce.
   - Before overwriting a generated file, compare on-disk content hash to
     the lockfile hash. If they differ (hand-edited generated file), **stop
     with exit 2** and list the drifted paths. Support `--force-generated`
     (or the just-equivalent flag) to overwrite only inside the generated
     area.
   - Files that disappear from the product manifest are deleted from the
     generated area (listed in dry-run first).
   - `site-sync` never writes outside `generated/<product>/` in C3. Do not
     implement serverapp inject-mode writes (Phase D / §5).
   - User area outside `generated/<product>/` is never touched.

5. Define a minimal v1 **product sync manifest** of generated files. C3 may
   ship a small, real scaffold (e.g. a marker/readme or empty fragment tree
   with a generated header) so lockfile create/update/drift/delete are fully
   testable without inventing Phase D adapters. Prefer one clear manifest
   source of truth under `control/site_contract/`. Do not invent site-map
   path remapping.

6. Modes and exit codes (site-contract §2):
   - `apply`: perform planned actions inside `generated/<product>/`
   - `dry-run`: print exact per-file actions (`create` / `overwrite` /
     `skip` / `delete` as applicable); no filesystem changes; exit 0 when
     preconditions pass
   - `docs`: self-contained Markdown for every sync step and its manual
     equivalent; generic values only (RFC 5737 / example names); no writes
   - exit 0 success/no-op; 1 precondition/input failure; 2 would overwrite
     drifted generated content (unless force-generated) or other
     would-overwrite-user-file cases

7. Destination resolution:
   - Honor explicit `dir=`
   - Else resolve like product tooling: `STAYTURGID_SITE_DIR`, else exactly
     one `site-*` under `OPS_ROOT` — no hardcoded production-site fallback
   - Reject destinations nested inside the product checkout (ADR 005)

8. Focused tests for acceptance test **3** plus safety invariants:
   - dry-run lists actions and writes nothing
   - apply creates/updates generated files + lockfile; second apply no-op
     when product unchanged
   - hand-edit a generated file → exit 2 naming the file; force-generated
     recovers
   - remove a path from the product manifest → dry-run lists delete; apply
     deletes it and updates lockfile
   - never writes outside `generated/<product>/`
   - docs mode deterministic, generic-only
   - bad dir / missing site / nested-in-product → exit 1

9. Do not initialize Git, install brew/Ansible, contact devices, create
   secrets, implement adapters, or add Entangled. Do not complete C4/C5/C6
   as convenience work.

## Verification

- Exercise `just site-sync` and the Python entry point for all modes and
  exit codes in temporary site dirs (prefer dirs created via `site-init`).
- Run the C1+C2+C3 focused suite with the project test environment,
  including `test_site_contract_templates.py` and `test_site_init.py`.
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

- [ ] `just site-sync` exposes apply/dry-run/docs and correct 0/1/2 exit codes
- [ ] dry-run and docs make no writes; docs contain only generic values
- [ ] apply maintains `generated/stayturgid/` + `.lockfile.yml`; re-sync no-op
      when unchanged
- [ ] hand-edited generated file → exit 2; `--force-generated` overwrites
      only inside the generated area
- [ ] manifest removals delete from generated area (dry-run then apply)
- [ ] no writes outside `generated/<product>/`; public/private separation held
- [ ] acceptance test 3 plus focused safety tests pass
- [ ] `just check`, strict overlay/upstream identity validation, diff checks,
      pre-commit, and hosted CI pass
- [ ] PR merged, branch deleted, checkout on pulled `master`

## End of session

Follow `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` exactly.
After C3 is human-confirmed and merged, append its ledger entry, prepare the
C4 baton from the execution-plan row, commit/push the site repo, and print the
new `NEXT-PROMPT.md` contents in chat.
