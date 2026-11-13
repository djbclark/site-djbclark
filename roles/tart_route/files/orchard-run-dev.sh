#!/bin/bash
# launchd job com.djbclark.orchard-dev runs this (installed copy:
# ~/.orchard/run-dev.sh; source: site-public-djbclark roles/tart_route/files/).
# Kept under its old name so the LaunchAgent plist and label do not change; the
# work is in orchard-launch.py (loopback-only authenticated controller + worker
# bigmac + the vmnet route watcher). `orchard dev` is no longer used: it listens
# on *:6120 with authentication disabled.
exec /opt/homebrew/bin/python3 -I "$HOME/.orchard/orchard-launch.py"
