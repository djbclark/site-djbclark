# NEXT: R3 — Phase D close-out review (D5 through M1-Q) (difficulty 55/100)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md`). Recovery-month
step 4 of {M1-R ✓, M1-F ✓, M1-Q ✓, R3}. This is the review checkpoint the
funding plan calls "R3 (After D8): D5–D8 + whole-phase architecture
close-out", widened by the recovery month to cover everything landed since
R2 — R1/M1-F/M1-Q already fixed every correctness/safety and cheap-arch
finding R1/M1-R raised, so R3 is verifying that closure held and catching
anything new introduced by the recovery-month sessions themselves.

**Recommended AI** (full row from `docs/reference/available-ai-models.md`):

- **Primary —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
  Auto) · _Next-gen long-running agents_ — **new second-Pro account**,
  effort Medium. This is the funding plan's explicit R3 assignment
  (§Recovery month M1, item 5: "M1-R3 (Fable 5, new account): the R3
  close-out review"), matching R1/M1-R's review-tier precedent.
- **Alternate —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort (default High on Claude
  Code/API) · _Default for most plans_ — **original account**, High effort,
  if the new account's Fable 5 weekly is empty (check CodexBar first).
- **Escalation —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol ·
  `gpt-5.6-sol` · Light, Medium, High, Extra High, Max, Ultra · _Flagship;
  complex coding, computer use, research, cybersecurity_ — effort High, only
  if both Claude accounts are exhausted.

**Working dir:** `/Users/djbclark/ops/stayturgid` (read/verify; fixes only
if a must-fix surfaces — branch+PR) and `/Users/djbclark/ops/site-djbclark`
(review doc + ledger/baton; straight to master).
`git fetch origin --prune && git pull --ff-only origin master` in both
before starting.

---

You are running **R3**, the phase-close-out review baton described in
`docs/relay/PROTOCOL.md` §Review batons. Read that section first, then read
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md` §Review checkpoints
and §Recovery month M1 for why this checkpoint exists and what "must-fix
vs may-defer" means under the relaxed FUND-B bar.

## Scope

Every commit landed since R2 (which reviewed D2–D4) in both repos:

- **stayturgid:** `d99b507..HEAD` on master — D5 (O-V-G-O adapters, PR #23),
  D6 (inventory→fragment projections, PR #24), D7 (legacy retirement, PR
  #25), D8 (edge otelcol, PR #26), M1-F (must-fix remediation, PR #27), and
  M1-Q (code-quality remediation, PR #28). Run
  `git log --oneline d99b507..HEAD` to confirm the exact list before
  starting; do not assume this list is still current if more sessions ran
  after this baton was written.
- **site-djbclark:** `fdb827f..HEAD` on master — the matching D5–M1-Q relay
  commits, registry changes, and the two M1-Q doc commits (20adb4b, 02bc3ee).

Judge against the immutable baseline
`docs/design/phase-d-adapter-design-notes.md` (incl. its R1 §1.9 amendment
and the M1-Q §5 deviation-log entry 3 for inject-mode `fragment_dir`),
stayturgid `docs/architecture/site-contract.md` §5, and every prior review's
dispositions (R1, R2, M1-R — read
`docs/relay/reviews/r1-d1-adapter-review.md`,
`docs/relay/reviews/r2-d2-d4-adapter-review.md`, and
`docs/relay/reviews/m1-r-phase-d-design-review.md` for what was already
found and fixed, so you don't re-litigate closed findings without new
evidence they regressed).

## What to actually check (this is a re-verification review, not a fresh audit)

R1/M1-R already did the deep architectural read of D1–D8. M1-F fixed all
five must-fix + three cheap-arch findings; M1-Q worked the code-quality
list. Your job is narrower and should move faster than R1/M1-R did:

1. **Spot-check that M1-F's fixes actually hold on current master** — don't
   re-derive them from scratch, verify the specific claims: MF-1 (plist
   mode 0600, live `stat` check), MF-2 (hd8's `stayturgid_otelcol_enabled:
   false` still present in site inventory), MF-3 (bootout-on-plist-change
   pattern still in caddy/grafana/olivetin tasks), MF-4 (fragment-checksum
   reload tasks still present), MF-5 (checksums still set on the OO/OliveTin
   `get_url` tasks), A-10/A-11/A-12 (header format, services.just fallback
   removed, Grafana noValue text).
2. **Spot-check M1-Q's changes for regressions or incompleteness** — the
   S-1/S-3/S-4/S-6/S-7/S-9/S-10/S-11/A-3/A-5 items closed in PR #28 (ledger
   `M1-Q` line has full detail); confirm `product_version` actually renders
   correctly in a real (not test-materializer) own-mode apply if you have
   live access, and that the `unsupported_mode` refusal kind didn't silently
   break any refusal-message expectations elsewhere.
3. **Judge the two items M1-Q explicitly deferred** — A-2 (own-mode
   port-availability pre-check) and A-6 (registry-sourced health ports).
   M1-Q's ledger line explains why each was judged too large for a
   no-behavior-change pass. Decide: still correctly deferred (not a
   correctness/safety issue, still not live-reachable / still zero live
   risk), or has something changed that promotes either to a must-fix? If
   still deferred, that's an acceptable R3 outcome — restate why in your
   review doc rather than silently dropping it.
4. **D7 route scheme (§11 #9)** — confirmed still explicitly deferred to the
   operator across R1→M1-R→M1-Q. Do not implement it. Note it as still-open
   in your review doc; this is the last checkpoint that should keep
   forwarding it if no operator decision has landed.
5. **Fresh read for anything new** — D5–D8 got a full R1-style read from
   M1-R already (see that review's Findings tables); your fresh-eyes pass
   should focus on whether M1-F's and M1-Q's *changes themselves*
   introduced anything new, not re-review D5–D8 line-by-line from zero.
6. **Whole-phase architecture close-out** — per the funding plan's R3
   framing, step back from individual findings and assess: does Phase D
   (D1–D8 + M1 recovery) hang together as a coherent system now? Anything
   that only becomes visible zoomed-out (e.g. accumulated deviations across
   D2/D3/D4/D5's "detect-path narrowing" pattern, or the generated-header
   format's evolution across A-10) belongs in a "whole-phase" section of
   your review doc, separate from the checkpoint-by-checkpoint spot-checks.

## Verification evidence to gather (same discipline as M1-R)

Re-run and record, on pulled masters of both repos:

- stayturgid `just check` + full `just test` + `pre-commit run --all-files`
  (compare counts to M1-Q's baseline: 497 passed, 1 skipped, collection
  suites 43/11/20/7/15/7 — flag any drift).
- Overlay + upstream-only `just validate-identity`; `just site-contract-check`.
- Site `bin/registry_lint.py`.
- Live (read-only): all 9 health endpoints 200
  (8080/8686/5080/8428/3000/1337/8088/4097 + HTTPS front door); D7 archive
  state and disabled-DB state still consistent; D8 per-device state
  unchanged (s24/p7a healthy, hd8 still `pending-incompatible-runtime` and
  not attempted-and-failing).
- Hosted CI green on both repos' current master (PR #27 run 29705800898,
  PR #28 run 29707111881 — confirm these are still the latest and still
  green, or re-check if newer commits landed).
- Branch hygiene: both repos master-only, no open PRs, no stale local
  branches.

## Output

Write `docs/relay/reviews/r3-phase-d-closeout-review.md` (site repo) in the
same structure as `m1-r-phase-d-design-review.md`: scope/baselines,
verification evidence table, decision matrix, findings split into
correctness/safety (must-fix — **fix these yourself in this session**,
same as R1's MF-1 fix), architecture (cheap-fix or justified-kept), and
code quality (list only — new M1-Q2 baton if the list is non-trivial,
otherwise fold into the ledger note). End with a verdict paragraph:
is Phase D done, or is there a real next step?

## Constraints

- No device contact unless a must-fix genuinely requires a live check beyond
  read-only health polling (say so explicitly if so, and use the same
  before/after health-check + tested-rollback discipline as every prior
  session).
- No secrets in output or commits.
- Design-baseline edits: none beyond what M1-Q's A-3 deviation-log entry
  already covers, unless you find a genuinely new deviation that needs
  recording — if so, append to §5, don't rewrite existing entries.
- If a must-fix surfaces: fix it yourself in stayturgid (branch + PR, merge
  after evidence, per PROTOCOL.md), not just document it. Architecture and
  code-style findings may defer to a follow-up ledger note instead of a new
  baton, at your judgment — Phase D does not require a fourth recovery
  session if nothing correctness/safety-shaped turns up.

## End of session

Per `docs/relay/PROTOCOL.md`: append one `R3` ledger line (evidence + any
must-fix commits + anything still deferred). If Phase D is genuinely done
(no must-fix, nothing left that needs a dedicated next session), rewrite
`NEXT-PROMPT.md` to reflect that — either a fresh baton for the next real
piece of work on this fleet (check `docs/plans/` for what comes after Phase
D), or a short "Phase D closed, nothing queued" placeholder the operator can
replace. If a must-fix required a same-session fix: merge + delete the
stayturgid branch, both repos end on pulled master. Print the new
NEXT-PROMPT.md in chat and run `pbcopy < docs/relay/NEXT-PROMPT.md`.
