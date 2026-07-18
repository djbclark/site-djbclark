# NEXT: B3 — Move operator docs to the site repo   (difficulty 30/100)

**Recommended AI:** Haiku 4.5 or Copilot chat · alt: Codex (low reasoning) · escalate to: Claude Sonnet 5
**Working dir:** `/Users/djbclark/ops/site-djbclark` (with `/Users/djbclark/ops/stayturgid` as the upstream source)   **Operator gate:** none

---

You are executing **step B3** of the two-repo Ansible split. The public
product repo is `/Users/djbclark/ops/stayturgid`; the private site repo is
`/Users/djbclark/ops/site-djbclark`. This is a documentation move and link
repair only. Do not make architecture decisions or broaden this into B5's
generic documentation/test scrub.

## Read first (in this order)

1. `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
   — §0 ground rules, §1 model routing, §2 risk register, and §3 row B3.
2. `/Users/djbclark/ops/stayturgid/AGENTS.md` and all applicable
   `/Users/djbclark/ops/stayturgid/.cursor/rules/` files.
3. `/Users/djbclark/ops/stayturgid/docs/architecture/multi-site-topology.md`
   — §4.2, §4.3, and §4.6 in particular.
4. `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step1-segmentation-architecture-v1.md`
   — §§3–4.
5. The current upstream `docs/handoff.md`, all tracked `human/` files, their
   inbound links, and the site repo's current documentation layout.

## Context carried from B1/B2

- B1 is complete in site commit `9038c2d`: the live identity inventory is in
  the private site repo.
- B2 is confirmed and is open as stayturgid PR #3 (`9bd1650`); it removes
  the tracked public production inventory and makes CI use the generic
  example. Check its merge state before starting; do not merge it yourself.
- Generic taxonomy `group_vars` remain product-side and the private site
  inventory retains its copies for Ansible loading. This B3 step does not
  revisit that mechanics decision.

## Task (B3): move operator-facing docs out of upstream

1. In both repos, inspect Git status first. In stayturgid, run
   `git fetch origin --prune && git pull --ff-only origin master`, create a
   dedicated branch, and open a PR; do not commit directly to upstream
   `master`. Preserve any pre-existing ignored/untracked operator files.
2. Move the live operational content of
   `/Users/djbclark/ops/stayturgid/docs/handoff.md` into the site repo as
   `/Users/djbclark/ops/site-djbclark/docs/handoff.md`.
3. Move the tracked operator documentation from upstream `human/` into the
   site repo's `human/`, preserving history as far as practical and repairing
   links relative to their new locations. Do **not** add ignored local files
   such as `human/RESPONSES.md`, secrets, credentials, or other operator-local
   material that Git does not track.
4. Replace upstream `docs/handoff.md` with a concise generic stub that points
   to `docs/architecture/multi-site-topology.md` §4 and tells operators that
   live handoff/operator docs belong in their private site overlay. Update
   links that would otherwise be broken by the move.
5. Keep generic product documentation in upstream. Do not perform the wider
   B5 replacement of historical names, tests, code, or research documents.

Commit/push the site-repo documentation change to site `master`. Commit/push
the upstream documentation change on its branch and open a clear PR. Do not
merge either upstream PR yourself.

## Verification (run all; paste concise outputs for the human)

1. `git diff --check` in both repos.
2. Run the relevant markdown checks in both repos (at minimum the changed
   files; run each repo's documented markdown lint command when available).
3. Confirm the private site repo now tracks the moved `docs/handoff.md` and
   intended tracked `human/` files, while the public repo has only the generic
   handoff stub and no tracked live operator-document copies.
4. Use `rg` or an equivalent link check to confirm that links altered by the
   move resolve from their new locations and that upstream's stub links to
   multi-site topology §4.
5. Report the site commit, upstream branch/commit/PR URL, and `git status
   --short` for both repos. The only acceptable unrelated upstream item is
   the pre-existing untracked `.claude/` directory.

## Human-verification checklist (wait for confirmation)

- [ ] Private site repo owns the live handoff and tracked operator docs.
- [ ] Public upstream handoff is a concise generic topology stub; no secrets
      or ignored local operator files were committed.
- [ ] Markdown/link checks and `git diff --check` pass.
- [ ] Intended site commit and upstream branch/PR are pushed; no unrelated
      changes exist.

## End of session

Follow `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` exactly.
After the human confirms the checklist, append the B3 ledger line, rewrite
`docs/relay/NEXT-PROMPT.md` for B4 from the step2 plan §3 (including B4's
**OPERATOR GATE** for a real deploy), commit/push the site relay update, and
print the new prompt in chat. If blocked twice on the same error, use protocol
ending B and escalate to Claude Sonnet 5.
