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
#   ./sip-doit-with-sudo.sh --check          monitor: silent when healthy, prints ONLY a
#                                            regression report (for the Hermes cron job)
#   csrutil wrappers, run from recoveryOS Terminal (csrutil only works there):
#   ./sip-doit-with-sudo.sh --sip-disable    disable SIP (no-op if already off)
#   ./sip-doit-with-sudo.sh --sip-enable     enable SIP  (no-op if already on)
#
# What "disabled" achieves — measured on this machine, not assumed (2026-10-10):
#   `launchctl disable <domain>/<label>` writes a persistent, reversible flag
#   (visible in `launchctl print-disabled <domain>`; on disk in
#   /var/db/com.apple.xpc.launchd/disabled.<UID>.plist) and never touches the
#   sealed system volume. BUT on this macOS build the flag does NOT stop
#   launchd activating these jobs on XPC/event demand: the machine rebooted
#   2026-10-05 with every flag already set (2026-10-04), and by 2026-10-10
#   launchd had still launched suggestd 22x, triald 148x, photoanalysisd 104x,
#   helpd 72x, spotlightknowledged 24x (+ .updater 31x) and cloudd 7x (the
#   then-unflagged system cloudd 187x). The flags are the durable, verifiable
#   half of the intent; killing running instances and the --check monitor
#   (which also reports "running despite flag") are what actually keeps CPU
#   time and semantic-store growth down. Flags may not survive a macOS
#   update: just run this script again.
#   `launchctl bootout` ("stop it now") is refused while SIP is on: rc 150
#   "Operation not permitted" by label, rc 5 "Input/output error" by plist
#   path (both tested as root 2026-10-10). With SIP off it succeeds but only
#   unloads the job for the current session: at the next login launchd
#   re-submits every /System/Library agent and activates it despite the flag.
#   The one-quiet-session sequence (two recovery trips) is therefore NOT a
#   fix, just a way to buy a single quiet session:
#     1. Recovery Terminal: --sip-disable, reboot.
#     2. Normal boot: sudo ./sip-doit-with-sudo.sh   (bootout now succeeds)
#     3. Recovery Terminal: --sip-enable, reboot.    (quiet ends at next login)
#   Remaining levers with SIP on: the watchdogd "apple-daemons" rule
#   (roles/watchdogd) TERMs every live instance on each 60 s pass — the
#   actual enforcement; apply-mode kills; the --check monitor. Demand-side is
#   already dark on macOS 27 (checked 2026-10-10): the old "Spotlight/Siri
#   Suggestions" checkboxes are gone, their successors ("Show Related
#   Content", per-app results, "Help Apple Improve Search", Siri itself) are
#   all off — and suggestd is still summoned by ProactiveHarvesting XPC
#   events anyway.
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
#   - 2026-10-10 (zcode review + fixes): falsified "flags apply at next
#     login/boot" (runs counters above) and rewrote this header accordingly;
#     added system-domain com.apple.cloudd and com.apple.triald.system;
#     replaced pgrep detection with launchd's own pid (pgrep -x never matched
#     triald — its process name is the truncated path "/usr/libexec/tri" — and
#     pgrep -x cloudd conflated the gui and system jobs); --check now also
#     reports jobs running despite their flag; dropped the stale powermetrics
#     one-off.
#
# Preconditions (operator-verified 2026-10-04; revisited 2026-10-10):
#   - No iCloud account is signed in (MobileMeAccounts domain absent), so
#     disabling cloudd (gui AND system) loses nothing now. RUN --revert BEFORE
#     signing into an Apple ID, or iCloud will silently not sync.
#   - suggestd: the stuck-harvesting loop was fixed via DB reset (2026-10-04),
#     but launchd still spawns it on ProactiveHarvesting XPC events despite
#     the flag; the demand-side switches above are the remaining lever.
#   - photoanalysisd disabled = no Photos face/scene analysis; helpd = no
#     in-app Help Viewer content; spindump/tailspind = no hang/stall reports;
#     triald + triald.system = no Apple experiment-treatment updates.

set -u

