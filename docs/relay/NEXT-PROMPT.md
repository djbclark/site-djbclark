# NEXT: M1-R — Phase D design/deviation recovery review (difficulty 65/100)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md`). This is recovery-month
step 1. The formal R3 close-out remains deferred until M1-R, M1-F, and M1-Q are
complete. Quality bar: **correctness/safety findings become must-fix work for
M1-F**; architecture is fixed if cheap or explicitly justified; code-quality
items are listed for M1-Q. No human gates.

**Recommended AI** (full row from `docs/reference/available-ai-models.md`):

- **Primary —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
  Auto) · _Next-gen long-running agents_ — use the **new second-Pro account**,
  effort **Medium**, exactly as FUND-B assigns M1-R.
- **Alternate —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol ·
  `gpt-5.6-sol` · Light, Medium, High, Extra High, Max, Ultra · _Flagship;
  complex coding, computer use, research, cybersecurity_ — effort **High** if
  the new-account Fable pool is unavailable.
- **Escalation —** the primary at effort **High** only if a suspected
  correctness/safety issue cannot be classified from repository and live
  read-only evidence at Medium.

**Working dir:** `/Users/djbclark/ops/stayturgid` +
`/Users/djbclark/ops/site-djbclark` (review both pulled masters; write the
review/relay only in the site repo, straight to master).

---

You are executing **M1-R**, recovery-month step 1 from FUND-B. Review every
Phase D change after the R1 checkpoint against the front-loaded design and all
accepted/deferred deviations. This is an evidence-based review session, not a
remediation implementation session: produce a precise M1-F fix baton. Do not
change public product code or live configuration. Correctness/safety findings
must not be deferred; put every one into M1-F with acceptance tests and rollback
notes. Architecture findings may be marked cheap-fix for M1-F or justified as
kept. List code-quality findings for M1-Q.

## Read first (absolute paths)

1. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` and
   `docs/relay/LEDGER.md`, especially R1, R2, D5, D6, D7, and D8.
2. FUND-B review/recovery sequencing in
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-phase-d-funding-plans-v1.md`.
3. Step2 ground rules/risk register (§§0–2), Phase D rows D2–D9, and Phase-end
   review text in
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`.
4. The immutable review baseline
   `/Users/djbclark/ops/site-djbclark/docs/design/phase-d-adapter-design-notes.md`,
   including the R1 §1.9 amendment, D6 projection rules, D8 rollout order, and
   §4 deviation protocol. Do not edit the design baseline.
5. Prior reviews:
   `/Users/djbclark/ops/site-djbclark/docs/relay/reviews/r1-d1-adapter-review.md`,
   `/Users/djbclark/ops/site-djbclark/docs/relay/reviews/r2-d2-d4-adapter-review.md`,
   and `/Users/djbclark/ops/site-djbclark/docs/relay/reviews/gate-debt-audit.md`.
6. `/Users/djbclark/ops/stayturgid/AGENTS.md`, current `docs/handoff.md`, and
   the implementation/tests changed by the commits in scope.

## Exact scope

- Product: review `c9e21b7..2784344` on pulled
  `/Users/djbclark/ops/stayturgid` master. That covers D2–D8, including PRs
  #20–#26; inspect individual commits and merge diffs, not only the final tree.
- Site: review changes after R1 relay commit `5171715` through the current
  pulled master, including D2–D8 registry, generated fragments, relay evidence,
  and live-ownership documentation. Do not expose private inventory or secrets
  in the report.
- Reconcile every R1/R2/D5–D8 deferred item and every deliberate design
  deviation. Mark each `closed`, `still-valid`, `superseded`, `must-fix`,
  `cheap-fix`, or `M1-Q`—none may silently disappear.
- Treat the D8 partial fleet result explicitly: s24 and p7a are verified;
  hd8 is reachable but `pending-incompatible-runtime` because the official
  AArch64 contrib binary hits Fire OS seccomp during the cilium/ebpf memcg
  probe. Determine whether this is a correctness/safety must-fix, an isolated
  compatibility recovery item, or an accepted limitation, and specify a safe
  recovery strategy. Do not weaken device security and do not contact devices.
- Reassess D7 coverage now that D8 transports repair/watchdog logs on two
  devices. The dashboard, fleet-health monitor, access monitor, port 4097, and
  `just health` remain live; decide what is still uniquely covered. Do not
  retire anything in this review.

## Required analysis

1. Build a design-decision matrix: decided rule → implementation evidence →
   tests/live evidence → disposition. Cover adapter mode ordering/refusals,
   ownership and legacy-label safety, fragment single-writer/closed-write-set,
   health/registry coupling, deterministic projections, secret handling,
   D7 retirement coverage, and D8 cache/ABI/checkpoint/boot/rollback behavior.
2. Review commit-by-commit for correctness and safety regressions, not only
   style. Pay special attention to launchd reload semantics, Vector secret-env
   interpolation, OpenObserve bind/advertise settings, exact-process stop
   safety, filelog offset/replay behavior, malformed JSON handling, and
   fail-closed behavior on unsupported runtimes.
3. Re-run device-free verification on both current masters: focused relevant
   tests, public `just check`, full `just test`, pre-commit, site registry lint,
   strict identity, Entangled/site-contract checks, and a site-sync dry-run or
   second-sync no-op as applicable. Record exact counts and failures.
4. Use read-only Mac health evidence if useful. No device contact, no live
   deployments, no daemon retirement, and no secret output.
5. Search for untested branches and stale docs/config paths. Findings need
   file/line or commit references, consequence, severity/class, and a concrete
   acceptance test. Do not list preferences as defects.

## Deliverables

1. Create
   `/Users/djbclark/ops/site-djbclark/docs/relay/reviews/m1-r-phase-d-design-review.md`
   with: scope/baselines; verification evidence; decision matrix; findings
   ordered by correctness/safety, architecture, code quality; full deferred
   item reconciliation; D7 coverage disposition; D8 per-device compatibility
   disposition; and an explicit verdict.
2. Do not implement product fixes. If findings exist, make the next baton
   **M1-F** a complete remediation specification with ordered files, tests,
   rollback, and public branch/PR/CI/merge hygiene. If there are no must-fix
   findings, M1-F still records/revalidates the zero-finding result and carries
   any cheap architecture fixes; it then routes to M1-Q.
3. Append exactly one `M1-R` ledger line. Preserve every deferred item in the
   report or next baton. R3 remains after M1-Q.

## End of session

Follow `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md`: commit and
push the report, ledger, and rewritten M1-F baton straight to site master;
leave both repositories clean and on pulled master; print the complete new
`NEXT-PROMPT.md` in chat; and run
`pbcopy < docs/relay/NEXT-PROMPT.md`.
