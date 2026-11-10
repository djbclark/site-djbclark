#!/bin/bash
# One-time privileged install for roles/container_route: the sudoers rule that
# lets the operator run exactly two `route` commands without a password. No root
# script is installed, so there is nothing user-writable for sudo to run: the
# rule names /sbin/route and the full argument list.
#
# The rule text travels in argv of a single sudo-ask (Touch ID) step, so the
# dialog shows exactly what gets installed. Root writes it to a dotted temp name
# in /etc/sudoers.d (includedir skips names with a dot), checks that copy with
# visudo -c, then sets owner and mode and renames it into place. No user-owned
# file is validated and then trusted, and every root command is an absolute
# path (no PATH lookup).
set -euo pipefail
sudoers=/etc/sudoers.d/container-route
operator=$(/usr/bin/id -un)

content="# site-djbclark roles/container_route (just container-route-setup); tailscale#22119; caller cfengine-all linuxgate/fix-route.sh
$operator ALL=(root) NOPASSWD: /sbin/route -n delete -net 192.168.64.0/24 192.168.68.1, /sbin/route -n add -net 192.168.64.0/24 -interface bridge100"

# Idempotency check: root cmp only with an already-cached ticket (never prompts).
if [ -f "$sudoers" ] && /usr/bin/printf '%s\n' "$content" \
    | /usr/bin/sudo -n /usr/bin/cmp -s - "$sudoers" 2>/dev/null; then
  echo "container-route-setup: already installed and current ($sudoers)"; exit 0
fi

install_body='umask 077; t=/etc/sudoers.d/.container-route.new; /usr/bin/printf "%s\n" "$1" >"$t" && /usr/sbin/visudo -cqf "$t" && /usr/sbin/chown root:wheel "$t" && /bin/chmod 0440 "$t" && /bin/mv -f "$t" /etc/sudoers.d/container-route || { /bin/rm -f "$t"; exit 1; }'
if command -v sudo-ask >/dev/null 2>&1; then
  sudo-ask /bin/sh -c "$install_body" sh "$content"
else
  /usr/bin/sudo /bin/sh -c "$install_body" sh "$content"
fi
echo "container-route-setup: installed $sudoers for $operator"
