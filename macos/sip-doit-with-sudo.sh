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
#   half of the intent; the watchdogd "apple-daemons" freeze/kill enforcement
#   and the --check monitor (which reports a daemon that has run UNFROZEN for
#   more than 2 minutes) are what actually keeps CPU time and semantic-store
#   growth down. Flags may not survive a macOS
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
#   (roles/watchdogd) SIGSTOPs every live gui-domain instance (frozen: no
#   CPU, no respawn) and TERMs the system-domain ones — the actual
#   enforcement; apply-mode kills; the --check monitor. Demand-side is
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
#     triald + triald.system = no Apple experiment-treatment updates;
#     sirittsd (Siri text-to-speech agent, added 2026-10-12) = no Siri voices
#     for Spoken Content/VoiceOver; it idle-exits on its own, so it is TERMed.
#     siriactionsd (Shortcuts / App Intents backend, VoiceShortcuts.framework;
#     added 2026-10-15) = no Shortcuts automations, App Shortcuts or Spotlight
#     actions. It is long-lived (launched by an XPC event at login, never
#     exits, re-triggered by every LaunchServices app-state notification), so
#     it is frozen, not TERMed: App Tamer had been SIGSTOPping it with no
#     visible side effect, and a kill would just respawn it.
#   - 2026-10-15 (later): knowledgeconstructiond (Apple Intelligence
#     IntelligencePlatformCore "FullPipeline", a nightly power-required
#     background task that tripped macOS's CPU-limit diagnostic four nights
#     running, Oct 9-12) = no on-device knowledge graph; one-shot, so TERMed.
#     sharingd (AirDrop, Handoff, Universal Clipboard, Continuity; KeepAlive +
#     RunAtLoad, so only a freeze sticks) and contactsd (Contacts store; it
#     lives in the user/<uid> background domain, not gui, hence USER_DAEMONS)
#     are frozen at the operator's request: AirDrop, Handoff and Contacts are
#     not used here. A frozen XPC daemon makes callers hang rather than fail,
#     so a stuck share sheet or Mail address lookup is the symptom to watch
#     for; undo one by removing it from the lists here and in
#     bin/apple_daemon_ban.sh, then `kill -CONT` its pid.
#   - 2026-10-15 (operator: "disable or kill every single thing mentioned"):
#     six more long-lived gui agents, all frozen on sight: duetexpertd
#     (CoreDuet suggestions expert, suggestd's sibling; two CPU-limit
#     diagnostics Oct 9/12) = no Siri Suggestions or app predictions;
#     mediaanalysisd (photoanalysisd's sibling, the main Neural Engine
#     client behind ANECompilerService's CPU) = no Visual Look Up, Live Text
#     or Photos object search; campo = Siri AI.app, the macOS 27 Siri app
#     (KeepAlive + RunAtLoad) and the client that reactivates
#     generativeexperiencesd; visualintelligenced; siriknowledged; and
#     intelligenceplatformd, knowledgeconstructiond's parent in the same
#     IntelligencePlatformCore group. Siri and Apple Intelligence are already
#     off by profile (no-apple-intelligence/). Not touched: ANECompilerService
#     is aned's XPC helper, not a job; it goes quiet once its clients are.
#   - 2026-10-13: Apple Intelligence runtime daemons added at the operator's
#     request: gui generativeexperiencesd, intelligencecontextd,
#     intelligenceflowd (TERMed, not frozen: on-demand XPC services, and a
#     SIGSTOPped one would hang its clients instead of failing them fast) and
#     system modelmanagerd, modelcatalogd (flag only, see below).
#     Expect Writing Tools, Siri/Apple Intelligence features and on-device
#     model downloads to stop working. Undo with --revert.
#   - 2026-10-13 (later, investigation): the five come straight back because
#     persistent clients reconnect within ~1 s of a kill (assistantd ->
#     intelligenceflowd -> intelligencecontextd; coreaudiod -> modelmanagerd ->
#     modelcatalogd; Siri AI.app/BackgroundShortcutRunner ->
#     generativeexperiencesd), and none can be stopped with SIP on. A 60 s kill
#     loop therefore costs ~4% of a core in respawn work and risks the reported
#     modelmanagerd -> coreaudiod/launchd CPU climb. modelmanagerd and
#     modelcatalogd are now FLAG-ONLY (FLAG_ONLY_DAEMONS below): the disable flag
#     is set and checked, nothing kills them, and --check ignores them running.
#     Later the same day the gui trio (generativeexperiencesd,
#     intelligencecontextd, intelligenceflowd) became flag-only too: 12 straight
#     minutes of per-minute respawns after the restrictions profile was in force.
#     With SIP on, launchd may drop the flags at
#     reboot (reported on 26.5/27): --check will then say "flag not set".

