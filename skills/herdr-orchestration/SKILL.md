---
name: herdr-orchestration
description: Drive a multi-agent handoff chain (e.g. a plan file listing sequential units of work for different AI tools/models) directly via Herdr instead of human-relayed clipboard handoffs. Use when the user asks to "continue handling handoffs yourself", "orchestrate the next agent", or references an orchestration plan file with a self-perpetuation protocol meant for human relay. Only the main session orchestrates — spawned sub-agents never launch further agents themselves.
---

# Herdr multi-agent orchestration

Built 2026-07-28 from a real session driving the stayturgid ops suite's
human-relayed agent chain directly via Herdr. Use this whenever you (the main
Claude Code session) are asked to take over spawning and monitoring a
sequence of agent units yourself, rather than handing a prompt to the human
to paste into a fresh tool session.

**Load the `herdr` skill first** for the underlying CLI primitives (panes,
tabs, `agent start`/`prompt`/`wait`/`read`). This skill is the orchestration
layer on top of that.

## Reference files (read when needed)

- [references/orc-restart-watchdog.md](references/orc-restart-watchdog.md) — read when orc's context is growing large, or when setting up or running the orc-meta watchdog.
- [references/quota-pacing.md](references/quota-pacing.md) — read before routing work to a model or account, before any Fable launch, and before any `cswap` switch.
- [references/pane-layout.md](references/pane-layout.md) — read before arranging, resizing, swapping or reading panes (Workflow per unit step 3).
- [references/yolo-mode-by-tool.md](references/yolo-mode-by-tool.md) — read when starting a sub-agent (Workflow per unit step 4), and when one looks stalled rather than slow.
- [references/herdr-cli-gotchas.md](references/herdr-cli-gotchas.md) — read when scripting herdr calls headlessly (new workspaces, `send-keys`, parsing output, `/exit` and resume).
- [references/anti-patterns.md](references/anti-patterns.md) — read before writing a sub-agent prompt, trusting its report, merging its PR, or bulk-closing panes.

## Core rule: only the orchestrator orchestrates

You (the main session) are the only thing that decides what happens next and
launches it. A sub-agent's own task prompt must never instruct it to use
Herdr to spawn its successor itself — even a plan file's own built-in
self-perpetuation protocol (check off a row, copy a prompt to the clipboard,
print a status line) is fine to leave in a sub-agent's instructions, since
that's just clipboard prep, not a herdr call — but never write "use herdr to
start Agent N+1" into a sub-agent's prompt. When a sub-agent finishes, you
read its output, verify it, decide the next unit and model yourself, and
launch it yourself.

## Herdr pane or ACP call? (2026-10-03)

Not every delegation needs a pane. For a **one-shot, headless unit** (a
review, a contained fix, a research question) sent to an agent that speaks
the Agent Client Protocol, use `~/ops/site-private/bin/acp-run <agent> -C
<dir> -f <brief> --model <m> --perm scoped:<owned paths>` instead of starting a
Herdr pane and prompting it. You get the final message on stdout, a summary
line (tool calls, permissions allowed/denied, tokens, cost), a full event log,
per-call edit scoping, and a clean timeout with `session/cancel`, with none of
the pane-busy races, unsubmitted-prompt resends or yolo aliases below. The
agent list, flags and current status are in the `model-routing` skill.

Herdr is still the right tool when:

1. the operator wants to **watch** the agent work, or step in mid-run;
2. the unit is **interactive or long-lived**: several prompts, corrections in
   the moment, a session handoff (the next section);
3. the target has **no working ACP route** (zcode, crush, muse; agy until its ACP server is logged in) and
   needs an interactive pane rather than its headless recipe;
4. it is **Hermes's live TUI pane**, i.e. you want the conversation Hermes is
   already having. For a fresh one-shot request to Hermes, `acp-run hermes`
   works.

Everything else in this skill (the orchestrator-only rule, verifying the
self-report, units ending in a merged PR) applies to an ACP-dispatched unit
too. `acp-run` exiting 0 means the agent ended its turn, not that the work is
right.

## Session-to-session handoffs: prefer live orchestration over clipboard relay

