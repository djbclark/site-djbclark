#!/usr/bin/env bash
# SessionStart hook: inject real Claude quota into session context.
#
# Why this exists: on 2026-08-15 a session read `aiuse --json`'s alerts[], saw
# kind:"conserve" on both Claude accounts, and scaled work down — while the
# weekly windows were at 4% and 16% used. aiuse's conserve alert is a PACE
# PROJECTION (extrapolates the current burn rate across the reset window), not a
# depletion measure. `cswap list` carries the real per-account 5h/7d state.
# Putting the real numbers in context at session start means the model reasons
# from them instead of rediscovering this.
#
# Emits SessionStart hookSpecificOutput.additionalContext. Fails open: any
# problem exits 0 silently rather than blocking session start.

set -uo pipefail

# ── stdout-purity check on the BASH_ENV chain ────────────────────────────
# settings.json sets BASH_ENV=~/.bashrc, so every hook shell sources it BEFORE
# the hook body runs. If anything above .bashrc's interactive guard prints to
# stdout, it prepends itself to this script's JSON and the hook fails silently
# — malformed JSON is discarded with no error anywhere. We cannot rescue our
# own stdout (the noise is already emitted by the time we run), so report on
# stderr, which is the one channel that survives the contamination.
if [ -n "${BASH_ENV:-}" ] && [ -r "${BASH_ENV}" ]; then
  noise="$(env BASH_ENV="$BASH_ENV" bash -c true 2>/dev/null)" || noise=""
  if [ -n "${noise//[[:space:]]/}" ]; then
    printf '%s\n' \
      "WARNING: ${BASH_ENV} prints to stdout when sourced non-interactively." \
      "Every Claude Code hook that returns JSON is now silently broken," \
      "including this one — the text below is prepended to their output:" \
      "---" "$noise" "---" \
      "Fix: move the printing line below the interactive guard in ${BASH_ENV}" \
      "(or ~/.bashrc.local, which is sourced above it). Verify with:" \
      "  [ -z \"\$(BASH_ENV=${BASH_ENV} bash -c true)\" ] && echo clean" >&2
  fi
fi

# ── full shell-config self-test, only after an actual edit ───────────────
# The check above catches stdout contamination only. ~/.config/bash/selftest.sh
# additionally asserts PATH ordering (herdr wrapper precedence, brew vs
# /usr/bin), duplicate/nesting stability, system dirs surviving a bare env,
# and brew-shellenv drift. It costs ~0.7s, so run it only when one of the
# shell config files is newer than the last passing run — the common case is
# a single stat and no shells spawned.
#
# Same stderr-only reporting rationale as above: stdout belongs to the JSON.
__selftest="$HOME/.config/bash/selftest.sh"
__stamp="$HOME/.config/bash/.selftest-passed"
if [ -x "$__selftest" ]; then
  __stale=0
  for __f in "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.bashrc.local" "$__selftest"; do
    [ -e "$__f" ] || continue
    [ "$__f" -nt "$__stamp" ] && __stale=1
  done
  if [ "$__stale" = 1 ]; then
    if __out="$("$__selftest" 2>&1)"; then
      : > "$__stamp"
    else
      printf '%s\n' \
        "WARNING: shell config self-test FAILED after a recent edit to" \
        "~/.bashrc, ~/.bash_profile, or ~/.bashrc.local:" "---" "$__out" "---" \
        "Re-run with: $__selftest" >&2
    fi
  fi
fi

command -v cswap >/dev/null 2>&1 || exit 0

raw="$(cswap list 2>/dev/null | grep -v 'A newer version of claude-swap')" || exit 0
[ -n "${raw//[[:space:]]/}" ] || exit 0

python3 -c '
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    sys.exit(0)
ctx = (
    "Current Claude quota, from `cswap list` at session start. These are the "
    "authoritative numbers for any go/no-go decision about how much work to "
    "run.\n\n"
    + raw
    + "\n\nNotes: the 5h window is usually the binding constraint, not the 7d. "
    "If one account is tight, others may have a fresh window — `cswap switch "
    "<n>` moves new sessions. Do NOT use `aiuse --json` alerts for this: its "
    "kind:\"conserve\" entry is a pace projection that fires on a fast hour "
    "even when the window is nearly untouched."
)
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": ctx,
    }
}))
' <<<"$raw"
