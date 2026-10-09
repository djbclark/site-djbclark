#!/bin/bash
#
# neofinder-spotlight-batch.sh — batch-mode Spotlight over exported NeoFinder
# data. On a machine that normally runs with Spotlight quiet: bring the mds
# daemon up, turn indexing off for '/' so it does not chew through the primary
# drive's modification backlog, index a dedicated staging volume only, hold
# the daemon open while the operator searches in Finder / Smart Folders, then
# tear everything back down (also on Ctrl-C). Teardown is idempotent; exit 0
# when the run converged — an SIP-blocked bootout is a warning, not a failure.
#
# Usage:
#   sudo ./neofinder-spotlight-batch.sh [--staging PATH] [--image FILE]
#                                       [--keep-mds] [--leave-root-off]
#                                       [--dry-run] [--verbose]
#   ./neofinder-spotlight-batch.sh --status    read-only: SIP, mds loaded?,
#                                               mdutil -s for / and the staging
#                                               point, importer list
#   ./neofinder-spotlight-batch.sh --help
#
#   --staging PATH     mount point to index (default /Volumes/NeoFinderBatch);
#                      must be a real mount point, mdutil requires one
#   --image FILE       sparse disk image to attach at the staging point first,
#                      created as a 4 GB APFS SPARSE image if missing; give it
#                      a .sparseimage extension or hdiutil appends one
#   --keep-mds         skip the final mds bootout deliberately
#   --leave-root-off   do not restore '/' indexing at teardown
#   --dry-run          print every privileged command prefixed "+ ", run none,
#                      skip the interactive pause; works unprivileged
#   --verbose          mdimport -t -d1 over the whole staging volume instead
#                      of one sample file
#
# Known limits / decisions (facts checked on this machine, macOS 27.0.1 build
# 26A434, 2026-10-09):
#
#   A. SIP is enabled here and refuses `launchctl bootout` of Apple's own
#      LaunchDaemons ("Operation not permitted..."; operator-verified
#      2026-10-04, see sip-doit-with-sudo.sh). Teardown still attempts the
#      bootout; when the error is the SIP refusal it says so (any other
#      error is shown as itself), reports that mds stays resident with
#      staging indexing off and '/' restored or left off as chosen, and
#      lists what is still running (`pgrep -l 'mds|mds_stores|mdworker'`).
#      --keep-mds skips the attempt. If mds is already loaded when the script
#      starts, the bootstrap is skipped and recorded as "this script did not
#      start mds".
#   B. Indexing on '/' was ENABLED here before the run. The prior state is
#      recorded before anything is touched and restored at teardown only if
#      it was enabled; re-enabling may make Spotlight reindex '/' (one-line
#      warning at restore time). --leave-root-off skips the restore. When
#      the prior state cannot be read (e.g. "Spotlight server is disabled",
#      which `mdutil -s` also says from inside an app sandbox) the run
#      refuses to touch '/' rather than guess.
#   C. `mdimport -d1` alone is only a TEST import on this macOS (man
#      mdimport: -d "requires -t"; -t "attributes will not be stored in the
#      Spotlight index"). The stored import is `mdimport -i` — the implied
#      default, recursive for a directory — and the -d1 wish is satisfied
#      with a clearly labelled `mdimport -t -d1` diagnostic that stores
#      nothing.
#   D. NeoFinder ships no Spotlight importer (`mdimport -L` lists none; no
#      /Applications/NeoFinder.app/Contents/Library/Spotlight). Per the
#      vendor FAQ (https://cdfinder.de/guide/25/faq.html, "Can Spotlight
#      search NeoFinder catalog files?"), Spotlight cannot search catalog
#      contents, so the staging volume must hold EXPORTED data (text/CSV/HTML
#      exports or a folder tree), not the raw *.neofinder7 catalogs. This
#      script indexes whatever regular files are at the staging path and
#      never exports from NeoFinder itself.
#   E. The staging path must be a mount point other than '/' and
#      /System/Volumes/Data (same device counts as the same volume), or the
#      "global exclusion" of requirement 2 would be undone by requirement 3.
#      Every mdutil/mdimport/hdiutil step that changes state is checked: a
#      setup failure aborts through the teardown; a teardown failure is
#      listed with the command to rerun by hand, mds is left up so the retry
#      can work, and the exit status is 1. Obligations are recorded before
#      the command that creates them and INT/TERM are ignored once teardown
#      has begun, so a Ctrl-C cannot skip a restore.
#
# History:
#   - 2026-10-09: written; facts A-D above verified on this machine the same
#     day. `hdiutil create` is deprecated on this macOS in favour of
#     `diskutil image create` but kept here: it still works and is the
#     portable recipe. Same day, after an adversarial review (codex): status
#     checks on every mutating step, '/' and the Data volume rejected as
#     staging, obligations recorded before the command, teardown immune to a
#     second Ctrl-C, unknown root state refused, --image attach failures
#     fatal, bootout errors no longer blamed on SIP unseen (limit E).

