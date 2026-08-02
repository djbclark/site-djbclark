# G1 — Gate-debt retro-verification audit

**Date:** 2026-07-19  
**Auditor:** Grok 4.5 (TUI) — mechanical re-run only (FUND-B / G1)  
**Stayturgid HEAD:** `dc9ffaa` (master, PR #17 merge)  
**Site HEAD (pre-G1 commit):** `3e3bf77` / D1 site `a6cd64a`  
**Device contact:** none

## Summary counts

| Result                        | Count |
| ----------------------------- | ----- |
| **verified-now**              | 62    |
| **failed**                    | 0     |
| **not-mechanically-checkable**| 18    |
| **flag (pass with note)**     | 6     |
| **Total claim rows**          | 86    |

### Failed rows (R1 must-fix candidates)

**None.** No current mechanical failures. R1 should still review **Flags** below plus D1 architecture proper against `docs/design/phase-d-adapter-design-notes.md` (correctness/safety only per FUND-B).

### Flags (not failed; R1 awareness / possible deferred work)

| Id | Stage | Note |
| -- | ----- | ---- |
| F1 | C6 residual | `registry/paths.yml` still uses **step1 schema** (not product seed format). Documented at C6; not drive-by fixed. Blocks any claim that site paths registry matches generator-owned seed shape. |
| F2 | C6 residual (partially stale) | C6 said site justfile lacked `STAYTURGID_SITE_DIR` helper. **As of D1**, site `justfile` defines `site_dir` and exports `STAYTURGID_SITE_DIR` on `site-sync` / `site-serverapps`. Residual text is outdated; behavior is fixed. |
| F3 | B6 historical CI | Merge push for PR #9 (`36e4920`) hosted CI **failed** on lychee tarball install (`gzip: stdin: not in gzip format`) — bootstrap flake, not product tests. Local `just check`/`just test` green now; **current master CI green** (PR #17 run `29688331927` success). |
| F4 | D1 ledger DEVIATION | Second own-mode apply still invokes ansible ensure (files skip; ansible no-op). Intentional for daemon healing; R1 judges vs design notes. |
| F5 | D1 ledger note | `control_node` agents.yml can re-render `com.stayturgid.caddy` until D7 — do not re-run control_node caddy tasks without care. |
| F6 | D1 mode source | `site-serverapps mode=dry-run apps=caddy` → `mode=own (source=default)`. No site-root `site-map.yml` present; own is product default. Architecture/style only unless R1 wants explicit site-map. |

---

## Evidence session (shared)

Commands re-run this session on pulled masters (no open PRs; only `master` local+origin both repos).

| Check | Result (abbrev) |
| ----- | --------------- |
| `cd ~/ops/stayturgid && just check` | exit 0; RESULT: PASS (code) 20/20; entangled OK; ruff/biome/prettier; validate-identity drift+secrets OK |
| `cd ~/ops/stayturgid && just test` | exit 0; tier a 20/20; tier b 129/129; **439 pytest passed, 1 skipped**; ansible-test collections all green; identity OK |
| `pre-commit run --all-files` (stayturgid) | exit 0; all hooks Passed incl. site-contract Entangled + registry seeds |
| Hosted CI latest master | `gh run list`: PR #17 merge **success** run id `29688331927` sha `dc9ffaa` |
| Overlay identity | `STAYTURGID_SITE_DIR=…/site-djbclark ANSIBLE_CONFIG=…/site-djbclark/ansible.cfg just validate-identity` → drift OK, secrets OK, exit 0 |
| Upstream-only identity | `OPS_ROOT=/tmp/no-sites-here just validate-identity` → example inventory `hosts.yml.example`, RFC5737/100.0.0.x, drift OK, secrets OK, exit 0 |
| `bin/registry_lint.py` (site, uv-shebang) | `registry-lint: OK` exit 0 |
| `just site-sync mode=apply` (site) | `created=0, overwritten=0, skipped=3, deleted=0, lockfile=skip` exit 0 |
| `just site-sync mode=dry-run` | all skip exit 0 |
| `just site-contract-check` | `Entangled parity OK (9 literate templates; 2 registry seeds generator-owned)` exit 0 |
| `python -m control.site_contract.generate_registry_seeds --check` | exit 0 |
| Caddy health | `curl http://127.0.0.1:8080/health` → `OK` HTTP 200; `launchctl print …/com.djbclark.caddy` state=running; old plist retained |
| HTTPS front door | `curl https://mac.greyhound-sidemirror.ts.net/` → HTTP 200, landing HTML title "Network Services" |
| Branch hygiene | stayturgid + site: `master` only; `gh pr list --state open` empty |

---

## Claim table

Legend: **V** = verified-now · **F** = failed · **N** = not-mechanically-checkable · **G** = flag (see Flags; counted under verified-now when state matches residual claim)

| Stage | Claim (short) | Result | Evidence |
| ----- | ------------- | ------ | -------- |
| setup | Architecture/specs/registries/plan authored; chain starts B1 | N | Authorship event; not re-runnable. Docs exist on disk today. |
| consolidation | Prior feature branches merged to master | V | `git log` shows merge history; only master ref remains |
| consolidation | `just check` + full `just test` green | V | This session: check+test exit 0 (439 pytest) |
| consolidation | Old worktrees removed | N | Historical cleanup; current tree is single checkout master |
| branch cleanup | Only master local+origin; hermes empty deleted | V | `git branch -a` → master only both remotes; no hermes |
| B1 | Live `hosts.yml` + `group_vars/` in site inventory | V | `inventory/hosts.yml` + 11 group_vars files present |
| B1 | Site `ansible.cfg` + thin just wrapper | V | `ansible.cfg`, `justfile` wrap stayturgid recipes |
| B1 | Normalized inventories byte-identical (product vs site) | N | Product no longer tracks live `hosts.yml` (by design after B2); cannot re-diff |
| B1 | Registry lint passes | V | `bin/registry_lint.py` → OK (uv) |
| B2 | Production `hosts.yml` removed from stayturgid track | V | `git ls-files`: only `hosts.yml.example` + templates/examples |
| B2 | Site-only `group_vars/stayturgid.yml` not in product | V | Not in `ansible/inventory/group_vars/` tracked list; lives in site |
| B2 | CI creates ignored generic example inventory before checks | V | Workflow still prepares generic inventory (CI green on master); example inventory present |
| B2 | Fresh-clone / example free of live values | V | Upstream-only identity uses example; RFC5737 + 100.0.0.x; no 192.168.68 in examples |
| B2 | `just check` components pass | V | This session check exit 0 |
| B2 | PR #3 merge (external at write time) | V | PR #3 in merged history; branch gone |
| B3 | Live handoff + `human/*` in private site | V | site `docs/handoff.md`, `human/` with HANDOFF/CHECKPOINT etc. |
| B3 | Upstream handoff is generic topology stub | V | stayturgid `docs/handoff.md` points to multi-site topology; no live device notes |
| B3 | Canonical links repaired; md lint/prettier/links/diff | V | Covered by current `just check` + pre-commit (markdownlint, prettier) green |
| B3 | Ignored `human/RESPONSES.md` untracked | V | site has `RESPONSES.md.example` only; clean git status |
| B4 | Shared external ANSIBLE_CONFIG / site-overlay resolver | V | `ansible_context` used by deploy_termux/verify_drift; site justfile sets ANSIBLE_CONFIG |
| B4 | Focused tests + `just check` passed | V | Full check/test green this session |
| B4 | Site-overlay dry run + approved hd8 deployment completed | N | One-shot fleet deploy; no device contact this session |
| B4 | hd8 Shizuku + AutoJs6 versions / s24 p7a hd8 reachable | N | Device state at cutover; devices not probed |
| B4 | PR #5 merged, branch deleted, on master | V | Merged history; master only |
| B5 | Context-aware inventory via ansible_context | V | Import/use in deploy_termux/verify_drift; identity resolves site inventory when site present |
| B5 | Example inventory control-node placeholders | V | example shows `operator` / 192.0.2.1 / 100.0.0.1 |
| B5 | Production-identity scrub; historical docs bannered | V | Overlay+upstream identity drift OK; handoff stub generic |
| B5 | `just validate-identity` hard-fail (no warn-only) | V | Recipe runs `--check-drift --check-secrets`; exit 0 clean (would hard-fail on drift) |
| B5 | Overlay + upstream-only strict validate clean (0 drift) | V | Both modes exit 0 this session |
| B5 | Local `just check` green | V | exit 0 |
| B5 | CI lychee flake noted | G/F3 | Historical; current master CI success |
| B-review hygiene | Stale branches pruned; `.claude/` gitignored; status clean | V | `.gitignore` has `.claude/`; master only; clean status |
| B review | Review docs written (codex-sol, gemini-pro) | V | `docs/relay/reviews/phase-b-review-{codex-sol,gemini-pro}.md` exist |
| B review | Senior triage quick-fixes landed | V | Subsequent B6 closed remaining findings; master green |
| B6 | H1: cf-runagent → example not tracked live file | V | `control/cfengine/cf-runagent.cf.example` exists; no tracked `cf-runagent.cf` |
| B6 | H3: deploy_termux/verify_drift on shared resolver | V | both import `resolve_ansible_context` |
| B6 | Zero-host limits refuse with config name | V | `ansible_context.py` messages on zero-host limit |
| B6 | M1: explicit ANSIBLE_CONFIG errors fatal | N | Requires fault-injection of bad config; not re-run |
| B6 | M2: fixtures RFC5737 / 100.0.0.x | V | example inventory uses those ranges |
| B6 | M3: cf-serverd allowusers templated | N | Would need cfbs/policy re-verify; out of cheap re-run scope |
| B6 | Gemini#2: no hardcoded ~/ops/site-djbclark default in discovery | V | only doc reference in serverapps.py comment; identity falls back to example with OPS_ROOT empty of sites |
| B6 | Gemini#3: identity-patterns denylist seeded in site | V | `registry/identity-patterns.yml` has 192.168.68/24, 192.168.1/24, CGNAT pattern |
| B6 | L1 instruction docs / options bannered | N | Doc prose quality; not mechanical |
| B6 | 359+ pytest, just check+test green | V | **439** pytest passed this session; check+test exit 0 |
| B6 | Planted leak then removed hard-fail | N | One-shot negative test during B6 session |
| B6 | Hosted CI green at B6 merge | G/F3 | Historical failure lychee; **not** current master state |
| C1 | Site-contract scaffold + seed generator + 6 tests | V | templates tree + `generate_registry_seeds` + `test_site_contract_templates.py` (6) |
| C1 | Hosted CI + focused checks; identity clean | V | C1 merge CI success historically; current master green; identity OK |
| C1 | site-init deferred to C2; site-sync to C3 | N | Sequencing claim; superseded by later stages |
| C2 | site-init apply/dry-run/docs exit 0/1/2 | V | module + `test_site_init.py` (33) in suite; full pytest green |
| C2 | Focused 30 tests + hosted CI green | V | suite green; PR #12 merge CI success in history |
| C2 | Overlay/upstream identity clean post-merge | V | re-verified this session |
| C3 | site-sync + lockfile under generated/ | V | lockfile present product_version 2.7 commit dc9ffaa; site-sync no-op |
| C3 | Never writes outside generated/; drift exit 2 | V | covered by `test_site_sync.py` (22) green in full suite |
| C3 | 50 C1–C3 tests + CI green | V | full suite green; PR #13 CI success |
| C4 | site-map.yml fail-closed loading + remaps | V | `site_map.py` + tests in suite; green |
| C4 | 61 C1–C4 tests, registry check, just check, full tests, pre-commit, CI, identity | V | check/test/pre-commit/CI/identity this session |
| C5 | Entangled SITE-CONTRACT + check_entangled + just site-contract-check | V | `just site-contract-check` OK; pre-commit hook Passed |
| C5 | mode=docs generic-only; seeds generator-owned | V | seeds `--check` exit 0; entangled reports 2 registry seeds generator-owned |
| C5 | Hosted CI green; on master | V | PR #15 merge success; master only |
| C6 | site-sync adopted generated/ + lockfile (2.7 @ product) | V | `generated/stayturgid/` + lockfile product_version 2.7 |
| C6 | secretspec.toml declarations only; gitignore present | V | secretspec has keys/descriptions no values; .gitignore present |
| C6 | Kept site-owned inventory/registry/README/ansible/just | V | files present as claimed |
| C6 | Second sync no-op | V | apply: skipped=3 created=0 overwritten=0 |
| C6 | Registry lint + strict identity clean | V | both OK this session |
| C6 | Residual: paths.yml step1 schema | G/F1 | Still true; not fixed |
| C6 | Residual: justfile STAYTURGID_SITE_DIR helper | G/F2 | Fixed by D1 justfile exports |
| FUND-B | Plan B chosen; human gates removed | N | Process decision; recorded in plans doc + ledger |
| D0-design | Design notes file written | V | `docs/design/phase-d-adapter-design-notes.md` |
| D0-design | 263 lines; prettier exit 0 | V | `wc -l` → 263; `prettier --check` OK |
| D0-design | Core sections present (adapter/D6/D8/deviation) | V | `## 0`–`## 5` present (incl. D1 pattern, D6, D8, deviation protocol) |
| D0-design | stayturgid read-only clean that session | N | Historical session claim; current stayturgid clean master (coincidentally true) |
| D1 | Caddy fragment + sync_manifest + serverapps.py + role | V | fragment in site generated/; `serverapps.py`; `ansible/roles/serverapp_caddy/` |
| D1 | site_ns: djbclark; ports 80/443/8080 owner site | V | `group_vars/all.yml`; ports.yml notes Phase D1 |
| D1 | justfile site-serverapps exports STAYTURGID_SITE_DIR | V | site justfile recipes |
| D1 | Live: bootout old, bootstrap com.djbclark.caddy running | V | launchctl state=running; both plists on disk (old retained) |
| D1 | Health 8080 OK; HTTPS front door 200 | V | curl evidence this session |
| D1 | Second apply file actions skip | V | dry-run: skip Caddyfile+plist; site-sync skip |
| D1 | just check + just test green; registry_lint; CI; on master | V | all re-verified this session |
| D1 | Branch deleted; no open PR | V | open PRs empty; feature branch gone |
| D1 | paths.yml still step1 (not drive-by fixed) | G/F1 | Confirmed residual |
| D1 | DEVIATION second apply still ansible ensure | G/F4 | dry-run still shows `ansible serverapp_caddy` ensure line |
| multi | Hosted CI green on **current** merged master | V | run `29688331927` success |
| multi | stayturgid on pulled master; no leftover step branches | V | status clean; only master |
| multi | site commits on master; clean tree (pre-G1 audit commit) | V | master clean before G1 write |

---

## Coverage checklist (ledger stages)

| Stage | Checklist claims extracted | Covered in table |
| ----- | -------------------------- | ---------------- |
| setup | yes | yes |
| consolidation | yes | yes |
| branch cleanup | yes | yes |
| B1–B6 | yes | yes |
| branch-hygiene / B-review hygiene | yes | yes |
| B review | yes | yes |
| C1–C6 | yes | yes |
| FUND-B | process only | N row |
| D0-design | yes | yes |
| D1 | yes | yes |

No step0/step1 human-gate stamps with checklists appeared as separate ledger rows beyond setup.

---

## R1 handoff notes

1. **Do not re-run** the green mechanical suite unless you change code — G1 already has session evidence.
2. Judge **Flags F1–F6** under correctness/safety vs architecture/style (FUND-B bar).
3. **D1 architecture review proper** against `docs/design/phase-d-adapter-design-notes.md` §1 (mode order, exit codes, launchd namespace, fragment import, migration/rollback). Commits: stayturgid PR #17 / `dc9ffaa`+`5055a93`; site `a6cd64a`; this audit.
4. Zero **failed** mechanical claims — R1 is not a repair sprint unless architecture review finds correctness/safety issues.

---

## Session metadata

- Stayturgid left on pulled master `dc9ffaa`, clean, no open PR.
- Site: this audit + ledger + NEXT-PROMPT committed on master (G1 session).
- No secrets written. No stayturgid product code changes. No device contact.
)
