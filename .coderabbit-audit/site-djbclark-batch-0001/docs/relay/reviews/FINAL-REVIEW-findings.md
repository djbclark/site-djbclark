# FINAL-REVIEW — project-level final review (2026-07-20)

Reviewer: Claude Sonnet 5 (Mac GUI, cswap account 2, djbclark@mit.edu,
`xhigh` effort) with a background multi-agent Workflow (5 parallel deep-dive
agents, each pipelined into an independent adversarial-verify pass). Scope
per step2 plan §10: the project-level final review across the whole
segmentation + FUND-B implementation chain (stayturgid Phases B–F,
site-djbclark). Not a residual triage, not a re-run of REVIEW-EF alone.

## Scope and baselines

- **site-djbclark** `3a9c6cb9` (pulled master at session start; this
  session's own commits — this findings doc plus the sudo-askpass hygiene
  fix — land directly on top per the site repo's straight-to-master rule).
- **stayturgid** `6ca9d317` (pulled master at session start, same commit
  REVIEW-1 left it on — confirmed zero drift since REVIEW-1: `git log
6ca9d31..HEAD` was empty before this session's fix commit). This session's
  fixes landed via **PR #35**, merged (fast-forward merge commit) to master
  at **`430560fa67ef1cdcd8d8ae53d261767186b74acb`**; merge-commit CI run
  green (`test` + `semgrep-cloud-platform/scan`, both `success`); branch
  deleted; no open PRs; checkout back on pulled master.

Required reading completed before review design: `docs/relay/PROTOCOL.md`;
step2 plan §0/§2/§10; step1 architecture doc; `docs/relay/LEDGER.md` tail;
all five prior review docs (`phase-b-review-{codex-sol,gemini-pro}.md`,
`gate-debt-audit.md`, `r1-d1-adapter-review.md`, `r2-d2-d4-adapter-review.md`,
`m1-r-phase-d-design-review.md`, `r3-phase-d-closeout-review.md`,
`REVIEW-1-findings.md`, `REVIEW-EF-findings.md`).

## Why this review targeted `control/site_contract/`

Reading the prior-review history turned up one real gap: **Phase C (the
site-contract implementation — `site-init`, `site-sync`, `site-map.yml`,
lockfile semantics, serverapp mode-resolution, Entangled doc sync) never got
a dedicated adversarial code review.** `gate-debt-audit.md` (G1) verified
that its acceptance tests exist and pass mechanically; nothing before this
session read the ~5,000-line module line-by-line hunting for logic bugs —
despite the spec's own Phase-C-review note calling it *"the public interface
others will depend on."* Every other phase (B, D, D7, E, F) had at least one
dedicated review pass. This review's fan-out was designed to close that gap
first, then sweep the rest of the project for anything the phase-scoped
reviews' own "targeted not exhaustive" caveats left uncovered.

## Review method

1. Pulled both masters, recorded baseline SHAs, confirmed zero drift on
   stayturgid since REVIEW-1.
2. Ran a background Workflow with 5 parallel deep-dive agents, each
   Explicitly told not to assume bugs exist (prior reviews found few) and to
   report only traced, concrete file:line findings with a reproducible
   failure scenario:
   - **site-init + site-map** (`site_init.py`, `site_map.py`,
     `generate_registry_seeds.py`, scaffold templates) — never independently
     reviewed.
   - **site-sync + lockfile + OliveTin projection** (`site_sync.py`,
     `olivetin_projection.py`, sync templates) — never independently
     reviewed.
   - **serverapps mode-resolution + Entangled** (`serverapps.py`'s
     `resolve_app_mode`/detect helpers, `check_entangled.py`) — the adapter
     *roles* were reviewed hard in D-phase reviews; this shared Python
     interface layer deciding which mode each adapter runs in was not.
   - **site-djbclark whole-project sweep**, biased toward the newest
     commits since REVIEW-EF (F2 execution, Immich retirement) which no
     review had touched yet.
   - **Cross-repo security lens** — secrets in git history, plist modes,
     loopback binds, `secretspec.toml`/`.gitignore` correctness, sudo
     askpass safety.
   Each finding was then adversarially re-verified by an independent agent
   instructed to default to "refuted" unless it could reproduce the claimed
   failure scenario itself.
3. In parallel, ran a live mechanical verification matrix myself (below) and
   independently hand-exercised all six Site Contract v1 §8 acceptance
   tests against the real `site-init`/`site-sync` CLI in a scratch
   directory, including symlink- and case-alias-based ADR-005 bypass
   attempts.
4. Fixed every surviving must-fix finding, added a regression test per fix,
   and — for six of the nine — confirmed the new test genuinely fails
   against the pre-fix source (reverted source only, kept tests, ran red;
   reapplied fixes, ran green) before re-verifying the full suite.

## Live verification evidence (this session)

| Check | Result |
| --- | --- |
| stayturgid `just check` | exit 0 — 20/20 code checks, Entangled parity OK, ruff/ansible-lint/yamllint/markdownlint/prettier/stylelint clean, validate-identity drift+secrets OK |
| stayturgid full `just test` | exit 0 — **510 passed, 1 skipped** (post-fix; pre-fix baseline was 497, matching R3/REVIEW-EF's baseline — the +13 is this session's new regression tests) |
| site `bin/registry_lint.py` | `registry-lint: OK` |
| Overlay strict identity (site `ANSIBLE_CONFIG`) | drift OK, secrets OK, exit 0 |
| Upstream-only strict identity (`OPS_ROOT=/tmp/no-sites-here`) | example inventory, RFC5737/100.0.0.x, drift OK, secrets OK, exit 0 |
| `just site-contract-check` (stayturgid) | Entangled parity OK (9 literate templates; 2 registry seeds generator-owned) |
| `just litellm-status` | launchd loaded; `/v1/models` → gpt-4o-mini, gpt-4o, claude-sonnet-5, gpt-5.5, smart-router |
| `just goose-status` | 1.43.0; litellm-local/smart-router; filesystem+fieldy(disabled); files 0600/0700 |
| `just site-agents-status` | both `com.djbclark.{system-state-backup,hibernate-disk-check}` loaded |
| `just brew-project` / `just brew-diff` | unchanged projection (2 taps/19 formulae/2 casks); diff exit 0, 23 present/0 missing/160 live-only informational |
| D7 front door (HTTPS, following redirects) | `/` `/grafana/` `/oo/` `/olivetin/` `/vm/` `/dashboard/` `/opencode/` `/stats/` — all **200** |
| D7 loopback health | 8080/8686/8428/3000/1337/8088/4000 all **200**; 5080/healthz **404** (base path is `/oo/`, expected, matches REVIEW-EF baseline) |
| Branch hygiene | both repos: `master` only local+origin at session start; no open PRs at start; this session's stayturgid PR #35 merged before session end (see below) |
| `git status` | clean throughout, both repos |

### Hand-exercised Site Contract v1 §8 acceptance tests (live, scratch dir)

All six ran directly against the real CLI (not just the pytest suite) as an
independent check, including two deliberate bypass attempts:

1. **dry-run in empty dir → action list, zero writes.** Confirmed: `create`
   listed for all 11 scaffold files, directory empty after, exit 0.
2. **apply → §3 layout exists; second run no-op.** Confirmed: first apply
   `created=11`; second apply `created=0, skipped=11`. Also confirmed
   README.md's "generated once, then user-owned" behavior directly: hand-edited
   README, re-applied, apply correctly refused (exit 2, `README.md` named)
   rather than silently overwriting it.
3. **Hand-edit a generated file → site-sync exits 2 naming it;
   `--force-generated` recovers.** Confirmed on both `mode=dry-run` (exit 2,
   no write) and `mode=apply` (exit 2, no write), then `--force-generated`
   recovered cleanly and a subsequent sync was a full no-op.
4. **site-map.yml remap → sync reads/writes only the mapped location.**
   Covered via the existing test suite plus this session's own new
   type-collision regression test (below).
5. **caddy adapter, inject mode against a pre-existing Caddyfile without the
   import line → exit 2 with instructions.** Covered via the existing test
   suite plus this session's new sibling-directory regression test.
6. **`mode=docs` output contains no site-specific values.** Confirmed:
   grepped rendered docs output for tailnet IPs, the real hostname, and
   `djbclark` — none found.

**ADR-005 bypass attempts (ran during hand-exercise, before finding this
was also independently caught by the Workflow review):**

- Symlink located inside a scratch directory but pointing at a target
  *outside* the product tree, targeted as `--dir <symlink>/nested` →
  correctly **accepted** (the physical destination — what `Path.resolve()`
  follows the symlink to — is genuinely outside the product tree, so this
  is the right outcome, not a bypass).
- Symlink located inside a scratch directory but pointing *at the product
  tree itself* (`<symlink> -> /Users/djbclark/ops/stayturgid`), targeted as
  `--dir <symlink>/nested` → correctly **rejected** — `.resolve()` follows
  the symlink to the real product path and the nesting check fires as
  expected. Symlink-based bypasses of the resolve-then-compare logic don't
  work; the real gap was the next row.
- `--dir` pointing at a differently-cased alias of the product root
  (`/Users/djbclark/ops/STAYTURGID/...` vs. the real
  `/Users/djbclark/ops/stayturgid`) on this Mac's actual case-insensitive
  APFS volume — **this succeeded before the fix**: `dry-run` printed a full
  `create` action list and exited 0, meaning `apply` would have written a
  private site directory physically inside the public product checkout.
  Fixed this session (must-fix finding, below); re-tested after the fix and
  confirmed exit 1 naming the collision.

## Must-fix findings — all fixed this session

Nine correctness/security bugs, all in stayturgid's `control/site_contract/`
module (the piece identified above as never having had a dedicated review).
Each has a regression test; six were confirmed to fail against the pre-fix
source before the fix was reapplied (the ADR-005 case-alias test and the
`home`-threading test are host/filesystem-dependent and self-skip when the
bypass condition doesn't apply on a given machine, so they weren't included
in that red/green sweep — their logic was verified by direct reproduction
during the Workflow's adversarial-verify pass instead, recorded in the
journal). Fixed in stayturgid PR #35, merged to master.

| # | Finding | File | Fix |
| - | ------- | ---- | --- |
| 1 | ADR-005 nesting rejection used case-sensitive `Path.relative_to()`, bypassable on the default case-insensitive macOS filesystem — a `--dir` differing only in case from the product root passed the nesting check and would have written a site dir physically inside the public product checkout. | `control/site_contract/site_init.py`, `site_map.py` | Added `site_map.is_physically_within()` (inode-identity comparison via `os.path.samestat`), used by `site_init.py`'s primary ADR-005 check and both of `site_map.py`'s escape checks (`_resolve_contract_path`, `_resolve_serverapp_path`). |
| 2 | `build_plan()`'s duplicate-destination check only caught exact string collisions, not a site-map remap making one planned path double as another's *ancestor directory* (e.g. `paths.inventory: group_vars` vs. the derived `group_vars/.gitkeep`) — would crash `apply_plan()` mid-write (`IsADirectoryError`) with partial writes already on disk, misreported as a clean exit-1 precondition failure. | `site_init.py` | Added a file-vs-ancestor-directory collision check in `build_plan()`, raising before any write. |
| 3 | `site-sync`'s delete planning never ran the drift check overwrite planning runs: a hand-edited generated file was silently deleted (exit 0, no warning) the instant its manifest entry disappeared from a product release — the exact acceptance-test-3 scenario, but for deletes. | `site_sync.py` | Deletes now compute the same on-disk-hash-vs-lockfile-hash drift check as overwrites and are gated behind the same `EXIT_WOULD_OVERWRITE`/`--force-generated` path. |
| 4 | Inventory-controlled `host.name`/`device_label` spliced unescaped into JSON string literals in the Grafana dashboard fragment template — a crafted host name (e.g. containing `", "pwned": "yes`) injected/overwrote arbitrary JSON keys with no error. | `sync_templates/fragments/grafana/dashboards/json/stayturgid-fleet.json.j2` | Added a `json_string_escape` Jinja filter (JSON-safe escaping, valid inside YAML double-quoted scalars too since JSON's escape set is a subset); applied to every inventory-derived interpolation in the template. Also added `_assert_rendered_content_parses()` in `site_sync.py` as defense-in-depth: every `.json`/`.yaml` fragment is round-tripped through the real parser before being written. |
| 5 | Same unescaped-interpolation pattern in the OliveTin actions template: a quote/newline in `device_label` produced structurally invalid YAML written straight to the committed `generated/` area, and `host.name` was spliced unquoted into a `shell:` command line (shell-metacharacter injection risk). | `sync_templates/fragments/olivetin/stayturgid_actions.yaml.j2` | Applied `json_string_escape` to the YAML string fields and a new `shell_quote` filter (POSIX `shlex.quote`) to the shell command's host-name argument. |
| 6 | Caddy's "does the foreign Caddyfile's import line cover fragment_dir?" check had a naive-substring fallback (`frag in target`) that wrongly accepted an import of an unrelated sibling directory sharing a name prefix (e.g. `caddy.d-other` "covering" `caddy.d`) — inject mode would report success while Caddy never actually imports the fragments. | `serverapps.py::_import_line_covers` | Removed the substring fallback; the pre-existing regex patterns (already correctly path-boundary-anchored) are now the sole check. |
| 7 | Vector's equivalent check just searched the *entire* plist text for the fragment_dir string with **no association to `--config` at all** — even less safe than the caddy version. | `serverapps.py::_vector_unit_includes_fragments` | Rewrote to parse consecutive `<string>--config</string>`/`<string><value></string>` plist array-element pairs and compare the resolved value path against fragment_dir (equal or a true descendant), instead of raw substring search. |
| 8 | `resolve_app_mode()` and the caddy/vector foreign-detect helpers it calls never accepted the `home` override that `build_plan()`/every `plan_<app>()` already threads through the rest of planning — mode *selection* always scanned the real process `Path.home()`, while everything downstream of mode selection correctly used the override. On a machine whose real home happens to have a file at one of the checked default candidate paths, this silently selects the wrong mode. | `serverapps.py` (7 call sites + `_caddy_detect_paths`, `_vector_detect_paths`, `_is_under_our_prefixes`) | Threaded `home` through `resolve_app_mode()` and every detect-path helper it calls; also fixed the same gap in `plan_caddy`'s/`plan_vector`'s own internal re-detection calls (site-map-forced-own-against-foreign checks, inject-mode foreign-config lookups). |
| 9 | vector/openobserve's `ansible.builtin.template` tasks rendering their secret-bearing launchd plists (`OPENOBSERVE_ROOT_PASSWORD`, `ZO_ROOT_USER_PASSWORD` embedded in plaintext) set `mode: "0600"` but omitted `no_log: true` — present on the equivalent litellm task and on vector's own earlier validate-command task in the same role. An ordinary `--diff`/`-vvv` troubleshooting invocation would print the plaintext password to the terminal/session transcript. | `ansible/roles/serverapp_{vector,openobserve}/tasks/main.yml` | Added `no_log: true` to both render tasks, matching the existing litellm pattern. |

**Also fixed (site-djbclark, style/hygiene, direct to master):** the GUI
sudo-askpass helper's dialog text still hardcoded "Immich LaunchDaemon" as
the reason for the privilege prompt, left over from before Immich's full
retirement (`IMMICH-RETIRE` ledger entry) — the script is still live and
used for general system-domain work (F2 execution used it too), so genericized
the wording rather than removing the script. `bin/sudo-askpass-osascript`.

## A finding that was investigated and explicitly not fixed (operator decision)

**Leaked CA private key in stayturgid's public git history.** The Workflow's
security-lens agent found a real, valid, unexpired RSA-2048 CA private key
(`root.key`/`root.crt`, "FireRPA LAMDA Root Trust") committed at `72c620c`
(2026-07-13) and removed from the working tree at `2bcdda2` (2026-07-18) —
but never purged from git history, and that commit's own "history purge
remains open" TODO had since silently fallen out of the docs (no trace in
any current doc, and none of the four prior reviews mention it). I
independently re-verified every factual claim: confirmed via a fresh
anonymous `git clone` of the public repo that `git show 72c620c:root.key`
still returns the full key today; confirmed via certificate-chain
verification (`openssl verify -CAfile ~/.config/stayturgid/firerpa-ca/root.crt
~/.config/stayturgid/firerpa.pem` → OK, with a **different** fingerprint
than the leaked key) that the live, currently-trusted FireRPA CA is a
separate key generated the same week — the leaked key was never deployed or
trusted by any live device. I raised this to the operator before taking any
action, since purging public git history requires a force-push that
invalidates any existing clone/fork. **Operator decision: leave the history
as-is permanently (accepted risk — the leaked key is confirmed inert); scrub
any remaining reference to it from current documentation and code.** A repo
sweep confirmed there was nothing left to scrub — the original 2026-07-18
removal commit already stripped the tracked files and the stale TODO
pointer was already gone from the docs tree before this session (grepped
`docs/architecture/*`, ADRs, `docs/options.md`, `root\.key\|root\.crt` —
zero hits outside `git log`/blame of the historical commits themselves).
Recording this disposition here so it isn't silently rediscovered by a
future review with no memory of this decision.

## Architecture / style — noted, not fixed (may ledger-defer)

None of these are correctness/safety must-fix; all are documented so a
future session doesn't need to rediscover them.

1. **Registry-seed "stale-output protection" only checks value drift, not
   completeness.** `generate_registry_seeds.py --check` verifies
   `registry_sources.yml` matches the files it already points at, but has no
   mechanism to detect that a *new* role/adapter's port or path was never
   added to `registry_sources.yml` in the first place — so acceptance test
   2's "registry/ports.yml contains every port the product's role defaults
   declare" isn't actually mechanically enforced end-to-end. Low practical
   risk today (single product, small and stable adapter set); would matter
   more with a second product contributing to the same site contract.
2. **`site-sync` writes (generated files, lockfile, OliveTin live-config
   projection) are not atomic or lock-guarded.** A crash mid-write or two
   concurrent `site-sync` invocations could leave a torn file, despite the
   module's "single writer" framing. No evidence this has happened; the
   realistic trigger (concurrent syncs) doesn't occur in the current
   single-operator, single-session relay workflow.
3. **OliveTin action-file YAML parsing has no anchor/alias expansion depth
   guard** (`yaml.safe_load` is memory-safe against code execution but not
   against a "billion laughs"-style resource-exhaustion input). The input is
   operator-authored (`olivetin/user-actions.yaml`), not attacker-reachable
   under the current threat model — noted for completeness, not a fix.
4. **Grafana's off-mode plan doesn't clean up previously-placed inject-mode
   fragments**, unlike caddy/vector's off-mode which explicitly deletes
   stale product-placed files from a foreign fragment_dir. Also,
   `site-contract.md` §5.1 never actually defines what "off" mode does
   (only own/inject are specified) — an underspecified area of the contract
   itself, not just an implementation gap. Nobody has used grafana inject
   mode → off transition yet; no live impact today.
5. **Off-mode apply-time behavior has near-zero test coverage** across all
   adapters (the delete-cleanup logic, and whether own-mode daemons are left
   running after flipping to off). Style/coverage gap, not a correctness bug
   in itself.
6. **`registry/paths.yml` still uses the step1 schema, not the product seed
   format** — carried forward unchanged from C6 (2026-07-19), flagged again
   in G1/gate-debt-audit and REVIEW-EF, still open. Confirmed today it
   remains a style residual with no live drift consequence — not
   re-litigated further here per the standing FUND-B quality bar and three
   prior reviews' consistent disposition of the same finding.
7. **`roles/litellm/tasks/service_linux.yml` is still dead code** — no
   online Linux host exists to exercise it (`mac-mini-intel`/`vps-primary`
   remain `offline_unprovisioned`, E5 residual closed by operator skip
   2026-07-20). Correct as written; will get its first live exercise
   whenever a Linux host joins the tailnet. Explicitly out of scope per this
   review's mandate (§10 baton: "do not treat offline placeholders or
   untested Linux LiteLLM path as must-fix").

## Immich retirement + F2 execution — spot-verified

The two substantive commits since REVIEW-EF (`7244c83` F2 execution,
`9aa89fe` Immich full retirement) had not been reviewed by anyone before
this session. Verified directly:

- **No residual Immich footprint anywhere in the live system or repo**:
  `/opt/services/immich` absent, no LaunchDaemon plists, no `immich` user/group
  (`dscl` record-not-found), ports 3001–3003 closed. Repo grep for `immich`
  (case-insensitive, excluding `docs/relay/` historical records) returned
  only the one stale askpass-dialog string (fixed above) and the two
  original planning-doc mentions (step1/step2 plans — accurate historical
  record of why the F3 step existed, correctly left alone).
- **F2's registry edits match live reality**: `redis` genuinely uninstalled
  (`redis-cli` absent, port 6379 closed) and its `ports.yml` claim dropped;
  orphaned `postgresql@14` launchd agent genuinely removed while its ~50MB
  data dir was correctly preserved on disk per the recorded decision; `et`
  system daemon still answers on `:2022` as expected (only the redundant
  user-domain agent was removed); `herdr`/`omlx` still running exactly as
  before F2 touched anything else.

## Verdict

**Project chain is complete.** All prior review baselines (Phase B, D/D7,
E/F) still hold — spot-verified live, nothing re-opened. This session closed
the one real gap in review coverage (`control/site_contract/`, never
independently reviewed despite being explicitly called out in the spec as
"the public interface others will depend on") and found genuine
correctness/security bugs there, all now fixed with regression tests and a
green full suite on both repos. The one item deliberately left as
permanent accepted risk (the inert leaked CA key in public git history) was
an explicit operator decision, not an oversight. Remaining architecture/style
notes above are non-blocking and consistent with the FUND-B quality bar
already applied throughout this review chain — deferred to the ledger, not a
new multi-session plan.

No further AI-relay implementation step is queued. See `NEXT-PROMPT.md` for
the CHAIN-COMPLETE baton.
