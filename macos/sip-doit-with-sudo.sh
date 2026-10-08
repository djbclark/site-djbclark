#!/bin/bash
#
# sip-doit-with-sudo.sh — converge this Mac on "noisy Apple background daemons
# disabled". Idempotent: safe to run any number of times; each run only acts
# on what is not yet in the desired state and exits 0 once everything is.
#
# Usage:
#   sudo ./sip-doit-with-sudo.sh             apply (default)
#   sudo ./sip-doit-with-sudo.sh --status    read-only: print the state, change nothing
#   sudo ./sip-doit-with-sudo.sh --revert    undo: re-enable every daemon listed below
#
# What "disabled" means here: `launchctl disable <domain>/<label>` writes a
# persistent flag (visible in `launchctl print-disabled <domain>`). It is
# reversible and does NOT touch the sealed system volume. `launchctl bootout`
# (stop it now) is refused by SIP for Apple's own jobs, so after a run the job
# may still be alive until the next login/boot; that is reported, not an error.
# The flag may not survive a macOS update: just run this script again.
#
# History / decisions:
#   - 2026-10-04 (zcode review): the AMFI bypass line of the downloaded original
#     (nvram boot-args=amfi_get_out_of_my_way=1) was removed and stays out: it
#     disables AMFI (unsigned code runs system-wide) and cannot be set while SIP
#     is enabled anyway. The rest of the original's daemon set is kept.
#   - 2026-10-08: added the CoreSpotlight semantic-search daemons
#     (spotlightknowledged, .updater, .importer) after the updater was found
#     burning CPU on an embedding backlog, and deletion of that semantic store.
#     The file index (index.spotlightV3, Priority) is deliberately left alone.
#     No Apple document describes the side effects of disabling
#     spotlightknowledged; expect semantic/"Siri Suggestions" style results in
#     Spotlight to go away. Undo with --revert.
#
# Preconditions (operator-verified 2026-10-04):
#   - No iCloud account is signed in (MobileMeAccounts domain absent), so
#     disabling cloudd loses nothing now. RUN --revert BEFORE signing into an
#     Apple ID, or iCloud will silently not sync.
#   - suggestd's stuck-harvesting loop was already fixed via DB reset; it is
#     disabled here as a precaution.
#   - photoanalysisd disabled = no Photos face/scene analysis; helpd = no
#     in-app Help Viewer content; spindump/tailspind = no hang/stall reports.

set -u

MODE=apply
case "${1:-}" in
  "") ;;
  --status) MODE=status ;;
  --revert) MODE=revert ;;
  -h|--help) sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "Unknown argument: $1 (use --status, --revert, or none)" >&2; exit 2 ;;
esac

if [ "$MODE" != status ] && [ "$EUID" -ne 0 ]; then
  echo "Error: This script must be run as root. Please run using: sudo $0 ${1:-}" >&2
  exit 1
fi

CONSOLE_USER=$(stat -f "%Su" /dev/console)
CONSOLE_UID=$(stat -f "%u" /dev/console)
if [ -z "$CONSOLE_USER" ] || [ "$CONSOLE_USER" = root ] || [ -z "$CONSOLE_UID" ]; then
  echo "Error: no logged-in console user (got '${CONSOLE_USER}'); log in at the console and retry." >&2
  exit 1
