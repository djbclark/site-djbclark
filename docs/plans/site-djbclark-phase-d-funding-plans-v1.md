# Phase D funding & sequencing plans — v1 (2026-07-19; rev B-final)

**DECIDED: Plan B (revised — second Pro account).** Human gates are removed
protocol-wide (operator was confirm-stamping; PROTOCOL.md now substitutes
extra verification + rollback notes for human eyes). Quality bar relaxed for
BOTH plans: only correctness/safety findings are must-fix; architecture and
code-style findings may be deferred to the ledger for month M1.

Two ways to fund and sequence D1–D8 plus end-of-stage code reviews. Both
front-load Claude Fable 5 onto the decisions where it matters most; they differ
in budget and in how much code quality is bought now vs. recovered after the
monthly resets. The operator picks one; the choice is recorded in the ledger
and every baton header notes which plan is in force.

Quota snapshot backing these plans (2026-07-19, CodexBar): Grok web 75%
weekly · Claude Pro 59% weekly (resets ~4d22h) · Codex 29% weekly (operator
authorized burning it; resets ~6d) · Cursor 42% total, API pool 0% ·
OpenRouter $18.90 · DeepSeek $4.99 · OpenCode Go / Antigravity Claude+GPT
effectively empty.

## Where Fable 5 matters most (both plans)

Ranked by leverage — spend Fable 5 here first, cheaper models everywhere else:

1. **D1 adapter architecture** — own/inject mode semantics, detection order,
   exit-code contract, launchd namespace pattern. This is the template every
   later adapter (D2–D5) copies; a wrong shape here multiplies across the
   phase. _Highest-leverage Fable 5 use in Phase D._
2. **R1 review (after D1)** — architecture review of the first adapter before
   D2–D4 clone it. Second-highest leverage: catches pattern errors while only
   one adapter exists.
3. **D6 tenant fragments** — inventory→projection blast radius (a bad
   projection rewrites many generated files across serverapps).
4. **D1 TLS cutover + D8 fleet rollout judgment** — operator-gated,
   hard-to-reverse actions; judgment beats horsepower.
5. **R3 review (after D8)** — phase close-out; matters more under Plan B
   (it is where deferred code quality is measured for the recovery month).

Explicitly _not_ Fable-5-critical: D2–D4 adapter cloning, D5 installs, D7
retirement mechanics, Grafana YAML drafting (DeepSeek V4 Pro is fine).

