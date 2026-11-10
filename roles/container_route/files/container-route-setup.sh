#!/bin/bash
# One-time privileged install for roles/container_route: the sudoers rule that
# lets the operator run exactly two `route` commands without a password. No root
# script is installed, so there is nothing user-writable for sudo to run: the
# rule names /sbin/route and the full argument list. Uses sudo-ask (Touch ID,
# shows the exact command) when available.
export PATH="/opt/homebrew/bin:$PATH"
set -euo pipefail
sudoers=${CONTAINER_ROUTE_SUDOERS_FILE:-/etc/sudoers.d/container-route}
operator=$(id -un)

tmp=$(gmktemp -d); trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/sudoers" <<SUDO
# Managed by site-djbclark roles/container_route (installed by \`just container-route-setup\`).
# Tailscale (exit node + "Allow local network access") replaces Apple container's
# 192.168.64.0/24 -> bridge100 route with one via the en0 gateway
# (tailscale/tailscale#22119). These two commands, exact argv, no wildcards, put
# it back. Caller: cfengine-all linuxgate/fix-route.sh.
$operator ALL=(root) NOPASSWD: /sbin/route -n delete -net 192.168.64.0/24 192.168.68.1, /sbin/route -n add -net 192.168.64.0/24 -interface bridge100
SUDO
visudo -cf "$tmp/sudoers" >/dev/null || { echo "sudoers rule failed visudo -c" >&2; exit 1; }

if [ -f "$sudoers" ] && sudo -n true 2>/dev/null && sudo -n cmp -s "$tmp/sudoers" "$sudoers"; then
  echo "container-route-setup: already installed and current ($sudoers)"; exit 0
fi

run_root() {
  if command -v sudo-ask >/dev/null 2>&1; then sudo-ask "$@"; else sudo "$@"; fi
}
run_root install -o root -g wheel -m 0440 "$tmp/sudoers" "$sudoers"
echo "container-route-setup: installed $sudoers for $operator"
