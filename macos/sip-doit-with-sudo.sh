#!/bin/bash

# Reviewed 2026-10-04 (zcode session). This is the downloaded original's
# daemon set, restored in full at the operator's request — the ONLY change
# kept from the review: the AMFI bypass line was removed and stays out
# (nvram boot-args=amfi_get_out_of_my_way=1 disables AMFI = unsigned code
# runs system-wide; it also cannot be set while SIP is enabled — sudo does
# not bypass SIP). One addition: kill the leftover powermetrics from the
# 2026-10-04 morning diagnostics.
#
# Operator-verified preconditions (2026-10-04):
#   - No iCloud account is signed in (MobileMeAccounts domain absent), so
#     disabling cloudd loses nothing now. RE-ENABLE IT before ever signing
#     into an Apple ID, or iCloud will silently not sync:
#     launchctl enable gui/<uid>/com.apple.cloudd
#   - suggestd's stuck-harvesting loop was already fixed via DB reset
#     (0% CPU over a 10-min watch); it is disabled here as a precaution.

if [ "$EUID" -ne 0 ]; then
  echo "Error: This script must be run as root. Please run using: sudo $0"
  exit 1
fi

CONSOLE_USER=$(stat -f "%Su" /dev/console)
CONSOLE_UID=$(stat -f "%u" /dev/console)

echo "Applying user-level (GUI) overrides for: $CONSOLE_USER (UID: $CONSOLE_UID)"
echo "------------------------------------------------------------------"

GUI_DAEMONS=(
  "com.apple.suggestd"
  "com.apple.cloudd"
  "com.apple.photoanalysisd"
  "com.apple.triald"
  "com.apple.helpd"
)

for daemon in "${GUI_DAEMONS[@]}"; do
  echo "Disabling $daemon..."
  launchctl bootout gui/"$CONSOLE_UID"/"$daemon" 2>/dev/null
  launchctl disable gui/"$CONSOLE_UID"/"$daemon"
  killall "${daemon##*.}" 2>/dev/null
done

echo ""
echo "Applying system-level (Root) overrides"
echo "------------------------------------------------------------------"

SYSTEM_DAEMONS=(
  "com.apple.spindump"
  "com.apple.tailspind"
)

for daemon in "${SYSTEM_DAEMONS[@]}"; do
  echo "Disabling $daemon..."
  launchctl bootout system/"$daemon" 2>/dev/null
  launchctl disable system/"$daemon"
  killall "${daemon##*.}" 2>/dev/null
done

echo ""
echo "Killing leftover powermetrics from the 2026-10-04 morning diagnostics..."
PIDS=$(pgrep -f '/usr/bin/powermetrics .*--samplers')
if [ -n "$PIDS" ]; then
  ps -p $PIDS -o pid,lstart,command
  kill $PIDS
  sleep 1
  pgrep -f '/usr/bin/powermetrics .*--samplers' >/dev/null \
    && echo "WARNING: still running, escalate with: sudo kill -9 $PIDS" \
    || echo "powermetrics gone."
else
  echo "No powermetrics running (already cleaned up)."
fi

echo ""
echo "Post-state of the targeted daemons:"
for daemon in "${GUI_DAEMONS[@]}" "${SYSTEM_DAEMONS[@]}"; do
  P=$(pgrep -x "${daemon##*.}")
  if [ -n "$P" ]; then
    echo "  $daemon: STILL RUNNING (pid $P) — SIP may block bootout; the"
    echo "    disable flag still applies at next login."
  else
    echo "  $daemon: stopped."
  fi
done

echo ""
echo "Top CPU consumers right now (for the record):"
ps -Arco pcpu,time,comm | head -8