**If `HERDR_ENV=1` and the `herdr` binary responds, don't hand off via
`pbcopy` + "go paste this into a fresh window."** Spawn and configure the
next session yourself: split a pane, `herdr agent start <name> --kind claude
-- --model <alias> --effort <level>`, then `herdr agent prompt <name>
"<handoff text>" --wait`. This isn't just tidier — it's more reliable. A
live Herdr pane can be corrected in the moment (see the `[Pasted text #1]`
resend-Enter step in the base `herdr` skill), monitored for a wrong turn
before it compounds, and re-prompted immediately with a precise correction.
A clipboard-pasted handoff into a manually-opened window has none of that:
if the new session misreads the handoff, the operator has to notice, relay
the correction back by hand, and round-trips get slow. Only fall back to
a clipboard/`pbcopy` handoff when Herdr genuinely isn't available (a
separate machine, a human-only channel, or the operator explicitly wants a
manually-started window) — check the environment first rather than
defaulting to clipboard out of habit.

**A real failure this surfaced, worth designing every handoff prompt
around:** a handoff prompt referenced a Claude Code task-tracking entry as
"task #46." The fresh session that received it via clipboard tried to look
this up with shell commands, found nothing (task state isn't a file it can
`grep` for — it's backed by the `TaskList`/`TaskGet`/`TaskUpdate`/
`TaskCreate` tool calls, which may be deferred and need `ToolSearch` with
`select:TaskList,TaskGet,TaskUpdate,TaskCreate` before they're callable),
and confidently reported a plausible-sounding but false conclusion ("that
tool is per-session and doesn't persist") instead of recognizing its own
lookup had failed. The task was still there the entire time, unchanged,
one tool call away. **Any handoff prompt that references harness-internal
state (task IDs, memory files, session IDs) must say explicitly which tool
retrieves it**, not just cite a bare ID — and should include a snapshot of
the current content inline as a fallback, so a failed live lookup doesn't
strand the receiving session with nothing. More generally: give absolute
filesystem paths (not `~`), full URLs (not shorthand like `repo#N`), and
spell out tool-vs-shell-vs-file distinctions for anything that isn't
obviously one or the other — a fresh session has no assumed familiarity
with what's a tool call, what's a real file, and what's ephemeral session
state, and will guess if you don't say.

### Durable file backing (Tier 1/Tier 2 system)

Live orchestration now rides on the session-handoff file system (spec:
site-private `docs/session-handoff-compaction-spec.md`):

- BEFORE spawning or prompting the next session, the owning session
  updates Tier 1 (`session-handoff` skill) — and writes a Tier 2 doc
  (`handoff` skill) if the work is substantial enough to deserve deep
  recovery.
- The spawn prompt is a **bootstrap packet**, not a context dump:
  1. repo + absolute workspace path
  2. one-line objective
  3. absolute Tier 1 path
     (`~/.local/state/handoffs/<repo>/<task>/SESSION_LOG.md`)
  4. instruction: "Report whether that file exists and whether its
     head_sha matches `git rev-parse HEAD` before doing anything else."
  5. a 2–3 line critical-fallback summary in case the path is wrong.
- Sub-agents never write Tier 1/Tier 2; they end by returning a
  completion report (what changed, commands run, blockers) and the
  owner folds it into Tier 1.

## Orchestrator tab identity and self-closure defense

**The orchestrator's own herdr tab must be named `orc`.** At the start of any
orchestration session, check your own tab's label:

```bash
herdr tab list --workspace "$HERDR_WORKSPACE_ID" | grep "$HERDR_TAB_ID"
```

If it isn't already `orc`, rename it yourself before doing anything else:

```bash
herdr tab rename "$HERDR_TAB_ID" orc
```

This exists so the orchestrator's own seat is unmistakable at a glance (and
identifiable programmatically) across a session with a dozen-plus sub-agent
tabs — never rely on remembering a raw tab ID or "whichever tab I started
in."

**A wrapper at `~/.herdr-wrapper/bin/herdr` (earlier in `PATH` than the real
binary at `~/.local/bin/herdr`) refuses `pane close` / `tab close` / `workspace
close` whenever the target ID equals this pane's own `$HERDR_PANE_ID` /
`$HERDR_TAB_ID` / `$HERDR_WORKSPACE_ID`.** It exists precisely because a real
orchestrator instance died this way: a cleanup loop closing a batch of
"done" tabs swept up its own tab ID along with the rest, killing its own
pane mid-loop (confirmed in `~/.config/herdr/herdr-server.log` — a
`tab.close` call took down 8 panes at once, immediately followed by four
consecutive `tab.close` calls erroring out because the calling process's own
connection was already gone). The wrapper is transparent for every other
command; if a self-close is ever genuinely intended, bypass it with
`HERDR_WRAPPER_FORCE=1 herdr <group> close <id>`. Verify it's present and
live before doing bulk closes in any new session:

```bash
which -a herdr   # expect ~/.herdr-wrapper/bin/herdr first, ~/.local/bin/herdr (the real binary) second
```

(Moved 2026-08-01 during the Homebrew→direct-install/preview-channel
migration — the real binary previously lived at `~/.local/bin/herdr`, which
is also the direct installer's default install path, so an `herdr update` or
reinstall could silently overwrite the wrapper. Now the real binary lives at
that default path on purpose, and the wrapper lives in its own directory
that no installer will ever target. See
[[project_herdr_homebrew_to_direct_preview_migration]] for the incident this
caught mid-migration.)

If it's missing (fresh machine, PATH tampered with), do not proceed with any
bulk tab/pane closing until you've restored it or are manually triple-checking
every ID against `$HERDR_TAB_ID`/`$HERDR_PANE_ID` by hand.

**Recovery, if a self-closure ever happens anyway:** Claude Code sessions
persist to disk by session ID regardless of what happens to the herdr pane
that hosted them. Find the dead orchestrator's session file (it stops
updating at the moment of death, so `find ~/.claude/projects/-Users-djbclark
-maxdepth 1 -name "*.jsonl" -newermt "<today>"` sorted by mtime narrows it
down fast, or check a herdr-orchestration project memory for a recorded
`originSessionId`), then resume it in a fresh pane — **don't overwrite your
current live pane** — so you can inspect what it was doing before deciding
how to proceed:

