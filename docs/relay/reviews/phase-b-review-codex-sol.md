# Phase B independent review — Codex Sol

**Date:** 2026-07-18
**Reviewed ranges:** `site-djbclark 90c2b0f..4ae3af8`; `stayturgid 2617f2b..b1aeb97`
**Post-range hygiene state:** `site-djbclark` and `stayturgid` are both clean,
pulled `master` checkouts; `master` is the only local and remote branch in each.

## Critical

No Critical findings.

## High

### H1 — A real deploy writes live inventory addresses into a tracked public file

- **Severity:** High
- **File:line:** `stayturgid/ansible/roles/control_node/tasks/agents.yml:60`
- **Description:** The control-node role renders the site's live addresses into
  tracked public-repository file `control/cfengine/cf-runagent.cf` (whose current
  lines 17–19 contain all three production Tailscale addresses), so Phase B did
  not actually make the product checkout identity-free.
- **Concrete scenario:** Running `just deploy` or `just deploy-mac` after an
  inventory address changes dirties the public checkout with the new private
  identity, which can then be committed or pushed; `just validate-identity`
  still reports zero drift because `.cf` is absent from `_SCAN_EXTS`.

### H2 — B5 left a live production address in a generic consumer inventory

- **Severity:** High
- **File:line:** `stayturgid/examples/consumer-full-fleet/inventory/hosts.yml.example:6`
- **Description:** The B5 scrub renamed the host in this example but left the
  address equal to the live `s24` management address instead of replacing it
  with the §4.1 `100.0.0.x` fixture.
- **Concrete scenario:** Anyone cloning or browsing the public product receives
  a real site address in a file explicitly presented as a reusable example, and
  the hard-fail validator cannot catch it because all of `examples/` is skipped.

### H3 — Two fleet entry points discard the selected site config and can succeed with no hosts

- **Severity:** High
- **File:line:** `stayturgid/control/bin/deploy_termux.py:82`; `stayturgid/control/bin/verify_drift.py:37`
- **Description:** Both scripts overwrite `ANSIBLE_CONFIG` with the upstream
  config rather than using the shared B4 resolver, bypassing the required
  explicit-config → site-overlay → upstream precedence implemented elsewhere.
- **Concrete scenario:** With the site config explicitly exported,
  `verify_drift.py --host s24` ignored it, parsed no inventory, skipped the play,
  and exited 0; `just deploy-termux` can follow the same path and report success
  without applying the site inventory.

### H4 — The site wrapper overrides an explicit `ANSIBLE_CONFIG`

- **Severity:** High
- **File:line:** `site-djbclark/justfile:13`
- **Description:** The site `deploy`, `deploy-check`, and `dryrun-termux` recipes
  unconditionally assign `$PWD/ansible.cfg`, so a caller-supplied explicit
  `ANSIBLE_CONFIG` does not win as the B4 contract requires.
- **Concrete scenario:** An operator deliberately selects a second/test site
  config and invokes the site wrapper, but the command silently targets
  `site-djbclark` instead, creating a wrong-fleet deployment risk.

## Medium

### M1 — An invalid explicit config silently downgrades identity validation to generic fixtures

- **Severity:** Medium
- **File:line:** `stayturgid/control/lib/site_identity.py:326`
- **Description:** `resolve_inventory_path()` catches every
  `AnsibleConfigError` and falls back to `hosts.yml.example`, even when the error
  came from an explicitly supplied `ANSIBLE_CONFIG` that should be authoritative.
- **Concrete scenario:** A misspelled or unreadable explicit config makes
  `just validate-identity` scan the generic example and return green instead of
  failing configuration validation, masking production drift before a deploy.

### M2 — B5 retained RFC1918 site-shaped addresses in active examples and tests

- **Severity:** Medium
- **File:line:** `stayturgid/tests/python/test_adb_resolve.py:57`
- **Description:** Tests, collection documentation, and consumer inventories
  still use `192.168.1.x` / `192.168.68.x` fixtures rather than the RFC 5737
  ranges mandated by multi-site-topology §4.3 and B5.
