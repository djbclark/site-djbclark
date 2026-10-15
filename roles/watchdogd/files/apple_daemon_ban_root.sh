#!/bin/bash
#
# apple_daemon_ban_root.sh — root half of bin/apple_daemon_ban.sh (the
# watchdogd "apple-daemons" rule). Kills the system-domain jobs from
# macos/sip-doit-with-sudo.sh; everything else about why is documented there.
#
# Installed by hand, root:wheel 0755, at
# /usr/local/libexec/djbclark/apple_daemon_ban_root.sh (commands in
# roles/watchdogd/README.md); the sudoers drop-in files/sudoers.apple-daemon-ban
# allows djbclark to run exactly this path, no arguments. It must stay
# root-owned: a user-writable copy would make that grant a root shell.
#
# modelmanagerd/modelcatalogd are deliberately NOT here (2026-10-13): coreaudiod
# re-activates them within ~1 s of a kill, so they are flag-only in
# macos/sip-doit-with-sudo.sh (FLAG_ONLY_DAEMONS).
#
# Output: one line per kill ("TERM system/<label> pid <n>"), for the caller's
# log. Exit 0 always — a job that is not running is not an error.

export PATH="/opt/homebrew/bin:$PATH"
set -u

# job_pid <label>: the pid launchd reports for the system-domain job, or empty.
job_pid() {
  launchctl print "system/$1" 2>/dev/null | gawk '/^\tpid =/{print $3; exit}'
}

# kill_pid <label>: TERM, then KILL if the same pid survives 1 s.
kill_pid() {
  local label=$1 pid
  pid=$(job_pid "$label")
  case "$pid" in ''|*[!0-9]*|0) return 0 ;; esac
  kill -TERM "$pid" 2>/dev/null || return 0
  sleep 1
  if [ "$(job_pid "$label")" = "$pid" ]; then
    kill -KILL "$pid" 2>/dev/null
    echo "$(gdate '+%F %T') KILL  system/$label pid $pid (ignored TERM)"
  else
    echo "$(gdate '+%F %T') TERM  system/$label pid $pid"
  fi
}

SYSTEM_LABELS=(
  "com.apple.cloudd"
  "com.apple.triald.system"
  "com.apple.spindump"
  "com.apple.tailspind"
)

for label in "${SYSTEM_LABELS[@]}"; do
  kill_pid "$label"
done
exit 0
