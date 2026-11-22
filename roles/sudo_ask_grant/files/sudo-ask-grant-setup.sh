#!/bin/bash
# Install / preview / verify / roll back the sudo-ask approval window (roles/sudo_ask_grant).
#
#   sudo-ask-grant-setup.sh --print            show the sudoers drop-in and the planned actions (no root)
#   sudo-ask-grant-setup.sh --check [--diff]   compare the installed files with the repo (no root, read-only)
#   sudo-ask-grant-setup.sh --live             install: ONE sudo-ask step (dialog + Touch ID)
#   sudo-ask-grant-setup.sh --verify --live    prove the split: grant needs a password, revoke needs none,
#                                              exec needs a window; warns when a sudo ticket is cached
#   sudo-ask-grant-setup.sh --rollback --live  remove the drop-in, helper and grant file (sudo-ask then prompts again)
#
# GUARD: install, --verify and --rollback change or probe the REAL machine, so they refuse (exit 2, before any
# privileged call) unless you pass --live. The one exception, for tests: install and --rollback also run when
# the `sudo-ask` they would call resolves (realpath) inside a temp directory (/tmp, /var/folders, $TMPDIR),
# i.e. a fake. --verify always needs --live (it calls sudo itself). A test must give its fake by absolute
# path or set PATH inside the test process, never rely on the shell's PATH (a shell startup can reorder it).
#
# Run it from a shell YOU are watching: the install opens a sudo-ask dialog that names the two files and
# their SHA-256 prefixes; compare them with `--print`. Root re-hashes its own copy of both files before
# it installs anything, so a file swapped after you approved cannot be installed.
# Tools run by this script, and by root inside the install body, come from the system directories only: never a
# user-writable one such as /opt/homebrew/bin. The caller's PATH is read once, to find a TEST fake sudo-ask.
caller_path=$PATH
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
src="$here/sudo-ask-granted"
BIN=/usr/local/libexec/sudo-ask-granted
SUDOERS=/etc/sudoers.d/sudo-ask-grant
STATE_DIR=/var/db/sudo-ask
LOGF=/var/log/sudo-ask-grant.log
operator=$(id -un)
[[ $operator =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "sudo-ask-grant-setup: unusual user name '$operator'" >&2; exit 1; }

render_sudoers() {
  cat <<SUDO
# Managed by site-djbclark roles/sudo_ask_grant (installed by \`just sudo-ask-grant-setup\`).
# The approval window: $operator may use an OPEN window (exec), read its state (status) and END it (revoke, with
# no arguments: the "" matches only an empty argument list) without a password. OPENING one (grant) matches no
# NOPASSWD line, so it needs a fresh password / Touch ID; timestamp_timeout=0 stops a cached ticket for this
# program from standing in for one (the helper also checks that sudo ran with -k).
Defaults!$BIN env_reset, timestamp_timeout=0
# Ticket off for $operator: this machine's 10-timestamp-global shares ONE sudo ticket with every process of the user, so
# a single Touch ID would let any agent run plain sudo. A later drop-in wins over an earlier one; removing this file
# (rollback) restores the exact prior state, and 10-timestamp-global is never touched.
Defaults:$operator timestamp_timeout=0
$operator ALL=(root) NOPASSWD: $BIN exec *, $BIN status, $BIN status *, $BIN revoke ""
SUDO
}

sha24() { shasum -a 256 <"$1" | cut -c1-24; }
tmp=$(mktemp -d /tmp/sag.XXXXXX); trap 'rm -rf "$tmp"' EXIT
render_sudoers > "$tmp/sudoers"

mode=install; diff_flag=0; live=0; explicit=0
for a in "$@"; do
  case $a in
    --print) mode=print ;; --check) mode=check ;; --diff) diff_flag=1 ;;
    --verify) mode=verify ;; --rollback) mode=rollback ;; --live) live=1 ;;
    *) echo "usage: $0 [--print | --check [--diff] | --live | --verify --live | --rollback --live]" >&2; exit 64 ;;
  esac
done

validate() {
  /usr/bin/python3 -IS -c 'import ast,sys; ast.parse(open(sys.argv[1]).read())' "$src"
  visudo -cf "$tmp/sudoers" >/dev/null || { echo "sudo-ask-grant-setup: the sudoers drop-in failed visudo -c" >&2; exit 1; }
}