set -u

MDS_SERVICE=system/com.apple.metadata.mds
MDS_PLIST=/System/Library/LaunchDaemons/com.apple.metadata.mds.plist
STAGING_DEFAULT=/Volumes/NeoFinderBatch

STAGING=$STAGING_DEFAULT
IMAGE=
KEEP_MDS=0
LEAVE_ROOT_OFF=0
DRY_RUN=0
VERBOSE=0
STATUS_ONLY=0

# Teardown bookkeeping: what this run actually changed (all checked by the
# idempotent teardown, which runs on EXIT/INT/TERM).
WE_STARTED_MDS=0
ROOT_TOUCHED=0
ROOT_WAS_ON=0
STAGING_ON=0
IMAGE_ATTACHED=0
TEARDOWN_RAN=0
TEARDOWN_FAILED=0
ROOT_STATE_OUT=
SAMPLE_FILE=

ORIG_ARGS=("$@")

while [ $# -gt 0 ]; do
  case "$1" in
    --staging)
      [ $# -ge 2 ] || { echo "Error: --staging needs a path argument." >&2; exit 2; }
      STAGING=$2; shift 2 ;;
    --image)
      [ $# -ge 2 ] || { echo "Error: --image needs a file argument." >&2; exit 2; }
      IMAGE=$2; shift 2 ;;
    --keep-mds) KEEP_MDS=1; shift ;;
    --leave-root-off) LEAVE_ROOT_OFF=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --verbose) VERBOSE=1; shift ;;
    --status) STATUS_ONLY=1; shift ;;
    -h|--help) sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Error: unknown argument: $1 (use --staging, --image, --keep-mds, --leave-root-off, --dry-run, --verbose, --status or --help)" >&2; exit 2 ;;
  esac
done

[ -n "$STAGING" ] || { echo "Error: --staging needs a non-empty path." >&2; exit 2; }
[ "$STAGING" != "/" ] && STAGING=${STAGING%/}

# run CMD...: echo the command prefixed "+ ", then execute it — unless
# --dry-run, in which case nothing runs. The echoed line is display only
# ($* collapses quoting); the invocation below keeps each argument intact.
run() {
  echo "+ $*"
  [ "$DRY_RUN" -eq 1 ] && return 0
  "$@"
}

sip_enabled() { csrutil status 2>/dev/null | grep -q 'status: enabled'; }

# mds_loaded: 0 when launchd has the mds service loaded (the launchctl query
# works unprivileged on this machine, so --status/--dry-run can use it too).
mds_loaded() { launchctl print "$MDS_SERVICE" >/dev/null 2>&1; }

# is_mountpoint PATH: 0 when PATH is itself a mount point. Compares st_dev of
# the directory against its parent's; "/" (whose parent is itself) is
# special-cased. No grep over `mount` output, so odd characters in PATH are
# safe.
is_mountpoint() {
  [ -d "$1" ] || return 1
  [ "$1" = "/" ] && return 0
  [ "$(stat -f %d "$1")" != "$(stat -f %d "$1/..")" ]
}

# root_index_state: 0 = '/' indexing enabled, 1 = disabled, 2 = unknown.
root_index_state() {
  ROOT_STATE_OUT=$(mdutil -s / 2>&1 | tr -d '\t' | tr '\n' ' ')
  echo "$ROOT_STATE_OUT" | grep -qi 'indexing enabled' && return 0
  echo "$ROOT_STATE_OUT" | grep -qi 'indexing disabled' && return 1
  return 2
}

# is_system_volume PATH: 0 when PATH is '/', the Data volume, or on the same
# device as either (so a symlink such as /Volumes/Macintosh\ HD counts too).
is_system_volume() {
  case "$1" in /|/System/Volumes/Data) return 0 ;; esac
  local dev root_dev data_dev
  dev=$(stat -f %d "$1" 2>/dev/null) || return 1
  root_dev=$(stat -f %d / 2>/dev/null)
  data_dev=$(stat -f %d /System/Volumes/Data 2>/dev/null || echo "$root_dev")
  [ "$dev" = "$root_dev" ] || [ "$dev" = "$data_dev" ]
}

