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
# graft-hook-timeout-fix.py keeps this prefix on graft's hook commands, since
# `graft init` rewrites them wholesale.
deny=(
  "$HOME/src/hermes-worktrees"
)
dir="${CLAUDE_PROJECT_DIR:-$PWD}"
for d in "${deny[@]}"; do
  case "$dir/" in
    "$d"/*) exit 0 ;;
  esac
done
exec "$@"
