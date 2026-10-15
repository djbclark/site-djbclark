#!/bin/bash
#
# auxkc_heal_root.sh — root half of the watchdogd "auxkc-heal" rule
# (bin/auxkc_heal.sh is the user half). Runs through exactly one sudoers line
# (files/sudoers.auxkc-heal), no arguments, no environment.
#
# One job: if the operator approved a kernel-extension rebuild in Privacy &
# Security (kernelmanager_helper stages the kexts and the kcgen instructions
# under /private/var/db/KernelExtensionManagement/AuxKC/CurrentAuxKC and arms
# NVRAM one-time-boot-command=kcgen) but the restart that was to build the
# auxiliary kernel collection never completed cleanly (shutdown stall → hard
# reset, power loss, panic), the staging is lost: on Apple silicon kcgend only
# runs during a clean restart, kernelmanagerd then logs "Kcgen roundtrip
# failed: found an instruction plist but not a checkpoint plist", and the
# "System software from Apple Inc. was updated, restart" dialog returns. This
# re-stages it with `kmutil load -z -b <id>` (root; -z skips the approval
# check that the dialog's OK already answered), which arms the kcgen boot
# again; the next clean restart builds the AuxKC without operator action.
#
# It never approves anything new: it only re-requests the bundle ids already
# in the staged instructions plist, which exist only because the operator
# clicked OK once. Nothing to do when no build is staged, when the kcgen boot
# is already armed, or when the AuxKC exists (bputil: auxi present).
#
# Output: one line ("ok: ...", "restaged: ...", "fail: ..."); exit 0 unless
# the re-stage failed (1). Root tools only (/usr/bin, /usr/sbin, /usr/libexec,
# fixed PATH): a brew g* tool here would put user-writable /opt/homebrew/bin
# on root's PATH (.gnu-tools-check-ignore).

PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
set -u

INSTR=/private/var/db/KernelExtensionManagement/AuxKC/CurrentAuxKC/com.apple.kcgen.instructions.plist

boot_command() {
  nvram one-time-boot-command 2>/dev/null | awk -F'\t' '{print $2}'
}

if [ ! -r "$INSTR" ]; then
  echo "ok: no staged kext build"
  exit 0
fi

if [ "$(boot_command)" = "kcgen" ]; then
  echo "ok: kcgen boot armed, restart pending"
  exit 0
fi

auxi=$(bputil -d 2>/dev/null | awk -F: '/Auxiliary Kernel Cache Image4 Hash/ {gsub(/^ +| +$/, "", $2); print $2}')
if [ -n "${auxi:-}" ] && [ "$auxi" != "absent" ]; then
  echo "ok: auxkc present"
  exit 0
fi

ids=$(plutil -extract kextsToBuild raw -o - "$INSTR" 2>/dev/null | tr '\n' ' ')
if [ -z "${ids// /}" ]; then
  echo "fail: no bundle ids in $INSTR"
  exit 1
fi

for id in $ids; do
  # The expected "error" is "Loading extension(s): <id> requires a reboot":
  # that is the staging succeeding.
  kmutil load -z -b "$id" >/dev/null 2>&1 || true
done

if [ "$(boot_command)" = "kcgen" ]; then
  echo "restaged: ${ids% }; kcgen boot armed, a clean restart builds the AuxKC"
  exit 0
fi
echo "fail: kmutil load -z did not arm the kcgen boot for: ${ids% }"
exit 1
