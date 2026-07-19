# NEXT: M1-Q — Phase D code-quality remediation (difficulty 35/100)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md`). Recovery-month
step 3 of {M1-R ✓, M1-F ✓, M1-Q}; R3 follows this step.

**Recommended AI** (full rows from `docs/reference/available-ai-models.md`):

- **Primary —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort (default High on Claude
  Code/API) · _Default for most plans_ — **original account**, default
  effort. Self-passoff from M1-F: this is code-quality cleanup, not novel
  design, and fits Sonnet 5's normal band.
- **Alternate —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol ·
  `gpt-5.6-sol` · Light, Medium, High, Extra High, Max, Ultra · _Flagship;
  complex coding, computer use, research, cybersecurity_ — effort Medium.
- **Escalation —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
  Auto) · _Next-gen long-running agents_ — **new second-Pro account**, effort
  Medium, only if a cleanup fights back (two failed attempts) or a proposed
  change turns out to have behavior implications requiring judgment.

**Working dir:** `/Users/djbclark/ops/stayturgid` (all fixes; branch+PR) and
`/Users/djbclark/ops/site-djbclark` (docs only; straight to master).
`git fetch origin --prune && git pull --ff-only origin master` in both
before editing.

---

You are executing **M1-Q**: the code-quality list from M1-R's review
(`docs/relay/reviews/m1-r-phase-d-design-review.md` §Code quality, plus the
justified-kept documentation items from §Decision matrix / §Findings). Read
that file first — it has full refs and rationale for every item below. Also
read `docs/relay/PROTOCOL.md` and stayturgid `AGENTS.md`.

**Scope discipline: no behavior changes.** This step is cleanup — dead code,
stale docs/help text, hard-coded defaults, test duplication, refusal-kind
naming. Every item below must leave `just test` green with no live-daemon
behavior difference. If an item turns out to need a real behavior change to
fix properly, stop and note it for R3 rather than improvising scope.

## Code-quality items (stayturgid, one PR)

1. **S-1** — `DEFAULT_CADDY_DETECT_PATHS` in `control/site_contract/serverapps.py`
   (~lines 63-66) is dead: `_caddy_detect_paths` recomputes instead of using
   it. Delete the dead constant, or wire it in if that's actually cheaper —
   whichever leaves less code.
2. **S-3** — Role config-template headers carry placeholder values instead of
   real ones: `vector.yaml.j2` says `product_version: own-mode site_ns=…`,
   `Caddyfile.j2` is similar, and `grafana.ini.j2` / `serverapp_olivetin/
   config.yaml.j2` / `serverapp_victoriametrics/scrape.yml.j2` literally say
   `product_version: unknown commit: unknown`. Two options: (a) pass the real
   `product_version` through as an ansible extra-var from `serverapps.py` and
   render it, or (b) document plainly in each template header why it's a
   placeholder (own-mode bootstrap configs are ansible-rendered, not
   site-sync-rendered, so they don't have `product_version`/`product_commit`
   in scope the way `generated/` fragments do). Prefer (a) if it's a small,
   low-risk plumbing change; otherwise (b). Either way, drop the stray
   `commit: unknown` text from the three static-placeholder headers to match
   A-10's fix (product_version only, no commit, in any generated-marker
   header) — even though these aren't churning, consistency matters.
3. **S-4 (grown)** — `_materialize_<app>_own_for_tests` duplication in
   `control/site_contract/serverapps.py` is now **7 materializers ≈ 430
   lines** mirroring the real role templates inside the product module —
   divergence risk grows with every adapter clone. Consolidate: either share
   one small Jinja-based render helper the tests call with each role's real
   template, or extract common structure into a single parameterized
   materializer. Check `tests/python/test_serverapps.py` for every call site
   before refactoring.
4. **S-6** — `forced_own_foreign` refusal kind is reused for two different
   situations: real "own mode forced against foreign config" (caddy/vector/
   OO/VM) and "inject mode unsupported for this app" (landing, olivetin).
   Add a distinct `unsupported_mode` kind for the second case; update the
   refusal-kind switch/tests accordingly (grep `forced_own_foreign` across
   `control/site_contract/` and `tests/python/`).
