---
name: session-handoff
description: "Read/write the out-of-tree Tier 1 session pointer file (SESSION_LOG.md) for any git-repo session, not just the ops-djbclark suite. Use at session start in any workspace, before handing off to another agent/session, and at session end. Triggers on: resume session, session log, tier 1, read the session log, update session log."
---

# Session Handoff — Tier 1 pointer file + chain-canonical log

Spec: `~/ops/site-private/docs/session-handoff-compaction-spec.md` (v0.4).
State root: `~/.local/state/handoffs/`. This root and everything under it is
project-agnostic — `<repo>`/`<task>` are just directory names, chosen per
the Project scope section below, not a fixed enum the tooling checks
against.

## Project scope

Two regimes, same mechanics either way — only how `<repo>`/`<task>` are
derived differs:

- **ops-djbclark suite** (cwd under `~/src/ops-worktrees/` or `~/ops/`):
  the existing convention, unchanged. `<task>` is the task-workspace dir
  name under `~/src/ops-worktrees/` (`main` for reference checkouts, `ops`
  for `~/ops` sessions); `<repo>` is the repo name (`stayturgid`,
  `site-djbclark`, `site-private`, `Shizuku`, `ops-djbclark`).
- **Any other git repository**: `<repo>` = the repo's toplevel directory
  basename (`git rev-parse --show-toplevel`, or `git remote get-url origin`
  parsed to the repo name if that's more stable across clones/forks);
  `<task>` = the current checkout's directory basename if it's one of
  several parallel worktrees/clones for that repo, else `main`. Derive
  once at session start and reuse — don't re-derive mid-session and risk
  a different `<task>` landing a second, orphaned pointer.

Two kinds of file live there:

- **Pointer**, one per touched location:
  `<repo>/<task>/SESSION_LOG.md`. Frontmatter-only:
  `redirect: chains/<chain-key>/SESSION_LOG.md`.
- **Canonical log**, one per chain: `chains/<chain-key>/SESSION_LOG.md`
  (`<chain-key>` = the first `chain` tag, slugified). Holds Current
  State, Recent History, and a `workspaces` list — one entry per location
  the session touched, each with its own `repo`/`task`/`dir`/`branch`/
  `head_sha`/`dirty`. This is what a session that works both a worktree
  task and `~/ops` at once uses instead of two independent files.

A pointer with **no** `redirect` key is a pre-v0.4 legacy full log — read
it as already-canonical; it migrates itself the next time that workspace
is included in a real write.

## Ownership

One writer per chain — the session that owns it, even when the chain
spans multiple workspace directories. Sub-agents NEVER write Tier 1 or
Tier 2 — they return completion reports; the owner writes. Any agent may
read.

## Reader protocol (session start, or when handed a Tier 1 path)

0. If cwd doesn't resolve to a `<repo>/<task>` pointer path (e.g. running
   in the bare home directory) and no explicit path was given: **don't
   just refuse.** Run the chain discovery fallback below, then continue
   at step 2 using whichever chain you land on.
1. Read the pointer at `<repo>/<task>/SESSION_LOG.md` if present.
2. If it has `redirect`, follow it to the canonical log — that file's
   `workspaces` list is the full picture, not just the workspace you
   started from. Also glob `precompact-*.md` in the *pointer's* directory
   (sidecars land next to the pointer, not the canonical file) — sidecars
   newer than the canonical `updated_at` are unplanned-compaction
   checkpoints that supersede the log's recency.
3. Staleness check: for every workspace listed, compare `head_sha` to
   actual `git rev-parse HEAD` in its `dir`. Any mismatch (or dirty-state
   drift) demotes the file from briefing to lead for that workspace —
   verify its claims against the repo before trusting them.
   `session_log.py read` does this mechanically and returns a per-workspace
   verdict.
4. **Check the memory layers the log cannot see** (added 2026-08-23). A
   `SESSION_LOG.md` only knows what *its own* session wrote. Decisions
   made in other sessions, or after that log was last touched, live
   elsewhere — so before stating a plan, spend one call on each that
   applies:

   - **This repo's curated docs.** `docs/queue.md` in `djbclark-ade`
     carries accepted-but-unstarted work and open blockers; a resume plan
     that contradicts the queue is already wrong.
   - **Memory search** (Basic Memory over `~/ops/site-private/memory`)
     — the `basic-memory` MCP
     `search_notes`, or `bm tool search-notes "<query>"`, for decisions
     and corrections from other sessions and for anything machine-wide.
     Hermes reads the same store, so this is also how you find what *it*
     decided. Notes under `hindsight/<repo>/` were exported from a retired
     LLM extractor: verify before relying on one.
   - **Verbatim recovery**, when the log references something it does not
     explain: `~/ops/site-djbclark/bin/s1_search.py search
     '<phrase>' --mode trigram`, then `neighbours <event_id>` for context.

   Prefer these over re-deriving from the code, and say in the resume
   plan which of them you actually consulted — an unsourced plan invites
   the operator to re-explain things that were already written down.
