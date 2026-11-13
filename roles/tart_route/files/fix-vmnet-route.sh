#!/bin/sh
# Restore tart's shared-NAT route -> bridge10x when Tailscale (exit node +
# "Allow local network access") has replaced it with one via the en0 gateway
# 192.168.68.1 (tailscale/tailscale#22119). With the bad route the host cannot
# reach the VM (Orchard's `orchard ssh vm` / port-forward time out dialling
# <subnet>.x:22) and the VM gets no internet. Two subnets are handled:
#   192.168.65.0/24  tart's NAT subnet while an Apple `container` network holds
#                    192.168.64.0/24; bridge100 or bridge101 holds 192.168.65.1.
#                    Sudoers rule /etc/sudoers.d/tart-route.
#   192.168.64.0/24  tart's NAT subnet when no container network is up; only
#                    bridge100 holding 192.168.64.1 is repaired. Uses the two
#                    argvs of /etc/sudoers.d/container-route (roles/container_route);
#                    tart-route is deliberately not widened.
#
# Installed copy: ~/.orchard/fix-vmnet-route.sh (source: site-public-djbclark
# roles/tart_route/files/fix-vmnet-route.sh). Run unprivileged; the Orchard
# launcher runs it every 15 s. Idempotent: exit 0 when the routes are already
# right or no tart VM network is up. `-q` prints nothing in those cases.
#
# The only privileged calls are constant-argv `sudo -n /sbin/route ...` commands
# allowed by those two sudoers rules; the only variable is a bridge name taken
# from a fixed list. Nothing user-writable runs as root. Exit 0 ok, 1 a case the
# rules do not cover (hand fix printed), 3 a rule is missing (message names it).
#
# Test hooks (tests/test_fix_vmnet_route.py): FIX_VMNET_ROUTE_FIXTURE_DIR makes
# the two read-only inputs come from files `netstat` and `ifconfig` in that
# directory; FIX_VMNET_ROUTE_DRYRUN=1 prints the sudo argv instead of running it.
# Neither can cause anything else to run.
set -u
GW=192.168.68.1
quiet=0; [ "${1:-}" = "-q" ] && quiet=1
say() { [ "$quiet" = 1 ] || echo "fix-vmnet-route: $*"; }

fixdir=${FIX_VMNET_ROUTE_FIXTURE_DIR:-}
if [ -n "$fixdir" ]; then
  netstat_out=$(/bin/cat "$fixdir/netstat") || exit 2
  ifconfig_out=$(/bin/cat "$fixdir/ifconfig") || exit 2
else
  netstat_out=$(/usr/sbin/netstat -rn -f inet)
  ifconfig_out=$(/sbin/ifconfig -a 2>/dev/null)
fi

# priv ARGV...: the only way to run anything as root. ARGV always starts with the
# literal /sbin/route at the call sites below.
priv() {
  if [ "${FIX_VMNET_ROUTE_DRYRUN:-}" = 1 ]; then
    echo "DRYRUN sudo -n $*"
  else
    /usr/bin/sudo -n "$@" >/dev/null
  fi
}

holds() { # holds BRIDGE IP: does BRIDGE have "inet IP"?
  printf '%s\n' "$ifconfig_out" | /usr/bin/awk -v b="$1" -v ip="$2" '
    /^[^ \t]/ { cur = $1; sub(/:$/, "", cur) }
    cur == b && $1 == "inet" && $2 == ip { f = 1 }
    END { exit !f }'
}

