# NEXT: B6 — Close the Phase B review findings   (difficulty 60/100)

**Recommended AI:** Anthropic Claude Fable 5, effort Medium · alt: OpenAI Codex GPT-5.6 Sol, reasoning High · escalate to: Claude Fable 5, effort High
**Working dir:** `/Users/djbclark/ops/stayturgid`   **Operator gate:** none (no real deploys required; do NOT deploy)

---

You are executing **step B6** of the two-repository Ansible split: closing the
findings from two independent Phase B reviews before Phase C may start. The
reviews are authoritative on WHAT is wrong; this prompt is authoritative on
HOW to fix it — the design decisions below are already made, do not
re-litigate them.

## Read first

1. The two review reports (full text, both):
   - `/Users/djbclark/ops/site-djbclark/docs/relay/reviews/phase-b-review-codex-sol.md`
   - `/Users/djbclark/ops/site-djbclark/docs/relay/reviews/phase-b-review-gemini-pro.md`
2. `/Users/djbclark/ops/stayturgid/AGENTS.md` + applicable `.cursor/rules/`.
3. `/Users/djbclark/ops/stayturgid/docs/architecture/multi-site-topology.md` §4 (esp. §4.1 fixture names/ranges, §4.8 precedence).
4. `/Users/djbclark/ops/stayturgid/control/lib/ansible_context.py` and `control/lib/site_identity.py` (the B4/B5 machinery you are amending).
5. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` (branch hygiene: you merge your own PR after operator confirmation).

## Already fixed — do not redo (verify only)

- H2 (live address in consumer example) + L2 (stale T3) — stayturgid `d97d726`
- H4 (site wrapper clobbered explicit `ANSIBLE_CONFIG`) + M4 (stale recipe names in site handoff) — site `b6b82e5`

## Task — each finding with its decided fix

**H1 — cf-runagent renders live identity into a tracked public file.**
`agents.yml` renders the inventory's addresses into tracked
`control/cfengine/cf-runagent.cf`. Fix: the tracked file becomes a generic
example (`cf-runagent.cf.example` with §4.1 fixture addresses, or delete it
if nothing needs a tracked copy); the rendered artifact moves to the runtime
config home (`~/.config/stayturgid/cfengine/cf-runagent.cf`) — same pattern
as the FIRERPA CA material. Repoint every consumer (deploy tasks, docs,
any Termux-side sync) at the runtime path. Add a regression test asserting
no tracked file is a render target of `agents.yml`.

**H3 — `deploy_termux.py` and `verify_drift.py` bypass the B4 resolver and
can succeed with zero hosts.** Route both through the same resolution used
by `deploy_fleet.py` (shared helper in `ansible_context.py` — extract one if
the logic is currently inline). Then add a guard used by all three: if the
resolved inventory matches zero hosts for the requested limit, exit nonzero
with a message naming the config file that was used. Regression tests: the
explicit-config-ignored scenario from the review (export a site config, run
with a host limit, assert it is honored) and the zero-host guard.

**M1 — invalid explicit `ANSIBLE_CONFIG` silently falls back.** In
`site_identity.py::resolve_inventory_path`, an `AnsibleConfigError` arising
from an *explicitly supplied* config is fatal (clear error, nonzero exit);
the example fallback remains only for the genuinely-unconfigured case.
Test both branches.

**M2 + Gemini #1 — RFC1918 fixtures in tests/examples/collection docs.**
Sweep `192.168.x.x` / `192.168.68.x` fixtures in active tests, examples,
and collection docs to RFC 5737 ranges (`192.0.2.x`, `198.51.100.x`,
`203.0.113.x`) or `100.0.0.x` for Tailscale-shaped values, per §4.1/§4.3.
Historical research docs stay as-is if already bannered (B5 convention).

**M3 — `cf-serverd.cf` hardcodes `djbclark`.** Template the allowed-user
list from inventory (`ansible_user` of the control peer) the same way
cf-runagent is templated; keep `root`. The tracked policy file gets the
generic example treatment consistent with your H1 fix (cfbs builds from the
templated source — check `device/termux/cfengine/README.md` for the build
flow before moving files).

**Gemini #2 — hardcoded `~/ops/site-djbclark` fallback in
`ansible_context.py`.** Replace the operator-specific default with generic
discovery: `OPS_ROOT` (default `~/ops`) scanned for `site-*` siblings of the
product checkout — exactly one match → use it; zero or multiple → no silent
default, fail with a message telling the operator to set
`STAYTURGID_SITE_DIR` or `ANSIBLE_CONFIG`. Update multi-site-topology §4.8
and the B4 tests to describe this rule.

**Gemini #3 + H1's scanner gap — validator blind spots.** In
`validate_site_identity.py`: (a) add `.cf` to `_SCAN_EXTS`; (b) support an
optional site-overlay file `registry/identity-patterns.yml` (list of
regexes) merged into the scan patterns when an overlay is active — the
operator's private subnets belong in the *private* repo, never as literals
in the public validator; (c) seed that file in `site-djbclark` with the
operator's known ranges (derive them from the site inventory — e.g. the
`192.168.68.0/24` LAN and the tailnet range — do not invent). Tests: a
planted `.cf` leak and a planted denylisted-subnet literal must both fail
validation with the overlay active.

**L1 — public docs still instruct with private aliases.** In
`docs/coding-rules.md` and `docs/options.md`, rewrite *current instruction*
text to §4.1 generic names (`oneui-device`, `stock-android-device`,
`fireos-device`); genuinely historical entries get the B5 banner instead of
rewriting.

## Verification

- All new/changed tests pass; full `just check` green.
- `just validate-identity` hard-fails on a planted `.cf` leak and a planted
  denylisted literal (demonstrate, then remove the plants); green otherwise
  in both overlay and upstream-only contexts.
- Grep evidence: no `100.x` live addresses, no unbannered private aliases,
  no `djbclark` literals in active product code/policy/examples
  (`git grep` outputs pasted).
- `git diff --check` clean in both repos.

## Human-verification checklist (present with evidence; wait for confirmation)

- [ ] H1/H3/M1/M2/M3 fixed with regression tests
- [ ] Site-overlay discovery is generic (no `site-djbclark` literal in product code)
- [ ] Validator catches `.cf` leaks + site-denylisted ranges; still green on clean trees
- [ ] `just check` green; grep evidence pasted
- [ ] PR merged (`gh pr merge <n> --merge --delete-branch`), checkout on pulled master

## End of session

Follow PROTOCOL.md exactly (merge your own PR after confirmation; end on
pulled master). Append the B6 ledger line, note in both review files that
their findings are dispositioned (one line at the top, do not rewrite them),
restore the **C1** baton as NEXT-PROMPT.md (C1's text is preserved in git
history at site commit `4ae3af8` — recover it from there and update its
"Context" section to mention B6), commit/push the site repo, and print the
C1 baton in chat. If blocked twice on the same error, escalate per header.
