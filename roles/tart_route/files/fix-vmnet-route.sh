#!/bin/sh
# Restore tart's shared-NAT route 192.168.65.0/24 -> bridge10x when Tailscale
# (exit node + "Allow local network access") has replaced it with one via the
# en0 gateway 192.168.68.1 (tailscale/tailscale#22119). With the bad route the
# host cannot reach the VM (Orchard's `orchard ssh vm` / port-forward time out
# dialling 192.168.65.x:22) and the VM gets no internet.
#
# Installed copy: ~/.orchard/fix-vmnet-route.sh (source: site-public-djbclark
# roles/tart_route/files/fix-vmnet-route.sh). Run unprivileged; ~/.orchard/run-dev.sh
# runs it every 15 s next to `orchard dev`. Idempotent: exit 0 when the route is
# already right or no tart VM network is up. `-q` prints nothing in those cases.
#
# The only privileged calls are exact-argv `sudo -n` commands allowed by
# /etc/sudoers.d/tart-route (roles/tart_route, `just tart-route-setup`). Nothing
# user-writable runs as root. Exit 3 means the rule is missing.
set -u
GW=192.168.68.1
NET=192.168.65.0/24
quiet=0; [ "${1:-}" = "-q" ] && quiet=1
say() { [ "$quiet" = 1 ] || echo "fix-vmnet-route: $*"; }

# tart's vmnet bridge is the one holding the NAT gateway 192.168.65.1: bridge100
# alone, bridge101 when an Apple container network came up first. The sudoers
# rule allows exactly those two.
bridge=
for b in bridge100 bridge101; do
  /sbin/ifconfig "$b" 2>/dev/null | /usr/bin/grep -q 'inet 192\.168\.65\.1 ' && { bridge=$b; break; }
done
[ -n "$bridge" ] || { say "no bridge holds 192.168.65.1 (no tart VM network up; nothing to do)"; exit 0; }

# Every non-interface-scoped 192.168.65[/24] line counts: "bad <gw>" if any goes
# via a gateway on en0, "ok" if one is on the tart bridge.
state=$(/usr/sbin/netstat -rn -f inet | /usr/bin/awk -v br="$bridge" '
  $1 ~ /^192\.168\.65(\/24)?$/ && $3 !~ /I/ {
    seen = 1
    if ($4 == "en0" && $2 !~ /^link#/) { bad = 1; gw = $2 }
    else if ($4 == br) ok = 1
    else other = $4
  }
  $1 ~ /^192\.168\.(64|65)\/(1[6-9]|2[0-3])$/ && $3 !~ /I/ && $4 == "en0" && $2 !~ /^link#/ { wide = $1 " " $2 }
  END {
    if (bad) print "bad " gw
    else if (ok) print "ok"
    else if (seen) print "other " other
    else if (wide) print "wide " wide
    else print "absent"
  }')
case "$state" in
  ok)     say "$NET already on $bridge (nothing to do)"; exit 0 ;;
  "bad $GW") ;;
  absent) ;;  # connected route gone (e.g. after a half-done repair): just add it
  wide*)  echo "fix-vmnet-route: Tailscale's ${state#wide } (en0) covers $NET and the sudoers rule does not; hand fix: sudo route -n delete -net <that net> <gw>; sudo route -n add -net $NET -interface $bridge" >&2; exit 1 ;;
  other*) echo "fix-vmnet-route: $NET is on ${state#other }, not $bridge or en0; not touching it" >&2; exit 1 ;;
  *)      echo "fix-vmnet-route: $NET goes via ${state#bad } on en0, not $GW; the sudoers rule does not cover it" >&2; exit 1 ;;
esac
if [ "$state" = "bad $GW" ]; then
  echo "fix-vmnet-route: $NET is routed via $GW (en0); restoring $bridge"
  /usr/bin/sudo -n /sbin/route -n delete -net "$NET" "$GW" >/dev/null || {
    echo "fix-vmnet-route: delete failed (sudoers rule missing? run: just tart-route-setup in site-public-djbclark)" >&2; exit 3; }
fi
/usr/bin/sudo -n /sbin/route -n add -net "$NET" -interface "$bridge" >/dev/null || {
  echo "fix-vmnet-route: add failed; by hand: sudo route -n add -net $NET -interface $bridge" >&2; exit 3; }
echo "fix-vmnet-route: restored $NET -> $bridge"