fi
CONSOLE_HOME=$(dscl . -read "/Users/$CONSOLE_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')

GUI_DOMAIN="gui/$CONSOLE_UID"

GUI_DAEMONS=(
  "com.apple.suggestd"
  "com.apple.cloudd"
  "com.apple.photoanalysisd"
  "com.apple.triald"
  "com.apple.helpd"
  "com.apple.spotlightknowledged"
  "com.apple.spotlightknowledged.updater"
  "com.apple.spotlightknowledged.importer"
)

SYSTEM_DAEMONS=(
  "com.apple.spindump"
  "com.apple.tailspind"
)

# CoreSpotlight semantic-search stores (embeddings, journals). Safe to delete;
# the daemons rebuild empty directories. NOT the file index.
SEMANTIC_STORES=(
  "Library/Metadata/CoreSpotlight/DocumentProcessing"
  "Library/Metadata/CoreSpotlight/SpotlightKnowledgeEvents"
  "Library/Metadata/CoreSpotlight/SpotlightKnowledge"
)

FAILED=0

# is_disabled <domain> <label>: 0 if the persistent disable flag is set.
is_disabled() {
  launchctl print-disabled "$1" 2>/dev/null \
    | grep -Eq "\"$2\" => (disabled|true)"
}

# is_loaded <domain> <label>: 0 if launchd currently has the job loaded.
is_loaded() {
  launchctl print "$1/$2" >/dev/null 2>&1
}

# proc_name <label>: process name = label without the com.apple. prefix
# (spotlightknowledged.updater is the real process name of that job).
proc_name() { echo "${1#com.apple.}"; }

# running_pids <label>: pids of the job's process (exact name match).
running_pids() { pgrep -x "$(proc_name "$1")"; }

converge_disabled() {
  local domain=$1 label=$2
  if is_disabled "$domain" "$label"; then
    echo "  $label: already disabled."
  else
    echo "  $label: disabling..."
    launchctl disable "$domain/$label"
    if is_disabled "$domain" "$label"; then
      echo "  $label: disabled."
    else
      echo "  $label: FAILED to set the disable flag." >&2
      FAILED=1
    fi
  fi
  # Stop it now if it is still alive. bootout is blocked by SIP for Apple's own
  # jobs ("Operation not permitted"); that is expected and not an error.
  if is_loaded "$domain" "$label"; then
    launchctl bootout "$domain/$label" >/dev/null 2>&1
  fi
  if [ -n "$(running_pids "$label")" ]; then
    pkill -x "$(proc_name "$label")" 2>/dev/null
  fi
}

converge_enabled() {
  local domain=$1 label=$2
  if is_disabled "$domain" "$label"; then
    echo "  $label: enabling..."
    launchctl enable "$domain/$label"
    is_disabled "$domain" "$label" && { echo "  $label: FAILED to enable." >&2; FAILED=1; }
  else
    echo "  $label: already enabled."
  fi
}

report_state() {
  echo ""
  echo "State of the targeted daemons:"
  local d p flag
  for d in "${GUI_DAEMONS[@]}"; do
    is_disabled "$GUI_DOMAIN" "$d" && flag=disabled || flag=enabled
    p=$(running_pids "$d" | tr '\n' ' ')
    echo "  $GUI_DOMAIN/$d: flag=$flag${p:+, running (pid ${p% })}"
  done
  for d in "${SYSTEM_DAEMONS[@]}"; do
    is_disabled system "$d" && flag=disabled || flag=enabled
    p=$(running_pids "$d" | tr '\n' ' ')
    echo "  system/$d: flag=$flag${p:+, running (pid ${p% })}"
  done
  if [ "$MODE" = apply ]; then
    for d in "${GUI_DAEMONS[@]}" "${SYSTEM_DAEMONS[@]}"; do
      if [ -n "$(running_pids "$d")" ]; then
        echo "  note: some disabled jobs are still running; SIP blocks bootout, so the"
        echo "        flag takes effect at the next login/boot. Re-run afterwards to confirm."
        break
      fi
    done
  fi
}

if [ "$MODE" = status ]; then
  report_state
  echo ""
  echo "Semantic-search stores under $CONSOLE_HOME:"
  for rel in "${SEMANTIC_STORES[@]}"; do
    du -sh "$CONSOLE_HOME/$rel" 2>/dev/null || echo "  (absent) $rel"
  done
  exit 0
fi

if [ "$MODE" = revert ]; then
  echo "Re-enabling daemons for: $CONSOLE_USER (UID: $CONSOLE_UID)"
  echo "------------------------------------------------------------------"
  for d in "${GUI_DAEMONS[@]}"; do converge_enabled "$GUI_DOMAIN" "$d"; done
  for d in "${SYSTEM_DAEMONS[@]}"; do converge_enabled system "$d"; done
  report_state
  echo ""
  echo "Re-enabled flags apply at the next login/boot (the deleted semantic stores are rebuilt by macOS)."
  exit "$FAILED"
fi

echo "Applying user-level (GUI) overrides for: $CONSOLE_USER (UID: $CONSOLE_UID)"
echo "------------------------------------------------------------------"
for d in "${GUI_DAEMONS[@]}"; do converge_disabled "$GUI_DOMAIN" "$d"; done

echo ""
echo "Applying system-level (Root) overrides"
echo "------------------------------------------------------------------"
for d in "${SYSTEM_DAEMONS[@]}"; do converge_disabled system "$d"; done

echo ""
echo "Deleting CoreSpotlight semantic-search stores (file index is kept)"
echo "------------------------------------------------------------------"
case "$CONSOLE_HOME" in
  /Users/?*)
    for rel in "${SEMANTIC_STORES[@]}"; do
      dir="$CONSOLE_HOME/$rel"
      if [ -d "$dir" ] && [ -n "$(ls -A "$dir" 2>/dev/null)" ]; then
        echo "  $rel: $(du -sh "$dir" | awk '{print $1}') — emptying..."
        # Empty the directory, keep the directory itself (macOS recreates it anyway).
        find "$dir" -mindepth 1 -delete 2>/dev/null || { echo "  $rel: FAILED to empty." >&2; FAILED=1; }
      else
        echo "  $rel: already empty or absent."
      fi
    done
    ;;
  *) echo "  skipped: unexpected home directory '$CONSOLE_HOME'" >&2; FAILED=1 ;;
esac

echo ""
echo "Killing leftover powermetrics from the 2026-10-04 morning diagnostics..."
PIDS=$(pgrep -f '^/usr/bin/powermetrics .*--samplers')
if [ -n "$PIDS" ]; then
  ps -p "${PIDS//$'\n'/,}" -o pid,lstart,command
  echo "$PIDS" | xargs kill
  sleep 1
  if pgrep -f '^/usr/bin/powermetrics .*--samplers' >/dev/null; then
    echo "WARNING: still running, escalate with: sudo kill -9 ${PIDS//$'\n'/ }"
  else
    echo "powermetrics gone."
  fi
else
  echo "No powermetrics running (already cleaned up)."
fi

report_state

echo ""
echo "Top CPU consumers right now (for the record):"
ps -Arco pcpu,time,comm | head -8

if [ "$FAILED" -ne 0 ]; then
  echo ""
  echo "Some steps failed (see stderr above); fix and re-run." >&2
fi
exit "$FAILED"