export PATH="/opt/homebrew/bin:$PATH"
set -u

MODE=apply
case "${1:-}" in
  "") ;;
  --status) MODE=status ;;
  --revert) MODE=revert ;;
  --check) MODE=check ;;
  --sip-disable) MODE=sip-disable ;;
  --sip-enable) MODE=sip-enable ;;
  -h|--help) gsed -n '2,/^$/p' "$0" | gsed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "Unknown argument: $1 (use --status, --check, --revert, --sip-disable, --sip-enable, or none)" >&2; exit 2 ;;
esac

sip_enabled() { csrutil status 2>/dev/null | ggrep -q 'status: enabled'; }

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

CONSOLE_USER=$(gstat -c "%U" /dev/console)
CONSOLE_UID=$(gstat -c "%u" /dev/console)
if [ -z "$CONSOLE_USER" ] || [ "$CONSOLE_USER" = root ] || [ -z "$CONSOLE_UID" ]; then
  [ "$MODE" = check ] && exit 0   # login window: nothing to verify, stay silent
  echo "Error: no logged-in console user (got '${CONSOLE_USER}'); log in at the console and retry." >&2
  exit 1
fi
CONSOLE_HOME=$(dscl . -read "/Users/$CONSOLE_USER" NFSHomeDirectory 2>/dev/null | gawk '{print $2}')

GUI_DOMAIN="gui/$CONSOLE_UID"

GUI_DAEMONS=(
  "com.apple.suggestd"
  "com.apple.cloudd"
  "com.apple.photoanalysisd"
  "com.apple.triald"
  "com.apple.helpd"
  "com.apple.sirittsd"
  "com.apple.siriactionsd"
  "com.apple.knowledgeconstructiond"
  "com.apple.sharingd"
  "com.apple.duetexpertd"
  "com.apple.mediaanalysisd"
  "com.apple.campo"
  "com.apple.visualintelligenced"
  "com.apple.siriknowledged"
  "com.apple.intelligenceplatformd"
  "com.apple.generativeexperiencesd"
  "com.apple.intelligencecontextd"
  "com.apple.intelligenceflowd"
  "com.apple.spotlightknowledged"
  "com.apple.spotlightknowledged.updater"
  "com.apple.spotlightknowledged.importer"
)

# Jobs in the per-user background domain (user/<uid>, LimitLoadToSessionType
# Background), which launchctl addresses only there, never as gui/<uid>.
# Treated exactly like the gui list (flag, kill, freeze, check, revert).
USER_DOMAIN="user/$CONSOLE_UID"
USER_DAEMONS=(
  "com.apple.contactsd"
)

# gui_like_jobs: prints "<domain> <label>" for every gui- and user-domain job.
gui_like_jobs() {
  local d
  for d in "${GUI_DAEMONS[@]}"; do echo "$GUI_DOMAIN $d"; done
  for d in "${USER_DAEMONS[@]}"; do echo "$USER_DOMAIN $d"; done
}

SYSTEM_DAEMONS=(
  "com.apple.cloudd"
  "com.apple.triald.system"
  "com.apple.spindump"
  "com.apple.tailspind"
  "com.apple.modelmanagerd"
  "com.apple.modelcatalogd"
)

# Daemons (gui or system domain) that get the disable flag but are NOT killed or
# checked for running: persistent clients (assistantd, coreaudiod, Siri AI)
# reactivate them within ~1 s of a kill, so enforcing them only churns.
FLAG_ONLY_DAEMONS=" com.apple.modelmanagerd com.apple.modelcatalogd com.apple.generativeexperiencesd com.apple.intelligencecontextd com.apple.intelligenceflowd "
is_flag_only() { case "$FLAG_ONLY_DAEMONS" in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

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
    | ggrep -Eq "\"$2\" => (disabled|true)"
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
  launchctl print "$1/$2" 2>/dev/null | gawk '/^\tpid =/{print $3; exit}'
}

