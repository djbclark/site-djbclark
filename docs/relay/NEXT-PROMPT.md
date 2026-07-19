# NEXT: C6 — Reference site re-init via contract (difficulty 50/100)

**Recommended AI:** Copilot premium (Sonnet-class) or Cursor composer
alt: Codex (medium); Grok 4 (thinking) if adoption diff is large
escalate to: Codex (high) or Sonnet 5 if live inventory/registry would be clobbered or adoption needs judgment

**Working dir:** `/Users/djbclark/ops/site-djbclark` (private site) + product at `/Users/djbclark/ops/stayturgid`
**Operator gate:** none for dry-run / plan; **confirm the apply diff** before writing live inventory, registry, secretspec, or ansible.cfg

---

You are executing **step C6** of the two-repository Ansible split. The private
reference site is `/Users/djbclark/ops/site-djbclark`; the public product is
`/Users/djbclark/ops/stayturgid` on pulled master with C1–C5 merged. Re-init
this site **as a consumer of the Site Contract**: adopt the product's
`generated/stayturgid/` area and lockfile (and any missing contract scaffold
pieces) **without clobbering existing live content**. Dry-run first; every
line of the real apply diff must be explainable.

Keep the step narrow. Do **not** implement Phase D serverapp adapters, move
daemons, change registry port/path *values* without operator intent, scrub
identity again (B5/B6 done), or re-open Entangled product work (C5 done). If
adoption requires an architecture decision not in the specs, stop and report.

## Read first

1. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md`.
2. Ground rules, model routing, risk register, and Phase C **C6** row in
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
   §§0–2 and §4.
3. Site contract spec (product):
   `/Users/djbclark/ops/stayturgid/docs/architecture/site-contract.md`
   §§2–4, §6 (site-map), §8 acceptance where relevant.
4. Product literate contract + tooling README:
   `/Users/djbclark/ops/stayturgid/SITE-CONTRACT.md`,
   `/Users/djbclark/ops/stayturgid/control/site_contract/README.md`.
5. Current site tree: `inventory/` (live hosts + group_vars),
   `registry/{ports,paths,identity-patterns}.yml`, `ansible.cfg`, `justfile`,
   `README.md`, `docs/`, `human/`, `bin/registry_lint.py` — **no**
   `generated/` yet.
6. Product CLIs (from product checkout, using site dir):
   `just site-init`, `just site-sync`, `site-map.yml` support (C4).
7. Relay ledger last lines for C4–C5 carry-forward.

## Current state and carry-forward gotchas

- stayturgid master at merge `240f7ee` (PR #15 C5). Product has full C1–C5:
  templates, `site-init`, `site-sync`+lockfile, fail-closed site-map,
  Entangled `SITE-CONTRACT.md` + `just site-contract-check`.
- C1 registry seeds: source-driven via `generate_registry_seeds`; site
  registries are live allocations — **do not overwrite** site
  `registry/ports.yml` / `paths.yml` with product seed defaults without an
  explicit, reviewed merge plan.
- C2: `site-init` never overwrites differing user files (exit 2). Use that:
  apply only creates missing paths; conflicts must be resolved deliberately.
- C3: `site-sync` only writes under `generated/stayturgid/`; lockfile records
  product version/commit; second apply is no-op when content matches.
- C4: optional `site-map.yml`; unknown keys fail closed. Site currently uses
  default layout (`inventory/hosts.yml`, `registry/ports.yml`,
  `registry/paths.yml`). Prefer defaults unless remapping is required.
- C5: only product contract is literate; do not make this site repo literate.
- CI baseline on product (PR #11): preserve generic inventory selection when
  touching stayturgid; this step primarily edits the **site** repo.
- Site `ansible.cfg` and `justfile` hardcode product path
  `/Users/djbclark/ops/stayturgid` today; product templates use Jinja
  `product_root` / OPS_ROOT detection. Adopting scaffold files must not break
  deploys — compare carefully; prefer keeping working site wrappers if they
  already satisfy the contract, and document deltas.
- Live inventory and operator docs must never be committed to the public
  product. All C6 work lands in this private site repo (and only product
  changes if a genuine contract bug is found — then branch+PR on stayturgid).
- There may be a leftover `~/ops/site-example` from earlier experiments that
  makes multi-site discovery ambiguous; do not delete it without asking. Prefer
  explicit `STAYTURGID_SITE_DIR` / `dir=` / `ANSIBLE_CONFIG` for this site.

## Exact task

1. `git fetch` / pull both repos; start from clean site `master`. Prefer a
   focused site branch if the operator wants review; site protocol allows
   straight-to-master for this private repo when the operator confirms the
   apply diff.
2. From product checkout, run **dry-run** only first:
   - `SITE_INIT_PYTHON=… just site-init sitename=djbclark dir=/Users/djbclark/ops/site-djbclark mode=dry-run`
   - Capture the full create/skip/overwrite action list.
   - Expect many **overwrite** candidates for existing files — **do not apply
     blind**. Classify each path: keep site live content vs adopt product
     scaffold for missing-only paths.
3. Strategy (must match specs; do not invent a third ownership model):
   - **Never clobber** live `inventory/hosts.yml`, `inventory/group_vars/*`,
     live `registry/ports.yml` / `paths.yml` / `identity-patterns.yml`,
     operator `docs/`, `human/`, or secrets values.
   - **Adopt** `generated/stayturgid/` via `site-sync` (create area + lockfile
     + manifest files). Dry-run `site-sync` then apply when the plan is only
     under `generated/stayturgid/`.
   - For missing contract scaffold only (e.g. `.gitignore` if absent,
     empty-dir placeholders): create with `site-init` apply **only if** dry-run
     shows pure `create` for those paths, or copy manually from product
     templates with the same bytes after reviewing.
   - If `site-init` dry-run shows overwrite for `ansible.cfg` / `justfile` /
     `README.md` / `secretspec.toml`, **diff and explain** — adopt only when
     the site file is strictly weaker and the operator-approved diff is clear;
     otherwise leave site-owned and document residual gaps.
4. Optional: add a minimal `site-map.yml` only if defaults are wrong for this
   layout. Fail closed on unknown keys. Default paths already match this site.
5. After apply: `site-sync` dry-run is no-op (or only expected creates once);
   second `site-sync` apply is no-op; lockfile present and committed.
6. Run site `bin/registry_lint.py`; from product with
   `STAYTURGID_SITE_DIR=/Users/djbclark/ops/site-djbclark` run
   `just validate-identity` (strict, zero drift); spot-check
   `just inventory-check` / deploy-check if safe (no surprise device contact
   without announce).
7. Do not contact devices unless operator asks; do not rotate secrets; do not
   implement adapters (Phase D).

## Verification

- Dry-run logs saved or pasted: every planned write classified.
- Apply (if any) only touches agreed paths; `git diff` on the site repo is
  fully explainable line-by-line.
- `generated/stayturgid/.lockfile.yml` exists, is committed, lists manifest
  files with hashes; `site-sync` second apply is no-op.
- Live inventory and registries unchanged unless a deliberate, reviewed edit.
- `bin/registry_lint.py` clean; strict identity validation clean with this
  overlay; no secret values in commits.
- Product stayturgid remains clean on master unless a justified product fix PR
  was required (then merge per product protocol).

## Human-verification checklist

- [ ] Dry-run of site-init/site-sync reviewed; overwrite risks identified
- [ ] Live inventory, group_vars, and registry allocations not clobbered
- [ ] `generated/stayturgid/` + lockfile adopted; second sync is no-op
- [ ] Diff vs pre-C6 tree explainable line-by-line
- [ ] registry lint + strict identity clean; no secrets committed
- [ ] Site repo committed/pushed; ledger + next baton updated per PROTOCOL.md

## End of session

Follow `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` exactly.
After C6 is human-confirmed and landed, append its ledger entry, prepare the
**Phase D / D1** baton from the execution-plan row (or phase-end review if the
plan says so), commit/push the site repo, and print the new `NEXT-PROMPT.md`
contents in chat.
