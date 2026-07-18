# NEXT: B4 — Externalize deploy configuration and inventory (difficulty 55/100)

**Recommended AI:** Claude Fable 5 (low effort) · alt: Codex (high reasoning) · escalate to: Claude Fable 5 (medium)
**Working dir:** `/Users/djbclark/ops/stayturgid` (inspect `/Users/djbclark/ops/site-djbclark` as the private overlay)   **Operator gate:** REQUIRED before any real deploy

---

You are executing **step B4** of the two-repository Ansible split. The public
product repo is `/Users/djbclark/ops/stayturgid`; the private site repo is
`/Users/djbclark/ops/site-djbclark`. Implement only the Phase 3 deploy-tooling
contract from `multi-site-topology.md` §4.8: upstream tooling must accept an
external `ANSIBLE_CONFIG` and inventory, while retaining a safe upstream
default and defaulting to the site overlay when it is present. Do not start
B5's identity scrub or invent a different site architecture.

## Read first (in this order)

1. `/Users/djbclark/ops/stayturgid/AGENTS.md` and every applicable file under
   `/Users/djbclark/ops/stayturgid/.cursor/rules/`.
2. `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
   — §0 ground rules, §1 model routing, §2 risk register, and §3 row B4.
3. `/Users/djbclark/ops/stayturgid/docs/architecture/multi-site-topology.md`
   — §§4.5–4.9, especially §4.8 Phase 3.
4. `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step1-segmentation-architecture-v1.md`
   — §§3–4 and the overlay contract.
5. Current `/Users/djbclark/ops/stayturgid/control/bin/deploy_fleet.py`,
   root `justfile`, `just/fleet.just`, and the site repo's `ansible.cfg`,
   `justfile`, and inventory layout.

## Context carried from B1–B3

- B1 is complete in site commit `9038c2d`: live identity inventory and site
  Ansible configuration are private.
- B2 is confirmed as stayturgid PR #3 (`9bd1650`); check its merge state but
  do not merge it yourself.
- B3 is complete in site commit `6238eda` and stayturgid PR #4 (`5e087e7`,
  https://github.com/djbclark/stayturgid/pull/4); live handoff/operator docs
  are private and upstream has only a generic stub. Do not undo that split.

## Task (B4): make deploy tooling overlay-aware

1. In both repos inspect status first. In stayturgid, run
   `git fetch origin --prune && git pull --ff-only origin master`, create a
   dedicated feature branch, and open a PR. Preserve the pre-existing
   ignored/untracked `.claude/` directory and unrelated work.
2. Update `control/bin/deploy_fleet.py` so a caller-supplied `ANSIBLE_CONFIG`
   is honored. Do not overwrite it with the upstream config. Resolve the
   active inventory, collections path, and playbook inputs from the active
   configuration/overlay as needed; an explicit external inventory must work.
   With no external configuration, preserve the current upstream behavior. If
   the private site repo is present, follow the documented topology contract
   for selecting its configuration as the default rather than hardcoding live
   values into upstream.
3. Update the root `justfile` and `just/fleet.just` wrapper/recipes so an
   externally exported `ANSIBLE_CONFIG` survives `just` invocation and the
   site overlay can invoke the upstream deploy tooling. Keep existing
   `hosts`, scope, dry-run, and check semantics compatible for upstream users.
4. Add focused tests or test seams for configuration precedence, upstream
   fallback, and external inventory resolution. Keep the implementation
   deterministic and fail clearly when the selected config/inventory is
   missing. Do not make B5 identity-scrub edits.

### OPERATOR GATE (mandatory)

Do not perform a real deployment until the human operator explicitly approves
it and identifies one currently online device. Run `just dryrun-termux` first.
Only after that approval, run exactly one real
`just deploy hosts=<online-device>` against the named device, verify the
expected host and result, and record the command, target, exit status, and
relevant health evidence. If approval is not given, stop after the dry run.

## Verification (run all; paste concise outputs for the human)

1. Run focused unit/syntax tests for `deploy_fleet.py` and the changed just
   recipes; run the relevant documented `just check` components.
2. Confirm `ANSIBLE_CONFIG` precedence and external-inventory resolution in a
   clean upstream invocation, plus the documented default behavior when the
   variable is unset.
3. Run `just dryrun-termux` before any deployment. After the operator gate,
   run the one-device real deployment and verify the expected host/result.
4. Run `git diff --check` in both repos and report `git status --short`.
   The only acceptable unrelated upstream item is the pre-existing `.claude/`
   directory.
5. Report the site state, upstream branch/commit, PR URL, test results, and
   the real-deploy target/exit/health evidence (or state that the gate was not
   granted and no real deployment was attempted).

## Human-verification checklist (wait for confirmation)

- [ ] Caller-supplied `ANSIBLE_CONFIG` and external inventory are honored;
      upstream fallback remains compatible.
- [ ] `just dryrun-termux` passes before deployment.
- [ ] The operator explicitly approved one online device and the one-device
      real `just deploy hosts=<online-device>` completed with expected host
      and health evidence (or no real deploy was attempted without approval).
- [ ] Focused tests, relevant checks, and `git diff --check` pass.
- [ ] Site relay and upstream PR are pushed; no unrelated changes exist.

## End of session

Follow `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` exactly.
After the human confirms the B4 checklist, append the B4 ledger line, rewrite
`docs/relay/NEXT-PROMPT.md` for B5 from step2 plan §3, commit/push the site
relay update, and print the new prompt in chat. If blocked twice on the same
error, use protocol ending B and escalate to Claude Fable 5 (medium).