# attach_image: create the --image sparse image if missing and attach it at
# the staging point. IMAGE_ATTACHED is set only when the attach succeeded
# (or was merely printed under --dry-run, which always "succeeds").
attach_image() {
  echo "  --image $IMAGE"
  if is_mountpoint "$STAGING"; then
    echo "Error: $STAGING is already a mount point; with --image it must be free (detach it first, or omit --image to index what is mounted there)." >&2
    exit 2
  fi
  if [ ! -e "$IMAGE" ]; then
    echo "  image does not exist; creating a 4 GB APFS sparse image (grows on demand)"
    run hdiutil create -size 4g -fs APFS -volname "${STAGING##*/}" -type SPARSE "$IMAGE" \
      || { echo "Error: hdiutil create failed; nothing was changed." >&2; exit 1; }
  fi
  run mkdir -p "$STAGING" || { echo "Error: cannot create $STAGING." >&2; exit 1; }
  IMAGE_ATTACHED=1   # obligation recorded before the command (a signal could land between)
  if ! run hdiutil attach -mountpoint "$STAGING" "$IMAGE"; then
    is_mountpoint "$STAGING" || IMAGE_ATTACHED=0
    echo "Error: hdiutil attach failed; not continuing against whatever is at $STAGING." >&2
    exit 1
  fi
}

preflight() {
  echo ""
  echo "1/6 preflight"
  echo "------------------------------------------------------------------"
  if [ "$EUID" -eq 0 ]; then
    echo "  running as root — ok"
  else
    echo "  running unprivileged (--dry-run): privileged commands below are printed, not run"
  fi
  echo "  SIP: $(csrutil status 2>/dev/null | head -n 1)"
  [ -n "$IMAGE" ] && attach_image
  if [ -d "$STAGING" ]; then
    STAGING=$(cd "$STAGING" 2>/dev/null && pwd -P) || { echo "Error: cannot enter $STAGING." >&2; exit 2; }
  fi
  if is_system_volume "$STAGING"; then
    echo "Error: $STAGING is the system volume (or shares its device); the staging volume must be a separate mount, or requirement 2 (indexing off for /) is undone by requirement 3." >&2
    exit 2
  fi
  if ! is_mountpoint "$STAGING"; then
    if [ "$DRY_RUN" -eq 1 ] && [ -n "$IMAGE" ]; then
      echo "  (dry-run: $STAGING is not yet a mount point because the attach above was"
      echo "   only printed; ending the run — the teardown below shows the remaining"
      echo "   commands a real run would execute. Re-run without --dry-run for real.)"
      exit 0
    fi
    echo "Error: $STAGING is not a mount point; mdutil needs a real mounted volume." >&2
    echo "Hint: mount a volume there first, or pass --image FILE.sparseimage to attach (and create, if missing) one." >&2
    exit 2
  fi
  echo "  staging mount point: $STAGING — ok"
  SAMPLE_FILE=$(find "$STAGING" -type f -not -path '*/.*' 2>/dev/null | head -n 1)
  if [ -z "$SAMPLE_FILE" ]; then
    echo "Error: no regular files under $STAGING; put the NeoFinder EXPORT data there first (raw catalogs are not Spotlight-searchable — header, known limit D)." >&2
    exit 2
  fi
  echo "  data present; sample file: $SAMPLE_FILE"
}

bring_mds_up() {
  echo ""
  echo "2/6 bring mds up"
  echo "------------------------------------------------------------------"
  if mds_loaded; then
    echo "  $MDS_SERVICE is already loaded; not bootstrapping (recorded: this script did not start mds)"
    return 0
  fi
  run launchctl bootstrap system "$MDS_PLIST"
  if [ "$DRY_RUN" -eq 1 ]; then
    WE_STARTED_MDS=1
    echo "  (dry-run: bootstrap printed, not run)"
  elif mds_loaded; then
    WE_STARTED_MDS=1
    echo "  mds is up (started by this script)"
  else
    echo "Error: mds did not come up; mdutil/mdimport need it alive. Nothing was changed; giving up." >&2
    exit 1
  fi
}

quiet_root() {
  echo ""
  echo "3/6 quiet the system volume"
  echo "------------------------------------------------------------------"
  root_index_state
  case $? in
    0) ROOT_WAS_ON=1; echo "  '/' indexing is enabled; recorded — teardown will restore it" ;;
    1) ROOT_WAS_ON=0; echo "  '/' indexing is already off; nothing to restore later" ;;
    *) echo "Error: cannot read the '/' indexing state (mdutil -s / said: ${ROOT_STATE_OUT:-nothing}); refusing to change it. Is the Spotlight server reachable (mds up, not sandboxed)?" >&2
       exit 1 ;;
  esac
  ROOT_TOUCHED=1   # obligation recorded before the command
  run mdutil -i off / || { echo "Error: mdutil -i off / failed; aborting (teardown restores what was recorded)." >&2; exit 1; }
}

