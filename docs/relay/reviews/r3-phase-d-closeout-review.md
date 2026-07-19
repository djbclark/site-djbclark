# R3 — Phase D close-out review (D5 through M1-Q)

**Date:** 2026-07-19
**Reviewer:** Claude Fable 5 (Medium effort) — FUND-B recovery month step 4
(the funding plan's "R3 (After D8)" checkpoint, widened by the recovery month
to everything since R2). This is a **re-verification review**, not a fresh
audit: R1/M1-R did the deep read; M1-F closed all five must-fix + three
cheap-arch findings; M1-Q worked the quality list. R3 verifies that closure
held, judges the two explicit deferrals, and takes the whole-phase view.

## Scope and baselines

- Product: stayturgid master `d99b507..b07ae21` — PRs #23 (D5 O-V-G-O), #24
  (D6 projections), #25 (D7 retirement), #26 (D8 edge otelcol), #27 (M1-F
  must-fix remediation), #28 (M1-Q code-quality remediation). Commit list
  re-confirmed with `git log --oneline d99b507..HEAD` at session start.
- Site: `fdb827f..668873a` — D5–M1-Q relay commits, registry changes, MF-2
  hd8 group_var, and the two M1-Q doc commits (20adb4b, 02bc3ee).
- Judged against `docs/design/phase-d-adapter-design-notes.md` (incl. R1
  §1.9 amendment and M1-Q §5 deviation-log entry 3), stayturgid
  `docs/architecture/site-contract.md` §5, and the R1/R2/G1/M1-R
  dispositions. Design baseline not edited (no new deviations found).

## Verification evidence (this session, pulled masters)