```bash
herdr pane split --current --direction right --cwd "$PWD" --no-focus
herdr agent start <name> --kind claude --pane <new-pane-id> -- --resume <session-id>
```

This actually worked live on 2026-08-01: the resumed session came back with
full context intact, sitting right where it left off.

**If the pane that resumed it ends up sharing the `orc` tab with the live
session that did the recovery** (this will usually happen, since you split
a sibling pane rather than overwriting your own), don't leave that
ambiguous — nothing auto-detects which one is "primary" and self-renames
(there is no such mechanism at all; labels only change via explicit
`herdr tab rename` / `herdr pane rename` / `herdr agent rename`). Decide
explicitly and rename both **agent handles** (distinct from the tab label,
which stays `orc` either way): the resumed session with real task
continuity becomes agent `orc`, the recovery/incident session becomes
something clearly secondary like `meta`. `herdr agent rename <target>
<name>` — target can be the live agent's current name or its pane ID.

## Workflow per unit

0. **Before starting any unit, make sure a roster/plan file actually
   exists for this project — don't assume the `/orc` bootstrap already
   created one.** The `/orc` command's step 3 creates the roster/pointer
   pair when it *starts* with a task to orchestrate, but a live orc
   picking up new work from an ordinary follow-up prompt after it's
   already gone idle — the normal way most units actually start in
   practice — doesn't re-run that bootstrap step. Real gap hit 2026-08-05:
   an orc session did several real units (a version bump, an issue close,
   a credential rotation) purely from conversational prompts with no
   roster file ever created, and only got one after the operator/orc-meta
   noticed and asked for it explicitly. Check for it yourself instead of
   waiting to be asked:
   ```bash
   # same key/pointer resolution /orc step 3 and orc-meta use
   test -s "$ORC_POINTER" && test -s "$(cat "$ORC_POINTER")"
   ```
   If that's false, create the file now (even a short one covering
   "what's done so far today" plus "what's in flight") and write the
   pointer, exactly like `/orc` step 3 describes for a fresh start. This
   file is what a restarted orc, orc-meta, and the mechanical watchdog all
   read to reconcile — it isn't optional bookkeeping, it's the only
   restart-survivable state that exists outside a live session's own
   context.