index_staging() {
  echo ""
  echo "4/6 index the staging volume"
  echo "------------------------------------------------------------------"
  STAGING_ON=1   # obligation recorded before the command
  run mdutil -i on "$STAGING" || { echo "Error: mdutil -i on $STAGING failed; aborting." >&2; exit 1; }
  echo "  stored import (mdimport -i: recursive, attributes ARE stored in the index):"
  run mdimport -i "$STAGING" || { echo "Error: mdimport -i $STAGING failed; aborting." >&2; exit 1; }
  echo "  test-import summary (mdimport -t -d1: stores NOTHING, diagnostic only):"
  if [ "$VERBOSE" -eq 1 ]; then
    run mdimport -t -d1 "$STAGING" || echo "  (test import returned non-zero; diagnostic only, continuing)"
  else
    run mdimport -t -d1 "$SAMPLE_FILE" || echo "  (test import returned non-zero; diagnostic only, continuing)"
  fi
}

search_window() {
  echo ""
  echo "5/6 search window"
  echo "------------------------------------------------------------------"
  echo "  staging index status:"
  run mdutil -s "$STAGING"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "+ mdfind -onlyin $STAGING -name Computers | wc -l"
  else
    MATCHES=$(mdfind -onlyin "$STAGING" -name Computers 2>/dev/null | wc -l | tr -d ' ')
    echo "  machine-side check: mdfind -onlyin $STAGING -name Computers -> $MATCHES match(es)"
  fi
  echo ""
  echo "  Validation: search in Finder for a file named \"Computers\" (scoped to"
  echo "  $STAGING — a Finder search or a Smart Folder) to confirm the temporary"
  echo "  index populated."
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  (dry-run: skipping the interactive pause)"
    return 0
  fi
  if [ -r /dev/tty ]; then
    read -r -p "  Press Enter to tear down (Ctrl-C tears down too): " < /dev/tty
  else
    echo "  (no controlling tty; skipping the pause and tearing down)"
  fi
}

# bootout_mds: attempt the mds unload, handling the SIP refusal verified on
# this machine (known limit A): warn, show what is still running, do not
# turn it into a failure exit.
bootout_mds() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "+ launchctl bootout $MDS_SERVICE"
    if sip_enabled; then
      echo "  (dry-run note: SIP is enabled here, so the real run's bootout is expected"
      echo "   to be refused and mds to stay resident — header, limit A)"
    fi
    return 0
  fi
  if ! mds_loaded; then
    echo "  mds is not loaded; nothing to boot out"
    return 0
  fi
  echo "+ launchctl bootout $MDS_SERVICE"
  if BOOTOUT_ERR=$(launchctl bootout "$MDS_SERVICE" 2>&1); then
    if [ "$WE_STARTED_MDS" -eq 1 ]; then
      echo "  mds booted out (this script started it)"
    else
      echo "  mds booted out (it was already loaded when this script started)"
    fi
    [ -n "$BOOTOUT_ERR" ] && echo "  $BOOTOUT_ERR"
  else
    echo "  warning: launchctl bootout failed: ${BOOTOUT_ERR:-<no message>}"
    case "$BOOTOUT_ERR" in
      *"Integrity Protection"*|*"not permitted"*)
        echo "  That is the SIP refusal (known limit A): SIP blocks unloading Apple's own"
        echo "  LaunchDaemons, so mds stays resident." ;;
      *)
        echo "  (not the SIP refusal; read the message above)" ;;
    esac
    echo "  Staging indexing is off and '/' was handled above (restored, or left off"
    echo "  with --leave-root-off). Still running:"
    pgrep -l 'mds|mds_stores|mdworker' | sed 's/^/    /'
  fi
}