case $mode in
  print)
    validate
    echo "== $SUDOERS (root:wheel 0440) =="; cat "$tmp/sudoers"
    echo "== plan =="
    echo "install -d root:wheel 0755   /usr/local/libexec  $STATE_DIR"
    echo "install root:wheel 0755      $BIN   (sha256[:24] $(sha24 "$src"))"
    echo "(the helper itself creates $LOGF, root:wheel 0644, on first use)"
    echo "install root:wheel 0440      $SUDOERS   (sha256[:24] $(sha24 "$tmp/sudoers"))"
    echo "sudo ticket for $operator: switched off by the same drop-in (Defaults:$operator timestamp_timeout=0); 10-timestamp-global is not touched"
    echo "grant file (written only by 'sudo-ask --grant'): $STATE_DIR/grant"
    exit 0 ;;
  check)
    validate; rc=0
    st() { /usr/bin/stat -f '%Su:%Sg %Lp' "$1" 2>/dev/null || echo missing; }
    if [ -f "$BIN" ] && cmp -s "$src" "$BIN"; then echo "ok       $BIN ($(st "$BIN"))"
    else echo "DIFFERS  $BIN ($(st "$BIN"))"; rc=3
      if [ "$diff_flag" = 1 ] && [ -f "$BIN" ]; then diff -u "$BIN" "$src" || true; fi; fi
    if [ -e "$SUDOERS" ]; then echo "present  $SUDOERS ($(st "$SUDOERS")); content is root-only, not compared"
    else echo "MISSING  $SUDOERS"; rc=3; fi
    echo "ticket   Defaults:$operator timestamp_timeout=0 is in the drop-in (a password every time; later files win over 10-timestamp-global)"
    if [ -e /etc/sudoers.d/10-timestamp-global ]; then echo "present  /etc/sudoers.d/10-timestamp-global (left untouched; overridden by $SUDOERS)"
    else echo "absent   /etc/sudoers.d/10-timestamp-global (nothing to override)"; fi
    [ "$diff_flag" = 1 ] && { echo "--- drop-in that would be installed ---"; cat "$tmp/sudoers"; }
    if [ -d "$STATE_DIR" ]; then echo "ok       $STATE_DIR ($(st "$STATE_DIR"))"; else echo "MISSING  $STATE_DIR"; rc=3; fi
    exit $rc ;;
esac

# The guard. Nothing below this line may run a privileged command before it has passed.
in_temp_prefix() {
  # Fixed temp roots only: $TMPDIR is the caller's to set, so it never counts. The operator's own sudo-ask never counts either.
  /usr/bin/python3 -IS -c '
import os, sys
p = os.path.realpath(sys.argv[1])
real = os.path.realpath(os.path.join(sys.argv[2], ".local", "bin", "sudo-ask"))
roots = {os.path.realpath(d) for d in ("/private/tmp", "/private/var/folders")}
sys.exit(0 if p != real and any(p.startswith(r.rstrip("/") + "/") for r in roots) else 1)' "$1" "$HOME"
}
if [ "$live" != 1 ]; then
  fake=$(PATH=$caller_path command -v sudo-ask 2>/dev/null || true)
  if [ "$mode" = verify ] || [ -z "$fake" ] || ! in_temp_prefix "$fake"; then
    echo "sudo-ask-grant-setup: refusing to run '$mode': it changes or probes the REAL machine (sudoers, /usr/local, /var/db)." >&2
    echo "  Read-only modes: --print, --check [--diff]. To do it for real, from a shell you are watching, add --live." >&2
    echo "  (Tests: only install/--rollback run, and only when sudo-ask resolves inside a temp dir; resolved: ${fake:-none})" >&2
    exit 2
  fi
fi

# Absolute paths only. Live: the operator's sudo-ask, else plain sudo.
if [ "$live" = 1 ]; then
  if [ -x "$HOME/.local/bin/sudo-ask" ]; then fake=$HOME/.local/bin/sudo-ask; else fake=/usr/bin/sudo; fi
fi
run_root() { "$fake" "$@"; }

