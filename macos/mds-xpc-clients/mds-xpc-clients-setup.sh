#!/bin/bash
# mds-xpc-clients-setup.sh: privileged install of the root-owned mds XPC-peer helper and its one sudoers line.
# Installs EXACTLY the committed bytes: refuses unless the working file equals `git show HEAD:<path>`, installs,
# then checks the installed file's sha256 against the committed blob and removes it on a mismatch.
# Uses sudo-ask (Touch ID, shows the exact command) when available. Idempotent.
# Usage: mds-xpc-clients-setup.sh [--status | --remove]
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:$PATH"
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
src="$here/mds-xpc-clients"
bin=/usr/local/libexec/djbclark/mds-xpc-clients
sudoers=/etc/sudoers.d/mds-xpc-clients
operator=$(id -un)

run_root() { if command -v sudo-ask >/dev/null 2>&1; then sudo-ask "$@"; else sudo "$@"; fi; }
sha() { shasum -a 256 "$1" | cut -d' ' -f1; }

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
# the trailing "" forbids every argument
printf '%s\n' "# Managed by site-djbclark macos/mds-xpc-clients (mds-xpc-clients-setup.sh). One root-owned, argument-free" \
  "# helper that prints COUNT PID NAME of the processes holding a send right to mds (load-watch mds probe)." \
  "$operator ALL=(root) NOPASSWD: $bin \"\"" > "$tmp/sudoers"

case "${1:-}" in
  --status)
    echo "helper:  $(ls -l "$bin" 2>/dev/null || echo "not installed")"
    if [ -f "$bin" ]; then echo "sha256:  installed $(sha "$bin")  source $(sha "$src")"; fi
    echo "sudoers: $(ls -l "$sudoers" 2>/dev/null || echo "missing")"
    exit 0 ;;
  --remove)
    run_root rm -f "$sudoers" "$bin"
    echo "mds-xpc-clients-setup: removed $sudoers and $bin"; exit 0 ;;
  "") ;;
  *) echo "usage: $0 [--status | --remove]" >&2; exit 2 ;;
esac

sh -n "$src"
visudo -cf "$tmp/sudoers" >/dev/null || { echo "sudoers rule failed visudo -c" >&2; exit 1; }
rel=$(git -C "$here" rev-parse --show-prefix)mds-xpc-clients
git -C "$here" show "HEAD:$rel" > "$tmp/committed" || { echo "helper is not committed at HEAD:$rel" >&2; exit 1; }
want=$(sha "$tmp/committed")
[ "$(sha "$src")" = "$want" ] || { echo "working file differs from the committed one: commit first" >&2; exit 1; }

if [ -f "$bin" ] && [ "$(sha "$bin")" = "$want" ] && [ -f "$sudoers" ] && sudo -n cmp -s "$tmp/sudoers" "$sudoers"; then
  echo "mds-xpc-clients-setup: already installed and current (sha256 $want)"; exit 0
fi

# install the committed copy staged in $tmp (the bytes just hashed), never the live working file
run_root mkdir -p /usr/local/libexec/djbclark
run_root install -o root -g wheel -m 0755 "$tmp/committed" "$bin"
if [ "$(sha "$bin")" != "$want" ]; then
  run_root rm -f "$bin"; echo "installed file's sha256 differs from the committed one: removed" >&2; exit 1
fi
run_root install -o root -g wheel -m 0440 "$tmp/sudoers" "$sudoers"
run_root visudo -c >/dev/null || { run_root rm -f "$sudoers"; echo "visudo -c failed: sudoers line removed" >&2; exit 1; }
echo "mds-xpc-clients-setup: installed $bin (sha256 $want) and $sudoers for $operator"