# is_frozen <pid>: 0 if the process is SIGSTOPped (stat T). The watchdogd
# "apple-daemons" rule freezes the gui-domain daemons on sight; a frozen
# instance is the intended end state — desired here, not a problem.
is_frozen() {
  case "$(ps -o stat= -p "$1" 2>/dev/null | gtr -d ' ')" in T*) return 0 ;; *) return 1 ;; esac
}

# age_s <pid>: seconds since process start, from ps etime ([[dd-]hh:]mm:ss).
# Prints nothing and fails if the pid is gone.
age_s() {
  local t parts d=0 h=0 m=0 s=0
  t=$(ps -o etime= -p "$1" 2>/dev/null | gtr -d ' ')
  [ -n "$t" ] || return 1
  case "$t" in *-*) d=${t%%-*}; t=${t##*-} ;; esac
  read -r -a parts <<<"${t//:/ }"
  case ${#parts[@]} in
    1) s=${parts[0]} ;;
    2) m=${parts[0]}; s=${parts[1]} ;;
    3) h=${parts[0]}; m=${parts[1]}; s=${parts[2]} ;;
  esac
  echo $(( d*86400 + h*3600 + m*60 + s ))
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
  # Stop it now if launchd still has it running and it is NOT frozen: the
  # apple-daemons watchdog SIGSTOPs the gui-domain daemons, and a TERM would
  # never be delivered to a stopped process anyway. bootout is refused by SIP
  # for Apple's own jobs (rc 150 by label, rc 5 by plist path), and the flags
  # do not stop XPC re-activation, so a respawn later is possible and expected.
  if is_loaded "$domain" "$label"; then
    launchctl bootout "$domain/$label" >/dev/null 2>&1
  fi
  pid=$(job_pid "$domain" "$label")
  if [ -n "$pid" ] && ! is_frozen "$pid"; then
    kill "$pid" 2>/dev/null
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
  local d pid flag any_unfrozen=0
  local dom
  while read -r dom d; do
    is_disabled "$dom" "$d" && flag=disabled || flag=enabled
    pid=$(job_pid "$dom" "$d")
    if is_flag_only "$d"; then
      echo "  $dom/$d: flag=$flag${pid:+, running (pid $pid)} (flag-only: not killed)"
      continue
    fi
    if [ -n "$pid" ] && is_frozen "$pid"; then
      echo "  $dom/$d: flag=$flag, frozen (pid $pid)"
    else
      [ -n "$pid" ] && any_unfrozen=1
      echo "  $dom/$d: flag=$flag${pid:+, running (pid $pid)}"
    fi
  done < <(gui_like_jobs)
  for d in "${SYSTEM_DAEMONS[@]}"; do
    is_disabled system "$d" && flag=disabled || flag=enabled
    pid=$(job_pid system "$d")
    if is_flag_only "$d"; then
      echo "  system/$d: flag=$flag${pid:+, running (pid $pid)} (flag-only: not killed)"
      continue
    fi
    [ -n "$pid" ] && any_unfrozen=1
    echo "  system/$d: flag=$flag${pid:+, running (pid $pid)}"
  done
  if [ "$MODE" = apply ] && [ "$any_unfrozen" -eq 1 ]; then
    echo "  note: some disabled jobs are running unfrozen (a window between watchdog passes;"
    echo "        the apple-daemons rule freezes/TERMs them within 60 s). --check alerts only"
    echo "        if one stays unfrozen longer than 2 minutes."
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
  # A daemon seen alive is a problem only when it has run UNFROZEN for more
  # than 2 minutes: the watchdogd apple-daemons rule freezes/TERMs on 60 s
  # passes, so younger sightings are enforcement windows, not failures, and
  # a frozen (SIGSTOP) instance is the intended steady state.
  SURVIVED_UNFROZEN_S=120
  while read -r dom d; do
    is_disabled "$dom" "$d" || PROBLEMS+=("flag not set: $dom/$d")
    is_flag_only "$d" && continue
    pid=$(job_pid "$dom" "$d")
    if [ -n "$pid" ] && ! is_frozen "$pid" \
       && [ "$(age_s "$pid" 2>/dev/null || echo 999999)" -gt "$SURVIVED_UNFROZEN_S" ]; then
      PROBLEMS+=("running despite flag, unfrozen ${SURVIVED_UNFROZEN_S}s+: $dom/$d")
    fi
  done < <(gui_like_jobs)
  for d in "${SYSTEM_DAEMONS[@]}"; do
    is_disabled system "$d" || PROBLEMS+=("flag not set: system/$d")
    is_flag_only "$d" && continue
    pid=$(job_pid system "$d")
    if [ -n "$pid" ] \
       && [ "$(age_s "$pid" 2>/dev/null || echo 999999)" -gt "$SURVIVED_UNFROZEN_S" ]; then
      PROBLEMS+=("running despite flag, unfrozen ${SURVIVED_UNFROZEN_S}s+: system/$d")
    fi
  done
  for rel in "${SEMANTIC_STORES[@]}"; do
    kb=$(gdu -sk "$CONSOLE_HOME/$rel" 2>/dev/null | gawk '{print $1}')
    [ "${kb:-0}" -gt "$MAX_STORE_KB" ] && PROBLEMS+=("semantic store regrew to $((kb / 1024)) MB: ~/$rel")
  done
  STATE_DIR="$CONSOLE_HOME/.local/state/macos-daemon-guard"
  STATE_FILE="$STATE_DIR/last-alert"
  if [ "${#PROBLEMS[@]}" -eq 0 ]; then
    [ "$EUID" -ne 0 ] && rm -f "$STATE_FILE"
    exit 0
  fi
  OSV="$(sw_vers -productVersion) ($(sw_vers -buildVersion))"
  SIG=$(printf '%s\n' "$OSV" "${PROBLEMS[@]}" | shasum | gawk '{print $1}')
  if [ -f "$STATE_FILE" ] && [ "$(ghead -1 "$STATE_FILE")" = "$SIG" ] \
     && [ -z "$(gfind "$STATE_FILE" -mmin +1440 2>/dev/null)" ]; then
    exit 0
  fi
  if [ "$EUID" -ne 0 ]; then mkdir -p "$STATE_DIR" && echo "$SIG" > "$STATE_FILE"; fi
  echo "macOS daemon-disable report on macOS $OSV (${#PROBLEMS[@]} problem(s)):"
  for p in "${PROBLEMS[@]}"; do echo "  x $p"; done
  echo "Likely cause: 'flag not set' = a macOS update reset the launchd disable flags;"
  echo "'running despite flag' = the watchdogd apple-daemons freeze/TERM enforcement is not"
  echo "keeping up (check ~/Library/Logs/watchdogd/watchdogd.log and apple-daemon-ban.log)."
  echo "Fix flags: sudo-ask ~/ops/site-djbclark/macos/sip-doit-with-sudo.sh   (idempotent)"
  exit 0
