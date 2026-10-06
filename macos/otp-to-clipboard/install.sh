#!/bin/bash
# Build, sign and (re)load otp-to-clipboard's two LaunchAgents.
#   com.djbclark.otp-banner-watch  Swift helper: reads banners from Notification
#                                  Center's accessibility tree (fast path)
#   com.djbclark.otp-to-clipboard  Python daemon: polls the usernoted DB (fallback)
# Detail and findings: site-private/memory/reference_otp_to_clipboard_2026-10-06.md
#
# Grants (System Settings > Privacy & Security), each given once:
#   Accessibility        -> ~/.local/bin/otp-banner-watch (signed with a stable
#                           identity, so rebuilds keep the grant)
#   Full Disk Access     -> the Python.app binary named in the DB plist. launchd
#                           must run THAT binary directly: FDA is checked against
#                           the process launchd starts, and /usr/bin/python3 is a
#                           shim that never gets the grant.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
uid=$(id -u)
bin="$HOME/.local/bin/otp-banner-watch"

# ~/.bashrc may export DEVELOPER_DIR at a removed Xcode; CLT is enough here.
dev=/Library/Developer/CommandLineTools
[ -d "${DEVELOPER_DIR:-/nonexistent}" ] && dev="$DEVELOPER_DIR"
DEVELOPER_DIR="$dev" swiftc -O "$here/otp-banner-watch.swift" -o "$bin"
codesign --force --timestamp=none -i com.djbclark.otp-banner-watch \
  -s "Apple Development: djbclark@gmail.com (R7NDWQV585)" "$bin"

py=$(sed -n 's#.*<string>\(/Applications/Xcode.app[^<]*/MacOS/Python\)</string>.*#\1#p' \
  "$here/com.djbclark.otp-to-clipboard.plist")
[ -x "$py" ] || echo "warning: $py missing (Xcode moved?): fix the DB plist and re-grant Full Disk Access" >&2

for label in com.djbclark.otp-banner-watch com.djbclark.otp-to-clipboard; do
  cp "$here/$label.plist" "$HOME/Library/LaunchAgents/$label.plist"
  launchctl bootout "gui/$uid/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$uid" "$HOME/Library/LaunchAgents/$label.plist"
done
echo "installed: $bin and both agents"
echo "logs: ~/Library/Logs/otp-banner-watch.log  ~/Library/Logs/otp-to-clipboard.log"
echo "DB agent takes ~10-70 s to log 'started' (first load of Xcode's Python)"
# First install only: trigger the Accessibility prompt so it names the helper.
launchctl submit -l com.djbclark.otp-banner-watch-perms -- "$bin" --request-permissions
sleep 3; launchctl remove com.djbclark.otp-banner-watch-perms 2>/dev/null || true