5. **S-7** — Role defaults hard-code `serverapp_*_uid: "501"` across all
   serverapp roles, but the live path always passes `os.getuid()` as an
   extra-var (see `serverapps.py`'s `ansible_extra` dicts). Either drop the
   hard-coded default (fail closed if the caller doesn't pass it) or document
   why it's a deliberate single-user-Mac fallback. Prefer removing it if
   nothing relies on the default in tests.
6. **S-9 — already closed by M1-F.** Olivetin's bootstrap task gained
   `until`/`retries: 5` as part of MF-3 (`ansible/roles/serverapp_olivetin/
   tasks/main.yml`). Just confirm it's still there; no action needed.
7. **S-10** — Edge otelcol's `json_parser` uses `on_error: drop_quiet` in
   `ansible/roles/serverapp_termux_userland/templates/otel-config.yaml.j2`
   (or wherever it now lives) — malformed JSONL lines vanish with zero
   signal. Add a low-cost visible counter or log route (e.g. a vector
   internal_metrics tap, or route parse failures to a `stayturgid_dropped`
   sink) so silent data loss becomes observable. If a real fix needs new
   infrastructure, scope it down to just adding the observability hook, not
   changing drop behavior.
8. **S-11** — `serverapps.py --apps` help text says "default: all known —
   caddy,vector" but it's actually all seven apps. Fix the help string to
   list them all or say "all known apps" generically so it doesn't need
   updating again per adapter.
9. **D6 residual (doc only)** — `olivetin/user-actions.yaml` surface exists
   (`USER_ACTIONS_RELATIVE` in `control/site_contract/olivetin_projection.py`)
   but is unused on this site (no site file yet). Document it in the site
   README (`~/ops/site-djbclark/README.md`) so a future operator knows the
   mechanism exists — site repo, straight to master, separate tiny commit
   from the stayturgid PR.
10. **A-2 (deferred hardening)** — Forced-own + unrelated foreign config
    currently proceeds to a bind-time failure (exit 1, KeepAlive loop)
    instead of exit 2, for caddy/vector/OO/VM. Add a port-availability
    pre-check in own mode (before the ansible role even runs): if the
    target port is already bound by something that isn't our own label,
    refuse with a typed refusal (exit 2) instead of letting the daemon fail
    to bind. Not live-reachable today (no site-map file exists on this
    site), so this is defense-in-depth, not a live bug.
11. **A-3 (doc only)** — Inject mode's default `fragment_dir` equals the
    committed `generated/` dir itself, so inject copies degenerate to
    no-ops. This is an intentional deviation from design §5.3's
    auto-detect-on-first-inject behavior. Document it plainly in
    `docs/design/phase-d-adapter-design-notes.md`'s deviation log (§5) if
    not already there, and in the relevant role/CLI docstring — no code
    change; implement real auto-detect only when an actual inject-mode site
    exists to validate against.
12. **A-5 (doc only, generic-product note)** — Legacy bootout is gated on
    "site label unloaded"; a dual-loaded mid-failure state would persist
    until manual bootout. Superseded in practice by D7 on this site (legacy
    plists archived+removed), but the product code path still exists for
    other sites. Add a short comment in the relevant role tasks (e.g.
    `serverapp_caddy/tasks/main.yml` near the legacy-bootout block) noting
    the edge case and that D7-style archival is the real fix once a site
    reaches that stage.
13. **A-6 (deferred hardening, larger — scope carefully)** — Health
    URLs/ports (8686/5080/8428/3000/1337/8088) are hard-coded in
    `serverapps.py` plans and role defaults instead of read from the site's
    `registry/ports.yml`. This is correct for this single-site setup
    (multi-site remap risk only). If it's a small, mechanical change
    (thread the registry-resolved port through the existing `ansible_extra`
    plumbing that already exists for other per-app values), do it. If it
    touches many call sites or risks a live port mismatch, defer to R3 and
    say so in the ledger — don't force it into M1-Q's "no behavior change"
    budget.
14. **D7 route scheme — do not implement.** §11 #9 (Caddy route-naming
    reconsideration; O-V-G-O UIs have no front-door routes) is explicitly an
    **operator architecture decision**, not a defect. Leave it for R3;
    mention it in the M1-Q ledger note as still-open, nothing more.

## Constraints

- No live daemon behavior changes. No device contact. No secrets in output
  or commits. No design-baseline edits except the documented deviation-log
  addition in item 11 (A-3), which the design doc explicitly allows for
  recording deviations. Do not touch D7/D8 retirement state.
- stayturgid: one branch + PR (`fix/m1-q-phase-d-quality`), merge it
  yourself after evidence per PROTOCOL.md, end on pulled master. Site:
  straight to master (item 9 doc note only).
- If any item's "small vs large" judgment call (S-3, A-6) comes out large,
  defer it explicitly in the ledger rather than quietly skipping it or
  quietly expanding scope.

## Verification checklist (record evidence in ledger note)

1. stayturgid `just check` + full `just test` + `pre-commit run --all-files`
   green (record counts; compare to M1-F baseline: 497 passed, 1 skipped,
   collection suites 43/11/20/7/15/7).
2. Overlay + upstream-only `just validate-identity` clean;
   `just site-contract-check`.
3. Site `bin/registry_lint.py` OK.
4. Live (read-only unless an item's fix requires an apply — if so, same
   before/after health-check discipline as M1-F): all 9 health endpoints
   200; no unexpected daemon reload from a "no behavior change" item.
5. Hosted CI green on the merged PR and merged master.

## End of session

Per `docs/relay/PROTOCOL.md`: append one `M1-Q` ledger line (evidence +
anything deferred, especially any S-3/A-6 items pushed to R3). Rewrite
`NEXT-PROMPT.md` for **R3** — read `docs/relay/PROTOCOL.md` §Review batons
and the funding-plans doc's review-checkpoint section for R3's scope (all
commits since R2, i.e. D5 onward through M1-Q; correctness/safety findings
must be fixed, architecture/style may defer). Commit and push site master;
merge + delete the stayturgid branch; both repos clean on pulled master.
Print the new NEXT-PROMPT.md in chat and run
`pbcopy < docs/relay/NEXT-PROMPT.md`.
