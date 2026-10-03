#!/usr/bin/env bash
# Reload a user LaunchAgent so an edited plist actually takes effect.
#
# Usage: launchd_reload.sh <label> [health-url] [health-timeout-seconds]
#
# Why this exists (2026-09-29): two traps hit when doing this by hand.
#   1. `launchctl kickstart -k` restarts the process but does NOT re-read the
#      plist, so edited EnvironmentVariables silently stay at the old values.
#      Only bootout + bootstrap re-reads it.
#   2. launchd does not finish tearing a job down before `bootout` returns, so
#      an immediate `bootstrap` can fail with "5: Input/output error". The same
#      command succeeds a moment later (see roles/basic_memory_mcp/tasks/main.yml).
# This script waits for teardown to finish and retries bootstrap, mirroring the
# Ansible roles' `until rc == 0` loop.
set -euo pipefail

label="${1:?usage: launchd_reload.sh <label> [health-url] [timeout]}"
health_url="${2:-}"
health_timeout="${3:-180}"

domain="gui/$(id -u)"
plist="$HOME/Library/LaunchAgents/${label}.plist"

[ -f "$plist" ] || { echo "no such plist: $plist" >&2; exit 1; }
plutil -lint "$plist" >/dev/null || { echo "plist failed lint: $plist" >&2; exit 1; }

if launchctl print "$domain/$label" >/dev/null 2>&1; then
  launchctl bootout "$domain/$label" || true
  # Wait until launchd has really forgotten the job (max ~30s).
  for _ in $(seq 1 30); do
    launchctl print "$domain/$label" >/dev/null 2>&1 || break
    sleep 1
  done
fi

ok=0
for attempt in $(seq 1 10); do
  if launchctl bootstrap "$domain" "$plist" 2>/dev/null; then ok=1; break; fi
  echo "bootstrap attempt $attempt failed (teardown race?); retrying in 3s" >&2
  sleep 3
done
[ "$ok" = 1 ] || { echo "bootstrap failed after retries: $label" >&2; exit 1; }
echo "bootstrapped $label"

if [ -n "$health_url" ]; then
  deadline=$((SECONDS + health_timeout))
  until curl -fsS -m 3 -o /dev/null "$health_url" 2>/dev/null; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "health check timed out after ${health_timeout}s: $health_url" >&2
      exit 1
    fi
    sleep 3
  done
  echo "healthy: $health_url"
fi
