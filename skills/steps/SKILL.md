---
name: steps
description: >-
  Step the operator through the open items one at a time, each as its own
  multiple-choice prompt (AskUserQuestion on Claude-class agents; clarify on
  Hermes, which is Telegram buttons whose labels are the choice text) with the
  recommended option first, acting on each answer before asking the next. Use
  when the operator types /steps (optionally with item numbers or a topic),
  says "step me through it", "one at a time", or "walk me through" a list of
  open items, options or pending decisions.
---

# steps — one open item at a time, recommendation first

Canonical copy: `~/ops/site-private/skills/steps/` (skill-everywhere hub).
Hermes Telegram `/steps` needs plugin `skill-slash` (not just the skill file).
Claude Code: `site-private/claude/commands/steps.md` → `~/.claude/commands/`.

He is choosing, not reading. Give him one decision per prompt, pre-ranked, and
do what he picked before asking the next one. Same motive as
`memory/feedback_walk_me_through_means_prompt_choices.md`. The difference is
pacing: that note allows four questions per call, but `/steps` asks **one per
call**, so each answer can change the next question.

Never dump numbered prose options for him to type back. The prompt tool is the
walk.

## Prompt tool (pick once per session)

Use the native chooser your runtime actually has. Do not invent a second UX.

1. **Claude Code, Copilot, Cursor, and any agent with `AskUserQuestion`:**
   `AskUserQuestion`. Arrow-key list. Keep using it even if you also have
   something else.
2. **Hermes:** `clarify`. On Telegram that is a native card: the **question**
   in the message, and **one full-width button per choice whose label is the
   choice text** (not `1`/`2`/`3`), plus "✏️ Other (type answer)".
   Discord/Slack get the same card on those adapters. CLI/TUI get numbered
   text. If the card fails to render, Hermes already falls back to a numbered
   list — do not pre-empt that with prose options of your own.
3. **No chooser at all:** one short sentence that you cannot prompt, then
   wait. Do not fake buttons as a numbered list in chat.

Do not call `AskUserQuestion` on Hermes (it is not a tool here). Do not call
`clarify` on Claude Code.

## 1. Collect the items

1. **From the arguments.** Numbers (`/steps 2 4`, `/steps 1a 3`) refer to items in
   your most recent numbered reply. A topic (`/steps the backup stuff`) means the
   open items about that topic.
2. **Otherwise from the conversation.** Take every open item from the latest
   list: loose ends, options you offered, deferred work, questions you asked that
   he never answered.
3. **Drop anything he has already decided.** Don't re-litigate it.
4. **Never invent items to fill the walk.** If nothing is open, say so in one line
   and suggest `/loose` to audit for what might be.

Before the first prompt, show the queue as a short numbered list of titles
("4 items: 1. …"), so he knows how long this will take.

## 2. Ask one item per prompt

Shared rules for every prompt, whichever tool:

1. **One question per call.** Never batch.
2. **Recommended option first.** Distinct outcomes. Include "Leave it as is"
   or "Skip for now" where that is a real choice. 2–4 options.
3. **"Other" is added by the tool.** He can type `stop` there to end the walk.
4. **Say what it is.** The question is not a title. Lead with position (`2/4`),
   then one or two sentences: what the item is, what it does, and why a choice
   is needed. Longer background is a short prose line *before* the call.

### 2a. `AskUserQuestion` (arrow keys)

1. Position in the `header` chip, `2/4`.
2. Put the what-it-is / what-it-does sentences in `question`.
3. Label the first option `(Recommended)` and say why in its description.
4. Put each option's consequence in its description.
5. Use `preview` when comparing concrete artifacts.

### 2b. `clarify` (Hermes / Telegram buttons)

`clarify` has no `header`, no per-option description, no `preview`. The choice
strings **are** the Telegram button labels.

1. Start `question` with the position, then what it is and does, e.g.
   `1/2 — landing-health pager: hourly Jobber job on this Mac that pages
   Telegram Inbox if a must-be-up listener is down. Investigate the last
   page and fix it?`
2. Pass 2–4 strings in `choices`. First string is the recommendation; Hermes
   marks it `(Recommended)` in CLI — do not write that label yourself.
3. Keep each choice under ~60 characters, self-contained (he should not need
   the message body to know what tapping the button does). Do not number
   them. Put the consequence in the string (`Skip — leave pager as-is`).
4. Artifacts go in the prose line before the call, not inside `choices`.
5. One entry in `questions`. `multi_select` stays off.

## 3. Act, then move on

1. **Do what he picked before you ask the next question**, if it is small and
   inside the session's scope. Confirm it in one line ("Done: pushed `abc123`"),
   then ask the next one.
2. **Queue anything bigger** (a long build, a multi-file change, an agent
   dispatch). Say it is queued and do the queue right after the last item.
3. **If an answer or its result changes a later item**, re-rank that item's
   options or drop it, and say so in a line. Don't ask a question an earlier
   answer has already settled.
4. On `stop`, stop. Report what was decided and what is still open.

## 4. Keep going until nothing is left

**Don't stop after one pass** (standing rule, 2026-10-05: "keep doing more /steps
until there is nothing left to do"). After the last item, work the queue, then
collect the open items again: new decisions the queued work raised, items it
re-opened, results that need a choice. If any exist, start another round (show the
new queue, ask one per prompt, act). Repeat until a round finds nothing open.

What ends the loop:

1. **Nothing open.** No item needs his decision now.
2. **Only waiting is left.** Every remaining item waits on something no answer
   can speed up (a running agent, a quota reset, a build, him holding a phone).
   Say what each waits on and when; don't ask him to re-decide something already
   decided just to keep the loop going.
3. **`stop`.**

## 5. Close with a summary

End with a table: item, his choice, outcome (done / queued / skipped / left
open), covering every round. Number any remaining open items so he can run
`/steps` on them again.

## What this is not

1. Not an audit. `/loose` finds the loose ends and verifies each one, then calls
   `/steps` itself to walk them. `/steps` walks a list that already exists,
   wherever it came from.
2. Not a licence to widen scope. An option you recommend should close the item,
   not start new work he didn't ask for.
