# Quota pacing across AI vendor subscriptions

## Account switching is MANUAL — cswap auto is off

**Read this before routing any work to a model.** The launchd job
`com.djbclark.cswap-auto` is stopped, disabled, and its plist renamed to
`.plist.disabled`. Nothing rotates accounts on its own any more. Never
assume a switch will happen, and never wait for one.

*Why, because the failure mode is silent:* it ran `cswap auto --threshold 90
--model all`, which selects on **5-hour headroom alone and is blind to
per-model entitlement**. Only `djbclark@gmail.com` carries Fable. When that
account's 5h window crossed 90%, the job moved the whole machine to
`djbclark@mit.edu`, which has **no Fable line at all** — silently destroying
the ability to run Fable agents while every quota number still looked
healthy. Optimizing one axis (headroom) quietly broke another (entitlement).

Read state with `cswap list`; the percentages are percent **USED**, not
remaining, and a `Fable:` line is the entitlement signal — an account
without one cannot run Fable at any effort.

**Fable is an ADDITIONAL gate, not a separate allowance — headroom on the
`Fable:` line is necessary but NOT sufficient.** From `relevant_windows()`
in `claude_swap/oauth.py`, the windows that gate an account are "**always**
the 5-hour and 7-day windows", with each per-model `weekly_scoped` entry
from the API's `limits` array included *too*. So a Fable run bills **both**
meters and a 5h window at 100% blocks Fable exactly like everything else.
Measured 2026-08-15: a 211k-token `fable-deep` run moved the 5h window
**56% → 87%** while the Fable weekly moved only **5% → 10%** — the 5h is
the binding constraint for Fable work, not the Fable line. Before a Fable
launch, check the active account's **5h and Fable lines together**.

Act with the narrowest tool that solves the problem:

```bash
cswap status                  # which account is active right now
cswap run <num|email> -- ...  # THIS TERMINAL ONLY — best for a one-off
cswap map <num|email> <path>  # pin a directory to an account
cswap switch <num|email>      # GLOBAL: hot-swaps every running session
```

`cswap switch` needs no restart, but it moves **every** running session
including orc and its panes — which in an orchestration context means you
can retarget other agents' accounts as a side effect. Prefer `run` or `map`;
use `switch` only when the whole machine should genuinely move.

**Hard rule before launching any Fable agent** (`fable-deep`, or
`--model fable`): run `cswap list` and confirm the **active**
account shows a `Fable:` line. If it does not, do not launch — switch first,
or tell the operator. Launching regardless yields a run on the wrong model
that still reports success, the same class of error
`[[stop-when-cannot-set-effort]]` exists to prevent. Verify what a subagent
actually ran from harness records, never by asking the agent.

To restore automatic switching (only on operator instruction) the
`launchctl enable` step is mandatory — the disable lives in launchd's
override database and survives the plist being put back, so skipping it
makes the job silently fail to load:

```bash
mv ~/Library/LaunchAgents/com.djbclark.cswap-auto.plist.disabled \
   ~/Library/LaunchAgents/com.djbclark.cswap-auto.plist
launchctl enable    "gui/$UID/com.djbclark.cswap-auto"
launchctl bootstrap "gui/$UID" ~/Library/LaunchAgents/com.djbclark.cswap-auto.plist
```

## Cross-vendor pacing

The operator relayed a Gemini-authored "system instruction" for aggressive
cross-vendor quota pacing. I fact-checked it against `aiuse`'s real schema
and public vendor docs, then had the operator run a cross-verification
prompt past Grok, ChatGPT, and Claude Opus 5 independently — all three
converged. Full corrected per-vendor table (OpenCode Go real numbers,
Codex's lack of a stable ratio, Claude's fixed-calendar weekly reset, etc.)
lives in `[[reference_ai_vendor_quota_structures]]` (site-private memory).
The load-bearing corrections, distilled:

**Financial directive — zero prepaid spend without asking.** Never route
work to an account where `aiuse`'s `billing_kind` is `prepaid_balance`
(OpenRouter, DeepSeek, opencode-zen — this field and these exact tags are
real, verified live) without the operator's explicit authorization. If every
`subscription_window` account is exhausted or locked out, halt and ask —
never fall through to a prepaid account automatically.

**Correction (2026-08-01, later same day): a `kind: "burn"` field DOES
exist — I was checking the wrong part of the output.** `aiuse --json`'s
top-level `accounts[]` array only has `billing_kind` (no burn/conserve
field), but the separate top-level `alerts[]` array is exactly this: each
entry has `kind` = `"burn"` | `"conserve"` | `"prepaid"`, computed by a real
pace algorithm (`src/aiuse/analysis/pace.py` + `use_or_lose.py` in
`~/src/aiuse`) that derives projected waste/exhaustion from live
remaining%, elapsed time, and (when available) a learned burn rate — never
from an assumed fixed ratio. **Use `alerts[]` entries with `kind: "burn"`
as the routing signal, not a hand-derived "high remaining_percent" — the
tool already does this better than reinventing it.** `kind: "conserve"`
means the opposite (pace yourself, you're burning faster than the window
warrants) — useful as a "don't push more work here" signal. `kind:
"prepaid"` entries are informational only (large idle prepaid balance),
never suggestion-eligible — matches the financial directive above.

**Don't derive remaining quota from an assumed fixed ratio between a short
window and a long one, or from elapsed-time math.** This looked plausible
for Codex (5h ≈ 12% of weekly → ~42h to exhaust a week) but three
independent fact-checks found no OpenAI primary source for that ratio, and
real-world reports of a single heavy task draining a large fraction of a
week's Codex quota in a few hours directly contradict it — Codex metering is
token-credit-based (up to ~9x spread in credits-per-message within one
model), not a stable time split. Same caution applies to Claude and
Antigravity's 5h+weekly nesting (real, but no published ratio) and to Grok
(no verifiable structure at all — check the live account view only).
**OpenCode Go is the one exception**: its real caps are $12/5h, $30/week,
$60/month (not the originally-relayed $4/$10/$20 — that was wrong), and the
40%/50% ratios genuinely do hold against those real numbers. Cursor,
GitHub Copilot, and OpenRouter aren't nested 5h+weekly systems at all —
monthly-pool or pure-balance respectively; don't force them into that
mental model.

**Watch for soft ceilings.** Claude usage credits, Codex credits, and
OpenCode Go's "Use balance" toggle all mean a headline limit may not
actually stop work if overage is enabled — it can silently start spending
real money instead. This is exactly why ["Workflow per unit"](../SKILL.md#workflow-per-unit) step 2 in SKILL.md
already says never to select a usage-credits-backed model without asking
first; the same caution extends to any account with an overage/credit
fallback, not just model selection.
