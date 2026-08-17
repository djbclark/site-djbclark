# Requirements, working style, and what is being thrown away

## The operator's hard requirements

1. **Actively maintained OSS with a real community.** Commits in the last
   ~60 days, multiple real (non-bot) contributors, real releases. A clever
   repo with one author and no commits since spring is a NON-answer. This is
   the requirement that killed most candidates.
2. **Subscription quota, not metered API billing.** Flat-rate vendor
   subscriptions with ROLLING USAGE WINDOWS (Claude 5-hour and 7-day caps).
   Running out of quota mid-loop is as real a failure as running out of
   context, and **a fresh session does NOT fix a capped account.** Tools that
   assume pay-per-token API keys and just retry are a poor fit.
3. **Terminal-native, self-hosted, local-first.** macOS. Not a SaaS that
   wants his source code.
4. **Multi-vendor.** Installed and in rotation: Claude Code, Codex, Gemini
   CLI, Grok, Cursor CLI, OpenCode. He rotates between them for quota
   reasons.
5. **Unattended execution, human-gated integration.** No per-action approval
   prompts. Work lands as PRs he reviews. Safety comes from tightly-scoped
   task definitions, not from a human watching every tool call.
6. **Multi-repo**, git worktrees for isolation of parallel work.
7. **Verifiability.** He distrusts agent self-reports. See below — this is
   the most important thing about him.

## Working style — read this before recommending anything

This operator's culture is adversarial verification. Representative behaviour
from his current project, in his own session log:

- Fixes are **reproduced before being written and mutation-verified after
  being committed**. He will neuter a check to confirm the test suite goes
  red; if it stays green, the check was never real.
- He caught himself claiming "eight mutations, all caught" when the *set* was
  incomplete, and recorded the correction rather than leaving it to be
  rediscovered.
- He commissioned three adversarial reviews of his own work and all three
  found real defects — which he describes as the session's main result.
- He found that an unapplied mutation and a surviving check produce
  **identical output**, and now asserts that a mutation anchor matched
  exactly once before trusting the result.
- He was burned twice by orchestrator status reporting: a clean
  `COMPLETED` on work that picked the WRONG task, and an `INTERRUPTED` /
  `0/1 completed` on work that had actually finished correctly.

**Implication:** do not recommend anything on the strength of its README, its
status UI, or its exit code. He will check. Recommendations should come with
the evidence and with an explicit statement of what was NOT verified.

He also responds well to being told he is wrong, and pushed back correctly
twice during the prior session — once on an unread script being praised, once
on being told to stay in an ecosystem he had said he was not attached to.

## What is being thrown away

The current architecture, which he has decided is wrong:

```
orc-meta   (LLM watchdog)      -> dies of context
orc        (LLM orchestrator)  -> dies of context
orc_watchdog.py (a PROGRAM)    -> immortal, but nohup'd INSIDE orc-meta's pane
```

The layering is inverted: the only immortal component is subordinate to a
mortal one. His proposed fix was `orc-meta-1`/`orc-meta-2` ping-ponging,
which he correctly felt was ugly — it is an infinite regress.

The manual ritual being replaced:
`/handoff` -> `/quit` -> `claude` -> `/baton` -> `continue` -> work ->
context fills -> repeat. This is a hand-rolled Ralph loop with a human as
the `while` and an LLM writing an expensive prose state file.

### Defects found in `~/.claude/hooks/orc-watchdog/orc_watchdog.py`

336 lines, single file, **untracked by any git repo**, last touched Aug 5,
log went quiet Aug 13. Documented here so the knowledge survives the script:

- **It probably was not measuring the agent it restarts.**
  `find_session_jsonl()` with no `--session-id` returns the most recently
  modified transcript across ALL of `~/.claude/projects` — which in a live
  multi-agent setup is whichever agent last wrote a turn. The caller
  (`/orc-meta`) never passes `--session-id`. The trigger signal was not
  bound to the restart target.
- **Its quota check contradicts the operator's own documented rule.** It
  calls `aiuse --json` and keys on `kind: "conserve"`, while both his
  auto-memory and the `/orc-meta` command say explicitly to use `cswap`, not
  `aiuse`, because the conserve alert is a pace projection.
- **The restart path is the known-flaky one, unguarded.** It drives
  `/quit` -> `agent start` -> `/orc` -> `continue` through
  `herdr agent prompt`, which his own notes document as intermittently
  leaving text unsubmitted in the composer (herdrdev/herdr#1878), with
  `herdr agent send-keys <name> enter` as the workaround. The watchdog does
  not have that workaround.
- **It only restarts when the agent is `idle`/`done`** — so a busy, bloated
  agent, the actual case, never got restarted.

**Do not port or replace this script.** In the target architecture nothing
long-lived is an LLM, so there is nothing to watch. Its job disappears.

## The ONE thing to keep

His independent verification protocol. After any run, do not trust the
orchestrator's status in either direction; check:

- `bd show <task-id>` — closed, with a real close reason that describes what
  actually happened (not a placeholder)?
- `git status --short` in the task workspace — clean if research-only, or a
  real diff matching what the task asked for?
- If the deliverable was a GitHub comment/issue/PR: `gh issue view` /
  `gh pr view` directly — does it exist, right content, right state?

Both Grok and Cursor independently identified this exact thing as a gap
nobody has shipped:

> A judge that diffs the tracker, the git range, and the test log, and
> **refuses** to mark work done if those three disagree — without asking the
> same agent "did you finish?"

He has it as a manual protocol. Nobody has it as software. Designing it is
one of your tasks (see `03-open-questions.md`).

## Environment facts

- macOS. Terminal multiplexer in use: **Herdr** (`herdr` CLI, agent-aware,
  background server owns PTYs, panes survive detach).
- **cswap** manages two Claude accounts (`djbclark@mit.edu`,
  `djbclark@gmail.com`). **Automatic switching is OFF since 2026-08-15** —
  the launchd job is disabled because `cswap auto` picks on 5-hour headroom
  alone and is blind to per-model entitlement; it silently moved the machine
  to an account with no Fable. Nothing rotates on its own. Never assume a
  switch will happen.
- Only `djbclark@gmail.com` has Fable. `cswap list` percentages are percent
  **USED**. A Fable run bills BOTH the Fable meter and the 5h meter, and the
  5h is the binding constraint (measured: a 211k-token Fable run moved 5h
  56%->87% while Fable moved only 5%->10%).
- Currently installed and relevant: `ralph-tui` (vendored at
  `~/src/vendor/ralph-tui`, and **stale upstream — last commit 2026-05-13**),
  `beads`/`bd`, Herdr, and a set of skills under `~/.claude/skills/`.
- Prepaid-balance agents (`deepseek`, `opencode-zen`, `openrouter`) are gated
  behind `RALPH_TUI_ALLOW_PREPAID=1` and spend real money. **Never enable
  without asking, every single time.**

## His existing safety doctrine (worth preserving in any new stack)

> **Task scope is the real safety control, not a human approval gate.**
> `autoCommit` stays false and controllers run autonomously; the thing that
> keeps a run safe is a tightly-scoped task description the agent reads and
> follows — not someone watching every action. Task authoring quality *is*
> the safety mechanism.

He arrived at this before the field converged on it. Any recommended stack
should encode it rather than replace it.

A related hard-won lesson: **a prose-sequenced task description with a
fallback step is an invitation to skip the harder intermediate step.** An
agent given "try A; if that fails, do B; then C" did A, saw it fail, and
jumped to C. Prefer one concrete command over multi-step prose the agent has
to interpret and sequence itself.
