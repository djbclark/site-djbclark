#!/bin/bash
# Install the athena-kerberos pieces for the current user (idempotent):
#   ~/Library/Preferences/edu.mit.Kerberos -> edu.mit.Kerberos (ATHENA realm,
#                                             forwardable + renewable TGTs)
#   ~/.ssh/config.d/mit                    -> ssh_config.mit (Include it from
#                                             ~/.ssh/config above "Host *")
#   ~/.local/bin/mosh                      -> mosh wrapper
#   LaunchAgent com.djbclark.athena-kinit  hourly renew + push to the dialup
# First run only: `athena-kinit init` (password dialog, saved to Keychain).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
uid=$(id -u)
label=com.djbclark.athena-kinit

ln -sfn "$here/edu.mit.Kerberos" "$HOME/Library/Preferences/edu.mit.Kerberos"
mkdir -p "$HOME/.ssh/config.d" "$HOME/.ssh/cm" "$HOME/.local/bin"
chmod 700 "$HOME/.ssh/cm"
ln -sfn "$here/ssh_config.mit" "$HOME/.ssh/config.d/mit"
ln -sfn "$here/mosh" "$HOME/.local/bin/mosh"
grep -q 'config.d/mit' "$HOME/.ssh/config" 2>/dev/null ||
  echo "add near the top of ~/.ssh/config: Include ~/.ssh/config.d/mit" >&2

cp "$here/$label.plist" "$HOME/Library/LaunchAgents/$label.plist"
launchctl bootout "gui/$uid/$label" 2>/dev/null || true
launchctl bootstrap "gui/$uid" "$HOME/Library/LaunchAgents/$label.plist"
echo "installed; log: ~/Library/Logs/athena-kinit.log"
klist -s 2>/dev/null || echo "no ticket yet: run $here/athena-kinit init"