**Fable 5 effort levels (corrected 2026-07-19 — operator-verified):** the
Claude GUI on monthly plans has a selectable Low/Medium/High/Extra/Max/Ultra
picker for Fable 5 (catalog row 10; no Auto for effort — the lower-left
yellow "Auto" is a separate safety/routing control, don't touch it). Since
quota burn scales with effort, assign per session:

- **D0-design, D6 escalation: High.** These are the judgment sessions Plan B
  exists to fund — Low here defeats the purpose. Never Extra/Max/Ultra
  (diminishing returns on quota) unless a session is genuinely stuck.
- **R1/R3 reviews, M1-R: Medium.** Reading-heavy verification; Medium is the
  get-away-with-it tier the operator asked about — yes, for reviews.
- **Mechanical Fable 5 work (rare; e.g. M1 remediation drafting): Low.**

## Gate-debt remediation (one-time)

Human gates in Phases B–C were confirm-stamped without inspection, so every
"human-verified" checklist claim in ledger entries through C6 is actually
unverified. Remediation, folded into **R1's scope** (no extra session):
R1 re-runs the C2–C6 checklist items that are still mechanically checkable
(test suites, strict identity, registry lint, second-sync no-op, entangled
parity, merged-master state) and records the evidence in its ledger line.
Anything not mechanically checkable is listed in the R1 ledger note as
permanently unverified-by-human — accepted under FUND-B. Going forward the
protocol's self-verify rules make this class of debt impossible to re-accrue.

## Review checkpoints (both plans; see PROTOCOL.md § Review batons)

| Id  | After | Scope                                      | Review AI (plan A / plan B)                |
| --- | ----- | ------------------------------------------ | ------------------------------------------ |
| R1  | D1    | First adapter pattern, both repos          | Fable 5 / Fable 5 (this is where B spends) |
| R2  | D4    | D2–D4 adapter clones + landing fix         | Sonnet 5 / Grok 4.5 High                   |
| R3  | D8    | D5–D8 + whole-phase architecture close-out | Fable 5 / deferred to recovery month (M1)  |

Under the relaxed quality bar, reviews must-fix **correctness/safety only**;
architecture and code-style findings are logged to the ledger as deferred.

## Plan A — "buy the month" (~$100: upgrade Claude Pro → Max 5x)

Upgrade the existing account (prorated, no second login, no ToU questions).
Downgrade after the month if desired.

**Sequencing** (Fable 5 as soon as possible):

| Session | Step                                                  | AI                                                                                                                                  |
| ------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| 1 (now) | D1 — Fable 5 runs the whole step, not just escalation | Claude 2.1.205 (web) · Anthropic · Claude Fable 5 · `claude-fable-5` · Adaptive Thinking (always on) · Next-gen long-running agents |
| 2       | R1 review                                             | Fable 5 (same row)                                                                                                                  |
| 3–5     | D2, D3, D4                                            | Grok 4.5 High (grok-web) primary; Codex GPT-5.6 Sol High until empty, then OpenRouter GPT-5.6 Sol                                   |
| 6       | R2 review                                             | Claude Sonnet 5 (web)                                                                                                               |
| 7       | D5                                                    | Grok 4.5 High; DeepSeek-V4-Pro (`deepseek-v4-pro`) for Grafana YAML drafting                                                        |
| 8       | D6                                                    | Fable 5                                                                                                                             |
| 9       | D7                                                    | Sonnet 5                                                                                                                            |
| 10      | D8                                                    | Grok 4.5 High, escalate Fable 5 if the rollout gets gnarly                                                                          |
| 11      | R3 review                                             | Fable 5                                                                                                                             |

**Outcome:** full D1–D8 + all three reviews at target quality in ~3–5 days.
No recovery month needed. Extra spend: ~$100 (minus proration).

## Plan B — REVISED & CHOSEN: "$20 second Pro" (second Claude Pro account)

Original $30-OpenRouter version superseded: API-metered Fable 5 runs ~$1/min
(operator-measured), so $30 buys ~2 sessions once, while a second $20 Pro
plan buys a Pro-sized Fable 5 weekly that renews all month (~5–10× more
Fable 5 per dollar) and also covers recovery month M1 with the same purchase.
The second account is held by a second human (no ToU exposure). Relay handoff
makes account switching cheap — every session starts fresh from a committed
baton, so nothing is lost by switching logins between sessions.

**Accounts** (every Claude baton names one):

- **Original** (djbclark@gmail.com): ~60% Fable 5 weekly remaining as of this
  revision. Spend it NOW on D0-design (highest-leverage session). Afterwards:
  Sonnet 5 and routine Claude work.
- **New** (second Pro, second human): all subsequent Fable 5 sessions — R1,
  D6 escalation, M1-R, M1-R3.

**Key move — architecture front-load (session 1, today, original account):**
one Fable 5 (web) session that does _no implementation_ and instead writes
`docs/design/phase-d-adapter-design-notes.md`: the D1 adapter pattern
(mode-selection order, exit codes, launchd namespace, fragment layout), the
D6 projection design (blast-radius rules), and the D8 rollout order. Cheaper
models then execute against a Fable-5-authored design. Design notes are
guidance, not law, under the relaxed bar — implementers may deviate where the
design proves awkward, recording the deviation in the ledger for M1-R to
re-judge.

**Sequencing** (no human gates; sessions self-verify per PROTOCOL.md):

| Session | Step                                                                    | AI (account)                                                                                                                                               |
| ------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 (now) | D0-design — architecture front-load                                     | Claude 2.1.205 (web) · Anthropic · Claude Fable 5 · `claude-fable-5` · Adaptive Thinking (always on) · Next-gen long-running agents — **original account** |
| 2       | D1 implementation against the design notes                              | Grok 4.5 High (grok-web)                                                                                                                                   |
| 3       | R1 review — must-fix correctness/safety only; defer the rest to ledger  | Fable 5 (web) — **new account**                                                                                                                            |
| 4–6     | D2, D3, D4 (self-passoff allowed: one Grok session may chain all three) | Grok 4.5 Medium/High; Codex until empty; Composer 2.5 for templating                                                                                       |
| 7       | R2 review (light)                                                       | Grok 4.5 High — free, quota permitting                                                                                                                     |
| 8       | D5                                                                      | Grok 4.5 High; DeepSeek-V4-Pro for dashboards                                                                                                              |
| 9       | D6 against the front-loaded design                                      | Grok 4.5 High; escalate to Fable 5 (web, **new account**) if the projection diverges from the design notes                                                 |
| 10–11   | D7, D8                                                                  | Sonnet 5 (**original account**, after weekly reset ~4d22h) / Grok 4.5 High                                                                                 |

**Realistic cutoff:** with no human gates stalling sessions and a renewing
Fable 5 weekly on the new account, **D1–D6 + R1 + R2 are achievable this
cycle**; D7–D8 ride on quota luck and defer cleanly to M1 if Grok runs dry.
Full D1–D8 at Plan-A quality inside this cycle is still not promised — the
promise is sound-enough architecture now and convergence in M1. Absolute
floor: D0-design + D1 + R1.

**Recovery month M1 (after all quotas/monthlies reset) — run these as normal
batons, in order:**

1. **M1-R (Fable 5, web, new account):** "Review every commit in
   ~/ops/stayturgid and ~/ops/site-djbclark since ledger entry R1 against
   docs/design/phase-d-adapter-design-notes.md and the deviations logged in
   LEDGER.md. Classify findings: correctness/safety (must-fix), architecture
   (fix if cheap, else justify keeping), code-quality (list). Rewrite
   NEXT-PROMPT.md as a remediation baton covering the must-fix list."
2. **M1-F (Sonnet 5, original account):** "Execute the remediation baton from
   M1-R. Run the full product test suite, strict identity, registry lint.
   Ledger + baton per PROTOCOL.md."
3. **M1-Q (Sonnet 5 original account, or Grok 4.5 High):** "Work through the
   deferred list in LEDGER.md entries R1..R2: simplify, dedupe, align adapter
   roles D2–D5 with the D1 pattern where they drifted. No behavior changes;
   tests must stay green."
4. **M1-D6..D8 (only if deferred):** run the deferred step batons exactly as
   written, primary Fable 5 (new account) for D6.
5. **M1-R3 (Fable 5, new account):** the R3 close-out review.

Result: within one normal month of reset quota (second Pro still active, no
further spend), Plan B converges near Plan A's quality — deviations were
ledgered rather than silent, so M1 recovery is targeted, not archaeology.

## Decision

**FUND-B (revised) chosen by operator 2026-07-19.** Recorded in LEDGER.md.
Action items: (1) second human purchases the $20 Pro plan and shares session
access; (2) operator runs D0-design on the original account today.
