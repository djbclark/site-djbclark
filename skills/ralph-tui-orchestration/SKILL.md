---
name: ralph-tui-orchestration
description: Operate the Ralph TUI + Beads multi-repo controller system (djbclark/ops-djbclark umbrella) — seeding tasks, going live with a controller for the first time, and the safety discipline that caught a real near-miss. Use when asked to run/seed/check a Ralph controller for stayturgid, site-djbclark, site-private, or Shizuku, or when setting up Ralph TUI for a new project.
---

# Ralph TUI orchestration

Built 2026-08-02 from the session that migrated djbclark's multi-agent task
orchestration from Herdr to Ralph TUI + Beads (`bd`) + Beads Viewer (`bv`),
including a real near-miss (an agent almost deleted a branch in an
explicitly hands-off checkout) caught and fixed the same day.

**The technical reference lives in `djbclark/ops-djbclark`'s
`docs/ralph-tui-setup-guide.md`** — read that first for exact paths, epic
IDs, config schema, and the full incident history. This skill is the
behavioral layer on top: what to actually *do* when seeding or running a
controller.

## Available agent vendors (as of 2026-08-02)

`~/.config/ralph-tui/config.toml` is the global agent config, applies to
every controller regardless of that repo's own `.ralph-tui/config.toml`.
Currently configured:

- **Monthly-subscription agents (freely usable)**: `claude`, `codex`,
  `github-copilot`, `pi`, `cursor` (fixed 2026-08-02, was hitting the
  wrong binary via a PATH collision), `antigravity` (custom built-in
  plugin, wraps `agy` — the built-in `gemini` plugin is dead for this
  account, don't use it), `grok` (custom built-in plugin). `opencode-go`
  exists but is currently disabled — see its own comment block in
  config.toml for why (a real, tracked upstream bug, not fixable locally).
- **Prepaid-balance agents (`deepseek`, `opencode-zen`, `openrouter`) —
  gated, never usable without asking first, every single time.** These
  spend real money, not included subscription quota. They're wired
  through `~/.local/bin/opencode-ralph-tui-{deepseek,zen,openrouter}`
  wrapper scripts that refuse to run unless `RALPH_TUI_ALLOW_PREPAID=1` is
  set in the environment of the process that spawns them — verified this
  actually blocks (tested with the flag unset: clean error, exit 99, zero
  API calls made, confirmed via `ralph-tui doctor --agent deepseek`
  reporting the gate message instead of a real request). **Never set that
  flag on the operator's behalf** — ask first, every time, no matter how
  routine the task seems; prior approval for one task does not carry over
  to the next. This mirrors the existing "never select a usage-credits-
  backed model without asking" rule in the `herdr-orchestration` skill —
  same principle, applied to Ralph TUI's own agent selection instead of
  Herdr's.

## The one rule everything else follows from

**Task scope is the real safety control, not a human approval gate.**
`autoCommit` stays `false` and controllers run autonomously; the thing
that keeps a run safe is a tightly-scoped task description the agent
reads and follows — not someone watching every action. This means task
authoring quality *is* the safety mechanism. Write every task like it's
the only thing standing between the agent and doing something you didn't
intend, because it is.

## Before any first-time live run for a controller

1. **Epic-based scoping only — never rely on labels for task selection.**
   `bv --robot-next`/`--robot-triage` silently ignore `--label` (confirmed
   broken, filed as
   [subsy/ralph-tui#401](https://github.com/subsy/ralph-tui/issues/401)).
   Every controller's `.ralph-tui/config.toml` must set
   `trackers.options.epicId` to that repo's controller epic
   (`ops-djbclark-cr0`/`-6ub`/`-6qp`/`-bk7` for
   stayturgid/site-djbclark/site-private/Shizuku as of 2026-08-02 — check
   the guide for current IDs). Labels stay on tasks as human-readable
   metadata only.
2. **Every task must carry its own scope constraints in its own
   description**, not just in your memory of what it should do. Explicitly
   state: what NOT to touch (name specific files/dirs/checkouts if
   relevant), whether code changes are allowed at all, what the deliverable
   is (a comment? which issue?), and whether it may close anything. A task
   seeded without this is the actual attack surface — an agent with real
   tool access will use it if the task doesn't say not to.
3. **If an epic could have more than one ready task and one of them must
   not be picked** (e.g. a permanently hands-off tracking task sitting
   under the same epic as a real one), don't trust `bv`'s scoring to land
   on the right one. Temporarily defer the one that must not be picked
   (`bd update <id> --defer <date>` or equivalent), confirm only the
   intended task shows as ready, run the controller, then **restore the
   deferred task afterward** — verify it's back to its normal state, not
   left in limbo.
4. **Watch the first iteration and verify the picked task ID yourself**
   against `bd list --parent <epicId>` (or `bd show <task-id>` — confirm
   its `PARENT` line matches) *before* letting the agent proceed past task
   selection. This is not optional the first time a controller goes live,
   or after any change to how it's invoked. This exact check is what
   caught the near-miss — a clean exit code would have looked fine
   without it.

## After any run, live or otherwise

**Verify the real outcome directly — don't trust Ralph's own status
report in either direction.** Two confirmed failure modes, both real,
both hit in the same session:

- **False positive**: a clean exit / `COMPLETED` status does not by
  itself prove the agent did the right thing (it can mean "picked the
  wrong task and completed *that* cleanly").
- **False negative**: Ralph's own session report can say `Status:
  INTERRUPTED` / `Tasks: 0/1 completed` for a run that actually finished
  correctly — the internal `iterations[].status` can say `"completed"`
  while the top-level summary disagrees. Confirmed 2026-08-02 on a real
  run (site-private controller); the actual work (`bd` bead closed with a
  real close reason, real GitHub comment posted, clean git tree) was
  fully correct despite the alarming-looking status.

The only reliable check is independent, every time:
- `bd show <task-id>` — is it closed, with a real `close_reason` that
  actually describes what happened (not a placeholder)?
- `git status --short` in the controller's task workspace — clean if the
  task was research-only, or a real diff matching what the task asked for
  if it wasn't.
- If the task's deliverable was a GitHub comment/issue/PR: `gh issue
  view`/`gh pr view` directly — does the comment exist, with the right
  timestamp and content, on the right issue, in the right state (still
  open if the task said not to close it)?

## autoCommit=false's built-in prompt tells agents to never commit — fixed globally (2026-08-02)

Ralph TUI's embedded default prompt template (beads-bv tracker; likely the
same for other trackers, not yet checked) has a workflow step that reads,
verbatim, whenever `autoCommit=false`: **"Do NOT create git commits. Leave
all changes uncommitted for manual review."** Every controller on this
machine runs with `autoCommit=false` as a standing choice (see "The one
rule everything else follows from" above) — so that blanket instruction
directly contradicts any task whose own description asks for a commit,
push, or PR as its deliverable.

Confirmed real: a Grok-run task (`ops-djbclark-bk7.4`) whose description
explicitly said "commit your changes... push... open a PR" did real,
correct work and then left it all uncommitted, closing the bead with a
close reason citing "Ralph no-commit policy." **The agent did nothing
wrong — it followed the template's literal instruction over the task's
own text**, which is a reasonable thing for it to do when the two
conflict. This is not an agent-competence problem, it's a config/prompt
problem, so don't just add "please actually commit" to future task
descriptions and hope — that's re-fighting the same conflict every time.

**Fixed globally**: `~/.config/ralph-tui/templates/beads-bv.hbs` overrides
the embedded default for every controller on this machine (template
precedence: `--prompt` > project `.ralph-tui/templates/` > this global
file > embedded default — confirmed via `ralph-tui template show
--tracker beads-bv`). The override's step 8 makes the task description
the authority on git actions instead of asserting a blanket rule — commit
exactly what the task asks for, leave uncommitted only if the task says
nothing about it or says not to. If you scaffold a new tracker type (not
just beads-bv) or a fresh machine, check whether its embedded template has
the same hard-coded instruction and copy this pattern before trusting a
commit/push/PR deliverable to actually land.

Regardless of this fix, still independently verify per the section below
— a template fix reduces how often this happens, it doesn't replace
checking `git status`/`git log` against what the task actually asked for.

## Where controllers run

Every controller runs from a dedicated `~/src/ops-worktrees/ralph-<repo>/<repo>`
task workspace on its own `ralph/<repo>` branch — **never**
`main/<repo>`. `main/<repo>` is the shared reference checkout; the moment
`parallel.mode` is enabled, Ralph forces `autoCommit: true` per worker,
and running from `main/` would put that directly on `master` with no
PR/review step. This was a real bug in the initial build, caught and
fixed before parallel mode was ever turned on — see the guide's §2 for
the full story. Don't reintroduce it if scaffolding a new repo into this
system.

## Seeding a good first validation task

The pattern that worked cleanly 4/4 times: pick a real, existing, small
piece of backlog (an open GitHub issue is ideal — gives a natural
deliverable target and a natural "don't close it" boundary), scope it as
**research/recommendation only, no code changes, no destructive actions**,
and require the finding be posted somewhere checkable (a GitHub comment,
or a `bd comment` on the task itself if there's no corresponding issue
yet). This is genuinely useful output, not busywork, and it's the safest
possible shape for a controller's first live run in a repo.

## External actions (GitHub comments/issues/PRs)

No separate review gate beyond `autoCommit` — decided 2026-08-02. If a
task's own scope calls for posting somewhere, a well-scoped controller
does it autonomously, same philosophy as `autoCommit` itself. This makes
task authoring (point 2 above) the only thing standing between a
controller and an external, visible, permanent action — don't get casual
about scoping a task just because local commits feel like the only thing
that matters.

## Review-gate tasks can get short-circuited (added 2026-08-02)

A real case: a task instructed a controller to (1) try `@coderabbitai
review` directly on a PR the operator doesn't own (CodeRabbit isn't
installed there, so this predictably gets no response), (2) as the
actual fix, open a throwaway twin PR in a repo the operator *does* own
to get a real CodeRabbit review there and apply the findings back, then
(3) do an independent frontier-model review as a second signal. What
actually happened: the agent tried step 1, saw no response, and jumped
straight to step 3 — skipping step 2 entirely. The deliverable (bead
closed, a real frontier-model review comment posted on the PR) looked
satisfied, and the "verify independently" check above (`bd show`, `gh pr
view`) confirmed a real review *was* posted — so this specific gap
wasn't caught by that check, only by manually re-reading whether every
described step actually happened, not just whether *a* deliverable
existed matching the bead's close reason.

**Lesson: a prose-sequenced task description with a fallback step is an
invitation to skip the harder intermediate step once the fallback looks
available.** If an intermediate step is load-bearing (not optional, not
just a nice-to-have), say so explicitly — "step 2 is not optional even
if step 1 fails, do not skip to step 3" — and prefer a single concrete
command over multi-step prose the agent has to interpret and sequence
itself, since a paragraph can be partially skipped in a way a single
command invocation can't.

**Fixed 2026-08-02**: the twin-PR mechanism is now a first-class
`crossfork` mode in `coderabbit-feeder` (`djbclark/coderabbit-feeder`,
split from `~/.config/coderabbit-feeder/` the same day), verified live
end-to-end. A review-gate task for a PR on a repo the operator doesn't
own should now just point at one command — see the `coderabbit-feeder`
skill for the current usage — instead of spelling out twin-PR steps by
hand in prose. The incident above stays as the concrete example of *why*
prose-sequenced steps are risky; the fix itself lives in that skill, not
here.

## Orchestrating a controller through Herdr

If you're driving a controller from a separate orchestrator session via
Herdr (see the `herdr-orchestration` skill for the general mechanics),
expect `herdr agent prompt` to intermittently leave text sitting
unsubmitted in the composer (`agent_prompt_stalled`, or the text visibly
sitting after a `[Pasted text #N]` placeholder) — this is a confirmed
upstream Herdr bug
([herdrdev/herdr#1878](https://github.com/herdrdev/herdr/issues/1878),
fixed on the preview channel, not yet in a stable release as of
2026-08-02). Workaround: `herdr agent send-keys <name> enter` immediately
after a stall, then re-check status. Don't mistake old unsubmitted
composer text for something mysterious — check `herdr agent read` before
assuming anything more concerning is going on.
