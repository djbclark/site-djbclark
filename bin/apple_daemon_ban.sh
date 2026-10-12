#!/bin/bash
#
# apple_daemon_ban.sh — freeze-on-sight for the Apple background daemons that
# macos/sip-doit-with-sudo.sh flags as disabled. On this macOS build the
# launchd disable flags do NOT stop launchd activating those jobs on
# XPC/event demand (measured 2026-10-10), and bootout is SIP-refused
# (rc 150 by label, rc 5 by plist path), so this script is the enforcement
# layer the flags cannot be.
#
# Gui-domain jobs are SIGSTOPped, not killed. Killing cannot contain a
# daemon that is pathological from its first second: 2026-10-10, kill-on-
# sight every 60 s still left suggestd burning ~a core for most of every
# pass, and it fought App Tamer — TERM is undeliverable to a stopped
# process, so the KILL escalation destroyed App Tamer's freezes and forced
# a respawn. A frozen job burns no CPU, never exits, and therefore never
# respawns; the only burn window is the ≤60 s after login/boot (or a reap).
# triald/helpd/sirittsd (short one-shots) and the root system-domain jobs are TERMed.
#
# Exit codes (watchdogd "apple-daemons" command probe):
#   0  healthy — nothing to do, or everything found was frozen/killed
#   1  the root helper is missing or failing (config problem: alert)
#   75 no console user / login window (skip)
#
# The one stdout line is the watchdogd probe detail; actions are logged to
# ~/Library/Logs/watchdogd/apple-daemon-ban.log. Labels must stay in step
# with macos/sip-doit-with-sudo.sh and the root helper's system half.

set -u

LOG_DIR="$HOME/Library/Logs/watchdogd"
LOG="$LOG_DIR/apple-daemon-ban.log"
ROOT_HELPER=/usr/local/libexec/djbclark/apple_daemon_ban_root.sh

CONSOLE_UID=$(stat -f %u /dev/console 2>/dev/null || true)
if [ -z "${CONSOLE_UID:-}" ] || [ "$CONSOLE_UID" = "0" ]; then
  echo "skip: no console user"
  exit 75
fi

mkdir -p "$LOG_DIR"
say() { echo "$(date '+%F %T') $*" >>"$LOG"; }

# job_pid <domain> <label>: the pid launchd reports, or empty. pgrep -x is
# wrong here (macos/sip-doit-with-sudo.sh, 2026-10-10): triald's process
# name is the truncated path "/usr/libexec/tri", and cloudd matches across
# the gui and system domains. launchd's pid is per-domain and per-label.
job_pid() {
  launchctl print "$1/$2" 2>/dev/null | awk '/^\tpid =/{print $3; exit}'
}

stat_of() { ps -o stat= -p "$1" 2>/dev/null | tr -d ' '; }

# freeze <domain> <label>: SIGSTOP on sight. Already stopped (by App Tamer
# or an earlier pass) means nothing to do — this must never fight or undo
# another freezer, and must never let launchd see the job exit.
freeze() {
  local domain=$1 label=$2 pid
  pid=$(job_pid "$domain" "$label")
  case "$pid" in ''|*[!0-9]*|0) return 0 ;; esac
  case "$(stat_of "$pid")" in T*) return 0 ;; esac
  if kill -STOP "$pid" 2>/dev/null; then
    say "STOP  $domain/$label pid $pid"
    FROZEN="$FROZEN ${label#com.apple.}($pid)"
  fi
}

# kill_pid <domain> <label>: TERM, then KILL if the same pid survives 1 s.
# A respawn gets a new pid; the next pass picks that up.
kill_pid() {
  local domain=$1 label=$2 pid
  pid=$(job_pid "$domain" "$label")
  case "$pid" in ''|*[!0-9]*|0) return 0 ;; esac
  kill -TERM "$pid" 2>/dev/null || return 0
  sleep 1
  if [ "$(job_pid "$domain" "$label")" = "$pid" ]; then
    kill -KILL "$pid" 2>/dev/null
    say "KILL  $domain/$label pid $pid (ignored TERM)"
  else
    say "TERM  $domain/$label pid $pid"
  fi
  KILLED="$KILLED ${label#com.apple.}($pid)"
}

FREEZE_LABELS=(
  "com.apple.suggestd"
  "com.apple.cloudd"
  "com.apple.photoanalysisd"
  "com.apple.spotlightknowledged"
  "com.apple.spotlightknowledged.updater"
  "com.apple.spotlightknowledged.importer"
)
TERM_LABELS=(
  "com.apple.triald"
  "com.apple.helpd"
  "com.apple.sirittsd"
)

FROZEN=""
KILLED=""
for label in "${FREEZE_LABELS[@]}"; do
  freeze "gui/$CONSOLE_UID" "$label"
done
for label in "${TERM_LABELS[@]}"; do
  kill_pid "gui/$CONSOLE_UID" "$label"
done

# System-domain jobs run as root. The helper is a fixed root-owned script
# allowed by exactly one sudoers line (no args, no env); sudo -n never
# prompts. Its stdout is kill log lines; append them to the log.
if [ ! -x "$ROOT_HELPER" ]; then
  say "root helper missing: $ROOT_HELPER (install: roles/watchdogd/README.md)"
  echo "root helper missing: $ROOT_HELPER"
  exit 1
fi
if ! ROOT_OUT=$(sudo -n "$ROOT_HELPER" 2>&1); then
  say "root helper failed: $ROOT_OUT"
  echo "root helper failed"
  exit 1
fi
[ -n "$ROOT_OUT" ] && printf '%s\n' "$ROOT_OUT" >>"$LOG"
while read -r line; do
  case "$line" in
    TERM\ *|KILL\ *) KILLED="$KILLED sys:${line#* }" ;;
  esac
done <<<"$ROOT_OUT"

out=""
[ -n "$FROZEN" ] && out="frozen:$FROZEN"
[ -n "$KILLED" ] && out="$out${out:+ }killed:$KILLED"
if [ -n "$out" ]; then
  echo "$out"
else
  echo "ok: nothing to enforce"
fi
exit 0
