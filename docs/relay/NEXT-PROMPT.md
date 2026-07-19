# NEXT: C1 — Site-contract scaffolding templates (difficulty 40/100)

**Recommended AI:** OpenAI Codex GPT-5.x, reasoning Medium (quota check
2026-07-18: Claude Pro session projected empty in ~1h21m and weekly is also
deficit-pacing — hold Sonnet 5/Fable 5 for after a reset)
alt: Copilot premium (Sonnet/GPT-5 class) or Cursor composer
escalate to: Claude Fable 5, effort Low — only after Claude session (~4h15m)
or weekly (~5d6h) resets, unless genuinely blocked

**Working dir:** `/Users/djbclark/ops/stayturgid`
**Operator gate:** none

---

You are executing **step C1** of the two-repository Ansible split. The public
product repo is `/Users/djbclark/ops/stayturgid`; the private site overlay is
`/Users/djbclark/ops/site-djbclark`. Implement the site-contract **scaffolding
templates only** (Phase C starts here). Do **not** implement `site-init`,
`site-sync`, adapters, or Entangled wiring yet (C2–C6).

## Read first

1. `/Users/djbclark/ops/stayturgid/AGENTS.md` and applicable
   `/Users/djbclark/ops/stayturgid/.cursor/rules/` files.
2. Ground rules + risk register + Phase C row C1:
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
   §§0–2 and §4 (C1 only).
3. **Authoritative spec** (follow exactly; no architecture improvisation):
   `/Users/djbclark/ops/stayturgid/docs/architecture/site-contract.md`
   especially §§1–3 (layout), registry seeding notes, and §8 acceptance
   items that apply to templates.
4. ADR + topology context:
   `/Users/djbclark/ops/stayturgid/docs/architecture/adr/005-two-repo-topology.md`,
   `/Users/djbclark/ops/stayturgid/docs/architecture/multi-site-topology.md` §4
   (esp. §4.8 configuration precedence — updated by B6).
5. Step1 segmentation (site contract purpose):
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step1-segmentation-architecture-v1.md` §§5–6.
6. Relay protocol:
   `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md`.
7. Existing product defaults you must **derive** registry seeds from (not
   copy as opaque literals): control-node / landing / observability role
   defaults and any checked-in port/path claims under
   `/Users/djbclark/ops/stayturgid/ansible/` and collections. Cross-check
   `/Users/djbclark/ops/site-djbclark/registry/` for the reference site's
   current claims shape.

## Context (B1–B6 done)

- Phase B is complete **including B6**, which closed both independent Phase B
  reviews (see `docs/relay/reviews/phase-b-review-{codex-sol,gemini-pro}.md`,
  dispositioned; stayturgid PR #9 → master `36e4920`).
- Inventory lives in the private site overlay; upstream ships only
  `ansible/inventory/hosts.yml.example` with §4.1 names + RFC 5737 addresses.
- **B6 amended the B4 contract — reuse it, do not invent a second rule:**
  explicit `ANSIBLE_CONFIG` wins (its errors are fatal, no silent fallback);
  else `STAYTURGID_SITE_DIR`; else exactly one discovered `site-*` checkout
  under `OPS_ROOT` (default `~/ops`); zero or multiple matches fail with
  instructions. There is **no hardcoded site default** anywhere in product
  code. Shared helpers live in `control/lib/ansible_context.py`
  (`resolve_ansible_context`, `resolved_env`, `require_limit_hosts` — all
  fleet entry points refuse zero-host limits).
- B6 also hardened `just validate-identity`: it scans `.cf` files and merges
  site-private denylist regexes from the active overlay's
  `registry/identity-patterns.yml` (this site seeds LAN + tailnet ranges
  there). cf-runagent renders to `~/.config/stayturgid/cfengine/` (never the
  tracked tree); `cf-serverd.cf` allowusers is templated from inventory.
  Your templates must respect both patterns (no rendered identity into
  tracked paths; no operator literals in templates).
- C1 is templates only. C2 will consume them via `site-init`.

## Task

1. In `stayturgid`, inspect status, then
   `git fetch origin --prune && git pull --ff-only origin master` before
   edits. Preserve any pre-existing untracked `.claude/` directory.
2. Create `control/site_contract/templates/` containing the scaffold
   artifacts defined by site-contract.md §3:
   - site `README.md` (generated once / user-owned after init — template
     should say so)
   - `ansible.cfg` (inventory in site dir; collections/playbooks → product)
   - thin `justfile` (OPS_ROOT / product path detection; deploy wrappers)
   - baseline `.gitignore` (secrets patterns; do **not** ignore `generated/`)
   - `registry/ports.yml` and `registry/paths.yml` **seeds** derived from
     product role defaults programmatically (script or documented generator
     under `control/site_contract/`), not hand-copied magic numbers
   - any other template files §3 requires for a complete empty site dir
     shape (inventory example pointer, `secretspec.toml` site profile stub
     if specified)
3. Prefer Jinja2 or clearly marked placeholders consistent with the rest of
   the product. Templates must not embed live site identity (real host
   aliases, production IPs, serials, operator home paths).
4. Add focused unit tests that:
   - render or load each template without error
   - assert registry seeds contain expected product-owned claims sourced
     from role defaults (not empty stubs)
   - assert `.gitignore` ignores secrets patterns and does not ignore
     `generated/`
5. Do **not** implement `just site-init` / CLI behavior (that is C2). A
   minimal package `__init__` or README under `control/site_contract/` is
   fine if needed for import/tests.

## Verification

- Templates exist at the paths implied by the spec.
- Registry seeds are explainable from role defaults (show the derivation).
- Focused tests pass; `just check` remains green; `just validate-identity`
  still hard-fails clean (0 drift) with overlay and with upstream-only
  example inventory.
- `git diff --check` passes; public diff has no production inventory or
  live identity.
- Branch + PR; after human confirmation: merge, delete branch, return to
  pulled master, re-verify checks.

## Human-verification checklist (present with evidence; wait for confirmation)

- [ ] `control/site_contract/templates/` matches site-contract.md §3 layout
- [ ] Registry seeds derive from product defaults (not hand-waved literals)
- [ ] Focused tests + `just check` + strict `validate-identity` pass
- [ ] PR merged, branch deleted, checkout on pulled master

## End of session

Follow `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` exactly.
After C1 is fully confirmed, append its ledger entry, prepare the C2 baton,
commit/push the site repo, and print that baton in chat.
