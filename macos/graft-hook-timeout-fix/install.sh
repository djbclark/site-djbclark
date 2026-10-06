#!/bin/bash
# Install the graft hook-timeout fixer: a LaunchAgent that re-runs the fixer
# whenever ~/.claude/settings.json changes (see graft-hook-timeout-fix.py).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
label=com.djbclark.graft-hook-timeout-fix
# Don't hard-code /usr/bin/python3: on this Mac it resolves to the Xcode shim
# (/Applications/Xcode.app/Contents/Developer/usr/bin/python3), which dies with
# "unable to locate xcodebuild" whenever Xcode is updating or its selected
# developer dir is stale — 82 such lines in the job log by 2026-10-03, i.e. the
# fixer silently never ran on those firings. Try each candidate, probe that it
# actually starts (an executable-but-broken shim is the whole failure mode), and
# exec the first that works. Script is stdlib-only, so any python3 will do.
PY_CANDIDATES="/opt/homebrew/bin/python3 /usr/bin/python3 /usr/local/bin/python3"
plist="$HOME/Library/LaunchAgents/$label.plist"
mkdir -p "$HOME/.local/state"
cat >"$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>-c</string>
    <string>for py in $PY_CANDIDATES; do [ -x "\$py" ] || continue; "\$py" -c pass 2>/dev/null || continue; exec "\$py" "$here/graft-hook-timeout-fix.py"; done; printf '%s no usable python3 interpreter (tried: $PY_CANDIDATES)\n' "\$(date '+%Y-%m-%d %H:%M:%S')" >>"$HOME/.local/state/graft-hook-timeout-fix.log"; exit 1</string>
  </array>
  <key>WatchPaths</key><array><string>$HOME/.claude/settings.json</string></array>
  <key>RunAtLoad</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>StandardOutPath</key><string>$HOME/.local/state/graft-hook-timeout-fix.log</string>
  <key>StandardErrorPath</key><string>$HOME/.local/state/graft-hook-timeout-fix.log</string>
</dict>
</plist>
EOF
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "installed $label (watching ~/.claude/settings.json)"
