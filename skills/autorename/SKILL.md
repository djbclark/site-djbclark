---
name: autorename
description: Rename the current Claude Code session (what /rename does) to a short title you derive from what you know about the session. Use when the operator types /autorename, says "name this session", "rename this session", "give this session a title", and automatically as the last step of /handoff.
---

# autorename — title the session from what you know

`/rename` is a built-in command a skill cannot call, so this skill writes the
same records `/rename` writes, through `autorename.py` next to this file.
Claude Code only (needs `CLAUDE_CODE_SESSION_ID`); in any other TUI say so and stop.

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
