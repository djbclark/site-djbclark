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
#                                       [--export [--catalog NAME]...]
#                                       [--python PATH] [--sudo CMD] [--keep-mds]
#                                       [--leave-root-off] [--dry-run]
#                                       [--verbose]
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
#   --export           first populate the staging volume from NeoFinder by
#                      running neofinder-stub-export.py (same directory) with
#                      --dest STAGING --progress --ignore-schedule; it is
#                      resumable, so a Ctrl-C here pauses it and the next
#                      --export run continues. Runs UNPRIVILEGED (limit F)
#   --catalog NAME     with --export: catalogue(s) to export (repeatable);
#                      without it the exporter uses its TOML config and, with
#                      no catalogue configured, prints the table and exits 2
#   --python PATH      interpreter for the exporter (needs Python >= 3.11;
#                      default: first python3.14/.13/.12/.11 on PATH, in
#                      /opt/homebrew/bin, /usr/local/bin or ~/.local/bin)
#   --sudo CMD         command used for the privilege re-exec (default sudo);
#                      e.g. --sudo sudo-ask to get a per-command Allow/Deny
#                      dialog from an agent shell with no terminal
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
#   F. --export talks to NeoFinder over AppleScript, which must run as the
#      logged-in GUI user (Automation permission is per user; root gets
#      -1743 or a prompt nobody sees). So the export is step 0, done BEFORE
#      the sudo re-exec: when --image is given the image is created and
#      attached unprivileged (hdiutil mounts it at /Volumes/<volname>, which
#      is the default staging path; a different --staging must match the
#      image's volume name) and the root phase inherits that attachment
#      through an internal marker so teardown still detaches it. Started as
#      root directly (`sudo ./script --export`), the exporter runs as
#      $SUDO_USER via `sudo -u`; the Automation permission is then attributed
#      to the terminal app, which usually already has it. Only stubs land on
#      the staging volume; the exporter's state and logs live under the
#      user's ~/Library (see the exporter's header), so Spotlight indexes
#      only our stub tree.
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
#   - 2026-10-09 (night): --sudo CMD for the privilege re-exec (sudo-ask from
#     an agent shell without a terminal).
#   - 2026-10-09 (evening): --export / --catalog / --python: populate the
#     staging volume from NeoFinder through neofinder-stub-export.py before
#     indexing (limit F). `hdiutil attach` is deprecated on this macOS in
#     favour of `diskutil image attach`; kept for the same reason as create.

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
EXPORT=0
EXPORT_DONE=0      # internal: set by --_exported in the re-exec'd root phase
CATALOGS=()
PYTHON=
SUDO_CMD=sudo

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
    --export) EXPORT=1; shift ;;
    --catalog)
      [ $# -ge 2 ] || { echo "Error: --catalog needs a name argument." >&2; exit 2; }
      CATALOGS+=("$2"); shift 2 ;;
    --python)
      [ $# -ge 2 ] || { echo "Error: --python needs a path argument." >&2; exit 2; }
      PYTHON=$2; shift 2 ;;
    --sudo)
      [ $# -ge 2 ] || { echo "Error: --sudo needs a command argument." >&2; exit 2; }
      SUDO_CMD=$2; shift 2 ;;
    --_exported) EXPORT_DONE=1; shift ;;          # internal, added by the re-exec
    --_image-attached) IMAGE_ATTACHED=1; shift ;; # internal, added by the re-exec
    -h|--help) sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Error: unknown argument: $1 (use --staging, --image, --export, --catalog, --python, --sudo, --keep-mds, --leave-root-off, --dry-run, --verbose, --status or --help)" >&2; exit 2 ;;
  esac
done

