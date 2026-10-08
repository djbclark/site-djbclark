---
name: session-finder-all
description: >-
  Find any agent session that ever worked on a topic — running or ended, every
  TUI (Claude Code, Codex, Hermes, Cursor, opencode, crush, Cline, Copilot, Qwen,
  muse, zcode, agy, ACP launches) plus handoff chains and memory — and say how to
  pick the work up: resume it, start a /baton session from its handoff, or brief
  a clean agent. Use when the operator asks "which session did X", "did we ever
  look at X", "find the session where we ...", "what happened to the X work", or
  when session-finder found no running session on the topic.
---

# session-finder-all — every session that ever ran, and how to pick the work up

This is `session-finder` with the net cast over everything: ended sessions of
every agent, handoff chains, launch records and memory. Read `session-finder`
first (its sections 2–6 apply unchanged: where it lives, the continue ladder,
conflicts, ACP launching, reach table); this skill only widens the search.

```bash
S=~/ops/site-private/skills/session-finder
python3 -I $S/session-history.py <keyword>...          # full text, all agents, live + ended (run_in_background on first use)
python3 -I $S/session-history.py --agent <a> --limit 20 <kw>...
python3 -I $S/fleet.py ended --days 30                  # handoffs with next steps, unanswered last questions
python3 -I $S/launch.py list                            # ACP sessions this tooling started
ls -t ~/.local/state/handoffs/chains/ | head             # chains, newest first
```

## 1. Search, widest to narrowest

1. `session-history.py` with 1–3 distinctive words (prefix matching and stemming
   are on). Hits show agent, id, LIVE/ended, last activity, cwd, title, the matching
   snippet, `send to:`/`where:` for running ones and `resume:` for ended ones.
   Raise `--limit` before loosening the words.
2. `fleet.py ended --days 30`: open items the transcripts do not show — a handoff
   chain whose next steps nobody took, a session that ended on a question.
3. Basic Memory (`search_notes`, project `main`, then `find`/`read_note` to
   confirm): handoff notes under `memory/handoffs/<repo>/`, project notes, todos.
4. `~/ops/site-djbclark/bin/s1_search.py search '<phrase>' --mode trigram` for a
   verbatim line you remember (session-handoff skill, reader step 4).

Prefer the session whose **latest** prompt is about the topic over one that only
mentioned it. Two close candidates: name both and ask.

## 2. Pick the work up

Apply `session-finder` section 3 exactly, with the ended-session rungs in front:

1. A live session on the topic → message it (3a), unless `FINISHED` (3b).
2. A handoff chain covers the directory → `launch.py --baton --cwd <dir> --agent
   <A> --model <M> -p "<instruction>"` (3b/3c). Name the chain with `--chain` when
   `fleet.py ended` shows more than one for that repo.
3. No handoff, small transcript, irreplaceable context → resume (3d, size limits).
4. Otherwise brief a clean agent (3e); the old transcript is evidence for the
   brief, not something to replay.

Run `fleet.py conflicts --cwd <dir>` before 2–4 (section 4 of session-finder).

## 3. Report

Three things per candidate: agent + session id (or name), title, and where it
lives / how to resume. For an ended session add its last activity time and
transcript size, because those decide rung 3 versus 4. End with the command you
recommend, ready to run.

## What this is not

1. Not a transcript reader: answer from snippets and `fleet.py show`, and open the
   raw transcript only for a specific line of evidence (prompt text is private;
   never copy it into a repo or memory note).
2. Not `helm-all`: that one walks the open items and sends answers; this one finds
   sessions and says how to continue them.
