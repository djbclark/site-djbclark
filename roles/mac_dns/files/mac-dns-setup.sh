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

if [ -f "$bin" ] && cmp -s "$src" "$bin" && [ -f "$sudoers" ] && sudo -n true 2>/dev/null \
   && sudo -n cmp -s "$tmp/sudoers" "$sudoers"; then
  echo "mac-dns-setup: already installed and current ($bin, $sudoers)"; exit 0
fi

run_root() {
  if command -v sudo-ask >/dev/null 2>&1; then sudo-ask "$@"; else sudo "$@"; fi
}
run_root sh -c "install -o root -g wheel -m 0755 '$src' '$bin' && install -o root -g wheel -m 0440 '$tmp/sudoers' '$sudoers'"
echo "mac-dns-setup: installed $bin and $sudoers for $operator"
sudo -n "$bin" --check resolver example.ts.net 100.100.100.100 >/dev/null && echo "mac-dns-setup: sudo -n works"