fi

if [ "$MODE" = status ]; then
  report_state
  echo ""
  echo "Semantic-search stores under $CONSOLE_HOME:"
  for rel in "${SEMANTIC_STORES[@]}"; do
    gdu -sh "$CONSOLE_HOME/$rel" 2>/dev/null || echo "  (absent) $rel"
  done
  exit 0
fi

if [ "$MODE" = revert ]; then
  echo "Re-enabling daemons for: $CONSOLE_USER (UID: $CONSOLE_UID)"
  echo "------------------------------------------------------------------"
  while read -r dom d; do converge_enabled "$dom" "$d"; done < <(gui_like_jobs)
  for d in "${SYSTEM_DAEMONS[@]}"; do converge_enabled system "$d"; done
  echo ""
  echo "Continuing (SIGCONT) instances frozen by the apple-daemons watchdog..."
  while read -r dom d; do
    pid=$(job_pid "$dom" "$d")
    case "$pid" in ''|*[!0-9]*|0) continue ;; esac
    case "$(ps -o stat= -p "$pid" 2>/dev/null | gtr -d ' ')" in
      T*) kill -CONT "$pid" 2>/dev/null && echo "  $d: continued pid $pid" ;;
    esac
  done < <(gui_like_jobs)
  report_state
  echo ""
  echo "Re-enabled flags apply at the next login/boot (the deleted semantic stores are rebuilt by macOS)."
  exit "$FAILED"
fi

echo "Applying user-level (gui + user domain) overrides for: $CONSOLE_USER (UID: $CONSOLE_UID)"
echo "------------------------------------------------------------------"
while read -r dom d; do converge_disabled "$dom" "$d"; done < <(gui_like_jobs)

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
        echo "  $rel: $(gdu -sh "$dir" | gawk '{print $1}') — emptying..."
        # Empty the directory, keep the directory itself (macOS recreates it anyway).
        gfind "$dir" -mindepth 1 -delete 2>/dev/null || { echo "  $rel: FAILED to empty." >&2; FAILED=1; }
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
ps -Arco pcpu,time,comm | ghead -8

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
