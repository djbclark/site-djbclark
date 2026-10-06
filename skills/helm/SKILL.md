---
name: helm
description: >-
  Run every agent session from one window. A no-model collector finds each
  session that is waiting on the operator (herdr panes, Orca terminals, the
  Claude Code registry), reads its pending question verbatim, and this skill
  relays it as one prompt titled with the project and where it lives, sends
  the answer back as key presses, and has idle sessions audit themselves with
  /loose. Use when the operator types /helm, says "take the helm", "run the
  fleet from here", "what needs me", "what is waiting on me", or asks to
  answer other sessions' prompts from this window (AskUserQuestion on
  Claude-class agents; clarify / Telegram buttons on Hermes).
---

# helm — every waiting session, one prompt at a time

Canonical copy: `~/ops/site-private/skills/helm/` (skill-everywhere hub).
Design and prior art: `~/src/djbclark-ade/docs/helm.md`.

Each session runs its own `/steps` and `/loose`, because that is where its
context is. Helm is the relay: `helm.py` (no model, no tokens) finds what is
waiting and carries answers back; you only present the choice. He changes
windows only when an item needs more depth than a prompt can carry.

```bash
H="python3 -I $HOME/ops/site-private/skills/helm/helm.py"
$H scan                      # open items (--all: every session)
$H wait --auto-audit         # block until something new needs him
$H answer <id> <n>           # pick option n; one number per question
$H answer <id> --text "..."  # free-text answer to a single question
$H audit <id>                # send /loose to an idle session
$H skip <id>                 # hide until that session changes
$H show <id>                 # full detail: question, last reply, screen
$H keys <id> <key>...        # raw keys for a prompt helm cannot parse
```

## 1. Start

1. Run `$H scan`. Show the queue as a short numbered list (project, where,
   kind), so he knows how long the walk is.
2. Walk the open items (section 2), most blocking first: questions, then
   plan/permission/blocked, then idle sessions.
3. Then wait (section 3). `/helm` stays on until he says `stop`.

## 2. Relay one item per prompt

Pick the prompt tool exactly as `steps` does (`AskUserQuestion`; `clarify` on
Hermes; never numbered prose). One item per call.

1. **`question`** — the session already wrote the summary, the options and
   its recommendation. Relay them, do not rewrite them.
   a. Header chip: the project name (12 characters at most).
   b. Question text: the item's heading (`project — where · "title"`) on the
      first line, then the session's question, unchanged.
   c. Options: its labels and descriptions, same order, `(Recommended)` kept
      where it put it. Do not add your own ranking. If you know something the
      session cannot (two sessions about to touch the same thing), say it in
      one prose line before the prompt.
   d. Send his pick: `$H answer <id> <n>`. Text typed under "Other" goes with
      `--text`. `skip` typed there means `$H skip <id>`; `stop` ends the walk.
   e. A prompt with several questions: ask each as its own prompt, then send
      once (`$H answer <id> 2 1`). A multi-select prompt cannot be sent this
      way: give him the `focus:` command.
2. **`permission`, `plan`, `blocked`** — helm could not parse a question.
   Show the screen excerpt in one prose block, offer the choices that are on
   that screen, and send with `$H keys <id> <key>`.
3. **`idle`, not audited, warm** — run `$H audit <id>` without asking: that is
   the standing instruction, and the script refuses when it is unsafe (input
   box not empty, session not idle). Its `/steps` prompts come back through
   the queue.
4. **`idle`, not audited, cold** (idle past 55 minutes, so the prompt cache
   has expired and an audit re-reads the whole context at full price), and
   every non-Claude agent: ask. Give a one or two sentence summary of its
   last reply, then offer Audit (name the transcript size), Skip, or Leave it
   in the queue.

**Never choose for him.** Not the recommended option, not an obvious one.
Helm relays; the answer is his. Never relay around a permission denial.

**Report against the artifact.** `answer` prints `answered [id] "…" = "…"`
only after the session's transcript records that answer. Repeat that line.
On exit 1, say what it printed; nothing went through.

## 3. Wait without spending tokens

Run `$H wait --auto-audit` with `run_in_background: true`. It polls locally and
exits only when an item is new or changed, printing only those items. When the
notification arrives, relay them (section 2) and start it again.

1. Never poll, never `/loop`, never schedule a recurring prompt for this.
2. One `wait` at a time.
3. `--auto-audit` sends `/loose` itself, with no model, to a Claude session
   that has been idle for 3 to 55 minutes, is not the focused pane, has an
   empty input box, and has not been audited since it last changed. Once
   audited, a session stays quiet until new work happens in it.

## 4. Keep this session cheap

1. Relay item text as given. No `show` unless he asks for depth.
2. One line per result. No recap of the queue between items.
3. When he wants depth, give the `focus:` command. That is the moment to
   change windows.
4. Say once, at the start: a helm session relays and does not judge, so a
   cheaper model (`/model`) is enough.

## 5. Hermes and the phone

1. **Hermes** (on Telegram: `/helm`, registered by Hermes's `skill-slash`
   plugin since 2026-10-06; `/skill helm` also works). Same script. Per item, one `clarify`: the question starts with
   `project · where — `, then the session's question; `choices` are its option
   labels (under about 60 characters each, first one is its recommendation).
   Then `$H answer`. Hermes is not re-invoked by a background command, so it
   runs `scan`, walks the items, and runs `scan` again until nothing is open.
2. **Hermes's own open approvals** (Claude side): `permissions_list_open` on
   the `hermes` MCP server lists them, `permissions_respond` answers. Check
   once per round and relay them the same way.
3. **Collie**: the helm pane is an ordinary herdr pane, so its prompts are
   answerable from the phone with nothing extra.

## 6. Limits (verified 2026-10-06, herdr 0.9.1, Claude Code 2.1.291)

1. Verified on herdr: a digit key selects and submits; "Type something" takes
   free text; a several-question prompt ends on a review tab that Enter
   submits. The Orca and tmux channels are written but not yet exercised.
2. Non-Claude agents (Cursor, Codex, …) give state and a screen excerpt only.
3. A Claude session outside herdr, Orca and tmux can be listed but not
   answered: use `SendMessage`, or his `focus`.
4. Keys sent when no prompt is on screen land in the input box. `answer`
   checks the screen first; `keys` checks only that the session is blocked.

## What this is not

1. Not an orchestrator: it starts no work (`orc`, `bigteam` do).
2. Not an auto-responder. agent-deck's conductor answers routine questions
   itself; helm deliberately does not.
3. Not a status feed. Periodic status is `fleet-watch`.
