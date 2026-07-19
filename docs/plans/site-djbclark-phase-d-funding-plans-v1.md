# Phase D funding & sequencing plans — v1 (2026-07-19)

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

## Review checkpoints (both plans; see PROTOCOL.md § Review batons)

| Id  | After | Scope                                      | Review AI (plan A / plan B)                |
| --- | ----- | ------------------------------------------ | ------------------------------------------ |
| R1  | D1    | First adapter pattern, both repos          | Fable 5 / Fable 5 (this is where B spends) |
| R2  | D4    | D2–D4 adapter clones + landing fix         | Sonnet 5 / Grok 4.5 High                   |
| R3  | D8    | D5–D8 + whole-phase architecture close-out | Fable 5 / deferred to recovery month (M1)  |

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

## Plan B — "$30 ceiling" (OpenRouter top-up only; ≤$30 extra)

Top up OpenRouter by $30 (→ ~$48.90 balance). Reserve it **exclusively** for
Fable 5 (OpenRouter row 58) at the moments listed below — one heavy agentic
Fable 5 session via API can run $10–20, so the balance buys roughly 2–3
Fable 5 sessions and nothing else.

**Key move — architecture front-load (do this first, TODAY, on the Claude Pro
weekly you already have, before buying anything):** one Fable 5 (web) session
that does _no implementation_ and instead writes
`docs/design/phase-d-adapter-design-notes.md`: the D1 adapter pattern
(mode-selection order, exit codes, launchd namespace, fragment layout), the
D6 projection design (blast-radius rules), and the D8 rollout order. Cheaper
models then execute against a Fable-5-authored design. This is how Plan B
keeps architecture quality while accepting lower code quality.

**Sequencing:**

| Session | Step                                                                                                   | AI                                                                                                                                                               |
| ------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 (now) | D0-design — architecture front-load (see above)                                                        | Claude 2.1.205 (web) · Anthropic · Claude Fable 5 · `claude-fable-5` · Adaptive Thinking (always on) · Next-gen long-running agents — on the existing Pro weekly |
| 2       | D1 implementation against the design notes                                                             | Grok 4.5 High (grok-web)                                                                                                                                         |
| 3       | R1 review — **architecture findings only must-fix**; log code-style findings to the ledger as deferred | Fable 5 via OpenRouter (api) · Anthropic · Claude Fable 5 · Adaptive Thinking (always on) (~$10–15 of the $30)                                                   |
| 4–6     | D2, D3, D4                                                                                             | Grok 4.5 Medium/High; Codex until empty; Composer 2.5 for templating                                                                                             |
| 7       | R2 review (light)                                                                                      | Grok 4.5 High — free, quota permitting                                                                                                                           |
| 8       | D5                                                                                                     | Grok 4.5 High; DeepSeek-V4-Pro for dashboards                                                                                                                    |
| 9       | D6 against the front-loaded design                                                                     | Grok 4.5 High; **escalate to remaining OpenRouter Fable 5 balance if the projection diverges from the design notes**                                             |
| 10–11   | D7, D8                                                                                                 | Sonnet 5 (after Pro weekly reset, ~4d22h) / Grok 4.5 High                                                                                                        |

**Realistic cutoff:** D1–D5 + R1 are achievable now on Grok + Codex + $30.
**D6–D8 are at risk** if Grok's weekly (75%, resets 3d18h) runs dry or gates
stall — that is acceptable: they defer cleanly to the recovery month below.
Completing *all* of D1–D8 at full quality inside the $30 ceiling is **not
realistic**; the plan's promise is D1–D5 done with sound architecture, and the
gap to Plan A closed in the recovery month. Absolute floor if everything goes
badly: D1 + R1 (the pattern is then safe to clone cheaply any time).

**Recovery month M1 (after all quotas/monthlies reset) — run these as normal
batons, in order:**

1. **M1-R (Fable 5, web):** "Review every commit in ~/ops/stayturgid and
   ~/ops/site-djbclark since ledger entry R1 against
   docs/design/phase-d-adapter-design-notes.md. Classify findings:
   architecture (must-fix), correctness (must-fix), code-quality (list).
   Rewrite NEXT-PROMPT.md as a remediation baton covering the must-fix list."
2. **M1-F (Sonnet 5):** "Execute the remediation baton from M1-R. Run the full
   product test suite, strict identity, registry lint. Ledger + baton per
   PROTOCOL.md."
3. **M1-Q (Sonnet 5 or Grok 4.5 High):** "Work through the code-quality
   deferred list in LEDGER.md entries R1..R2: simplify, dedupe, align adapter
   roles D2–D5 with the D1 pattern where they drifted. No behavior changes;
   tests must stay green."
4. **M1-D6..D8 (only if deferred):** run the deferred step batons exactly as
   written, primary Fable 5 for D6, per the checkpoint table above.
5. **M1-R3 (Fable 5):** the R3 close-out review from the checkpoint table.

Result: within one normal month of reset quota (no extra spend), Plan B
converges on Plan A's quality — architecture was never allowed to drift, so
the recovery is code-polish, not redesign.

## Decision

Operator has chosen: **A + B hybrid is not defined — pick one.** Record the
choice as a ledger line (`FUND-A` or `FUND-B`) when the next session starts.
