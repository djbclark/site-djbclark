# NEXT: C2 — `site-init` CLI (difficulty 55/100)

**Recommended AI:** OpenAI Codex GPT-5.x, reasoning High
alt: Grok 4 (thinking)
escalate to: Claude Fable 5, effort Low — only after rechecking the Claude
session and weekly quota, unless genuinely blocked

**Working dir:** `/Users/djbclark/ops/stayturgid`
**Operator gate:** none

---

You are executing **step C2** of the two-repository Ansible split. The public
product repo is `/Users/djbclark/ops/stayturgid`; the private reference site
overlay is `/Users/djbclark/ops/site-djbclark`. Implement the `site-init` CLI
surface with `apply`, `dry-run`, and `docs` modes and the exit codes defined by
the accepted Site Contract v1 specification.

Keep the step narrow. Do **not** implement `site-sync`, generated-file
lockfile/hash/delete semantics, serverapp adapters, Entangled wiring, or the
full `site-map.yml` remapping feature. Those belong to C3–C5. C4 owns complete
site-map support; do not invent partial remapping behavior. If the accepted
spec cannot be followed without making a later-step architecture decision,
stop and report the conflict rather than improvising.

## Read first

1. `/Users/djbclark/ops/stayturgid/AGENTS.md` and applicable files under
   `/Users/djbclark/ops/stayturgid/.cursor/rules/`.
2. Ground rules, model routing, risk register, and the Phase C C2 row in
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
   §§0–2 and §4.
3. **Authoritative specification:**
   `/Users/djbclark/ops/stayturgid/docs/architecture/site-contract.md`,
   especially §§1–3 and §8 acceptance tests 1, 2, and 6. Follow it exactly;
   deviations require operator approval.
