---
name: todo
description: >-
  Use when the operator asks "what could I work on", "what's on my todo",
  "any todos I could pick up", or similar, in any agent TUI. Tracks optional,
  do-whenever-you-like tasks (open-source PR opportunities, side projects,
  cleanup ideas — anything NOT urgent or scheduled) as Basic Memory notes and
  surfaces them on request.
---

# todo — "what could I work on whenever" surface

A cross-agent todo list of **optional, do-whenever** items: things worth doing
but with no deadline and no owner assigned yet — upstream PR/issue
opportunities, side-project ideas, cleanup tasks, "would be nice" follow-ups.
Not for active/assigned/time-boxed work (that belongs in the task's own repo,
handoff doc, or cron).

Stored as notes in the **shared** Basic Memory pool (`main`, backed by
`~/ops/site-private/memory`, git-tracked), not any one agent's private memory.
Any agent on this machine can read and add to it via the `basic-memory` MCP
tools (`mcp__basic_memory__*`) or the `bm` CLI.

## Convention

- Folder: `todo/`
- Tag: `todo-item` (plus a freeform category tag: `opensource`, `cleanup`,
  `idea`, `infra`, etc.)
- Frontmatter: `status: open` or `status: closed` (plus `type: task`)
- One note per item: what it is, why it's worth doing, links to any upstream
  issue/PR/repo, where supporting evidence/logs live, current status.

## When Basic Memory is unreachable

The session's MCP tools may be missing ("failed to connect ... ECONNREFUSED") while
the server itself is fine: the client gave up during a restart and does not retry.

1. **Fix it first** (standing rule, 2026-10-05: "always fix it if it has issues").
   Probe the server with a real MCP `initialize` POST to
   `http://127.0.0.1:18796/mcp` (a bare GET returns 400 even when healthy), then
   a `search_notes` call. If it fails, look at the launchd job
   `com.djbclark.basic-memory-mcp` and its watchdog
   (`~/Library/Logs/basic-memory-mcp/`), and restart with
   `launchctl kickstart -k gui/$(id -u)/com.djbclark.basic-memory-mcp`.
2. **If the server answers but this session's tools are gone**, tell djbclark to
   run `/mcp` and reconnect `basic-memory` (an agent cannot reconnect its own
   client).
3. **Don't block on it — write the note as a file.** Notes are plain Markdown in
   git, and the server indexes them on its next sync:
   1. `cd ~/ops/site-private && git pull --rebase`
   2. Write `memory/todo/<Title>.md` with this frontmatter (copy an existing
      note under `memory/todo/` for the shape):
      ```yaml
      ---
      title: <Title, same as the file name>
      type: task
      tags:
      - todo-item
      - <category>
      status: open
      ---
      ```
   3. `git add "memory/todo/<Title>.md"` (by path), commit, `git push`.
4. To read the list without MCP: `bm tool search-notes "todo-item"`, or
   `grep -l 'status: open' ~/ops/site-private/memory/todo/*.md`.

## When asked "what could I work on" / "what's on the todo"

1. Search the shared pool for open items:
   - MCP: `mcp__basic_memory__search_notes` (or `search`) with query/tag
     `todo-item`, project `main`.
   - CLI: `bm tool search-notes "todo-item"` (or grep
     `~/ops/site-private/memory/todo/` directly if MCP is down).
2. Filter to `status: open`, list each with a one-line summary + link.
3. If none exist, say so plainly rather than inventing suggestions.

## When you find or create one

Write a new note under `todo/` in project `main` with the convention above
(`mcp__basic_memory__write_note`, directory `todo`). Set `status: open`. Flip
to `status: closed` (edit in place, don't delete) once done/merged/stale, so
the surface stays accurate without losing history.

## Coding tasks carry a paste-ready prompt (standing rule, 2026-10-03)

When the item is a **coding task** (anything that ends in editing a repo), the
note must include a `## Prompt` section: a prompt djbclark can paste into **any
Claude agent started from any working directory** and have it succeed with no
other context. Write it so that:

1. **It never relies on the current directory or this conversation.** Start by
   telling the agent to `cd` to the absolute repo path (or `git clone` it, with
   the URL, if it may not exist), and name the branch to start from or create.
   Use absolute paths everywhere, never `~/`-relative guesses about cwd and never
   "this repo" or "as discussed".
2. **It is self-contained.** State the goal, why it matters, the symptoms or
   evidence (log lines, issue/PR links, file:line), what has already been tried
   or ruled out, and the exact files or symbols involved.
3. **It names the rules that bite**, e.g. which repo's `AGENTS.md` to read first,
   commit/push policy (`~/ops` repos commit to `master` and push; stage by path,
   never `git add -A` in a shared checkout), and anything not to touch.
4. **It ends with a verifiable done condition**: the test or command to run and
   what passing looks like, plus "report what you changed and the commit sha".
5. **It runs standalone**: no sub-agent or tool the prompt does not itself say
   how to reach. Put it in a fenced code block so it copies cleanly.

Non-coding items (operator logins, checks, decisions) need no prompt; give the
exact command or manual steps instead.

## Example

`todo/Open-source PR opportunity- mcp python-sdk issue #3641.md` — a
streamable-HTTP transport race found while debugging a local basic-memory-mcp
wedge, filed upstream as
https://github.com/modelcontextprotocol/python-sdk/issues/3641, not yet picked
up.
