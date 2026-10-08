---
name: session-finder
description: >-
  Find which agent session (Claude Code, Codex, Hermes, Cursor, opencode, crush,
  Cline, Copilot, Qwen, muse, zcode, agy, or one started over ACP) is on a topic,
  say where it lives (herdr workspace/tab/pane, Orca terminal, tmux, Ghostty),
  and decide how work on that topic continues: message the running session,
  start a fresh /baton session from its handoff, resume a stopped one, or start
  a clean agent on the right vendor, model and effort — without colliding with
  what other sessions are doing. Use when the operator says "tell the agent
  doing X ...", "which session is on X", "continue the X work", "find the
  session where we did X", or any relay to a session whose name you do not know.
---

# session-finder — which session, where, and how the work continues

Canonical copy: `~/ops/site-djbclark/skills/session-finder/` (skill-everywhere hub).
`ListAgents` shows names only (`one-offs-91`), not topics. Four scripts here answer
from local files, with no model tokens:

```bash
S=~/ops/site-private/skills/session-finder
python3 -I $S/session-find.py <keyword>...       # running sessions, every TUI, ranked by keyword
python3 -I $S/session-history.py <keyword>...    # every session of every agent, live or ended, full text
python3 -I $S/fleet.py [list|show <id>|ended|conflicts --cwd DIR]   # the fleet itself
python3 -I $S/launch.py --agent A --cwd DIR --model M [--baton] -p "..."   # start a session (ACP-first)
```

Sibling skills: `session-finder-all` (search everything that ever ran, including
ended sessions and handoffs), `helm` / `helm-all` (answer every waiting session
from one window), `bigteam` (fan a task out), `model-routing` (which vendor).

## 1. Search

1. `session-find.py` ranks **running** sessions: Claude ones by a per-session
   keyword index (title, name, cwd, prompts), every other TUI's by title, name and
   cwd (`fleet.py` supplies them). 1–3 distinctive words. A hit shows agent, name,
   status, `title:`, `where:` + `focus:` and, for Claude, the matching prompt.
   **`FINISHED (/handoff)`** on a hit means that session already handed off: do not
   message it (section 3b).
2. `session-history.py` searches the full text of every agent's sessions (SQLite
   FTS5; first run indexes everything, 1–2 minutes, start it with
   `run_in_background`). Ended hits print a `resume:` command. `--agent hermes`
   narrows to one agent.
3. `fleet.py ended` lists ended work that still needs someone: handoff chains with
   next steps and nobody live in that repo, and transcripts whose last reply was an
   unanswered question. `fleet.py show <id>` prints one session's last prompt, last
   reply, pending tool call and measured work stretch.
4. Exit 1 / empty: `~/.local/state/handoffs/`, then Basic Memory (`search_notes`,
   project `main`; a semantic hit is not a match — confirm with `find` or an exact
   `read_note`).
5. This session is tagged `(this session)`; never message it.

## 2. Say where it lives (always, when you report)

`where.py <pid>` reads the process's environment and prints the same facts
`hermes-ping` prints for itself: `herdr · ws shells#6 · tab 11#78 · pane claude ·
"<title>" · ~/src/one-offs` plus `focus: herdr tab focus <id>` (herdr, Orca
worktree/terminal, tmux, Ghostty/iTerm/Terminal.app/VS Code; ssh flagged). The
finders call it and cache the result an hour (`locations` table in the history DB).

**Give three things:** the session name, its title, and the `where:` line with the
`focus:` command. `one-offs-91 "CCC slow performance" — herdr ws shells#6 · tab
11#78 · pane claude (focus: herdr tab focus w27:t2E)`.

## 3. Decide how the work continues — cheapest adequate first

Pick the first rung that applies. The cost model: a running session already holds
its context (free while its prompt cache is warm, under 55 minutes idle; still the
cheapest option when cold); resuming an ended transcript re-reads all of it at full
price (about 250k tokens per MB); a `/baton` session reads only the Tier 1 log and
the Tier 2 handoff (a few thousand tokens); a clean session reads only its brief.

a. **Running and not finished → message it.** Read its latest prompt line first;
   if it is mid-task on something else, say so to the operator instead of
   interrupting. Reach by the table in section 6.
