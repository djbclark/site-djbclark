#!/bin/bash
# Install the athena-kerberos pieces for the current user (idempotent):
#   ~/Library/Preferences/edu.mit.Kerberos -> edu.mit.Kerberos (ATHENA realm,
#                                             forwardable + renewable TGTs)
#   ~/.ssh/config.d/mit                    -> ssh_config.mit (Include it from
#                                             ~/.ssh/config above "Host *")
#   ~/.local/bin/mosh                      -> mosh wrapper
#   LaunchAgent com.djbclark.athena-kinit  hourly renew + AFS token + push to the dialup
#   athena-locker (attach/detach/add/fsid) + LaunchAgent com.djbclark.athena-lockers
# First run only: `athena-kinit init` (password dialog, saved to Keychain).
export PATH="/opt/homebrew/bin:$PATH"
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
uid=$(id -u)
label=com.djbclark.athena-kinit

ln -sfn "$here/edu.mit.Kerberos" "$HOME/Library/Preferences/edu.mit.Kerberos"
mkdir -p "$HOME/.ssh/config.d" "$HOME/.ssh/cm" "$HOME/.local/bin"
chmod 700 "$HOME/.ssh/cm"
ln -sfn "$here/ssh_config.mit" "$HOME/.ssh/config.d/mit"
ln -sfn "$here/mosh" "$HOME/.local/bin/mosh"
ggrep -q 'config.d/mit' "$HOME/.ssh/config" 2>/dev/null ||
  echo "add near the top of ~/.ssh/config: Include ~/.ssh/config.d/mit" >&2

cp "$here/$label.plist" "$HOME/Library/LaunchAgents/$label.plist"
launchctl bootout "gui/$uid/$label" 2>/dev/null || true
launchctl bootstrap "gui/$uid" "$HOME/Library/LaunchAgents/$label.plist"
echo "installed; log: ~/Library/Logs/athena-kinit.log"

# AFS lockers: attach/detach/add/fsid (one script, symlinked under each name),
# the `add` shell function, and the LaunchAgent that pre-attaches the lockers
# in ~/.config/athena/lockers into /mit (a synthetic symlink to /Users/Shared/mit,
# created once as root by install-root.sh; /afs itself comes from the AuriStor pkg).
ln -sfn "$here/athena-locker" "$HOME/.local/bin/athena-locker"
for c in attach detach fsid; do ln -sfn athena-locker "$HOME/.local/bin/$c"; done
ln -sfn athena-locker "$HOME/.local/bin/add"
mkdir -p "$HOME/.config/athena" /Users/Shared/mit
[ -e "$HOME/.config/athena/lockers" ] || printf 'djbclark\nsipb\nconsult\nscripts\n' > "$HOME/.config/athena/lockers"
ggrep -q 'athena-locker.sh' "$HOME/.bashrc.local" 2>/dev/null ||
  printf '\n# Athena `add` (site-djbclark macos/athena-kerberos)\n[ -r "%s/athena-locker.sh" ] && . "%s/athena-locker.sh"\n' "$here" "$here" >> "$HOME/.bashrc.local"
llabel=com.djbclark.athena-lockers
cp "$here/$llabel.plist" "$HOME/Library/LaunchAgents/$llabel.plist"
launchctl bootout "gui/$uid/$llabel" 2>/dev/null || true
launchctl bootstrap "gui/$uid" "$HOME/Library/LaunchAgents/$llabel.plist"
echo "installed lockers agent; log: ~/Library/Logs/athena-lockers.log"
klist -s 2>/dev/null || echo "no ticket yet: run $here/athena-kinit init"
