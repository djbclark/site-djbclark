# REVIEW-1 CONTINUATION — paste-able successor prompt

**Status: IN PROGRESS** (updated at each checkpoint; if this says IN PROGRESS
and you are a fresh AI session, the previous session died mid-run — resume
from "Next actions" below.)

You are continuing **REVIEW-1: whole-repo code review + fix** across
`~/ops/stayturgid`, `~/ops/site-djbclark`, `~/src/AutoJs6`. Read
`docs/relay/PROTOCOL.md` and the REVIEW-1 baton context in
`docs/relay/LEDGER.md` (site repo) first. The full task spec is the REVIEW-1
prompt — recoverable via `git show 57cad9a:docs/relay/NEXT-PROMPT.md` in the
site repo.

## Ground rules (from the baton)

- Do NOT start E1 (LiteLLM), E2, or E3. E1 baton text preserved at site repo
  `8436cb3:docs/relay/NEXT-PROMPT.md`.
- Fix policy: stayturgid + AutoJs6 via PR branches, merge only when green
  (stayturgid: `just syntax && just check && just test && just lint` + CI;
  AutoJs6: compile check only if sources touched). site: direct to master,
  `just lint` green. ASCII-only path policy applies to new code. Risky /
  judgment-heavy findings: document, don't fix. Don't change behavior
  contracts from stayturgid #29–#32 without evidence of a real bug.
- Don't break D7-ROUTES-E Caddy routes or O-V-G-O daemons; fleet devices
  read-only. No secrets in commits. No Docker. No new ports without
  `registry/ports.yml`.

## State at last checkpoint

- Phase 0 (preflight): DONE. All three repos pulled ff-only:
  stayturgid @ ab329a5, site-djbclark @ 57cad9a, AutoJs6 @ 3a0f0696.
  ccusage baseline: session block started 2026-07-20 02:00 ET-ish, 34m
  elapsed at baseline, ~102k output tokens already burned this block —
  session meter is the binding constraint, checkpoint constantly.
  codexbar per-provider probes running in background →
  scratchpad `codexbar/{claude,codex,grok}.json` (NOT committed; re-run if
  lost: `codexbar usage --format json --provider <p>`, background to file,
  never head).
- Phase 1 (mandated carry-forward deep review): DONE. Reviewed #29
  (199ea20), #31 (0053f00), #30 (c5e52e1), #32 (ab329a5), AutoJs6
  4c2c3522..3a0f0696, site D7-ROUTES-E parity. Sticky-a11y state machine
  agrees end-to-end (comonitor degraded-notify-once; guard hard-notify but
  with 20s recheck debounce; AutoJs6 isMalfunctioning=hasService&&!hasInstance
  with privileged rebind). #32 parity: generated caddy/vector fragments match
  templates + registry ports (3000/5080/1337/8428/8088), /oo prefix correct.
  stayturgid full suite baseline running in background (scratchpad
  st-baseline.log).
- Phase 2 (whole-repo sweep): IN PROGRESS.
- Phase 3 (fixes): NOT STARTED.
- Phase 5 (wrap-up): NOT STARTED.

## Findings log (append as found; mark FIXED(commit) / FLAGGED)

- FLAGGED R1-1 (consistency, judgment): PR31 softened comonitor sticky
  detection to degraded/notify-once because auto.service flickers null on
  s24, but device/autojs6/lib/guard.js enforce() still hard-notifies
  "a11y-stale" every watchdog cycle on the same flicker-prone check.
  Mitigation already present: guard re-checks after termux repair + 20s
  poll before notifying, and notify.show replaces same-tag. No evidence of
  real-world spam from guard path; do NOT change without device evidence
  (behavior contract #29/#31).
- FLAGGED R1-2 (security, operator design): Choice E front door exposes
  OliveTin (action executor) and VictoriaMetrics (unauth'd admin API incl.
  /api/v1/admin/tsdb/*) to the whole tailnet with no auth layer at Caddy.
  Grafana/OO have own logins. Acceptable per D7-ROUTES-E decision
  (single-user tailnet) — revisit if tailnet gains nodes/users.
- NIT R1-3: WATCHDOG_FRESH_SEC=1800 duplicated as literal 1800 in
  device/termux/py/stayturgid_repair.py (comment cross-references; fine).

## Next actions

1. Phase 1 deep review, in this order (interlocking sticky-a11y state
   machine must agree end-to-end across repos):
   - stayturgid #29 (merge 199ea20): control/bin/dashboard.py,
     control/bin/fleet_health_monitor.py, control/lib/fleet_health.py,
     device/autojs6/lib/comonitor.js, device/autojs6/lib/guard.js,
     device/termux/py/stayturgid_repair.py + tests. Themes: sticky-a11y
     detect, catastrophic 2h window, Fire skip-catastrophic.
   - stayturgid #31 (merge 0053f00): comonitor.js sticky → degraded-not-FAILED.
   - AutoJs6 4c2c3522..3a0f0696: AccessibilityBridgeImpl.java,
     AccessibilityTool.kt, AccessibilityService.kt.
   - stayturgid #30 (merge c5e52e1): autojs6_deploy_util.py ASCII paths.
   - stayturgid #32 (ab329a5): serverapp_grafana/openobserve + site_contract
     + landing/discover.py + caddy/vector fragments vs live registry/ports.yml.
   - site D7-ROUTES-E (HEAD~3..HEAD at 8436cb3): generated fragments are
     renders of #32 templates — parity check only.
2. Phase 2 sweep (blast-radius order: stayturgid control/ + device/ +
   ansible/, site bin/registry_lint.py + registry consistency + secretspec +
   justfile + generated-vs-lockfile, AutoJs6 fleet-patch surface only).
3. Phase 3 fix batches per policy above; commit each batch; update this file.
4. Phase 4 if budget remains: adversarial re-passes over Phase 1 scope.
5. Phase 5 wrap-up obligations (MANDATORY, do even if cutting Phase 2/4
   short):
   - Write docs/relay/reviews/REVIEW-1-findings.md (site repo).
   - Append one REVIEW-1 ledger line to docs/relay/LEDGER.md.
   - Restore E1 baton into docs/relay/NEXT-PROMPT.md from
     `git show 8436cb3:docs/relay/NEXT-PROMPT.md`, minus its "next project
     code review MUST include" mandate (done by this review), plus any
     flagged-not-fixed findings as E-phase notes, plus fresh codexbar quotas.
   - Commit/push all touched repos; stayturgid back on master, no open PRs.
   - Verify front-door curl matrix
     https://mac.greyhound-sidemirror.ts.net/{grafana,oo,olivetin,vm}/ all
     200 and O-V-G-O daemons up.
   - Mark this file COMPLETE; print new baton; `pbcopy < docs/relay/NEXT-PROMPT.md`.