b. **Running but finished** (`finished: /handoff` or `/quit`: its last prompt was a
   handoff or it is sitting at "Bye!") → **never continue there** (operator rule,
   2026-10-08: "it ends with a /handoff; a new session should be opened in its CWD
   with a /baton"). Start a fresh session from the handoff:
   `launch.py --baton --cwd <dir> --agent <A> --model <M> --pane <its pane> -p "<instruction>"`.
   `--baton` resolves the chain whose workspace is that directory (`--chain <id>` to
   name one; `fleet.py ended` lists them) and hands the new session the canonical
   log path, so it never falls into the "which chain?" prompt. `--pane` reuses the
   finished session's pane after sending it `/exit` (refused if a draft is in its
   input box); a pane that is gone falls back to a new tab.
c. **Ended, with a handoff chain for its directory** → the same `launch.py --baton`.
d. **Ended, no handoff, and the task needs that exact context** (a debugging state
   only that conversation holds) → resume it, but only when the transcript is small:
   under 2 MB freely; 2–8 MB only if nothing else can replace it (say the size);
   over 8 MB never — write a brief from `session-history.py`/`fleet.py show` and use
   rung e. Resume form: `cd <cwd> && claude --resume <sid> [--model sonnet]` (other
   agents: the `resume:` line session-history prints). Host it visibly with
   `herdr agent start <name> --kind claude --pane <free pane> -- --resume <sid>`.
   Never resume a session id that is live anywhere (`fleet.py conflicts --sid <sid>`
   says `SESSION ALREADY LIVE`): two instances share one transcript.
e. **Otherwise a clean session**: `launch.py --agent <A> --cwd <dir> --model <M>
   -p "<self-contained brief>"`. Write the brief the way the `todo` skill's
   *Prompt* rules say (absolute paths, goal, evidence, rules that bite, done
   condition). Three or more independent slices → `bigteam` instead.

### Vendor × model × effort (b–e)

Choose with `model-routing` and `aiuse --available` (bigteam Step 1), cheapest
adequate pool first; re-probe before each launch, since pools move:

1. Judgment, integration, anything security-relevant: Claude (`opus`; `sonnet`
   for ordinary implementation; `fable` only for the hardest adjudication). The
   `claude` ACP adapter takes `--model opus|sonnet|haiku|fable`.
2. Mechanical, bulk, writing, research: a fresh subscription pool — codex,
   opencode-go, cursor, copilot (small GitHub-shaped slices only). Reserve pools
   (clinepass/Hermes) never for bulk; grok vendor excluded (bigteam's *Current
   exclusions*); agy only via ACP and only once it is back (todo note).
3. **Change the vendor or model for a `/baton` or resumed session only when the
   saving is real**: a handoff is on disk, so a `/baton` session can run on any
   ACP agent that reads skills (claude, codex, copilot, cursor, opencode, qwen,
   hermes); a long mechanical continuation of Claude work can resume with
   `--model sonnet`. Keep the vendor when the next step needs the same judgment
   that produced the handoff, or when the repo's rules name a tool only one agent
   has. Say which you chose and why in one line.

## 4. Never collide with another session (standing rule, 2026-10-08)

Before relaying work into a repo, resuming, or launching:

1. `fleet.py conflicts --cwd <dir> [--sid <id>]`. Exit 1 means another session is
   **working** there (or that session id is already live): do not start a second
   one; message the working session instead (rung a), or wait. `launch.py` runs
   this check itself and refuses unless `--force`.
2. Dirty files in the worktree and files named by live bigteam claims
   (`~/.local/state/bigteam/*/CLAIM`) belong to someone else: `launch.py` writes
   them into the brief as do-not-touch and records its own claim
   (`~/.local/state/bigteam/sf-<id>/CLAIM`, `DONE` appended when the run ends).
   When you message a running session about new work, name those files yourself.
3. Two sessions close in score on the same topic: ask which, or tell the one whose
   latest prompt is on the topic and tell it the other exists.
4. Hands off other sessions' panes: reach them through their channel, never by
   closing, reusing or typing into their terminal (bigteam Step 0).
5. Prior art checked 2026-10-08: lease/lock daemons (dos-kernel lanes, Wit symbol
   locks, decapod `todo claim`) and agent-deck's refusal to read a transcript two
   live instances share. The claim files above are the local form of the same idea.