1. **Read the plan/roster row** for the next unit. Note what it suggests for
   vendor/model/effort — treat this as a hint, not a decision.
   - **"Update X" can mean more than one artifact — scope it fully before
     declaring done.** A real miss (2026-08-05, Collie 0.24.0 bump): the
     originating issue said "update the workstation," but the unit as
     executed only bumped a CI-tracking/detection-baseline pin in a repo
     (site-djbclark's release-monitor workflow) — a different thing from
     the actual running install the issue meant (`~/.collie`, a separate
     git checkout + launchd daemon, still stuck on the old version after
     the PR merged). The PR-and-merge steps below (9-11) all looked clean
     because the CI-pin half genuinely was done correctly; nothing caught
     that it was only half the task until the operator asked directly why
     the old version was still showing up. Before checking a unit off,
     re-read the original issue/request's exact wording for words like
     "workstation," "install," "running," "deployed," "the actual X" —
     those point at a live artifact distinct from any repo/CI
     representation of the same version number, and both may need
     updating separately.
2. **Check real quota and real model availability before deciding.**
   - `aiuse --json` for cswap-tracked accounts (5-hour and weekly windows).
     Swap accounts (`cswap`) only when actually low, never preemptively —
     asked to "play with syntax" is fine, don't actually swap as a test.
   - Model names get renamed/retired. A plan written days ago may reference a
     model no longer offered (e.g. "Opus" superseded by "Fable 5" in one
     session's `/model` picker). Open the target tool's own model picker and
     see what's *actually* there before committing to a name.
   - **Never select a usage-credits-backed model without asking the operator
     first** — even if credits are available and enabled. If credits are
     found *disabled*, treat that as a deliberate spend-control setting; do
     not re-enable it yourself. Ask, don't assume.
   - Pick effort/reasoning level based on the task's actual complexity, not
     just what the plan guessed — a multi-language (e.g. Kotlin + DSL +
     Python), high-stakes, or "critical path" unit justifies the highest
     effort tier available; a contained single-file fix doesn't need it.
3. **Arrange panes before launching** (see [references/pane-layout.md](references/pane-layout.md)).
4. **Start the agent, then IMMEDIATELY set it to auto-approve/yolo mode**
   before sending any task content:
   - `claude` kind: global default is `permissions.defaultMode:
     "bypassPermissions"` in `~/.claude/settings.json` (set once, applies to
     all future sessions — see [references/yolo-mode-by-tool.md](references/yolo-mode-by-tool.md)). If a session was already started
     before this was set, `shift+tab` *may* cycle the live mode, but this was
     unreliable for an in-progress Claude Code pane in practice — don't rely
     on it once the session has already produced output; prefer having the
     setting active before start, or ask the operator to flip it if a
     mid-session pane is stuck.
   - `agy` (Antigravity) and other CLI kinds: see the alias table in [references/yolo-mode-by-tool.md](references/yolo-mode-by-tool.md) —
     these were reliable via shell alias since Herdr spawns the bare command
     name and shell aliases expand for interactive panes.
   - The only reason to let a sub-agent stop is if it decides on its own to
     ask for genuine human input (a real judgment call, a destructive action,
     something it's honestly unsure about) — never because of routine
     read-only tool-permission friction.
5. **Send the full task prompt** (`herdr agent prompt <name> "<prompt>"
   --wait --timeout <ms>`). Long tasks legitimately exceed the wait timeout —
   a `timeout` error from the tool just means keep checking with `herdr agent
   get`/`read`, it does not mean the agent failed.
   - **Prompts — of any length, not just large ones — can land unsubmitted,
     sitting visibly at the prompt line (sometimes as a `[Pasted text #1]`
     placeholder, sometimes as the literal text).** Confirmed 2026-08-02: this
     is a real, intermittent **Herdr** bug, not a Claude Code paste-UX
     requirement as earlier assumed —
     [herdrdev/herdr#1878](https://github.com/herdrdev/herdr/issues/1878)
     and [#2063](https://github.com/herdrdev/herdr/issues/2063), a race
     between the text arriving and the Enter actually starting a turn,
     hit 3/6 times in one real session per the upstream reporter's own
     captured trial. Fixed on Herdr's preview channel, not yet in a stable
     release. If `agent prompt --wait` comes back with `agent_prompt_stalled`
     (or `timeout` with `state_change_seq` unchanged), check `herdr agent
     read <name> --source visible` — if your text is sitting at the prompt
     line unsubmitted, send `herdr agent send-keys <name> enter` to actually
     submit it. This can recur on every single prompt in a long orchestration
     session — don't be surprised if you need this workaround repeatedly,
     not just once. See `~/.claude/skills/ralph-tui-orchestration/SKILL.md`
     for a worked example of orchestrating a Ralph controller through this.
6. **A fresh sub-agent being skeptical of the framing is a good sign, not a
   problem.** A new session with no context of "why is a plan file telling me
   I'm Agent N of a chain" should verify the premises (read the plan file,
   check the referenced issue/PRs are real) before acting on faith. Approve
   its read-only reconnaissance and let it proceed once satisfied.
7. **New handoff/design docs fail CI on markdownlint/prettier constantly** —
   this happened on nearly every PR across one session. When briefing a
   sub-agent that will write a new `.md` file (handoff docs, design notes),
   tell it up front to run this repo's markdown lint/format check (e.g.
   `just markdownlint` / `just prettier`) on its own new file *before*
   pushing, not just before declaring done — saves a full round-trip nearly
   every time. Also: a wrapped line that happens to start with `#NNN` (an
   issue reference) trips markdownlint's ATX-heading rule (MD018) — either
   don't let issue references land at the start of a wrapped line, or
   backtick-wrap them (immune to reflow position, and matches how issue refs
   are usually code-quoted anyway).
8. **CodeRabbit review needs an explicit trigger in repos with auto_review
   disabled** (as of 2026-08-01: `djbclark/stayturgid`, `site-djbclark`,
   `site-private`, `frdminc/Shizuku` — check for a `.coderabbit.yaml` with
   `reviews.auto_review.enabled: false` before assuming a PR will get
   reviewed automatically). Live-tested finding: adding the `review-ready`
   label via `gh pr edit --add-label` after the PR already exists does
   **not** reliably trigger a review — it silently stays at "skipped:
   automatic reviews are disabled." The label alone is not enough. What
   actually works: `gh pr comment <n> --repo <repo> --body "@coderabbitai
   review"` — confirmed live, flips the check to "Review in progress"
   within seconds, works regardless of the `enabled` setting. Do both (label
   for tracking, comment as the real trigger) once, at the point a
   sub-agent's PR is genuinely believed ready — not after every push, since
   the whole point of disabling auto-review was to stop paying for a fresh
   review on every incremental fixup commit. See
   `~/.config/coderabbit-feeder/feeder.py`'s `open_batch_pr()` for the
   working reference implementation.
9. **Independently verify the self-report before trusting it.** Don't just
   read the final summary. Check actual CI status (`gh pr checks`), re-read
   the real diff, and confirm concrete claims ("tests pass", "verified") from
   command output. This caught two real problems in one session: an
   inaccurate "verified, passes" claim (CI was actually failing), and a
   genuine functional regression a cosmetic-looking fix glossed over. If
   verification finds a real problem, send the sub-agent back with the
   *precise* root cause (not just "fix your CI") — this converges much faster
   than a vague "something's wrong, look again."
10. **A unit is not done until its PR is merged (or explicitly, durably left
    open with a real documented reason).** "CI green" and "I read the diff" are
    verification steps, not a stopping point — actually run `gh pr merge`
    yourself once satisfied. Do not let a unit's row get checked off `[x]` in
    the plan file while its PR just sits open "pending review" — that phrase
    with no owner is how PRs go stale for good (see [references/anti-patterns.md](references/anti-patterns.md)).
    The only legitimate reasons to leave a PR unmerged after verification are
    ones you'd write down: a real design decision needs the operator's input,
    or the PR is intentionally a stacked/dependent follow-up waiting on
    another PR first (name which one, in the plan file, right there).
11. **Only after the merge (or the documented exception above)**, decide the
    next unit yourself and repeat from step 1. Update the plan file's row
    yourself (check it off, note what actually happened, including any
    correction rounds) rather than trusting the sub-agent's own edit to be
    complete or accurate — spot-check it.
12. **Periodically sweep for orphaned open PRs across every repo the plan
    touches**, not just the one you're currently focused on — do this before
    starting a new phase/section of the roster, and again near the end of a
    long session. `gh pr list --repo <repo> --state open --json
    number,title,createdAt` for each repo, cross-referenced against the plan
    file's checked-off rows. A PR that's old, CI-green, and still open is a
    signal something got dropped, not a signal it's fine to ignore — go
    verify and merge it (or document why not) before moving on. This is the
    single check that would have caught the failure mode described in the
    anti-pattern in [references/anti-patterns.md](references/anti-patterns.md) immediately instead of ~15 agents later.
