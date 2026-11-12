#!/bin/bash
# launchd agent com.djbclark.orchard-dev runs this (installed copy:
# ~/.orchard/run-dev.sh; source: site-public-djbclark roles/tart_route/files/).
# `orchard dev` = controller + worker "bigmac", API on *:6120 with NO auth
# (orchard dev has no listen flag; see README caveat 5).
#
# 1. VMs use tart's default shared NAT (create them WITHOUT --net-softnet:
#    softnet needs root). A background watcher runs fix-vmnet-route.sh every
#    15 s, which repairs the Tailscale route clash on 192.168.65.0/24 through
#    the exact-argv sudoers rule from roles/tart_route; it logs only on change.
# 2. `orchard dev` logs at DEBUG with no flag to lower it (~15 MB/day of sync
#    loop lines). stderr is filtered: DEBUG lines and the worker's own 5 s
#    poll lines are dropped; warnings, errors and real requests stay.
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
here="$HOME/.orchard"
self=$$

(
  set +e  # a failed repair must not end the watcher
  last=
  while /bin/kill -0 "$self" 2>/dev/null; do
    out=$("$here/fix-vmnet-route.sh" -q 2>&1); rc=$?
    if [ -n "$out" ] && [ "$out" != "$last" ]; then
      printf '%s route-watch rc=%s %s\n' "$(/bin/date '+%Y-%m-%dT%H:%M:%S%z')" "$rc" "$out" >>"$here/route-watch.log"
    fi
    last=$out
    # Rule missing (rc 3): back off instead of a sudo failure every 15 s.
    if [ "$rc" = 3 ]; then /bin/sleep 300; else /bin/sleep 15; fi
  done
) </dev/null >/dev/null 2>&1 &

tab=$'\t'
exec 2> >(exec /usr/bin/grep --line-buffered -v -E \
  -e "${tab}DEBUG${tab}" \
  -e "${tab}INFO${tab}worker/worker\.go:[0-9]+${tab}syncing [0-9]+ local VMs" \
  -e "\"status\": 200, \"method\": \"(GET|PUT)\", \"path\": \"/v1/(vms\", \"query\": \"filter=worker%3Dbigmac|workers/bigmac\", \"query\": \")\", \"ip\": \"127\.0\.0\.1\", \"user-agent\": \"Orchard/" \
  >&2)
exec /opt/homebrew/bin/orchard dev -d "$here/dev-data"