[ -n "$STAGING" ] || { echo "Error: --staging needs a non-empty path." >&2; exit 2; }
if [ ${#CATALOGS[@]} -gt 0 ] && [ "$EXPORT" -eq 0 ]; then
  echo "Error: --catalog only means something with --export." >&2; exit 2
fi
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

# find_python: honour --python, else the first interpreter >= 3.11 among the
# usual names and places (sudo's secure_path hides /opt/homebrew/bin).
find_python() {
  local cand dir name ver
  if [ -n "$PYTHON" ]; then
    ver=$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null) || { echo "Error: --python $PYTHON does not run." >&2; exit 2; }
    case "$ver" in 3.1[1-9]|3.[2-9]*) return 0 ;; esac
    echo "Error: --python $PYTHON is Python $ver; the exporter needs >= 3.11 (tomllib)." >&2; exit 2
  fi
  for name in python3.14 python3.13 python3.12 python3.11 python3; do
    for dir in "" /opt/homebrew/bin /usr/local/bin "${SUDO_USER:+/Users/$SUDO_USER/.local/bin}" "$HOME/.local/bin"; do
      if [ -z "$dir" ]; then cand=$(command -v "$name" 2>/dev/null) || continue; else cand="$dir/$name"; fi
      [ -x "$cand" ] || continue
      ver=$("$cand" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null) || continue
      case "$ver" in 3.1[1-9]|3.[2-9]*) PYTHON=$cand; return 0 ;; esac
    done
  done
  echo "Error: no Python >= 3.11 found for the exporter (brew install python@3.14, or pass --python PATH)." >&2
  exit 2
}