- **Concrete scenario:** A historical or nearby production LAN address can be
  reintroduced in a skipped test/example path and hard-fail validation remains
  green, while public consumers may mistake locally routable values for safe
  documentation fixtures.

### M3 — The deployed CFEngine server policy still hardcodes the operator username

- **Severity:** Medium
- **File:line:** `stayturgid/device/termux/cfengine/policy/cf-serverd.cf:24`
- **Description:** The active recovery policy allows `root` and `djbclark`
  instead of deriving the allowed user from inventory, leaving production
  identity and single-site behavior in product code after B5.
- **Concrete scenario:** A second operator deploys the generic product under a
  different control-node username and CFEngine run-agent recovery is denied,
  removing the intended Tier-4 repair channel.

### M4 — The moved live handoff advertises recipe names removed by B5

- **Severity:** Medium
- **File:line:** `site-djbclark/docs/handoff.md:468`
- **Description:** The canonical private handoff still instructs operators to
  run `fix-hd8-google` and `verify-hd8-google`, while upstream now exposes only
  `fix-fireos-device-google` and `verify-fireos-device-google`.
- **Concrete scenario:** An operator following the Phase-B-moved source of truth
  gets an unknown-recipe error during the documented Fire OS recovery flow.

## Low

### L1 — Current public operator instructions still use private fleet aliases without historical banners

- **Severity:** Low
- **File:line:** `stayturgid/docs/coding-rules.md:105`
- **Description:** Current instructions still direct agents to use `S24`, `P7A`,
  and `HD8`, and similar unbannered aliases remain in `docs/options.md`, even
  though current generic instructions should use the §4.1 names.
- **Concrete scenario:** A contributor at another site follows the public safety
  rules and targets aliases that do not exist in their inventory, while the
  validator cannot enforce the banner convention because it skips all docs.

### L2 — The public work menu still describes identity consolidation as deferred

- **Severity:** Low
- **File:line:** `stayturgid/docs/options.md:220`
- **Description:** Track T3 says identity consolidation is deferred although the
  site plan and ledger declare B5 complete and `validate-identity` hard-failing.
- **Concrete scenario:** A later agent cannot tell whether identity consolidation
  is complete, deferred, or reopened and may either duplicate B5 or trust a gate
  that the same document says has not shipped.

## Verification evidence

- Landmark commits and merge ordering match the ledger; the Phase B endpoints
  are `4ae3af8` (site relay close-out) and `b1aeb97` (upstream B5 merge).
- Current hygiene is clean after the post-range fixes: both checkouts equal
  remote `master`, and both remotes advertise only `master`.
- A CI-equivalent fresh checkout of upstream at `b1aeb97`, with the ignored
  example inventory copied exactly as the workflow does and no site overlay
  available, completed `just check` successfully (20/20 code checks plus ruff,
  Biome, shfmt, justfile, Markdown/Prettier, HTML/style, and identity checks).
- `just check` also passed against the live site context, but its identity stage
  printed `drift: OK` and `secrets: OK` despite H1/H2, demonstrating the scanner
  blind spots rather than disproving them.
- `site-djbclark/bin/registry_lint.py` passed: `registry-lint: OK`.
- Offline link checking of the moved handoff/human documents and the upstream
  stub checked 67 links with zero errors; `human/RESPONSES.md` is not tracked in
  either repository, and no private-key/token signature was found in either
  Phase B diff.
- Upstream tracks only `hosts.yml.example`; `hosts.yml` is ignored, and CI makes
  its ephemeral copy before syntax/check/test/lint steps.

## Verdict

**No — Phase B is not yet safe to build Phase C on top of.** The test suites and
branch hygiene are green, but H1–H4 violate the central identity boundary and
configuration-precedence contract. Fix and regression-test those High findings
before beginning Phase C; the Medium/Low findings can then be closed in the same
scrub and documentation pass.