MODE=apply
case "${1:-}" in
  "") ;;
  --status) MODE=status ;;
  --revert) MODE=revert ;;
  --check) MODE=check ;;
  --sip-disable) MODE=sip-disable ;;
  --sip-enable) MODE=sip-enable ;;
  -h|--help) sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "Unknown argument: $1 (use --status, --check, --revert, --sip-disable, --sip-enable, or none)" >&2; exit 2 ;;
esac

sip_enabled() { csrutil status 2>/dev/null | grep -q 'status: enabled'; }

case "$MODE" in
  sip-disable|sip-enable)
    if [ "$EUID" -ne 0 ]; then echo "Error: run as root (recoveryOS Terminal is root)." >&2; exit 1; fi
    if ! command -v csrutil >/dev/null 2>&1; then echo "Error: csrutil not found." >&2; exit 1; fi
    if [ "$MODE" = sip-disable ]; then
      if sip_enabled; then csrutil disable || exit 1; echo "SIP disabled. Reboot into normal macOS, then: sudo $0"
      else echo "SIP already disabled; nothing to do. Reboot into normal macOS, then: sudo $0"; fi
    else
      if sip_enabled; then echo "SIP already enabled; nothing to do."
      else csrutil enable || exit 1; echo "SIP enabled. Reboot into normal macOS."; fi
    fi
    csrutil status
    exit 0 ;;
esac

if [ "$MODE" != status ] && [ "$MODE" != check ] && [ "$EUID" -ne 0 ]; then
  echo "Error: This script must be run as root. Please run using: sudo $0 ${1:-}" >&2
  exit 1
fi

CONSOLE_USER=$(stat -f "%Su" /dev/console)
CONSOLE_UID=$(stat -f "%u" /dev/console)
if [ -z "$CONSOLE_USER" ] || [ "$CONSOLE_USER" = root ] || [ -z "$CONSOLE_UID" ]; then
  [ "$MODE" = check ] && exit 0   # login window: nothing to verify, stay silent
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
  "com.apple.cloudd"
  "com.apple.triald.system"
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

# job_pid <domain> <label>: the pid launchd reports for the job, or empty.
# Detection deliberately avoids pgrep: triald's process name is the truncated
# path "/usr/libexec/tri" (an exact-name match never fires), and pgrep -x cloudd
# conflates the gui- and system-domain jobs. launchd's pid is per-domain and
# per-label. Non-root callers can read the system domain too (verified
# 2026-10-10), so the Hermes-run --check sees everything.
job_pid() {
  launchctl print "$1/$2" 2>/dev/null | awk '/^\tpid =/{print $3; exit}'
}

# is_running <domain> <label>: 0 only for a plausible positive pid (a stray
# non-numeric value must never reach `kill` — kill -1 as root would broadcast).
is_running() {
  case "$(job_pid "$1" "$2")" in
    ''|*[!0-9]*|0) return 1 ;;
    *) return 0 ;;
  esac
}

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
  # Stop it now if launchd still has it running. bootout is refused by SIP for
  # Apple's own jobs (rc 150 by label, rc 5 by plist path), and the flags do
  # not stop XPC re-activation, so a respawn later is possible and expected.
  if is_loaded "$domain" "$label"; then
    launchctl bootout "$domain/$label" >/dev/null 2>&1
  fi
  if is_running "$domain" "$label"; then
    kill "$(job_pid "$domain" "$label")" 2>/dev/null
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
  local d pid flag any_running=0
  for d in "${GUI_DAEMONS[@]}"; do
    is_disabled "$GUI_DOMAIN" "$d" && flag=disabled || flag=enabled
    pid=$(job_pid "$GUI_DOMAIN" "$d")
    [ -n "$pid" ] && any_running=1
    echo "  $GUI_DOMAIN/$d: flag=$flag${pid:+, running (pid $pid)}"
  done
  for d in "${SYSTEM_DAEMONS[@]}"; do
    is_disabled system "$d" && flag=disabled || flag=enabled
    pid=$(job_pid system "$d")
    [ -n "$pid" ] && any_running=1
    echo "  system/$d: flag=$flag${pid:+, running (pid $pid)}"
  done
  if [ "$MODE" = apply ] && [ "$any_running" -eq 1 ]; then
    echo "  note: some disabled jobs are still/again running. The disable flag does NOT stop"
    echo "        launchd re-activating them on XPC events (2026-10-10); --check reports them."
  fi
}

