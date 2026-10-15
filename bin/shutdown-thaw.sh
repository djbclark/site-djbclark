#!/bin/bash
#
# shutdown-thaw.sh — thaw the SIGSTOPped Apple daemons when a logout, restart
# or shutdown begins, so the shutdown can complete.
#
# Why (2026-10-15): the watchdogd "apple-daemons" rule (bin/apple_daemon_ban.sh)
# SIGSTOPs the gui-domain Apple daemons that macos/sip-doit-with-sudo.sh
# disables. A stopped process never acts on launchd's SIGTERM, so every
# restart stalled (/Library/Logs/DiagnosticReports/shutdown_stall_*.shutdownStall
# lists the "(suspended)" processes), the machine hard-reset about four minutes
# later, and the hard reset dropped the staged kernel-extension (kcgen/AuxKC)
# rebuild, so the "System software from Apple Inc. was updated, restart"
# dialog came back after every restart.
#
# How: this runs as a persistent LaunchAgent (com.djbclark.shutdown-thaw,
# KeepAlive, roles/watchdogd). At logout, restart or shutdown launchd sends
# every gui job SIGTERM; the TERM trap here SIGCONTs, then SIGTERMs, every
# stopped process of this user (ps STAT starting with T), SIGKILLs any still
# alive three seconds later, logs one line per pid and exits. Between signals
# it only sleeps. watchdogd itself cannot do this: it is a StartInterval job
# alive for a few seconds per minute, so nothing of it exists at shutdown.
#
# Log: ~/Library/Logs/watchdogd/shutdown-thaw.log. Test without rebooting:
#   sleep 1000 & p=$!; kill -STOP $p
#   launchctl kill TERM gui/$(id -u)/com.djbclark.shutdown-thaw
#   ps -p $p   # gone; KeepAlive has restarted the agent

export PATH="/opt/homebrew/bin:$PATH"
set -u

LOG_DIR="$HOME/Library/Logs/watchdogd"
LOG="$LOG_DIR/shutdown-thaw.log"
mkdir -p "$LOG_DIR"
say() { echo "$(gdate '+%F %T') $*" >>"$LOG"; }

SLEEP_PID=""

thaw() {
  local sig=$1 pid stat comm n=0 thawed=""
  while read -r pid stat comm; do
    [ -n "${pid:-}" ] || continue
    if kill -CONT "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null
      say "$sig: CONT+TERM $pid $comm (was $stat)"
      thawed="$thawed $pid"
      n=$((n + 1))
    fi
  done < <(ps -axo pid=,stat=,comm= -U "$(id -u)" | gawk '$2 ~ /^T/')
  if [ -n "$thawed" ]; then
    sleep 3
    for pid in $thawed; do
      if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null && say "$sig: KILL $pid (still alive after TERM)"
      fi
    done
  fi
  say "$sig: thawed $n stopped process(es); exiting"
  [ -n "$SLEEP_PID" ] && kill "$SLEEP_PID" 2>/dev/null
}

trap 'thaw TERM; exit 0' TERM
trap 'thaw HUP; exit 0' HUP
trap 'thaw INT; exit 0' INT

say "started pid $$"
while :; do
  sleep 86400 &
  SLEEP_PID=$!
  wait "$SLEEP_PID"
done
