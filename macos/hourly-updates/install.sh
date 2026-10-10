#!/bin/bash
# Install (or refresh) the com.djbclark.hourly-updates LaunchAgent.
#
# The plist lives beside this script (macos/hourly-updates/); the generic runner
# it launches is bin/hourly-updates, whose per-app scripts sit in
# bin/hourly-updates.d/. Add an app by dropping one executable file there.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
label="com.djbclark.hourly-updates"
cp "$here/$label.plist" "$HOME/Library/LaunchAgents/$label.plist"
exec "$HOME/ops/site-djbclark/bin/launchd_reload.sh" "$label"