case $mode in
  install)
    validate
    h1=$(sha24 "$src"); h2=$(sha24 "$tmp/sudoers")
    # Short on purpose: sudo-ask's dialog cuts its text at 700 characters.
    # PATH pinned inside the body: sudo may pass the caller's PATH (with user-writable directories) to root.
    # `install -S` writes the helper to a temp name and renames it; a full `visudo -c` after the move removes the
    # drop-in again if the whole sudoers set no longer parses.
    body='PATH=/usr/bin:/bin:/usr/sbin:/sbin;set -e;B='"$BIN"';S='"$SUDOERS"';t=$(mktemp -d /tmp/r.XXXXXX);trap "rm -rf $t" EXIT;install -m 600 "$1" $t/h;install -m 600 "$2" $t/s;[ "$(shasum -a 256 <$t/h|cut -c1-24)" = "$3" ]||exit 1;[ "$(shasum -a 256 <$t/s|cut -c1-24)" = "$4" ]||exit 1;visudo -cf $t/s;install -d -o root -g wheel -m 755 /usr/local/libexec '"$STATE_DIR"';install -S -o root -g wheel -m 755 $t/h $B;install -o root -g wheel -m 440 $t/s $S.new;mv -f $S.new $S;visudo -c>/dev/null||{ rm -f $S;exit 1;}'
    keep="$tmp/h.copy"; cp "$src" "$keep"; cp "$tmp/sudoers" "$tmp/s.copy"
    shown="$body $keep $tmp/s.copy $h1 $h2"
    [ ${#shown} -le 700 ] || { echo "sudo-ask-grant-setup: dialog text is ${#shown} chars (>700); sudo-ask would hide the tail" >&2; exit 1; }
    run_root /bin/sh -c "$body" sh "$keep" "$tmp/s.copy" "$h1" "$h2"
    echo "sudo-ask-grant-setup: installed $BIN and $SUDOERS for $operator"
    if [ "$live" = 1 ]; then "$0" --verify --live; else echo "sudo-ask-grant-setup: not live: skipped --verify"; fi ;;
  rollback)
    body="PATH=/usr/bin:/bin:/usr/sbin:/sbin; rm -f $SUDOERS $STATE_DIR/grant $BIN; rm -rf $STATE_DIR"
    run_root /bin/sh -c "$body"
    echo "sudo-ask-grant-setup: removed the drop-in (so the sudo ticket behaves as before), helper and grant file. $LOGF is kept as the audit record; sudo-ask prompts again." ;;
  verify)
    fail=0
    ok() { echo "ok    $1"; }
    bad() { echo "FAIL  $1"; fail=1; }
    [ -x "$BIN" ] && ok "helper installed" || { bad "helper missing ($BIN)"; exit 1; }
    # A cached machine-wide ticket is what would let `sudo -n /bin/sh -c "<helper> grant 24h"` open a window: say so.
    if /usr/bin/sudo -n /usr/bin/true >/dev/null 2>&1; then
      echo "WARN  a sudo ticket is cached (an earlier sudo ran with no -k). The helper's own check still refuses a grant" \
           "that was not run as 'sudo -k'; end the ticket with: sudo -k"
    fi
    echo "NOTE  the ticket is off for $operator (Defaults:$operator timestamp_timeout=0): after one authentication, a plain 'sudo -n true' must still fail"
    /usr/bin/sudo -k
    # grant must NOT be reachable without a password. If this succeeds a 60 s window just opened: roll back.
    if /usr/bin/sudo -n "$BIN" grant 60s >/dev/null 2>&1; then bad "grant ran WITHOUT a password: run --rollback now"; else ok "grant needs authentication"; fi
    # revoke only lowers privilege and needs none, but takes no arguments. `sudo -l CMD` asks sudoers without running it.
    if /usr/bin/sudo -n -l "$BIN" revoke >/dev/null 2>&1; then ok "revoke needs no password"; else bad "revoke is not allowed without a password"; fi
    if /usr/bin/sudo -n -l "$BIN" revoke extra >/dev/null 2>&1; then bad "revoke with extra arguments is allowed"; else ok "revoke with extra arguments is refused"; fi
    s=0; /usr/bin/sudo -n "$BIN" status >/dev/null 2>&1 || s=$?
    if [ $s -le 1 ]; then ok "status works without a password (exit $s)"; else bad "status needs a password (exit $s)"; fi
    e=0; /usr/bin/sudo -n "$BIN" exec -- /usr/bin/true >/dev/null 2>&1 || e=$?
    if [ $s -eq 1 ] && [ $e -eq 75 ]; then ok "exec refuses with no window (75)"
    elif [ $s -eq 0 ]; then ok "a window is open; exec check skipped"
    else bad "exec with no window exited $e (want 75)"; fi
    [ "$(/usr/bin/stat -f '%Su:%Sg %Lp' "$STATE_DIR")" = "root:wheel 755" ] && ok "$STATE_DIR root:wheel 755" || bad "$STATE_DIR ownership/mode"
    [ $fail -eq 0 ] && { echo "sudo-ask-grant-setup: verified"; exit 0; }
    echo "sudo-ask-grant-setup: VERIFY FAILED; run: $0 --rollback --live" >&2; exit 1 ;;
esac
