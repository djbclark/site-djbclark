#!/bin/bash
# Run a graft Claude Code hook unless the session's project dir is denied.
#
#   graft-hook-guard.sh node "/Users/djbclark/.claude/helpers/graft-hooks.cjs" <event>
#
# graft's Stop hook spawns a detached `graft build .` (dist/claude/sync-run.js,
# 120 s cap) whenever the project's graft stats are dirty. A non-git directory
# holding two or more git checkouts is a "workspace" to graft
# (isWorkspaceBuildRoot), so that build splits into every child. Under
# ~/src/hermes-worktrees each child is a full hermes-agent tree (~159k nodes,
# ~1 GB of graph); on 2026-10-18 a build there took 25+ min and 11 GB, load 140.
# graft 0.23.0 has no per-directory opt-out, and TRAIL_NO_HOOKS is global, so
# this wrapper skips every graft hook event for the denied trees instead.
#
# A single hermes-agent checkout is too big for the Stop build alone: fully
# cached (0 of 10951 files parsed) it still took 270 s wall, 3.25 GB peak, at
# load ~75 on 2026-10-18, so it overran the 120 s cap at the end of every turn.
# Those trees skip only `stop`; queries still refresh the graph on demand.
#
# graft-hook-timeout-fix.py keeps this prefix on graft's hook commands, since
# `graft init` rewrites them wholesale.
deny=(
  "$HOME/src/hermes-worktrees"
)
deny_stop=(
  "$HOME/.hermes/hermes-agent"
  "$HOME/.cow/pastures/hermes-agent"
)
dir="${CLAUDE_PROJECT_DIR:-$PWD}"
event="${*: -1}"
# graft's per-prompt pack (UserPromptSubmit `prompt`) was removed on 2026-10-10 and
# `graft init` puts it back: ~120-300 tokens on every prompt, kept in history, often
# off-target (djbclark-ade docs/disabled-skills.md). Skip it unless GRAFT_PROMPT_HOOK=1.
if [ "$event" = prompt ] && [ -z "${GRAFT_PROMPT_HOOK-}" ]; then
  exit 0
fi
for d in "${deny[@]}"; do
  case "$dir/" in
    "$d"/*) exit 0 ;;
  esac
done
if [ "$event" = stop ]; then
  for d in "${deny_stop[@]}"; do
    case "$dir/" in
      "$d"/*) exit 0 ;;
    esac
  done
fi
exec "$@"
