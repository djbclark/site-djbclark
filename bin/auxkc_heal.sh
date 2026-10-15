#!/bin/bash
#
# auxkc_heal.sh — watchdogd "auxkc-heal" probe: re-stage a kernel-extension
# (AuxKC) rebuild that an unclean restart lost. The why and the mechanism are
# in the root half, roles/watchdogd/files/auxkc_heal_root.sh (installed as
# /usr/local/libexec/djbclark/auxkc_heal_root.sh through one sudoers line).
#
# This half does the cheap checks without root (no staged build; kcgen boot
# already armed; machine booted < 2 min ago, while kernelmanagerd is still
# cleaning up the failed round trip; already checked this boot), calls the
# root helper otherwise, logs its line, and when the helper re-staged a build
# tells the operator once via hermes-ping that a clean restart is needed.
#
# Exit codes (watchdogd command probe):
#   0  healthy — nothing staged, armed, AuxKC present, or re-staged now
#   1  the root helper is missing or failed (config problem: alert)
# Log: ~/Library/Logs/watchdogd/auxkc-heal.log.

export PATH="/opt/homebrew/bin:$PATH"
set -u

LOG_DIR="$HOME/Library/Logs/watchdogd"
LOG="$LOG_DIR/auxkc-heal.log"
STATE_DIR="${WATCHDOGD_STATE_DIR:-$HOME/.local/state/watchdogd}"
MEMO="$STATE_DIR/auxkc-heal.boot"
ROOT_HELPER=/usr/local/libexec/djbclark/auxkc_heal_root.sh
INSTR=/private/var/db/KernelExtensionManagement/AuxKC/CurrentAuxKC/com.apple.kcgen.instructions.plist
PING="$HOME/.local/bin/hermes-ping"

if [ ! -r "$INSTR" ]; then
  echo "ok: no staged kext build"
  exit 0
fi

if [ "$(nvram one-time-boot-command 2>/dev/null | gawk -F'\t' '{print $2}')" = "kcgen" ]; then
  echo "ok: kcgen boot armed, restart pending"
  exit 0
fi

boot=$(sysctl -n kern.boottime | gawk -F'[ ,]+' '{print $4}')
now=$(gdate +%s)
if [ $((now - boot)) -lt 120 ]; then
  echo "ok: booted $((now - boot)) s ago, waiting for kernelmanagerd"
  exit 0
fi
if [ -r "$MEMO" ] && [ "$(cat "$MEMO")" = "$boot" ]; then
  echo "ok: checked this boot"
  exit 0
fi

if [ ! -x "$ROOT_HELPER" ]; then
  echo "root helper missing: $ROOT_HELPER (roles/watchdogd/README.md install lines)"
  exit 1
fi

out=$(sudo -n "$ROOT_HELPER" 2>&1)
rc=$?
mkdir -p "$LOG_DIR" "$STATE_DIR"
echo "$(gdate '+%F %T') rc=$rc $out" >>"$LOG"
case "$out" in
  restaged:*)
    echo "$boot" >"$MEMO"
    "$PING" "site-djbclark: watchdogd auxkc-heal re-staged the kernel-extension rebuild the last unclean restart lost ($out). Restart cleanly to finish it; the 'System software from Apple Inc. was updated' dialog can be ignored until then." >/dev/null 2>&1 || true
    ;;
  ok:*)
    echo "$boot" >"$MEMO"
    ;;
esac
echo "$out"
exit $rc
