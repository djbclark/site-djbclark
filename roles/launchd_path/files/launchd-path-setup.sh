#!/bin/bash
# One-time (and after any change to launchd-path-apply) privileged install for
# roles/launchd_path: copies the applier to a root-owned path and installs the
# narrow sudoers rule that lets `just launchd-path-apply` / `just deploy-mac`
# call it without a password. Uses sudo-ask (Touch ID, shows the exact command)
# when available.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
src="$here/launchd-path-apply"
bin=${LAUNCHD_PATH_APPLY_BIN:-/usr/local/libexec/launchd-path-apply}
sudoers=${LAUNCHD_PATH_SUDOERS_FILE:-/etc/sudoers.d/launchd-path}
operator=$(id -un)

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/sudoers" <<SUDO
# Managed by site-djbclark roles/launchd_path (installed by \`just launchd-path-setup\`).
# Lets \`just launchd-path-apply\` / \`just deploy-mac\` keep launchd's per-user PATH
# equal to the login-shell PATH through ONE root-owned, input-validating script.
$operator ALL=(root) NOPASSWD: $bin
SUDO
visudo -cf "$tmp/sudoers" >/dev/null || { echo "sudoers rule failed visudo -c" >&2; exit 1; }
sh -n "$src"

if [ -f "$bin" ] && cmp -s "$src" "$bin" && [ -f "$sudoers" ] \
   && sudo -n true 2>/dev/null && sudo -n cmp -s "$tmp/sudoers" "$sudoers"; then
  echo "launchd-path-setup: already installed and current ($bin, $sudoers)"; exit 0
fi

run_root() {
  if command -v sudo-ask >/dev/null 2>&1; then sudo-ask "$@"; else sudo "$@"; fi
}
run_root sh -c "install -d -o root -g wheel -m 0755 '$(dirname "$bin")' && install -o root -g wheel -m 0755 '$src' '$bin' && install -o root -g wheel -m 0440 '$tmp/sudoers' '$sudoers'"
echo "launchd-path-setup: installed $bin and $sudoers for $operator"
sudo -n "$bin" --check /usr/bin:/bin:/usr/sbin:/sbin >/dev/null && echo "launchd-path-setup: sudo -n works"
