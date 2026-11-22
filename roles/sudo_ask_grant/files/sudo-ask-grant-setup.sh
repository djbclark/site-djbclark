#!/bin/bash
# Install / preview / verify / roll back the sudo-ask approval window (roles/sudo_ask_grant).
#
#   sudo-ask-grant-setup.sh --print            show the sudoers drop-in and the planned actions (no root)
#   sudo-ask-grant-setup.sh --check [--diff]   compare the installed files with the repo (no root, read-only)
#   sudo-ask-grant-setup.sh                    install: ONE sudo-ask step (dialog + Touch ID)
#   sudo-ask-grant-setup.sh --verify           prove the split: grant needs a password, exec needs a window
#   sudo-ask-grant-setup.sh --rollback         remove the drop-in, helper and grant file (sudo-ask then prompts again)
#
# Run it from a shell YOU are watching: the install opens a sudo-ask dialog that names the two files and
# their SHA-256 prefixes; compare them with `--print`. Root re-hashes its own copy of both files before
# it installs anything, so a file swapped after you approved cannot be installed.
export PATH="/opt/homebrew/bin:$PATH"
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
# The approval window: $operator may use an OPEN window (exec) and read its state (status) without a
# password. Opening or closing a window (grant, revoke) matches no NOPASSWD line, so it needs a fresh
# password / Touch ID, and timestamp_timeout=0 stops a cached sudo ticket from standing in for one.
Defaults!$BIN env_reset, timestamp_timeout=0
$operator ALL=(root) NOPASSWD: $BIN exec *, $BIN status, $BIN status *
SUDO
}

sha24() { shasum -a 256 <"$1" | cut -c1-24; }
tmp=$(mktemp -d /tmp/sag.XXXXXX); trap 'rm -rf "$tmp"' EXIT
render_sudoers > "$tmp/sudoers"

mode=install; diff_flag=0
for a in "$@"; do
  case $a in
    --print) mode=print ;; --check) mode=check ;; --diff) diff_flag=1 ;;
    --verify) mode=verify ;; --rollback) mode=rollback ;;
    *) echo "usage: $0 [--print | --check [--diff] | --verify | --rollback]" >&2; exit 64 ;;
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
    [ "$diff_flag" = 1 ] && { echo "--- drop-in that would be installed ---"; cat "$tmp/sudoers"; }
    if [ -d "$STATE_DIR" ]; then echo "ok       $STATE_DIR ($(st "$STATE_DIR"))"; else echo "MISSING  $STATE_DIR"; rc=3; fi
    exit $rc ;;
esac

run_root() { if command -v sudo-ask >/dev/null 2>&1; then sudo-ask "$@"; else sudo "$@"; fi; }

case $mode in
  install)
    validate
    h1=$(sha24 "$src"); h2=$(sha24 "$tmp/sudoers")
    # Short on purpose: sudo-ask's dialog cuts its text at 700 characters.
    body='set -e; t=$(mktemp -d /tmp/r.XXXXXX); trap "rm -rf $t" EXIT; install -m 600 "$1" $t/h; install -m 600 "$2" $t/s; [ "$(shasum -a 256 <$t/h|cut -c1-24)" = "$3" ] || exit 1; [ "$(shasum -a 256 <$t/s|cut -c1-24)" = "$4" ] || exit 1; /usr/sbin/visudo -cf $t/s; install -d -o root -g wheel -m 755 /usr/local/libexec '"$STATE_DIR"'; install -o root -g wheel -m 755 $t/h '"$BIN"'; install -o root -g wheel -m 440 $t/s '"$SUDOERS"'.new; mv -f '"$SUDOERS"'.new '"$SUDOERS"
    keep="$tmp/h.copy"; cp "$src" "$keep"; cp "$tmp/sudoers" "$tmp/s.copy"
    shown="$body $keep $tmp/s.copy $h1 $h2"
    [ ${#shown} -le 700 ] || { echo "sudo-ask-grant-setup: dialog text is ${#shown} chars (>700); sudo-ask would hide the tail" >&2; exit 1; }
    run_root /bin/sh -c "$body" sh "$keep" "$tmp/s.copy" "$h1" "$h2"
    echo "sudo-ask-grant-setup: installed $BIN and $SUDOERS for $operator"
    "$0" --verify ;;
  rollback)
    body="rm -f $SUDOERS $STATE_DIR/grant $BIN; rmdir $STATE_DIR"
    run_root /bin/sh -c "$body"
    echo "sudo-ask-grant-setup: removed the drop-in, helper and grant file. $LOGF is kept as the audit record; sudo-ask prompts again." ;;
  verify)
    fail=0
    ok() { echo "ok    $1"; }
    bad() { echo "FAIL  $1"; fail=1; }
    [ -x "$BIN" ] && ok "helper installed" || { bad "helper missing ($BIN)"; exit 1; }
    sudo -k
    # grant must NOT be reachable without a password. If this succeeds a 60 s window just opened: roll back.
    if sudo -n "$BIN" grant 60s >/dev/null 2>&1; then bad "grant ran WITHOUT a password: run --rollback now"; else ok "grant needs authentication"; fi
    if sudo -n "$BIN" revoke >/dev/null 2>&1; then bad "revoke ran WITHOUT a password"; else ok "revoke needs authentication"; fi
    s=0; sudo -n "$BIN" status >/dev/null 2>&1 || s=$?
    if [ $s -le 1 ]; then ok "status works without a password (exit $s)"; else bad "status needs a password (exit $s)"; fi
    e=0; sudo -n "$BIN" exec -- /usr/bin/true >/dev/null 2>&1 || e=$?
    if [ $s -eq 1 ] && [ $e -eq 75 ]; then ok "exec refuses with no window (75)"
    elif [ $s -eq 0 ]; then ok "a window is open; exec check skipped"
    else bad "exec with no window exited $e (want 75)"; fi
    [ "$(/usr/bin/stat -f '%Su:%Sg %Lp' "$STATE_DIR")" = "root:wheel 755" ] && ok "$STATE_DIR root:wheel 755" || bad "$STATE_DIR ownership/mode"
    [ $fail -eq 0 ] && { echo "sudo-ask-grant-setup: verified"; exit 0; }
    echo "sudo-ask-grant-setup: VERIFY FAILED; run: $0 --rollback" >&2; exit 1 ;;
esac
