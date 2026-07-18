# NEXT: B2 — Genericize the upstream inventory and CI   (difficulty 50/100)

**Recommended AI:** Codex (gpt-5.x-codex, high reasoning) · alt: Claude Sonnet 5 or Copilot premium (Sonnet/GPT-5 class) · escalate to: Claude Fable 5 (low effort, if CI wiring fights back)
**Working dir:** `/Users/djbclark/ops/stayturgid`   **Operator gate:** none

---

You are a junior developer AI working on the second step of a two-repo
Ansible split. `~/ops/stayturgid` is the public product repo and
`~/ops/site-djbclark` is the private site repo. Execute **step B2** exactly;
do not make architecture decisions.

## Read first (in this order)

1. `/Users/djbclark/ops/stayturgid/AGENTS.md` and all applicable
   `/Users/djbclark/ops/stayturgid/.cursor/rules/` files.
2. `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
   — §0 ground rules, §1 model routing, §2 risk register, and §3 row B2.
3. `/Users/djbclark/ops/stayturgid/docs/architecture/multi-site-topology.md`
   — §4, especially §§4.1–4.4 and §4.7–4.8.
4. `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step1-segmentation-architecture-v1.md`
   — §§3–4, for the two-repo ownership model.
5. The current `ansible/inventory/`, `ansible/ansible.cfg`, `justfile`,
   `just/fleet.just`, and CI workflow(s) in stayturgid before editing.

## Context carried from B1

B1 is complete in private `site-djbclark` commit `9038c2d`: its live
`inventory/hosts.yml` is an exact copy of the current production inventory,
and **every** current upstream `inventory/group_vars/` file was copied into
`site-djbclark/inventory/group_vars/`. The site wrapper points Ansible at
that site inventory; normalized `ansible-inventory --list` output was
byte-identical to upstream before this B2 work.

This was deliberately copy-first. In particular, Ansible auto-loads
`group_vars` relative to the inventory source. Do not delete the site copies,
and do not casually deduplicate the generic taxonomy files: preserve correct
loading for both the live site inventory and the upstream example inventory.
The architecture says generic taxonomy vars remain upstream while
site-specific peer/identity data moves out. Inspect the actual loader
behavior and make only the architecture-compliant change required for B2;
record any remaining split mechanics as a deferred item rather than
inventing a new abstraction.

`just validate-identity` is warn-only with known historical violations. Do
not broaden this B2 session into B5 cleanup.

## Task (B2): make stayturgid generic without breaking CI

Everything in this implementation step happens in
`/Users/djbclark/ops/stayturgid`. Start with `git fetch origin --prune` and
`git pull --ff-only origin master`, then create a branch and open a PR; do not
commit directly to `master`. Preserve the pre-existing untracked `.claude/`
directory.

1. Make `ansible/inventory/hosts.yml.example` match the authoritative example
   in multi-site-topology §4.4 exactly in intent: generic aliases
   `oneui-device`, `stock-android-device`, and `fireos-device`; RFC 5737 /
   example addresses; example serials; and the specified taxonomy groups and
   common vars. It must contain no live site identity.
2. Remove the tracked production inventory from the public repo. A fresh
   checkout must contain the generic example, never a live
   `ansible/inventory/hosts.yml` with the operator's hosts, IPs, serials, or
   control-peer identity. Do not alter the copied private inventory in the
   site repo.
3. Update `ansible/ansible.cfg` per topology §4.7 so it no longer defaults to
   production identity. Follow the documented ephemeral-CI inventory approach
   required by the B2 plan rather than adding a new configuration mechanism.
4. Update the relevant CI workflow(s) so they copy `hosts.yml.example` to the
   ephemeral `hosts.yml` before Ansible syntax checking / `just check` needs
   it. The copied live-path file must not be committed. Keep the change
   minimal and compatible with the existing just recipes.
5. Keep generic upstream `group_vars` and the private site copy loading
   correctly. The site-specific group vars belong with the site inventory;
   apply the split only where the architecture and B2 scope make it
   unambiguous. Do not turn this into the wider documentation/test scrub in
   B5.

Commit the branch, push it, and open a clear PR. Do not merge it yourself.

## Verification (run all; paste concise outputs for the human)

1. Run the relevant upstream checks, including `just check`, after the CI
   inventory preparation is represented locally as necessary.
2. Create a genuinely fresh clone in a temporary directory and prove that it
   has no tracked live `ansible/inventory/hosts.yml`, contains the generic
   example inventory, and passes `just check` using the same ephemeral copy
   preparation CI uses.
3. Verify the changed CI workflow syntax/path and that the example copy occurs
   before Ansible syntax checks.
4. Confirm `git status --short` in both repos: stayturgid contains only the
   intended branch changes (plus the pre-existing untracked `.claude/`), and
   site-djbclark remains clean.
5. Report the branch name, commit hash, and PR URL.

## Human-verification checklist (wait for confirmation)

- [ ] Fresh clone has no production inventory or live identity in its
      inventory path; the generic example is present.
- [ ] `just check` passes with CI's ephemeral example-inventory setup.
- [ ] CI copies the example before syntax checking.
- [ ] Group-vars loading remains correct for the site and example inventory;
      any unavoidable follow-up is explicitly recorded.
- [ ] Intended branch/PR is pushed; neither repo has unrelated changes.

## End of session

Follow `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` exactly.
After the human confirms the checklist, append the B2 ledger line in the site
repo, rewrite `docs/relay/NEXT-PROMPT.md` for B3 from the step2 plan §3,
commit/push the relay update on site `master`, and print the new prompt in
chat. If blocked twice on the same CI error, use protocol ending B and
escalate to Claude Fable 5 (low effort).
