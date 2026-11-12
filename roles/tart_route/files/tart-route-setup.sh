#!/bin/bash
# One-time privileged install for roles/tart_route: the sudoers rule that lets
# the operator run exactly three `route` commands without a password, so the
# unprivileged fix-vmnet-route.sh can repair tart's shared-NAT network
# (192.168.65.0/24) after Tailscale replaces its route. No root script is
# installed, so there is nothing user-writable for sudo to run: the rule names
# /sbin/route (root-owned, SIP-protected) and the full argument lists.
#
# Same shape as roles/container_route/files/container-route-setup.sh: the rule
# text travels in argv of a single sudo-ask (Touch ID) step, so the dialog shows
# exactly what gets installed. Root writes it to a dotted temp name in
# /etc/sudoers.d (includedir skips names with a dot), checks that copy with
# visudo -c, then sets owner and mode and renames it into place. Every root
# command is an absolute path (no PATH lookup).
set -euo pipefail
sudoers=/etc/sudoers.d/tart-route
operator=$(/usr/bin/id -un)

content="# site-djbclark roles/tart_route (just tart-route-setup); tailscale#22119; caller ~/.orchard/fix-vmnet-route.sh
$operator ALL=(root) NOPASSWD: /sbin/route -n delete -net 192.168.65.0/24 192.168.68.1, /sbin/route -n add -net 192.168.65.0/24 -interface bridge100, /sbin/route -n add -net 192.168.65.0/24 -interface bridge101"

# Idempotency check: root cmp only with an already-cached ticket (never prompts).
if [ -f "$sudoers" ] && /usr/bin/printf '%s\n' "$content" \
    | /usr/bin/sudo -n /usr/bin/cmp -s - "$sudoers" 2>/dev/null; then
  echo "tart-route-setup: already installed and current ($sudoers)"; exit 0
fi

# shellcheck disable=SC2016 # "$1"/"$t" expand in root's sh, not here
install_body='umask 077; t=/etc/sudoers.d/.tart-route.new; /usr/bin/printf "%s\n" "$1" >"$t" && /usr/sbin/visudo -cqf "$t" && /usr/sbin/chown root:wheel "$t" && /bin/chmod 0440 "$t" && /bin/mv -f "$t" /etc/sudoers.d/tart-route || { /bin/rm -f "$t"; exit 1; }'
# sudo-ask cuts its dialog at 700 chars, and the rule line is the tail.
shown=$(printf '%q ' /bin/sh -c "$install_body" sh "$content")
[ ${#shown} -le 700 ] || { echo "tart-route-setup: dialog text is ${#shown} chars (>700); sudo-ask would hide the rule" >&2; exit 1; }
if [ "${1:-}" = "--print" ]; then
  printf '%s\n' "$content"; echo "(dialog text ${#shown} chars)"; exit 0
fi
if command -v sudo-ask >/dev/null 2>&1; then
  sudo-ask /bin/sh -c "$install_body" sh "$content"
else
  /usr/bin/sudo /bin/sh -c "$install_body" sh "$content"
fi
echo "tart-route-setup: installed $sudoers for $operator"
