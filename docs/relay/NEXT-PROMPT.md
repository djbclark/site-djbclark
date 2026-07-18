# NEXT: B4 — Externalize deploy configuration and inventory   (difficulty 55/100)

**Recommended AI:** Anthropic Claude Fable 5, effort Low · alt: OpenAI Codex GPT-5.6 Terra, reasoning High · escalate to: Claude Fable 5, effort Medium
**Working dir:** `/Users/djbclark/ops/stayturgid` (inspect `/Users/djbclark/ops/site-djbclark` as the private overlay)   **Operator gate:** REQUIRED before any real deploy

---

You are executing **step B4** of the two-repository Ansible split. The public
product repo is `/Users/djbclark/ops/stayturgid`; the private site repo is
`/Users/djbclark/ops/site-djbclark`. Implement only the deploy-tooling
contract from `multi-site-topology.md` §4.8: upstream tooling must accept an
external `ANSIBLE_CONFIG` and inventory, retain a safe upstream default, and
default to the site overlay when present. Do not start B5's identity scrub
or invent a different architecture.

## Read first

1. `/Users/djbclark/ops/stayturgid/AGENTS.md` and applicable `.cursor/rules/`.
2. `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md` — §§0–3, especially B4.
3. `/Users/djbclark/ops/stayturgid/docs/architecture/multi-site-topology.md` — §§4.5–4.9, especially §4.8.
4. `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step1-segmentation-architecture-v1.md` — §§3–4.
5. Current `control/bin/deploy_fleet.py`, root `justfile`, `just/fleet.just`, the site repo's `ansible.cfg`/`justfile`/`inventory/` (from B1), and `~/Library/LaunchAgents/com.stayturgid.termux-pkg-nightly.plist`.

## Context (updated 2026-07-18 — read carefully, it corrects earlier batons)

- B1: site commit `9038c2d` (live inventory + site `ansible.cfg` + wrapper justfile in the site repo).
- B2 and B3 are **MERGED into stayturgid master** (PR #3 → `6613d2e`, PR #4 → `ed97237`); their branches are deleted. Do not look for open PRs from prior steps — there are none, by design.
- **Branch hygiene rule (new, in PROTOCOL.md):** every step now ends with its
  own stayturgid PR *merged* (`gh pr merge <n> --merge --delete-branch`),
  the local checkout back on a pulled `master`, and no leftover branches.
  Earlier batons said "do not merge" — that rule is REPLACED.
- Transitional state you are fixing: upstream has no live inventory anymore
  (CI uses an ephemeral copy of the example; the live one is in the site
  repo). Until B4 lands, real deploys only work via the site repo's
  `just deploy`; launchd-driven ansible on the Mac may fail to resolve hosts.

## Task

1. Inspect both repos (`git status`, current branch). In stayturgid:
   `git fetch origin --prune && git pull --ff-only origin master`, create a
   feature branch. Preserve pre-existing untracked `.claude/`.
2. Update `control/bin/deploy_fleet.py` so a caller-supplied `ANSIBLE_CONFIG`
   is honored and never overwritten; resolve inventory/collections/playbooks
   from the active config; when unset, **default to the site overlay if
   `~/ops/site-djbclark/ansible.cfg` exists** (path discoverable via an env
   var like `STAYTURGID_SITE_DIR` with that default), else fall back to the
   upstream example-only behavior with a clear error for real deploys.
3. Update root `justfile` and `just/fleet.just` so an external
   `ANSIBLE_CONFIG` survives `just` invocation and the site overlay can call
   upstream recipes without breaking host/scope/dry-run/check semantics.
4. **Launchd entry points:** make the Mac launchd-driven ansible jobs
   (`com.stayturgid.termux-pkg-nightly`, and any other agent that invokes
   ansible/deploy tooling) resolve the site overlay under the same
   precedence, and regenerate their plists via the control_node tasks so
   tonight's nightly run works again.
5. Add focused tests: config precedence, upstream fallback, external
   inventory resolution, missing-config failure messages. No B5 edits.

## OPERATOR GATE

Do not perform a real deployment until the human explicitly approves and
names one currently-online device. Run `just dryrun-termux` (site-config
path) first. Only after approval, run exactly one
`just deploy hosts=<online-device>` and record command, target, exit status,
and health evidence. If approval is not given, stop after the dry run.

## Verification

- Focused tests + relevant `just check` components pass.
- `ANSIBLE_CONFIG` precedence, site-overlay default, and upstream fallback
  each demonstrated (paste the resolution evidence).
- `just dryrun-termux` passes via the site overlay.
- Nightly-job plist regenerated and its invocation resolves live inventory.
- `git diff --check` clean in both repos; only intended changes present.

## Human-verification checklist (present with evidence; wait for confirmation)

- [ ] External `ANSIBLE_CONFIG` honored; site-overlay default works; upstream fallback intact
- [ ] Dry run green; approved single-device deploy done and verified (or explicitly not attempted)
- [ ] Launchd ansible jobs resolve the site inventory again
- [ ] Tests and checks pass; no unrelated changes

## End of session

Follow `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` exactly —
including the branch-hygiene rule: after the human confirms, **merge your PR
with `gh pr merge <n> --merge --delete-branch`, `git checkout master &&
git pull --ff-only` in `~/ops/stayturgid`, and re-verify green on master**.
Then append the B4 ledger line, rewrite this file for B5 from step2 plan §3
(carrying the branch-hygiene rule forward into every future baton's
End-of-session section), commit/push the site repo, and print the new prompt
in chat. If blocked twice on the same error, escalate per header.
