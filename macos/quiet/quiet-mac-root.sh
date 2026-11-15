#!/bin/bash
# System-domain half of quiet-mac. Installed root-owned, no arguments.
# Basename selects the mode: quiet-mac-root disables and TERMs;
# quiet-mac-root-revert enables and does not signal anyone.
# Policy is the root-owned daemons.tsv beside this script.
# QUIET_MAC_POLICY overrides that path and skips the root-owned check (tests).
set -u
if [ "$#" -ne 0 ]; then
  echo "quiet-mac-root: no arguments" >&2
  exit 2
fi

here=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
policy=${QUIET_MAC_POLICY:-$here/daemons.tsv}
case "$(basename "$0")" in
  quiet-mac-root) mode=enforce ;;
  quiet-mac-root-revert) mode=revert ;;
  *)
    echo "quiet-mac-root: refuse basename $(basename "$0")" >&2
    exit 2
    ;;
esac

uid_of() {
  if uid=$(stat -f %u "$1" 2>/dev/null); then
    printf '%s\n' "$uid"
  else
    stat -c %u "$1"
  fi
}

if [ ! -f "$policy" ]; then
  echo "quiet-mac-root: missing policy $policy" >&2
  exit 1
fi
if [ -z "${QUIET_MAC_POLICY:-}" ]; then
  if [ "$(uid_of "$policy")" != 0 ] || [ "$(uid_of "$0")" != 0 ]; then
    echo "quiet-mac-root: helper and policy must be root-owned" >&2
    exit 1
  fi
fi

job_pid() {
  launchctl print "system/$1" 2>/dev/null | awk '/^\tpid =/{print $3; exit}'
}

kill_pid() {
  label=$1
  pid=$(job_pid "$label")
  case "$pid" in
    ''|*[!0-9]*|0) return 0 ;;
  esac
  kill -TERM "$pid" 2>/dev/null || return 0
  sleep 1
  if [ "$(job_pid "$label")" = "$pid" ]; then
    kill -KILL "$pid" 2>/dev/null
    echo "KILL system/$label pid $pid"
  else
    echo "TERM system/$label pid $pid"
  fi
}

while IFS=$'\t' read -r action domain label _why; do
  case "$action" in
    ''|\#*) continue ;;
  esac
  [ "$domain" = "system" ] || continue
  case "$action" in
    term|flag) ;;
    *) continue ;;
  esac
  if [ "$mode" = "revert" ]; then
    launchctl enable "system/$label"
    echo "enable system/$label"
    continue
  fi
  launchctl disable "system/$label"
  if [ "$action" = "term" ]; then
    kill_pid "$label"
  fi
done <"$policy"
exit 0
