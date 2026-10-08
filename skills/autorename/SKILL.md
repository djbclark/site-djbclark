---
name: autorename
description: Rename the current Claude Code session (what /rename does) to a short title you derive from what you know about the session, then, inside herdr, offer to move its tab out of a generic workspace (a number, "shells", "src", "~") into a fitting existing or new one. Use when the operator types /autorename, says "name this session", "rename this session", "give this session a title", when the autorename_nudge hook says the session is untitled, and automatically as the last step of /handoff.
---

# autorename — title the session from what you know

`/rename` is a built-in command a skill cannot call, so this skill writes the
same records `/rename` writes, through `autorename.py` next to this file.
Claude Code only (needs `CLAUDE_CODE_SESSION_ID`); in any other TUI say so and stop.

It runs three ways: the operator asks (`/autorename`), `/handoff` Step 8 calls it
with `--auto`, and the `autorename_nudge.py` UserPromptSubmit hook (next to this
file, registered in `~/.claude/settings.json`) asks for an `--auto` run at the end
of the first substantive turn of an untitled interactive session.

## 1. Pick the title

You already know the session: the goal, what shipped, what is still open. Do not
re-read the transcript or run tools to find out. Write one title:

1. 3 to 7 words, sentence case, at most 60 characters.
2. Name the **work**, not the ceremony: "Aiuse muse quota fix", not "Handoff
   2026-10-04" or "Session about stuff".
3. Lead with the project or subsystem when the operator juggles several, then the
   outcome or open question ("Aiuse autorename skill and handoff hook").
4. No quotes, dates, emoji, or trailing punctuation.

If the session covered several unrelated things, name the one that is still live
or took the most effort.

## 2. Apply it

```bash
python3 ~/ops/site-private/skills/autorename/autorename.py "<title>"          # operator asked
python3 ~/ops/site-private/skills/autorename/autorename.py --auto "<title>"   # called from /handoff
```

`--auto` leaves the title alone when the operator renamed the session by hand
(the current title is not the one this script last wrote), so an automatic call
never overwrites a deliberate name. A direct `/autorename` always renames.

The script prints `renamed: …`, `unchanged: …` or `skipped: …`; exit 2 means it
could not run. Report that one line to the operator, nothing more. The title is
persisted (the `/resume` picker shows it), but the running session never re-reads
titles from disk, so its live label and `~/.claude/sessions/<pid>.json` keep the
old name until the operator types `/rename <title>` (upstream:
anthropics/claude-code#91468). Say so in the report when it renamed.

`autorename.py --show` prints the current title.

## 3. herdr placement (only when `HERDR_ENV=1`)

Run this after step 2 whatever it printed (renamed, unchanged or skipped). /handoff\nStep 8 skips it: a session being handed off is about to end.

```bash
python3 ~/ops/site-private/skills/autorename/herdr_place.py check          # operator asked
python3 ~/ops/site-private/skills/autorename/herdr_place.py check --auto   # the nudge hook
```

It prints JSON: this tab, its workspace (with `generic` and `reason`), the other
workspaces with their tab labels, and `ask`. If `in_herdr` is false or `ask` is
false, stop. (`--auto` gives `ask: false` once the operator answered this session.)
Skip the question too if you are a dispatched worker no human is watching.

Otherwise ask with **one** AskUserQuestion, recommended option first:

1. Each existing workspace (at most two) whose label or tab labels plainly match
   the session's project or topic: "Move to `<label>`". Never offer another
   generic workspace.
2. "New workspace `<name>`": a plain, short, lowercase name for the project or
   area (`herdr`, `mac`, `hermes`), the kind the existing workspaces use; no `-t`.
3. "Leave it in `<current>`".

The tab label for a move is a short kebab-case form of the title with the `-t`
suffix (`autorename-hook-t`), per the herdr naming convention. Then:

```bash
herdr_place.py move --workspace <workspace_id> --tab-label <label>-t
herdr_place.py move --new-workspace <name> --tab-label <label>-t
herdr_place.py decline                      # "leave it": no re-ask this session
```

`move` carries every pane of the tab (this one into a new tab in the target with
focus, the others split into it) because herdr has no tab-to-workspace move; the
old pane id stays valid as an alias. Report its one line.
