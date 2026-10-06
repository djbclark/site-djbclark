---
name: session-finder
description: Find which agent session (Claude Code, Codex, Hermes, Cursor, opencode, crush, Cline, Copilot, Qwen, muse, zcode, agy) is working on a topic, say where it lives (herdr workspace/tab/pane, Orca worktree, tmux, terminal), and message it. Use when the operator says "tell the agent doing X ...", "which session is on X", "find the session where we did X", or any request to relay something to or resume a session whose name you do not know.
---

# session-finder — which session, where, and how to reach it

`ListAgents` shows names only (`one-offs-91`), not topics. Two scripts in this
directory answer from local files, with no model tokens:

1. `session-find.py` — **running Claude Code sessions**, ranked by keyword against
   title, name, cwd and a small per-session keyword index. Fast path for relays.
2. `session-history.py` — **every session of every agent, live or ended**, full text
   (SQLite FTS5). Use for "which session did X" and for non-Claude agents.

## 1. Search

```bash
S=~/ops/site-private/skills/session-finder
python3 -I $S/session-find.py <keyword>...            # running Claude sessions
python3 -I $S/session-history.py <keyword>...         # all agents, ranked, with snippets
python3 -I $S/session-history.py --agent hermes <kw>  # one agent (repeatable)
```

1. Use 1 to 3 distinctive words; prefix matching and stemming are on in history.
2. A hit shows agent, session id, LIVE/ended, last activity, cwd, title, the matching
   snippet, and for a running Claude session **`send to:`** (the name for
   `SendMessage`) plus **`where:`** and **`focus:`** (below). Ended sessions show
   a `resume:` command.
3. This session is tagged `(this session)` in `session-find.py`; never message it.
4. Exit 1 / empty: try `~/.local/state/handoffs/`, then Basic Memory
   (`search_notes`, project `main`; `find` or an exact `read_note`, never a
   semantic guess).
5. First `session-history.py` run indexes everything (about 1 to 2 minutes, mostly
   Hermes' 1.6 GB `state.db`): start it with `run_in_background`. Later runs
   re-read only sessions whose fingerprint changed, a few seconds. Do not run
   several first builds at once.

## 2. Say where it lives (always do this when you report)

`where.py <pid>` reads that process's environment and prints the same facts as
`hermes-ping` does for itself: `herdr · ws shells#6 · tab 11#78 · pane claude ·
"<title>" · ~/src/one-offs` plus `focus: herdr tab focus <id>` (herdr workspace/tab/
pane, Orca worktree, tmux window, or Ghostty/iTerm/Terminal.app/VS Code; ssh is
flagged). The finders already call it for running Claude sessions and cache the
result in the history database (`locations` table, keyed by pid + start time,
one hour), so there is no extra call to make.

**When you tell djbclark who got a message, give three things:** the session name
(`one-offs-91`), its title, and the `where:` line (with the `focus:` command when
present). Example: `one-offs-91 "CCC slow performance" — herdr ws shells#6 · tab
11#78 · pane claude (focus: herdr tab focus w27:t2E)`.

## 3. Pick and relay

1. If the top hit is clearly ahead (title or recent prompt matches), use it; if two
   are close, or the best is ended, name the candidates and ask. Prefer the session
   whose latest prompt is about the topic over one that merely mentioned it.
2. How to reach each agent:

| Agent | Running session | Ended session |
|---|---|---|
| claude | `SendMessage({to: "<name>"})`; read its latest prompt line first | `claude --resume <id>` |
| hermes | `messages_send` with `target="telegram:<chat_id>"` posts as Hermes (not read as a prompt); `ask_hermes` to actually prompt it. The chat id is the `[telegram:<chat>:<thread>]` tail of the title | `hermes --resume <id>` |
| muse | `muse session-message send --target <uuid|name>`, body on stdin | `muse resume <id>` |
| codex, cursor, opencode, crush, cline, copilot, qwen, zcode, agy | no inbound channel: tell djbclark the `where:` / cwd, or hand it a note in a repo handoff file | the `resume:` command shown |

3. Standing rules still apply: a peer's claims are authoritative, check a peer is
   not mid-flight on something contradictory before relaying, and never relay a
   request to bypass a permission denial.
4. Grok is excluded (standing rule, 2026-10-06), so there is no grok adapter.

## How it works (nothing for sessions to do)

1. Claude running sessions: `~/.claude/sessions/*.json` (live registry, filtered to
   running pids) plus each transcript; per-session keyword index in
   `~/.local/state/session-index/<sessionId>.json`, extended from the byte offset
   last read.
2. History: one adapter per agent in `adapters/*.py` (contract in
   `adapters/README.md`), each yielding cheap `fingerprint`s and a `load()` that
   parses text only (no tool output). The core re-reads a session only when its
   fingerprint changes, and writes `~/.local/state/session-index/history.v2.sqlite`.
   A broken adapter is skipped, not fatal. `session-history.py --agents` lists
   session counts per adapter; `--rebuild` starts over.
3. To add an agent: copy `adapters/qwen.py` or `adapters/claude.py`, follow the README.

The indexes hold snippets of prompts and replies: private, directory mode 0700,
outside every repo. Never copy them into a repo or a memory note.