# teardown: undo exactly what this run changed. Idempotent (a second call is
# a no-op) and called from the main flow, the EXIT trap and the INT/TERM
# traps; it never re-runs setup. Silent when the run touched nothing.
teardown() {
  [ "$TEARDOWN_RAN" -eq 1 ] && return 0
  TEARDOWN_RAN=1
  trap '' INT TERM   # once begun, teardown runs to the end; a second Ctrl-C must not skip a restore
  [ "$STAGING_ON$ROOT_TOUCHED$IMAGE_ATTACHED$WE_STARTED_MDS" = "0000" ] && return 0
  local failed=""
  echo ""
  echo "6/6 teardown"
  echo "------------------------------------------------------------------"
  if [ "$STAGING_ON" -eq 1 ]; then
    run mdutil -i off "$STAGING" || failed="$failed
    mdutil -i off $STAGING"
  else
    echo "  staging: indexing was not turned on by this run; leaving it alone"
  fi
  if [ "$ROOT_TOUCHED" -eq 1 ]; then
    if [ "$LEAVE_ROOT_OFF" -eq 1 ]; then
      echo "  --leave-root-off: '/' indexing stays off"
    elif [ "$ROOT_WAS_ON" -eq 1 ]; then
      echo "  restoring '/' indexing — note: re-enabling may make Spotlight reindex '/'"
      run mdutil -i on / || failed="$failed
    mdutil -i on /"
    else
      echo "  '/' was already off before this run; leaving it off"
    fi
  fi
  if [ "$IMAGE_ATTACHED" -eq 1 ]; then
    run hdiutil detach "$STAGING" || failed="$failed
    hdiutil detach $STAGING   (EBUSY = a Finder window or process still has it open; close it, or hdiutil detach -force)"
  fi
  if [ -n "$failed" ]; then
    echo "  skipping the mds bootout: a cleanup step above failed and mds is needed to retry it"
  elif [ "$KEEP_MDS" -eq 1 ]; then
    echo "  --keep-mds: skipping the mds bootout"
  else
    bootout_mds
  fi
  echo "  mds-family processes now:"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "+ pgrep -l 'mds|mds_stores|mdworker'"
  elif ! pgrep -l 'mds|mds_stores|mdworker'; then
    echo "  (none)"
  fi
  if [ -n "$failed" ]; then
    TEARDOWN_FAILED=1
    echo "teardown INCOMPLETE — run by hand (as root):$failed" >&2
    echo "done, with failures."
  else
    echo "done."
  fi
}

# shellcheck disable=SC2329  # invoked only through the trap strings below,
# which shellcheck cannot trace
on_signal() {
  echo ""
  echo "Interrupted; tearing down before exit ($1)."
  exit "$1"   # the EXIT trap runs teardown
}

status_mode() {
  echo "SIP:     $(csrutil status 2>/dev/null | head -n 1)"
  if mds_loaded; then
    echo "mds:     $MDS_SERVICE is loaded"
  else
    echo "mds:     $MDS_SERVICE is NOT loaded (mdutil/mdimport fail until it is up)"
  fi
  ROOT_LINE=$(mdutil -s / 2>/dev/null | tail -n 1 | tr -d '\t')
  echo "/:       ${ROOT_LINE:-(mdutil -s / failed — is mds up?)}"
  if is_mountpoint "$STAGING"; then
    STAGING_LINE=$(mdutil -s "$STAGING" 2>/dev/null | tail -n 1 | tr -d '\t')
    echo "staging: $STAGING is a mount point; ${STAGING_LINE:-(mdutil -s failed)}"
  else
    echo "staging: $STAGING is NOT a mount point (nothing to report)"
  fi
  IMPORTERS=$(mdimport -L 2>/dev/null)
  IMPORTER_COUNT=$(printf '%s\n' "$IMPORTERS" | grep -c '"')
  NEO_COUNT=$(printf '%s\n' "$IMPORTERS" | grep -ci neofinder)
  echo "importers: mdimport -L lists $IMPORTER_COUNT; $NEO_COUNT mention NeoFinder:"
  printf '%s\n' "$IMPORTERS" | sed 's/^/  /'
}

if [ "$STATUS_ONLY" -eq 1 ]; then
  status_mode
  exit 0
fi

# Re-exec under sudo for the real flow. --help (handled above), --status
# (handled above) and --dry-run stay unprivileged.
if [ "$EUID" -ne 0 ] && [ "$DRY_RUN" -eq 0 ]; then
  echo "Not root; re-execing under sudo..."
  exec sudo "$0" ${ORIG_ARGS[@]+"${ORIG_ARGS[@]}"}
fi

trap 'teardown; if [ "$TEARDOWN_FAILED" -eq 1 ]; then exit 1; fi' EXIT
trap 'on_signal 130' INT
trap 'on_signal 143' TERM

echo "Batch Spotlight run: staging=$STAGING image=${IMAGE:-none} keep-mds=$KEEP_MDS leave-root-off=$LEAVE_ROOT_OFF dry-run=$DRY_RUN verbose=$VERBOSE"

preflight
bring_mds_up
quiet_root
index_staging
search_window
teardown
[ "$TEARDOWN_FAILED" -eq 1 ] && exit 1
exit 0
