---
name: cow-workspaces
description: Give an agent its own workspace with `cow` (APFS copy-on-write pastures) instead of a plain clone or `git worktree` — via the `cow-pasture` wrapper that scrubs copied secrets and can register the pasture with Orca. Use when starting parallel or isolated work on any primary checkout under ~/src, ~/orca/projects or ~/.hermes, when dispatching an Orca or Hermes worker into its own directory, or when asked about cow, pastures, `cow migrate`, or why an Orca worker in a pasture stalled.
---

# cow workspaces

`cow` (github.com/joeinnes/cow, `/opt/homebrew/bin/cow`) clones a whole repo
directory with APFS `clonefile(2)`. A pasture is an **independent repo with
its own `.git`** that carries the source's untracked content (`node_modules`,
build output), so agents start without reinstalling. Measured: 36.5 GB
logical in 4.4 GB on disk across 10 pastures. The win is space and dependency
reuse, not speed.

## The rule

For a new isolated workspace on a **primary checkout**, run:

```bash
~/orca/projects/djbclark-ade/bin/cow-pasture create <name> --source <repo> [--branch <b>] [--orca]
```

It prints the pasture path. Do not use `git worktree add` or a plain clone
for agent workspaces unless cow refuses (see limits). Default pasture root
is `~/.cow/pastures/<source-name>/<name>`.

Never create pastures from `~/ops/*` — those are deployment checkouts that
running services read directly; the wrapper refuses (exit 3). Work there in
place with plain git (operator decision 2026-08-23).

## Why the wrapper, not bare `cow create`

Verified 2026-09-20:

1. **cow copies gitignored secrets.** `.env`, `*.pem`, keys — everything
   untracked comes along, `uchg` flag included. `cow-pasture` deletes
   gitignored secret-like files after the clone (patterns in the script),
   warns about *tracked* ones, keeps dependency dirs. `--keep-secrets` opts
   out. Credentials a task really needs go through `sudo-secretspec`.
2. **`uchg` strands pastures.** Copied `.env` files are often user-immutable,
   so `cow remove` fails. `cow-pasture remove <name>` (short name or
   `<source>/<name>`) runs `chflags -R nouchg` first.
3. **Orca can't see pastures** (own `.git` ⇒ absent from `git worktree
   list`). `--orca` runs `orca repo add --path <pasture>` so `worker-start
   --worktree path:<pasture>` resolves and the pasture groups under the
   source's project. Removal: `cow-pasture remove <name>` unregisters it via
   `orca project setup-delete --setup <repo-id>` (plain `cow remove` leaves a
   dangling registration that Orca still resolves). Real fix: stablyai/orca#16226.

## Orca dispatch recipe

```bash
P=$(cow-pasture create task-foo --source ~/src/aiuse --orca)
orca orchestration worker-start --spec "<task>" --worktree "path:$P" --agent codex --json
```

`worker-start` must run from a coordinator terminal: run
`orca orchestration run-create --objective "<text>"` once first, or it fails
with `consumer_fenced`.

**Claude workers and folder trust.** Claude Code shows a folder-trust "Quick
safety check" in any directory it has never seen, so `worker-start --agent
claude` fails at `agent_readiness` (reproduced 2026-09-20). There is no flag
or env var for it (the binary's only trust env vars are for Anthropic's cloud
runner); the mechanism is `~/.claude.json` → `projects[<path>].
hasTrustDialogAccepted = true`. `cow-pasture create` now pre-seeds that
(atomic write, backup at `~/.claude.json.bak.cow-pasture`; `--no-trust` to
skip), and a Claude worker then dispatches and completes normally. Tradeoff:
the pasture's own `.claude/` settings, hooks and MCP config run without the
prompt — acceptable for a clone of your own repo with secrets scrubbed, not
for untrusted code. Codex, Cursor and Copilot are pre-trusted by Orca itself
(`src/main/agent-trust-presets.ts`); Claude has no preset upstream.

**graft.** Agent sessions write `graft/.cache/session/*.json` into the
workspace. `create` adds `graft/.cache/` to the pasture's `.git/info/exclude`
so the pasture is not "dirty", and `remove` deletes that untracked cache first
so no `--force` is needed. Tracked `graft/` content is never touched.

## Limits

- cow refuses linked worktrees ("is a git worktree, not a primary
  repository") and bare stores ("No VCS found"). `~/src/core-*`,
  `libntech-*`, `ss-*`, `ralph-tui-*-plugin` are linked worktrees; use their
  primaries. `~/src/ops-worktrees/` sits on bare stores — leave it alone.
- `cow migrate` fails when the source has an uncommitted `.gitignore` edit;
  keep tracked `.gitignore` clean, put local ignores in `.git/info/exclude`.
- `cow migrate` skips dirty worktrees; `--force` needs the operator.

## Reclaiming space

`cow gc --merged --dry-run` (then without `--dry-run`, with the operator's
go) removes pastures whose branch merged. `cow stats` before and after.

## Turning it off

Delete this skill directory; nothing else runs automatically. The MCP server
(`mcp__cow__*`, user-scope stdio) and `cowcd` shell function are independent.
