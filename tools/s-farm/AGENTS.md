# `~/s` is a generated view of `~/src`. Agents use `~/src`.

`~/s` exists so that a human can browse `~/src`, which holds about 85 projects
in one flat directory. It is a tree of symbolic links, sorted into topics, that
a tool regenerates. It contains no projects of its own. This file is
`~/s/AGENTS.md` (and `~/s/CLAUDE.md`); the real file is
`~/ops/site-djbclark/tools/s-farm/AGENTS.md`.

## Rule 1: never reference `~/s`. Reference `~/src`.

**Every path you write, run, record or pass on uses `~/src/<name>`, never
`~/s/...`.** That covers shell commands, scripts, configs, docs, commit
messages, memory notes, handoffs, prompts to other agents, and replies to
djbclark.

1. If you are given a `~/s/...` path, resolve it first (`realpath <path>`, or
   read the link with `readlink`) and use the result. The last component of any
   farm path is the entry's name in `~/src`, so `~/s/android/physiboard/physiboard-spec`
   is `~/src/physiboard-spec`.
2. If your working directory is under `~/s`, `cd` to the `~/src` path before
   doing any work (`cd "$(pwd -P)"` when you are already inside a project).
3. Do not start an agent session in `~/s`. Start it in `~/src/<name>`.

Why: the layout of `~/s` is rearranged whenever `layout.conf` changes, so its
paths are not stable. Tools that key state on a path (git worktrees, session
handoffs, Claude project directories, graft indexes, editors, shell history)
would otherwise hold two names for one directory and split their state.

## Rule 2: never write to `~/s`.

Nothing is created, edited, moved or deleted in `~/s` by hand or by any tool
except the generator below. Every directory in the farm is mode `0555` and
carries the BSD user-immutable flag (`uchg`), so a write fails with `Operation
not permitted`. That failure is intended. Do not work around it with
`chflags nouchg`, `chmod` or `just unlock`; put the file somewhere else.

1. A new project goes in `~/src`, and then the farm is updated (below).
2. The lock covers the farm's own directories only. A link's target is the real
   project in `~/src`, which is as writable as ever.
3. To see the state: `ls -lO ~/s` shows `uchg`; `xattr -p com.djbclark.sfarm ~/s`
   prints a note naming the tool; `just -f ~/s/justfile status` reports both.

## How it is built

The tool is three files in `~/ops/site-djbclark/tools/s-farm/` (git, `master`):
`justfile` (linked as `~/s/justfile`), `sfarm.py` and `layout.conf`.

| Command | Effect |
| --- | --- |
| `just -f ~/s/justfile` | Update: unlock, add missing links, prune stale ones, lock again |
| `just -f ~/s/justfile plan` | Show what an update would change; changes nothing |
| `just -f ~/s/justfile check` | Exit 1 if the farm is out of date or any directory is unlocked |
| `just -f ~/s/justfile status` | Lock state, link counts, dangling and foreign entries |
| `just -f ~/s/justfile tree` | Print the farm |
| `just -f ~/s/justfile where NAME` | Find an entry by name; prints farm path and real path |
| `just -f ~/s/justfile layout` | Edit the layout rules |
| `just -f ~/s/justfile lock` / `unlock` | Re-apply or remove the lock (repair only) |

The update is not automatic. Run it after adding, removing or renaming
anything at the top level of `~/src` (a new clone, a new worktree). It is safe
to run at any time and takes under a second.

## Layout

1. **Topic tree**: `~/s/<topic>[/<group>]/<name> -> ~/src/<name>`. Every
   non-hidden top-level entry of `~/src` appears here exactly once, under its
   own name. Placement comes from `layout.conf` (`directory: glob glob ...`,
   first match wins). An entry with no rule is placed automatically: a git
   worktree beside its main repo, `<repo>-worktrees` beside `<repo>`, a loose
   file in `files/`, anything else in `unsorted/`. The update names everything
   in `unsorted/`; give each a line in `layout.conf`.
2. **`by-owner/<owner>/<name>`**: git checkouts grouped by the owner in their
   `origin` URL (`_no-remote` when there is none).
3. **`by-kind/{repo,dir,file,link}/<name>`** and
   **`by-kind/worktree/<main repo>/<name>`**.
4. `AGENTS.md`, `CLAUDE.md` and `justfile` in the root link to the tool.

To change where something appears, edit `layout.conf`, run `plan`, run the
update, then commit and push `site-djbclark`. That repo is public, so
`layout.conf` publishes the names it lists (djbclark's decision, 2026-10-06). Do not rename or move things in
`~/src` to change the view.

## What the tool will and will not delete

It removes only symbolic links that point into `~/src` (or at the tool) and
directories that are empty afterwards. Anything else it finds in the farm is
reported as a foreign entry and left alone; remove it by hand after `just
unlock` once you know what it is. It refuses to run on a non-empty directory
that does not carry its `com.djbclark.sfarm` extended attribute.