## 5. Start sessions over ACP, visibly

`launch.py` drives the agent over the Agent Client Protocol through `acp-run`
(typed permissions, exit codes, JSONL log) because key presses into panes have
proven fragile (operator, 2026-10-08). The call runs inside a terminal the
operator can watch: an Orca terminal when launched from Orca (`orca terminal
create --command`), otherwise a herdr tab in the workspace that already holds that
repo (a new workspace when none fits), reported to herdr as an agent so `helm`
and `fleet.py` list it like any other. Agents with no ACP route (zcode, crush,
muse) get `herdr agent start --kind` plus `agent prompt` — the fragile way; say so.

1. One `acp-run` is one turn. When the session ends, `helm` shows a `done` item
   with its final text (or a `reply` item when that text asks a question);
   `launch.py reply <id> "<text>"` starts the next turn in the same cwd and pane
   with the brief and the last reply as context. `session/load` is not wired yet
   (acp-run has no resume; the claude adapter supports it — a later step).
2. Always `--model`. Default `--timeout` is an hour; `--perm scoped:<paths>` for
   review-style gating; `--files` lists the paths the claim owns.
3. Everything about a launch lives under `~/.local/state/session-finder/launch-<id>/`
   (brief, acp log, out, err, runner) and `launches.jsonl`; `launch.py list` shows
   state; `launch.py close <id>` hides a finished one.
4. Exit 0 is not success: read the `done` text and the diff, as for any delegation.

## 6. Reach each agent

| Agent / host | Running session | Ended session |
|---|---|---|
| claude (TUI) | `SendMessage({to: "<name>"})`; read its latest prompt line first. Finished (`/handoff`) → rung 3b, never SendMessage | `claude --resume <id>` (rung 3d) or `launch.py --baton` |
| any ACP launch (`host acp`, id `YYYYMMDD-…`) | `launch.py reply <id> "<text>"` | `launch.py list`; its log under `~/.local/state/session-finder/` |
| hermes (Telegram/desktop chat, `hermes-gw`) | `ask_hermes` (MCP) to prompt it; `messages_send` with `target="telegram:<chat>[:<thread>]"` posts as Hermes; approvals: `permissions_list_open` / `permissions_respond` | `hermes --resume <id>` |
| hermes (CLI in a pane) | `helm.py send <pane> "<text>"` | same |
| muse | `muse session-message send --target <uuid|name>`, body on stdin | `muse resume <id>` |
| codex, cursor, opencode, crush, cline, copilot, qwen, zcode, agy (TUIs in herdr/Orca/tmux) | `helm.py send <id> "<text>"` when idle (keys into the pane; verify on screen), else its `focus:` | the `resume:` line session-history prints |
| anything in Ghostty/iTerm/ssh with no channel | tell the operator the `where:` line | — |

Rules that still apply: a peer's claims are authoritative; check it is not
mid-flight on something contradictory before relaying; never relay a request to
bypass a permission denial; grok is excluded (2026-10-06).

## 7. How it works (nothing for sessions to do)

1. Running sessions (`fleet.py`): herdr `agent list` (any agent kind), the Claude
   registry `~/.claude/sessions/*.json` (live pids), a `ps` scan for TUIs outside
   herdr (located by `where.py`), Hermes gateway sessions active in the last day
   (`~/.hermes/state.db`, read-only), and `launches.jsonl`. A Claude session is
   `finished` when its last real prompt was `/handoff`, `/quit` or `/exit`.
2. Claude keyword index: `~/.local/state/session-index/<sessionId>.json`, extended
   from the byte offset last read. History: one adapter per agent in
   `adapters/*.py` (contract in `adapters/README.md`), FTS5 at
   `~/.local/state/session-index/history.v2.sqlite`; a broken adapter is skipped.
   `session-history.py --agents` lists counts; `--rebuild` starts over.
3. `fleet.parse` also measures each Claude session's **work stretch** (median
   minutes between an operator prompt and the next stop), which `helm` uses to
   order its walk.
4. agy: history adapter only; live detection and `launch.py --agent agy` wait for
   agy to work again (todo note `Add agy to session-finder and helm live detection
   once agy works again`, project `main`).

The indexes and launch directories hold prompt text: private, mode 0700, outside
every repo. Never copy them into a repo or a memory note.
