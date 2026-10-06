---
name: reorg-orca
description: Reorganize a cluttered Orca setup from the CLI — rename worktrees/projects/tabs, reparent worktrees, split and close terminals — the way herdr lets an AI restructure workspaces. Snapshots current structure, proposes a numbered plan, applies only verbs Orca actually has, and says plainly which requested moves it cannot do yet (move terminal, swap, resize, reorder, repo rm). Use when asked to tidy, clean up, reorganize or restructure Orca workspaces, worktrees, projects or tabs.
---

# reorg-orca

Orca's CLI can create/rename/reparent/close but cannot yet move, swap, resize
or reorder (upstream: stablyai/orca#23272 umbrella). This skill does what
exists and reports the rest. Never improvise a missing verb with
close-and-recreate on a live agent: that kills the running process.

## 0. Re-probe first — verbs may have landed

```bash
~/orca/projects/djbclark-ade/bin/orca-reorg-watch --show   # cli:{...} true = verb now exists
orca --version
```

If `cli` shows `terminal move`, `repo rm`, etc. as `true`, read that verb's
`--help` and use it. The tables below are a 2026-09-26 snapshot (Orca 1.4.212).

## 1. Snapshot (read-only, all `--json`)

```bash
orca project list --json
orca repo list --json
orca worktree list --json            # add --repo <sel> to narrow
orca terminal list --include-visual-layouts --json   # group > tab > pane tree, handles, split direction; no split ratios (verified 1.4.212; nodes are `group` and `pane-split`)
orca worktree ps --json
```

Selectors: `path:<abs>`, `name:<display>`, `branch:<b>`, `id:<repo>::<path>`,
`active`. Terminal handles (`term_…`) come from `terminal list`.

## 2. Plan — number it, then confirm

Present the plan as a numbered list of concrete commands (operator standing
rule: number every list, unique across the reply, e.g. `1.1`, `1.2`, `2.1`).
Split it into **2.x doable now** and **3.x not doable via CLI** (say which
upstream issue tracks it). Wait for the operator's go-ahead before any
mutation. Group by risk: renames and reparents are reversible; closes and
`worktree rm` are not.

## 3. What you can apply

| Goal | Command |
|---|---|
| Rename worktree | `orca worktree set --worktree <sel> --display-name "<n>"` |
| Reparent worktree | `orca worktree set --worktree <sel> --parent-worktree <sel>` or `--no-parent` |
| Status / note | `orca worktree set --worktree <sel> --workspace-status <id> --comment "<t>"` |
| Rename project | `orca project setup-update --setup <repo-id> --display-name "<n>"` |
| Rename tab | `orca terminal rename --terminal <handle> --title "<t>"` |
| New terminal in a worktree | `orca terminal create --worktree <sel> --title "<t>" [--command "<c>"]` |
| Split a pane | `orca terminal split --terminal <handle> --direction horizontal\|vertical [--command "<c>"]` |
| Close one terminal / whole tab | `orca terminal close --terminal <handle> [--tab]` |
| Remove worktree | `orca worktree rm --worktree <sel>` — **also deletes the local branch unless Orca can't prove it merged; list unmerged branches to the operator first, never `--force` unasked** |
| Close all terminals in a worktree | `orca terminal close --worktree <sel> --all` — kills every process; confirm each agent is idle |

Cross-repo parents are refused (`LINEAGE_PARENT_CONTEXT_CONFLICT`); report,
don't work around.

## 4. What you cannot do yet (tell the operator; do not fake it)

| Wanted | herdr has | Orca status |
|---|---|---|
| Move a live terminal to another worktree | `pane move --tab` | none; PR #15108 open (#9632) |
| Move pane/tab into a split or other tab | `pane move --tab --split` | GUI "Move Tab to Split" only (#12083) |
| Swap panes | `pane swap` | none, unfiled → #23272 |
| Resize an existing split | `pane resize` | none; `split --ratio` only requested (#15771) |
| Reorder tabs / worktrees / groups | – | drag only (#20515, #12306, #8766) |
| Remove a repo/project | `workspace close` | none (#22433) |
| Group projects | – | UI only (#8766) |

For these, list them as "manual (GUI)" steps in the plan with exact targets
("drag tab X onto worktree Y"). The `orca computer` family can drive the GUI
but is fragile — offer it, don't default to it.

## 5. Verify

Re-run the snapshot for what changed and show the operator before/after.
Report failures verbatim; don't retry a refused verb with a different trick.
