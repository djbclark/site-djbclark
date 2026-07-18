# NEXT: B5 — Upstream identity scrub and strict validation (difficulty 55/100)

**Recommended AI:** Anthropic Claude Fable 5, effort Medium
alt: OpenAI Codex GPT-5.6 Terra, reasoning High
escalate to: Claude Fable 5, effort High

**Working dir:** `/Users/djbclark/ops/stayturgid`
**Operator gate:** none

---

You are executing **step B5** of the two-repository Ansible split. The public
product repo is `/Users/djbclark/ops/stayturgid`; the private site overlay is
`/Users/djbclark/ops/site-djbclark`. Complete the upstream production-identity
scrub required by `multi-site-topology.md` §4.6. Keep real inventory and
historical operator material private. Do not begin Phase C site-contract work.

## Read first

1. `/Users/djbclark/ops/stayturgid/AGENTS.md` and all applicable
   `/Users/djbclark/ops/stayturgid/.cursor/rules/` files.
2. The step2 execution plan, §§0–3 (including the risk register and B5):
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`.
3. The topology architecture, §§4.1 and 4.5–4.8 (especially §4.6):
   `/Users/djbclark/ops/stayturgid/docs/architecture/multi-site-topology.md`.
4. The step1 segmentation architecture, §§3–4:
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step1-segmentation-architecture-v1.md`.
5. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md`.
6. Current `control/bin/validate_site_identity.py`,
   `control/lib/site_identity.py`, `control/lib/ansible_context.py`,
   `just/tests.just`, CI workflow(s), and the current validator report.

## Context

- B1–B4 are complete and merged. B4 is upstream merge commit `d247e8e`
  (PR #5), with the checkout on pulled `master`.
- B4 introduced `control/lib/ansible_context.py`: explicit `ANSIBLE_CONFIG`
  wins; otherwise a site overlay defaults to
  `${STAYTURGID_SITE_DIR:-~/ops/site-djbclark}/ansible.cfg`; otherwise the
  upstream configuration is used. Reuse this contract rather than adding a
  second resolution rule.
- `just check` is currently green on master, but
  `validate-identity` is still warn-only and directly looks for the removed
  `ansible/inventory/hosts.yml`. Supplying the site config does not fix it,
  because the validator itself hardcodes that old path. This is a B5 tool
  defect to fix as part of making validation strict.
- The previous validator report described 193 hard-coded-production-identity
  violations. Generate the current worklist from the private overlay locally;
  do not paste real addresses, serials, or other site identity into the public
  PR, commits, or generic docs.
- The plan directs B5 to use **2–3 PRs by area**. Keep each focused and
  reviewable; do not broaden into architecture changes. The phase-end review
  is Sonnet 5 over the diff series, with `/code-review ultra` if B5 touches
  more than 40 files.

## Task

1. In `stayturgid`, inspect status, then run
   `git fetch origin --prune && git pull --ff-only origin master` before each
   edit/PR. Preserve the pre-existing untracked `.claude/` directory.
2. Make `site_identity` and `validate_site_identity` resolve the active
   inventory through B4's shared Ansible context. An explicit external config
   and the site-overlay default must work; upstream/fresh-clone validation
   must use only generic example/ephemeral inventory and never require or
   recreate production inventory in the public tree. Keep cache freshness
   correct for the resolved inventory.
3. Use the validator report as the worklist and scrub upstream tracked
   user-facing docs, tests, tools, defaults, and fixtures per §4.6:

   - use §4.1 example aliases (`oneui-device`, `stock-android-device`,
     `fireos-device`) and RFC 5737 example addresses in generic fixtures;
   - remove production hostnames, IPs, USB serials, operator paths, and
     site-specific default target names from public-facing content;
   - retain legitimate generic examples and move/retain historical material
     only under the private site repo or with the §4.6 historical banner;
   - do not re-do already merged fixes to `peers.json.j2`, peer bootstrap,
     `cf-runagent.cf`, and ADB defaults unless the validator identifies a
     remaining concrete defect.

4. Add/adjust focused tests for context-aware identity loading, example
   fallback, cache behavior, strict validator errors, and representative
   scrubbed fixtures. Do not hide violations by broadly expanding scanner
   skip paths.
5. Change `just validate-identity`, `just check`, and CI from advisory
   `--warn-only` behavior to hard failure only after the full report is clean.
   A fresh upstream clone/CI must remain green without the private overlay;
   an overlay-backed run must scan real identity locally without publishing it.

## Verification

- Run the strict validator using the site overlay (keep output containing
  live identity local) and show a zero-violation summary to the human.
- Demonstrate explicit external-config precedence, site-overlay default, and
  generic upstream/fresh-clone fallback.
- Run focused tests plus `just check`; run the relevant CI-equivalent
  inventory setup where needed. `just validate-identity` must be strict—no
  `--warn-only` remains in its check/CI path.
- `git diff --check` passes and the public diff contains no production
  inventory, real device identity, secrets, or private documentation.
- Use 2–3 focused PRs by area. Each PR must have its own human verification
  before it is merged; after each approved merge, delete its branch, return
  the checkout to pulled `master`, and re-run the relevant checks. Do not
  declare B5 complete until the entire strict-validation exit criterion is
  met.

## Human-verification checklist (present with evidence; wait for confirmation)

- [ ] Strict identity validation is clean with the private overlay, and a
      fresh upstream checkout validates only generic/example data
- [ ] Public docs/tests/tools are scrubbed per §4.6 without masking findings
- [ ] `just check` and CI use hard-fail validation and pass
- [ ] All B5 PRs are merged, deleted, and verified on pulled master; no
      unrelated changes remain

## End of session

Follow `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` exactly.
Every B5 PR must use the branch-hygiene rule: after human confirmation, merge
with `gh pr merge <n> --merge --delete-branch`, then run `git checkout master
&& git pull --ff-only` in `/Users/djbclark/ops/stayturgid` and verify the
applicable check suite on merged master. Do not leave an open step PR, deleted
branch pending locally, or the checkout off `master`. Once B5 as a whole is
confirmed, append its ledger line, rewrite the baton for C1 from the step2
plan, commit/push the private site repo, and print the new baton in chat.
