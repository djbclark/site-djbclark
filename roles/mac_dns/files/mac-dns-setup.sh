#!/bin/bash
# One-time (and after any change to mac-dns-apply) privileged install for
# roles/mac_dns: copies the applier to a root-owned path and installs the
# narrow sudoers rule that lets the daily unattended run call it. Uses
# sudo-ask (Touch ID, shows the exact command) when available.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
src="$here/mac-dns-apply"
bin=${MAC_DNS_APPLY_BIN:-/usr/local/libexec/mac-dns-apply}
sudoers=${MAC_DNS_SUDOERS_FILE:-/etc/sudoers.d/mac-dns}
allow=${MAC_DNS_ALLOW_FILE:-/etc/mac-dns.allow}
groupvars="$here/../../../inventory/group_vars/all.yml"
operator=$(id -un)

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/sudoers" <<SUDO
# Managed by site-djbclark roles/mac_dns (installed by \`just mac-dns-setup\`).
# Lets the daily unattended \`just mac-dns-apply\` refresh /etc/resolver and the
# tailnet search domains through ONE root-owned, input-validating script.
$operator ALL=(root) NOPASSWD: $bin
SUDO
visudo -cf "$tmp/sudoers" >/dev/null || { echo "sudoers rule failed visudo -c" >&2; exit 1; }
sh -n "$src"

# The allow-list is rendered from the same group_vars the role converges from,
# so the privileged applier can only ever reproduce the declared config. Same
# line format the role asserts against (roles/mac_dns/tasks/main.yml).
"$here/render-allow-list.py" "$groupvars" > "$tmp/allow"

if [ -f "$bin" ] && cmp -s "$src" "$bin" && [ -f "$sudoers" ] && [ -f "$allow" ] && cmp -s "$tmp/allow" "$allow" \
   && sudo -n true 2>/dev/null && sudo -n cmp -s "$tmp/sudoers" "$sudoers"; then
  echo "mac-dns-setup: already installed and current ($bin, $sudoers, $allow)"; exit 0
fi

run_root() {
  if command -v sudo-ask >/dev/null 2>&1; then sudo-ask "$@"; else sudo "$@"; fi
}
run_root sh -c "install -o root -g wheel -m 0755 '$src' '$bin' && install -o root -g wheel -m 0440 '$tmp/sudoers' '$sudoers' && install -o root -g wheel -m 0644 '$tmp/allow' '$allow'"
echo "mac-dns-setup: installed $bin, $sudoers and $allow for $operator"
first_domain=$(awk '$1 == "resolver" { print $2; exit }' "$tmp/allow")
first_ns=$(awk '$1 == "nameserver" { print $2; exit }' "$tmp/allow")
sudo -n "$bin" --check resolver "$first_domain" "$first_ns" >/dev/null && echo "mac-dns-setup: sudo -n works"
