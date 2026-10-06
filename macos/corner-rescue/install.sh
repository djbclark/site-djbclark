#!/bin/bash
# Build corner-rescue into ~/.local/bin and (re)load its LaunchAgent.
# Also clears the native top-left hot corner so Mission Control doesn't fire
# on top of the rescue. After a rebuild, re-grant Accessibility to
# ~/.local/bin/corner-rescue (the ad-hoc signature changes each build).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
label=com.djbclark.corner-rescue
bin="$HOME/.local/bin/corner-rescue"
plist="$HOME/Library/LaunchAgents/$label.plist"

# ~/.bashrc may export DEVELOPER_DIR at a removed Xcode; CLT is enough here.
dev=/Library/Developer/CommandLineTools
[ -d "${DEVELOPER_DIR:-/nonexistent}" ] && dev="$DEVELOPER_DIR"
DEVELOPER_DIR="$dev" swiftc -O "$here/corner-rescue.swift" -o "$bin"
# Real identity (never ad hoc, per standing rule): the designated requirement
# is then identifier + certificate, so TCC grants survive rebuilds.
codesign --force --timestamp=none -i com.djbclark.corner-rescue \
  -s "Apple Development: djbclark@gmail.com (R7NDWQV585)" "$bin"

mkdir -p "$HOME/.local/state"
cat >"$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array><string>$bin</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
  <key>StandardOutPath</key><string>$HOME/.local/state/corner-rescue.out.log</string>
  <key>StandardErrorPath</key><string>$HOME/.local/state/corner-rescue.out.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"

if [ "$(defaults read com.apple.dock wvous-tl-corner 2>/dev/null || echo 1)" != 1 ]; then
  defaults write com.apple.dock wvous-tl-corner -int 1
  defaults write com.apple.dock wvous-tl-modifier -int 0
  killall Dock
fi
echo "installed: $bin ($label)"
# TCC grants are keyed to the signature; with the stable identity above they
# only need giving once (re-requesting when already granted is a no-op).
# Requesting from a launchd job makes the prompts name corner-rescue itself
# (run from a terminal, they'd be attributed to the terminal app instead).
launchctl submit -l "$label-perms" -- "$bin" --request-permissions
sleep 3; launchctl remove "$label-perms" 2>/dev/null || true
echo "Enable corner-rescue in System Settings > Privacy & Security > Input Monitoring,"
echo "Accessibility and Screen Recording, then: launchctl kickstart -k gui/$(id -u)/$label"
echo "Check: grep 'recorder: grants' ~/.local/state/corner-rescue.log | tail -1"
