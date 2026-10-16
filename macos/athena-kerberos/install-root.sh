#!/bin/sh
# One-time, as root (run: sudo-ask /bin/sh <this file>): make /mit a synthetic
# symlink to /Users/Shared/mit, the directory attach fills with locker symlinks.
# Takes effect after the next reboot (macOS builds synthetic entries at boot).
# /usr/bin tools only: this runs as root, so no Homebrew PATH.
set -eu
conf=/etc/synthetic.conf
[ -e "$conf" ] || : > "$conf"
chmod 600 "$conf"
if ! /usr/bin/grep -q '^mit[[:space:]]' "$conf"; then
  printf 'mit\tUsers/Shared/mit\n' >> "$conf"
fi
/usr/bin/grep -E '^(afs|mit)([[:space:]]|$)' "$conf"
