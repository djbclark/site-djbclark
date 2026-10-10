#!/bin/bash
# neofinder-index-setup.sh — privileged install for the nightly index (run it
# once, and again after any change to neofinder-spotlight-index; `just setup`).
# Copies the applier to a root-owned path, writes the root-owned config naming
# the batch image, and installs the one-line sudoers rule that lets the 01:15
# Jobber job call the applier without Touch ID. Uses sudo-ask (Touch ID, shows
# the exact command) when available. Idempotent: exits 0 with "already
# installed" when everything matches, and only then needs no Touch ID.
#
# Usage: neofinder-index-setup.sh [--status | --remove]
#   NEOFINDER_IMAGE overrides the image path (default ~/nfbatch.sparseimage).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
src="$here/neofinder-spotlight-index"
bin=/usr/local/libexec/neofinder-spotlight-index
sudoers=/etc/sudoers.d/neofinder-spotlight-index
conf=/etc/neofinder-spotlight-index.conf
image=${NEOFINDER_IMAGE:-$HOME/nfbatch.sparseimage}
operator=$(id -un)

run_root() {
  if command -v sudo-ask >/dev/null 2>&1; then sudo-ask "$@"; else sudo "$@"; fi
}

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/sudoers" <<SUDO
# Managed by site-djbclark macos/neofinder (installed by \`just setup\`).
# Lets the 01:15 Jobber job index the NeoFinder batch volume through ONE
# root-owned script that takes no paths (on|off|status only).
$operator ALL=(root) NOPASSWD: $bin on, $bin off, $bin status
SUDO
printf 'image=%s\n' "$image" > "$tmp/conf"

current() {
  [ -f "$bin" ] && cmp -s "$src" "$bin" && [ -f "$conf" ] && cmp -s "$tmp/conf" "$conf" \
    && [ -f "$sudoers" ] && sudo -n "$bin" status >/dev/null 2>&1
}

case "${1:-}" in
  --status)
    echo "applier: $(ls -l "$bin" 2>/dev/null || echo "not installed")"
    if [ -f "$bin" ] && ! cmp -s "$src" "$bin"; then echo "applier: STALE (differs from $src; run just setup)"; fi
    echo "config:  $(cat "$conf" 2>/dev/null || echo "missing")"
    echo "sudoers: $(sudo -n -l "$bin" on >/dev/null 2>&1 && echo "NOPASSWD ok" || echo "missing")"
    exit 0 ;;
  --remove)
    if [ ! -e "$bin" ] && [ ! -e "$sudoers" ] && [ ! -e "$conf" ]; then
      echo "neofinder-index-setup: nothing installed"; exit 0
    fi
    run_root rm -f "$sudoers" "$bin" "$conf"
    echo "neofinder-index-setup: removed $sudoers, $bin and $conf"
    exit 0 ;;
  "") ;;
  *) echo "usage: $0 [--status | --remove]" >&2; exit 2 ;;
esac

visudo -cf "$tmp/sudoers" >/dev/null || { echo "sudoers rule failed visudo -c" >&2; exit 1; }
sh -n "$src"
[ -e "$image" ] || echo "neofinder-index-setup: note: $image does not exist yet (the batch script creates it)"

if current && sudo -n cmp -s "$tmp/sudoers" "$sudoers"; then
  echo "neofinder-index-setup: already installed and current ($bin, $sudoers, $conf)"; exit 0
fi

run_root sh -c "mkdir -p /usr/local/libexec && install -o root -g wheel -m 0755 '$src' '$bin' && install -o root -g wheel -m 0644 '$tmp/conf' '$conf' && install -o root -g wheel -m 0440 '$tmp/sudoers' '$sudoers'"
echo "neofinder-index-setup: installed $bin, $conf and $sudoers for $operator"
sudo -n "$bin" status >/dev/null && echo "neofinder-index-setup: sudo -n works"