5. State a resume plan to the operator BEFORE touching anything.
6. Never ask the operator for information the file already answers.
7. Pointer missing or unparseable: not an error. Bootstrap a minimal
   canonical log from `git status` / `git log -1` / current branch with
   Active work: "no prior context found", then proceed.

### Chain discovery fallback (cwd doesn't resolve to a workspace)

The chain-canonical layout (v0.4) makes this cheap: the canonical logs
themselves are the index, no separate discovery file needed.

1. `ls ~/.local/state/handoffs/chains/` — one directory per active chain.
2. Read each `chains/<id>/SESSION_LOG.md` frontmatter (`updated_at`,
   `workspaces`) and the Current State's Active work line.
3. **Exactly one chain exists:** don't make the operator name a path —
   state the resume plan from that chain directly (reader protocol steps
   2–5), same as if its pointer had been handed to you explicitly.
4. **Multiple chains:** list them briefly (chain id, `updated_at`, Active
   work) and ask the operator which one — this is information the state
   directory doesn't answer, so asking here doesn't violate rule 5.
5. **No chains exist:** legitimately fresh state — say so, don't
   fabricate a workspace to resume.

## Writer protocol (before handoff, at session end, after major state changes)

Use the helper — it owns caps, sidecar folding, atomicity, git anchoring,
and pointer bookkeeping so you don't have to get them right by hand:

    ~/.claude/hooks/handoff-tools/.venv/bin/python \
      ~/.claude/hooks/handoff-tools/session_log.py write \
      --state-root ~/.local/state/handoffs

with the JSON payload on stdin (`session_id`, `writer`, `chain`,
`latest_handoff`, `active_work`, `blockers`, `next_steps`,
`history_bullets` — max 3, and `workspaces`: a list of
`{"repo": ..., "task": ..., "dir": <absolute path>}`, one entry per
location this session is touching — list every location still active,
since `workspaces` is replaced wholesale each write same as Current
State). List **both** locations in the same write when a session is
working a worktree task and `~/ops` concurrently — that's the whole point
of v0.4, one call updates the canonical log and every pointer at once.

`read`/`fold` take `--state-root` and `--dir <pointer-directory>`; `read`
returns the staleness verdict pre-computed per workspace. Only edit files
by hand if the helper is broken, and then follow the same rules it
enforces (replace Current State and `workspaces` wholesale; 10-entry/
30-day/3-bullet caps; temp-file + rename; sidecars fold into the
canonical file, never the pointer).

Composition rule regardless of path: every Next-steps item must be a
path, a runnable command, or an ID resolvable from cold start. Never
"as discussed above"; never a bare reference to tool-backed state (task
lists, memory) without the exact tool call that retrieves it.

## File format

Canonical log (`chains/<chain-key>/SESSION_LOG.md`):

    ---
    schema_version: 2
    updated_at: 2026-08-04T14:22:17-0400
    session_id: <herdr pane id, or session uuid, or "solo">
    writer: claude-code
    chain: [<bead/epic ids or standalone-hex>]
    latest_handoff: <site-private-relative path, or "none">
    workspaces:
      - repo: <repo name>
        task: <task dir name>
        dir: <absolute path>
        branch: <branch>
        head_sha: <full sha>
        dirty: true|false
      - repo: <repo name>
        task: ops
        dir: <absolute path>
        branch: master
        head_sha: <full sha>
        dirty: false
    ---

    ## Current State
    - Active work: <bead ID + description, or free text>
    - Blockers: <list or "None">
    - Next steps: <bullets per the Writer protocol's Composition rule>

    ## Recent History
    ### 2026-08-04T14:22:17-0400 — claude-code
    - <max 3 bullets>

Pointer (`<repo>/<task>/SESSION_LOG.md`):

    ---
    schema_version: 2
    updated_at: 2026-08-04T14:22:17-0400
    chain: [<bead/epic ids or standalone-hex>]
    redirect: chains/<chain-key>/SESSION_LOG.md
    ---

    This is a pointer file — the durable log lives at the path in
    `redirect` above.

## Guards

- **Writing** requires a real git repo to anchor to — `session_log.py
  write` needs actual `head_sha`/`branch`/`dirty` state per workspace, not
  a bare directory. The ops-djbclark suite (`~/src/ops-worktrees/`,
  `~/ops/`) is the well-worn case; any other git repo works the same way
  per the Project scope section above. A directory that isn't a git repo
  at all: the writer protocol does not apply there.
- **Reading/resuming** does NOT require being inside a workspace — cwd
  outside any resolvable repo (e.g. the bare home directory) triggers the
  chain discovery fallback above, not a refusal.
- Deep recovery (12-item mining, chain docs) is the separate `handoff`
  skill (Tier 2). This skill is the cheap pointer only.