# export_stubs: step 0, --export. Make sure the staging volume is mounted
# (attaching --image unprivileged if needed, see limit F), then run
# neofinder-stub-export.py as the GUI user. Nothing here needs root.
export_stubs() {
  local exporter rc as_user=()
  exporter=$(cd "$(dirname "$0")" && pwd -P)/neofinder-stub-export.py
  echo ""
  echo "0/6 export NeoFinder stubs to the staging volume"
  echo "------------------------------------------------------------------"
  [ -f "$exporter" ] || { echo "Error: $exporter not found next to this script." >&2; exit 2; }
  find_python
  echo "  exporter: $exporter  (python: $PYTHON)"
  if [ -n "$IMAGE" ] && ! is_mountpoint "$STAGING"; then
    if [ "$EUID" -eq 0 ]; then
      attach_image
    else
      if [ ! -e "$IMAGE" ]; then
        echo "  image does not exist; creating a 4 GB APFS sparse image (grows on demand)"
        run hdiutil create -size 4g -fs APFS -volname "${STAGING##*/}" -type SPARSE "$IMAGE" \
          || { echo "Error: hdiutil create failed; nothing was changed." >&2; exit 1; }
      fi
      echo "  attaching unprivileged: hdiutil mounts it at /Volumes/<volume name>"
      IMAGE_ATTACHED=1
      if ! run hdiutil attach "$IMAGE"; then
        IMAGE_ATTACHED=0
        echo "Error: hdiutil attach failed." >&2; exit 1
      fi
      if [ "$DRY_RUN" -eq 0 ] && ! is_mountpoint "$STAGING"; then
        echo "Error: the image did not mount at $STAGING (its volume name differs from the staging basename); detaching. Pass --staging /Volumes/<volume name>, or let this script create the image." >&2
        hdiutil detach "$STAGING" >/dev/null 2>&1; IMAGE_ATTACHED=0
        hdiutil info | grep -F "$IMAGE" >&2 || true
        exit 2
      fi
    fi
  fi
  if [ "$DRY_RUN" -eq 0 ] && ! is_mountpoint "$STAGING"; then
    echo "Error: $STAGING is not a mount point; --export writes only onto the staging volume." >&2
    echo "Hint: mount a volume there first, or pass --image FILE.sparseimage." >&2
    exit 2
  fi
  if [ "$EUID" -eq 0 ]; then
    if [ -z "${SUDO_USER:-}" ] || [ "$SUDO_USER" = root ]; then
      echo "Error: --export must run as the logged-in user (NeoFinder AppleScript, limit F); run this script without sudo and let it re-exec." >&2
      exit 2
    fi
    echo "  running the exporter as $SUDO_USER (sudo -u), not root"
    as_user=(sudo -u "$SUDO_USER" -H)
  fi
  run ${as_user[@]+"${as_user[@]}"} "$PYTHON" "$exporter" export --dest "$STAGING" --progress --ignore-schedule \
    ${CATALOGS[@]+"${CATALOGS[@]/#/--catalog=}"}
  rc=$?
  # A `neofinder-stub-export.py pause` from another terminal makes the exporter
  # finish its page and exit 0 with the run marked paused; do not index that.
  if [ "$rc" -eq 0 ] && [ "$DRY_RUN" -eq 0 ] \
     && ${as_user[@]+"${as_user[@]}"} "$PYTHON" "$exporter" status 2>/dev/null | grep -q '^paused: *yes'; then
    rc=130
  fi
  if [ "$rc" -ne 0 ]; then
    if [ "$rc" -eq 130 ]; then
      echo "  export interrupted; its state is saved, the next --export run resumes it."
    else
      echo "Error: exporter exited $rc (see ~/Library/Logs/neofinder-stub-export/latest.log); not indexing a partial tree." >&2
    fi
    if [ "$IMAGE_ATTACHED" -eq 1 ] && [ "$EUID" -ne 0 ]; then
      run hdiutil detach "$STAGING" || echo "  (detach failed; hdiutil detach $STAGING by hand)" >&2
    fi
    exit "$rc"
  fi
  echo "  export done; stubs under $STAGING (exporter log: ~/Library/Logs/neofinder-stub-export/latest.log)"
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
  if [ -n "$IMAGE" ] && [ "$IMAGE_ATTACHED" -eq 1 ]; then
    echo "  --image $IMAGE: attached in the export phase; teardown will detach it"
  elif [ -n "$IMAGE" ]; then
    attach_image
  fi
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
    echo "Error: no regular files under $STAGING; put the NeoFinder EXPORT data there first, or pass --export [--catalog NAME] to have neofinder-stub-export.py do it (raw catalogs are not Spotlight-searchable — header, known limit D)." >&2
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
if [ "$EXPORT" -eq 1 ] && [ "$EXPORT_DONE" -eq 0 ] && [ "$EUID" -ne 0 ]; then
  export_stubs   # step 0, unprivileged (limit F); the root phase below skips it
  EXPORT_DONE=1  # also stops --dry-run (no re-exec) from printing it twice
fi
if [ "$EUID" -ne 0 ] && [ "$DRY_RUN" -eq 0 ]; then
  echo "Not root; re-execing under $SUDO_CMD..."
  EXTRA_ARGS=()
  [ "$EXPORT" -eq 1 ] && EXTRA_ARGS+=(--_exported)
  [ "$IMAGE_ATTACHED" -eq 1 ] && EXTRA_ARGS+=(--_image-attached)
  exec "$SUDO_CMD" "$0" ${ORIG_ARGS[@]+"${ORIG_ARGS[@]}"} ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
fi

trap 'teardown; if [ "$TEARDOWN_FAILED" -eq 1 ]; then exit 1; fi' EXIT
trap 'on_signal 130' INT
trap 'on_signal 143' TERM

echo "Batch Spotlight run: staging=$STAGING image=${IMAGE:-none} export=$EXPORT keep-mds=$KEEP_MDS leave-root-off=$LEAVE_ROOT_OFF dry-run=$DRY_RUN verbose=$VERBOSE"

if [ "$EXPORT" -eq 1 ] && [ "$EXPORT_DONE" -eq 0 ]; then
  export_stubs   # started as root directly: runs the exporter as $SUDO_USER
fi
preflight
bring_mds_up
quiet_root
index_staging
search_window
teardown
[ "$TEARDOWN_FAILED" -eq 1 ] && exit 1
exit 0