# fix_net PREFIX GWIP REPAIRABLE OBSERVE RULE
#   PREFIX     "192.168.65" (netstat shows PREFIX or PREFIX/24)
#   GWIP       the NAT gateway address a bridge must hold
#   REPAIRABLE bridges we may point the route at
#   OBSERVE    bridges that may hold GWIP but are only checked, never repaired
#   RULE       sudoers rule name for messages
# Returns 0, 1 or 3.
fix_net() {
  pfx=$1; gwip=$2; repairable=$3; observe=$4; rule=$5
  net="$pfx.0/24"
  bridge=; can_fix=0
  for b in $repairable; do
    holds "$b" "$gwip" && { bridge=$b; can_fix=1; break; }
  done
  if [ -z "$bridge" ]; then
    for b in $observe; do
      holds "$b" "$gwip" && { bridge=$b; break; }
    done
  fi
  [ -n "$bridge" ] || { say "no bridge holds $gwip (no tart VM network on $net; nothing to do)"; return 0; }

  # Every non-interface-scoped PREFIX[/24] line counts: "bad <gw>" if any goes
  # via a gateway on en0, "ok" if one is on the bridge.
  state=$(printf '%s\n' "$netstat_out" | /usr/bin/awk -v br="$bridge" -v p="$pfx" '
    ($1 == p || $1 == p "/24") && $3 !~ /I/ {
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
  if [ "$state" = ok ]; then say "$net already on $bridge (nothing to do)"; return 0; fi
  if [ "$can_fix" = 0 ]; then
    echo "fix-vmnet-route: $bridge holds $gwip and $net is not on it ($state); neither sudoers rule covers $bridge for $net; hand fix: sudo route -n add -net $net -interface $bridge (after deleting any en0 route)" >&2
    return 1
  fi
  case "$state" in
    "bad $GW") ;;
    absent) ;;  # connected route gone (e.g. after a half-done repair): just add it
    wide*)  echo "fix-vmnet-route: Tailscale's ${state#wide } (en0) covers $net and the sudoers rule does not; hand fix: sudo route -n delete -net <that net> <gw>; sudo route -n add -net $net -interface $bridge" >&2; return 1 ;;
    other*) echo "fix-vmnet-route: $net is on ${state#other }, not $bridge or en0; not touching it" >&2; return 1 ;;
    *)      echo "fix-vmnet-route: $net goes via ${state#bad } on en0, not $GW; the sudoers rule does not cover it" >&2; return 1 ;;
  esac
  miss="/etc/sudoers.d/$rule missing? run: just $rule-setup in site-public-djbclark"
  if [ "$state" = "bad $GW" ]; then
    echo "fix-vmnet-route: $net is routed via $GW (en0); restoring $bridge"
    # Constant argvs only: one literal pair per subnet and bridge.
    case "$net/$bridge" in
      192.168.65.0/24/bridge100) priv /sbin/route -n delete -net 192.168.65.0/24 192.168.68.1 ;;
      192.168.65.0/24/bridge101) priv /sbin/route -n delete -net 192.168.65.0/24 192.168.68.1 ;;
      192.168.64.0/24/bridge100) priv /sbin/route -n delete -net 192.168.64.0/24 192.168.68.1 ;;
      *) return 1 ;;
    esac || { echo "fix-vmnet-route: delete failed ($miss)" >&2; return 3; }
  fi
  case "$net/$bridge" in
    192.168.65.0/24/bridge100) priv /sbin/route -n add -net 192.168.65.0/24 -interface bridge100 ;;
    192.168.65.0/24/bridge101) priv /sbin/route -n add -net 192.168.65.0/24 -interface bridge101 ;;
    192.168.64.0/24/bridge100) priv /sbin/route -n add -net 192.168.64.0/24 -interface bridge100 ;;
    *) return 1 ;;
  esac || { echo "fix-vmnet-route: add failed ($miss); by hand: sudo route -n add -net $net -interface $bridge" >&2; return 3; }
  echo "fix-vmnet-route: restored $net -> $bridge"
  return 0
}

rc=0
fix_net 192.168.65 192.168.65.1 "bridge100 bridge101" "" tart-route; r=$?
[ "$r" -gt "$rc" ] && rc=$r
fix_net 192.168.64 192.168.64.1 "bridge100" "bridge101" container-route; r=$?
[ "$r" -gt "$rc" ] && rc=$r
exit "$rc"