| Check | Result |
| ----- | ------ |
| stayturgid `just check` | exit 0 — RESULT: PASS (code); html-validate all passed |
| stayturgid full `just test` | exit 0 — **497 passed, 1 skipped** + collection suites 43/11/20/7/15/7 — **exact match to M1-Q baseline, zero drift** |
| `pre-commit run --all-files` | exit 0 — all hooks passed |
| Overlay strict identity (site ANSIBLE_CONFIG) | drift OK, secrets OK, exit 0 |
| Upstream-only strict identity (`OPS_ROOT=/tmp/no-sites-here`) | example inventory, drift OK, secrets OK, exit 0 |
| `just site-contract-check` | Entangled parity OK (9 literate templates; 2 registry seeds generator-owned), exit 0 |
| site `bin/registry_lint.py` | `registry-lint: OK`, exit 0 |
| Live health (read-only) | 8080/health, 8686/health, 5080/healthz, 8428/health, 3000/api/health, 1337/, 8088/health, 4097/, HTTPS front door (mac.greyhound-sidemirror.ts.net/health) — all **200** |
| `just site-sync mode=dry-run` (session start) | 9 fragments + olivetin projection all **skip**; only `.lockfile.yml` pending overwrite (product_commit stamp `0ae6d28` → `b07ae21`) — **A-10's fix proven**: a product merge no longer flips any generated fragment, only the stamp. Restamped this session (see below); dry-run now full no-op (11 skips) |
| D7 archive state | 5 legacy serverapp plists still byte-archived at `~/.config/djbclark/retired-plists/`, absent from `~/Library/LaunchAgents/`; retained monitors (dashboard, fleet-health, access-monitor + device utilities) still loaded under `com.stayturgid.*`; all 10 `com.djbclark.*` site labels loaded |
| D8 per-device state | s24: otelcol running, log present (ssh). p7a: ssh 8022 refused, **but** fleet-health shows it reporting 7 min ago and OpenObserve's latest `android_logs` record is from p7a (19:36Z) — collector shipping fine; the ssh refusal is part of a device-side AutoJs6/a11y issue the retained D7 monitors are correctly flagging (`autojs6_a11y_missing`, port CLOSED_NO_SHELL) — a fleet-ops item, not a Phase D defect. hd8: `stayturgid_otelcol_enabled: false` in effect, fleet-health "ok", not attempted-and-failing |
| OpenObserve pipeline (read-only API query) | `android_logs` stream holds D8 pilot markers from both s24 and p7a; latest record p7a 2026-07-19T19:36Z |
| Hosted CI | stayturgid master: run 29707111881 (PR #28 merge) success, still the latest; run 29705800898 (PR #27) success. **Site repo has no hosted CI workflows** — the baton's "both repos" phrasing was imprecise; both quoted run IDs are stayturgid runs. Nothing to check on site, noted for future batons |
| Branch hygiene | both repos master-only local+origin, no open PRs, clean trees (site's lockfile restamp committed this session) |

Live plan-layer check (read-only): `build_plan()` on this site yields
`product_version='2.7'` for exactly the five header-bearing apps
(caddy/vector/victoriametrics/grafana/olivetin), None for openobserve/landing
— S-3's plumbing verified end-to-end at the plan layer.

## Spot-check matrix — M1-F fixes on current master (baton item 1)

| Fix | Claim | Verified |
| --- | ----- | -------- |
| MF-1 | vector/OO plists mode 0600 | Role tasks `mode: "0600"` (vector tasks:69,138; OO tasks:100); live `stat`: both `~/Library/LaunchAgents/com.djbclark.{vector,openobserve}.plist` are `-rw-------` |
| MF-2 | hd8 otelcol disabled persistently | `inventory/group_vars/model_kindle_hd8.yml` carries `stayturgid_otelcol_enabled: false` + pending-incompatible-runtime comment; fleet-health shows hd8 ok |
| MF-3 | bootout-on-plist-change in caddy/grafana/olivetin | "Boot out site-namespace <app> when its launchd plist changed" tasks present in all three roles (caddy:213, grafana:144, olivetin:216) |
| MF-4 | fragment-checksum reload | "Reload caddy on fragment-content change" + `.fragments.sha256` state file in caddy (tasks:89,113) and vector (1 hit) |
| MF-5 | pinned checksums on installs | `serverapp_{openobserve,olivetin}_archive_sha256` in defaults; `checksum: "sha256:{{ … }}"` on both `get_url` tasks; fail-closed asserts present |
| A-10 | commit: out of headers | zero `commit:` in `control/site_contract/sync_templates/` or `olivetin_projection.py` headers; commit only in `.lockfile.yml`. Behaviorally proven by this session's dry-run (fragments all-skip across a product merge) |
| A-11 | services.just fallback gone | zero `site-djbclark` references in `just/services.just` |
| A-12 | honest noValue | dashboard template `noValue: "no metrics pipeline yet"` + updated description |

**All eight hold. Nothing regressed.**

## M1-Q spot-check (baton item 2)

Read the full PR #28 diff (`0ae6d28..b07ae21`, 16 files, +211/−258):

- **S-4 consolidation** — the highest-risk change. Verified each of the 8
  materializer plist blocks maps parameter-for-parameter onto
  `_render_test_launchd_plist()` (caddy/vector stdout+stderr; OO
  working_directory + 5 extra_env; VM/grafana/olivetin stdout-only;
  landing×2 keep_alive/start_interval split). Faithful; explicitly
  documented as test-only scaffolding, not the real templates. No regression.
- **S-6 `unsupported_mode`** — only landing/olivetin inject refusals changed
  kind; the 4 real forced-own-foreign refusals kept `forced_own_foreign`;
  the sole `.kind` consumer (`_refusals_recoverable_with_force`) checks only
  `"drifted"` — no refusal-expectation broke anywhere (full suite green).
- **S-7 uid-default removal** — verified all 7 roles now fail closed;
  `serverapps.py` is the only invoker and always passes `os.getuid()`.
- **S-10 `drop` vs `drop_quiet`** — config + test updated consistently;
  forwarding behavior unchanged, drops now visible in otelcol's own log.
- **S-3 `product_version` render** — plan layer verified (see above). **Live
  configs still carry the old placeholder headers** ("own-mode site_ns=…" /
  "unknown commit: unknown") because M1-Q deliberately did no apply. I
  attempted the real own-mode apply the baton asks for; this session's
  permission policy blocked apply-mode commands, so it remains **deferred to
  the next operator/session apply** — which will rewrite the five base
  configs (header line) and restart those daemons through the now-verified
  MF-3/MF-4 reload paths. Cosmetic, no live risk; explicitly not silent.
- **A-3 deviation log** — §5 entry 3 present; docstrings on both
  `_*_fragment_dir` helpers match it.

## New findings (fresh-eyes pass, baton item 5)

### Correctness/safety — must-fix (fixed this session)

| Id | Finding | Fix + evidence |
| -- | ------- | -------------- |
| **R3-1** | **`~/ops/stayturgid/.env` was world-readable (0644) and holds `OPENOBSERVE_ROOT_PASSWORD`** (secretspec dotenv source; also TELEGRAM_BOT_TOKEN, VECTOR_INGESTION_TOKEN) — the exact exposure class MF-1 closed for plists, one directory over. Not introduced by a Phase D commit (file predates, gitignored, never committed — verified `git log --all -- .env` empty) but M1-F's MF-1 sweep verified the plists and missed the sibling file feeding them. | `chmod 0600 .env`; before `-rw-r--r--` → after `-rw-------` (stat recorded). Rollback: `chmod 0644` (none needed — secretspec reads as same user; verified secretspec still resolves). Live-state-only fix; nothing to commit, so no stayturgid PR. Hardening follow-up (quality note): a `just check`-level assert that secretspec dotenv files are 0600 would make this class unrecurrable. |

### Architecture (notes; nothing to fix)

- **Lockfile-only churn per product merge is the accepted residue of A-10** —
  intended (the lockfile records the stamp). Practical rule for the ledger:
  after a product merge, a `site-sync mode=apply` + one-line site commit
  restamps it (done this session, commit below). Fragments stay untouched.
- **The site repo has no hosted CI** — future batons should stop asking to
  verify "CI green on both repos"; stayturgid CI + site registry lint is the
  actual gate set.

### Code quality (list only — folded into the ledger note, no M1-Q2 baton)

1. Secretspec dotenv file-mode assert (from R3-1, above).
2. `olivetin_projection.py` still takes a now-unused `product_commit`
   parameter (A-10 removed it from the rendered header) — dead parameter ×2
   signatures.

The list is trivial (2 items); per baton constraints, no fourth recovery
session is warranted — a follow-up ledger note suffices.

## Deferred-item judgments (baton items 3–4)

| Item | Judgment |
| ---- | -------- |
| **A-2** own-mode port-availability pre-check | **Still correctly deferred.** No site-map file exists on this site (`ls site-map.yml` → absent), so forced-own-against-foreign remains unreachable; nothing in D5–M1-Q changed that. M1-Q's sizing argument (live port probing inside a pure planning layer, TOCTOU, ×4 apps) stands. Not correctness/safety. Revisit when a site-map-bearing site exists. |
| **A-6** registry-sourced health ports | **Still correctly deferred.** Single-site; role defaults match `registry/ports.yml` (spot-checked 8686/8428/3000/1337). M1-Q correctly noted a real fix must control daemon listen ports, not just health-check URLs — that's multi-site work. Zero live risk today. |
| **D7 route scheme (§11 #9)** | **Still open — and this is the last checkpoint that forwards it.** Confirmed unimplemented across R1→M1-R→M1-Q→now. It is an operator architecture decision (route naming + whether O-V-G-O UIs get front-door routes). Handed to the operator explicitly in NEXT-PROMPT.md; future sessions should treat it as an operator backlog item, not a review deferral. |

## Whole-phase architecture close-out (baton item 6)

Zoomed out, Phase D (D1–D8 + M1 recovery) **hangs together**:

- **The adapter pattern held under cloning.** The D1 template survived seven
  apps with one systematic class of deviation (detect-path narrowing,
  D2/D3/D4/D5) — reviewed, accepted permanently, and recorded in the
  deviation log rather than silently accumulated. The pattern's weak points
  (launchd reload semantics) were found by review (M1-R MF-3/MF-4), fixed
  once, and encoded as tests so clones can't regress them.
- **The generated-header story converged.** After A-10 (commit out of
  headers) + S-3 (real product_version in role templates), every generated
  surface — sync fragments, role base configs, the olivetin projection —
  carries the same one-line provenance format, and idempotence across
  product merges is now real and behaviorally proven.
- **Write-boundary discipline is coherent end-to-end:** site-sync owns
  `generated/`, projections are pure with a closed write set and a single
  writer for olivetin, roles own `~/.config/<site_ns>/`, user content is
  refused. Nothing in the recovery month blurred those lines.
- **Supply-chain posture is now uniform** (D8's pinned-checksum pattern
  back-ported to the D5 installs via MF-5) instead of best-in-one-place.
- **Known, recorded asymmetries — deliberate, not drift:** no metrics leg
  (Grafana per-host panels honestly labeled; precondition for ever retiring
  D7 monitors), hd8 without edge telemetry (persisted disable + OCB
  minimal-build recovery plan in M1-R §D8), O-V-G-O UIs without front-door
  routes (operator's §11 #9 decision). Each has an owner and a trigger.

## Verdict

**Phase D closes.** Every M1-F fix holds on current master with live
evidence; M1-Q introduced no regressions (its riskiest refactor verified
line-by-line); both M1-Q deferrals remain correctly deferred; the one new
must-fix (R3-1, world-readable secrets file — same class as MF-1, missed by
its sweep) was fixed in-session with before/after evidence. All suites,
identity, contract, and lint checks are green at the exact M1-Q baseline,
and all nine live endpoints answer 200.

Two loose ends leave the phase, neither blocking: (1) the S-3 header
refresh rides the next credentialed apply (cosmetic; this session's policy
blocked apply-mode); (2) **D9 — the step2 plan's cheap Logging Phase-2
close-out verification — was never sequenced by the funding plan (it stops
at D8) and is the genuine next step.** NEXT-PROMPT.md carries a D9 baton;
the operator separately owes the §11 #9 route-scheme decision.