4. Site-contract purpose and CLI context in
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step1-segmentation-architecture-v1.md`
   §§5–6.
5. Topology and configuration precedence:
   `/Users/djbclark/ops/stayturgid/docs/architecture/adr/005-two-repo-topology.md`
   and
   `/Users/djbclark/ops/stayturgid/docs/architecture/multi-site-topology.md`
   §4, especially §4.8.
6. The completed C1 inputs under
   `/Users/djbclark/ops/stayturgid/control/site_contract/`, including
   `README.md`, `templates/`, `registry_sources.yml`, and
   `generate_registry_seeds.py`; read
   `/Users/djbclark/ops/stayturgid/tests/python/test_site_contract_templates.py`.
7. Relay rules:
   `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md`.

## Current state and carry-forward gotchas

- Phase B is complete, including B6. Explicit `ANSIBLE_CONFIG` wins and its
  errors are fatal; otherwise resolution uses `STAYTURGID_SITE_DIR`, then
  exactly one discovered `site-*` checkout under `OPS_ROOT` (default
  `~/ops`). There is no hardcoded production-site fallback.
- C1 merged through stayturgid PR #10 as master commit `982a4b0`. Its branch
  is deleted and the checkout ended clean on pulled `master`.
- C1 provides the complete scaffold template tree and reproducible registry
  seeds. The seed source manifest contains selectors, not copied port/path
  literals. Preserve that single-authority design.
- The scaffold uses Jinja2 variables `site_name`, `product_root`,
  `stayturgid_root`, and `site_dir`; the inner `justfile` expressions are
  protected by a Jinja raw block.
- Direct system `python3` on the current Mac did not have PyYAML, while the
  project test environment did. Use the declared test/runtime dependencies
  and the project venv for verification; do not make tests depend on an
  accidental globally installed package.
- The generated-area placeholder from C1 is intentional. C3 owns the
  `.lockfile.yml` format and all sync drift/hash/delete semantics; do not
  implement those early in C2.
- PR #11 (`3091d10`) repaired the pre-existing GitHub Actions baseline. Do
  not undo its pinned Lychee/dotenv installers, job-wide generic Ansible
  selection, named test environment, or deterministic tests.

## Exact task

1. Inspect status, then run
   `git fetch origin --prune && git pull --ff-only origin master` before
   edits. Create a focused C2 branch. Preserve unrelated or pre-existing
   user changes.
2. Add one Python implementation under `control/site_contract/` and wire the
   product `justfile` surface exactly as specified:

   ```text
   just site-init sitename=<name> [dir=<path>] [map=<site-map.yml>] [mode=apply|dry-run|docs]
   ```

   `mode=apply` is the default. Keep Python behavior directly testable; the
   `just` recipe should remain a thin wrapper.

3. Resolve the default destination as sibling `site-<name>` under
   `OPS_ROOT` while honoring an explicit `dir`. Validate the site name and
   destination before any write. A private site directory must never be
   nested inside the public product working tree.
4. Render or copy the C1 template tree into the destination:
   - render `.j2` files with explicit context and remove the `.j2` suffix;
   - copy non-template files byte-for-byte;
   - preserve empty scaffold directories/placeholders;
   - treat every initialized file outside `generated/stayturgid/` as
     user-owned after creation;
   - never overwrite a user file. A second identical apply must be a no-op.
5. Implement deterministic modes and exit codes from site-contract §2:
   - `apply`: perform the planned filesystem actions;
   - `dry-run`: print the exact per-file action list (`create`, `overwrite`,
     or `skip` as applicable), make **no filesystem changes**, and exit 0
     when preconditions pass;
   - `docs`: emit self-contained Markdown describing every initialization
     step and its manual equivalent, without writing files;
   - exit 0 for success/no-op, 1 for precondition or input failure, and 2
     before any would-overwrite-user-file operation. Report the conflicting
     path clearly.
6. Keep docs output generic: only RFC 5737/example inventory values and
   generic names are allowed. Do not read or render the private reference
   site's identity into public output or tests.
7. Add focused tests for acceptance tests 1, 2, and 6, plus the safety
   invariants needed to prove them:
   - dry-run in a nonexistent/empty temporary destination lists actions and
     leaves the filesystem byte-for-byte unchanged;
   - apply creates the §3 scaffold, parses rendered structured files, and
     copies the complete derived port/path registries;
   - a second apply is a no-op;
   - a conflicting user-owned file returns exit 2 without partial writes;
   - bad input/preconditions return exit 1;
   - a destination nested in the product checkout is rejected before write;
   - docs mode is deterministic, self-contained Markdown and contains no
     site-specific identity or operator home path.
8. Do not initialize Git, install brew/Ansible, contact devices, or create
   secrets unless the accepted spec explicitly requires it for C2. Do not
   add `site-sync`, lockfile semantics, adapters, or Entangled as
   convenience work.

## Verification

- Exercise the `just site-init` wrapper and the Python entry point in
  temporary directories for all three modes and all exit codes.
- Run the C1+C2 focused suite using the project test environment, including
  `/Users/djbclark/ops/stayturgid/tests/python/test_site_contract_templates.py`.
- Run the registry seed stale-output check with the same project interpreter.
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

- [ ] `just site-init` exposes the specified apply/dry-run/docs surface and
      correct 0/1/2 exit codes
- [ ] dry-run and docs modes make no writes; docs contain only generic values
- [ ] apply creates the complete C1 scaffold and a second apply is a no-op
- [ ] user-owned files and public/private repository separation are protected
- [ ] acceptance tests 1, 2, and 6 plus focused safety tests pass
- [ ] `just check`, strict overlay/upstream identity validation, diff checks,
      pre-commit, and hosted CI pass
- [ ] PR merged, branch deleted, checkout on pulled `master`

## End of session

Follow `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` exactly.
After C2 is human-confirmed and merged, append its ledger entry, prepare the
C3 baton from the execution-plan row, commit/push the site repo, and print the
new `NEXT-PROMPT.md` contents in chat.