if [ "$MODE" = check ]; then
  # Regression monitor (Hermes cron --no-agent contract): empty stdout = healthy.
  # Alerts once per distinct problem set (and again after 24 h if it persists).
  # "running despite flag" strings carry no pid on purpose: the signature must
  # stay stable for the dedup to work.
  MAX_STORE_KB=51200   # 50 MB; DocumentProcessing was 42 MB and regrowing on
                       # 2026-10-10 while the updater kept running despite its flag
  PROBLEMS=()
  for d in "${GUI_DAEMONS[@]}"; do
    is_disabled "$GUI_DOMAIN" "$d" || PROBLEMS+=("flag not set: $GUI_DOMAIN/$d")
    is_running "$GUI_DOMAIN" "$d" && PROBLEMS+=("running despite flag: $GUI_DOMAIN/$d")
  done
  for d in "${SYSTEM_DAEMONS[@]}"; do
    is_disabled system "$d" || PROBLEMS+=("flag not set: system/$d")
    is_running system "$d" && PROBLEMS+=("running despite flag: system/$d")
  done
  for rel in "${SEMANTIC_STORES[@]}"; do
    kb=$(du -sk "$CONSOLE_HOME/$rel" 2>/dev/null | awk '{print $1}')
    [ "${kb:-0}" -gt "$MAX_STORE_KB" ] && PROBLEMS+=("semantic store regrew to $((kb / 1024)) MB: ~/$rel")
  done
  STATE_DIR="$CONSOLE_HOME/.local/state/macos-daemon-guard"
  STATE_FILE="$STATE_DIR/last-alert"
  if [ "${#PROBLEMS[@]}" -eq 0 ]; then
    [ "$EUID" -ne 0 ] && rm -f "$STATE_FILE"
    exit 0
  fi
  OSV="$(sw_vers -productVersion) ($(sw_vers -buildVersion))"
  SIG=$(printf '%s\n' "$OSV" "${PROBLEMS[@]}" | shasum | awk '{print $1}')
  if [ -f "$STATE_FILE" ] && [ "$(head -1 "$STATE_FILE")" = "$SIG" ] \
     && [ -z "$(find "$STATE_FILE" -mmin +1440 2>/dev/null)" ]; then
    exit 0
  fi
  if [ "$EUID" -ne 0 ]; then mkdir -p "$STATE_DIR" && echo "$SIG" > "$STATE_FILE"; fi
  echo "macOS daemon-disable report on macOS $OSV (${#PROBLEMS[@]} problem(s)):"
  for p in "${PROBLEMS[@]}"; do echo "  x $p"; done
  echo "Likely cause: 'flag not set' = a macOS update reset the launchd disable flags;"
  echo "'running despite flag' = launchd re-activated a disabled job (known on this build; it"
  echo "is killed by the next apply run). Fix: sudo-ask ~/ops/site-djbclark/macos/sip-doit-with-sudo.sh   (idempotent)"
  exit 0
fi

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

report_state

echo ""
echo "Top CPU consumers right now (for the record):"
ps -Arco pcpu,time,comm | head -8

if sip_enabled; then
  echo ""
  echo "SIP is enabled: bootout of Apple's jobs is refused (rc 150), so still-running jobs were"
  echo "killed by pid. The disable flags do NOT stop launchd re-activating these jobs on XPC"
  echo "events (2026-10-10), so respawns are expected; --check reports them, and the demand-side"
  echo "switches in this script's header reduce them."
else
  echo ""
  echo "SIP is DISABLED: bootout succeeded, so the jobs are unloaded for THIS login session."
  echo "They return at the next login (re-submitted, then activated despite the flags)."
  echo "When satisfied, boot to recoveryOS and run: $0 --sip-enable"
fi

if [ "$FAILED" -ne 0 ]; then
  echo ""
  echo "Some steps failed (see stderr above); fix and re-run." >&2
fi
exit "$FAILED"
