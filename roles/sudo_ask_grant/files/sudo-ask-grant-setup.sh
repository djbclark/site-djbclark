#!/bin/bash
# Install / preview / verify / roll back the sudo-ask approval window (roles/sudo_ask_grant).
#
#   sudo-ask-grant-setup.sh --print            show the sudoers drop-in and the planned actions (no root)
#   sudo-ask-grant-setup.sh --check [--diff]   compare the installed files with the repo (no root, read-only)
#   sudo-ask-grant-setup.sh --live             install: ONE sudo-ask step (dialog + Touch ID)
#   sudo-ask-grant-setup.sh --verify --live    prove the split: grant needs a password, revoke needs none,
#                                              exec needs a window; fails when the sudo ticket is not off
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
    --ticket-checks) mode=ticketchecks ;;   # tests (and a manual re-check): the two ticket checks, nothing else
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
rollback_body="PATH=/usr/bin:/bin:/usr/sbin:/sbin; rm -f $SUDOERS $STATE_DIR/grant $BIN; rm -rf $STATE_DIR"

# Is the shared sudo ticket really off? The drop-in line can be overridden (a later file, a Defaults entry) and the
# failure would be silent, so the install checks it. `sudo -n -l` asks sudo itself what Defaults apply to this user,
# after ALL of sudoers (every drop-in, any order), and runs with no password because of the NOPASSWD lines. It prints
# two sections, in this order (sudo's display_privs): "Matching Defaults entries for USER on HOST:" (generic, host and
# user entries, in the order sudo applies them: the LAST timestamp_timeout is the effective one) and then
# "Runas and Command-specific defaults for USER:" (every Defaults> and Defaults! entry, which holds this drop-in's own
# `Defaults!HELPER ... timestamp_timeout=0` line LAST, so the listing as a whole proves nothing). sudo also glues the
# first Defaults! entry onto the end of the last Defaults> line (no newline between them), so those lines are split
# again before they are judged. Therefore:
#   1. the user section must exist and its last timestamp_timeout must be 0 (a bare `!timestamp_timeout` counts as 0);
#      a value is read only in sudo's own number grammar ([+-]digits[.digits]): anything else is unreadable, and so is
#      a quoted value that mentions timestamp_timeout (a list value can hide a `,timestamp_timeout=0,`);
#   2. no Defaults> entry may mention timestamp_timeout (it applies after the user entries to every command run as that user);
#   3. no Defaults! entry may carry a non-zero or unreadable timestamp_timeout (it would give a ticket to that command);
#   4. the Runas section must exist exactly once and hold the helper's own Defaults! line, and after the user section
#      no unknown line may start at column 0 (a renamed header or a stray line would leave entries unchecked).
# The headers are translated by gettext, so the listing is asked for in the C locale. A failed, unreadable or unclear
# listing fails (an unchecked ticket is not an off ticket). The listing is read on stdin.
ticket_state() {
  /usr/bin/python3 -IS -c '
import re, sys
operator, helper = sys.argv[1], sys.argv[2]
GLUE = re.compile(r"\s+(?=Defaults[>!])")
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
def fail(msg):
    print(msg); sys.exit(1)
sections = []
seen_user_section = False
for line in sys.stdin.read().splitlines():
    if not line.strip():
        continue
    if line[0] in " \t":
        if sections:
            sections[-1][1].append(line.strip())
        continue
    hdr = line.strip()
    if hdr.startswith("Matching Defaults entries for "):
        seen_user_section = True
    elif seen_user_section and not hdr.startswith(("Runas and Command-specific defaults for ", "User ")):
        fail("an unrecognised line follows the defaults in the listing: %s" % hdr)
    sections.append((hdr, []))
def values(text):
    if "timestamp_timeout" not in text:
        return []
    if "\"" in text or "\x27" in text:
        return [None]
    out = []
    for tok in text.split(","):
        if "timestamp_timeout" not in tok:
            continue
        m = re.fullmatch(r"\s*(!?)timestamp_timeout(?:=([^\s,]+))?\s*", tok)
        if not m:
            out.append(None)
            continue
        neg, val = m.groups()
        if neg:
            out.append(0.0 if val is None else None)
        elif val is None or not NUMBER.fullmatch(val):
            out.append(None)
        else:
            out.append(float(val))
    return out
mine = [ls for hdr, ls in sections if hdr.startswith("Matching Defaults entries for %s on " % operator)]
if len(mine) != 1:
    fail("the listing has no single \"Matching Defaults entries for %s on\" section" % operator)
vals = [v for line in mine[0] for v in values(line)]
if not vals:
    fail("the listing has no timestamp_timeout for %s (the default, 5 minutes, would apply)" % operator)
if vals[-1] is None or vals[-1] != 0:
    fail("the effective timestamp_timeout for %s is %s, not 0" % (operator, "unreadable" if vals[-1] is None else "%g" % vals[-1]))
want = "Runas and Command-specific defaults for %s:" % operator
if any(hdr.startswith("Runas and Command-specific defaults for") and hdr != want for hdr, _ in sections):
    fail("a Runas and Command-specific section is not the one for %s" % operator)
runas = [ls for hdr, ls in sections if hdr == want]
if len(runas) != 1:
    fail("the listing has no single \"%s\" section" % want)
entries = [e for line in runas[0] for e in GLUE.split(line) if e]
if not any(e.split(None, 1)[0] == "Defaults!" + helper for e in entries):
    fail("the helper\x27s own Defaults! line is missing from the Runas section")
for entry in entries:
    if "timestamp_timeout" not in entry:
        continue
    head, _, rest = entry.partition(" ")
    if head.startswith("Defaults>"):
        fail("a Defaults> entry sets timestamp_timeout and applies after the user entries: %s" % entry)
    if not head.startswith("Defaults!"):
        fail("an unrecognised entry sets timestamp_timeout: %s" % entry)
    vs = values(rest)
    if not vs or any(v is None or v != 0 for v in vs):
        fail("a Defaults! entry gives a ticket to %s: %s" % (head[len("Defaults!"):], entry))
print("effective timestamp_timeout=0 for %s" % operator)' "$operator" "$BIN"
}
ticket_gate() {   # $1: the sudo to ask for the listing
  local listing msg
  if ! listing=$(LC_ALL=C LANG=C "$1" -n -l 2>&1); then
    echo "FAIL  cannot read the sudoers listing ('sudo -n -l' failed): the ticket state is unproven"; return 1
  fi
  if msg=$(printf '%s\n' "$listing" | ticket_state); then echo "ok    the sudo ticket is off for $operator ($msg)"; return 0; fi
  echo "FAIL  the sudo ticket is NOT off for $operator: $msg"
  printf '%s\n' "$listing" | /usr/bin/grep -i 'timestamp' || true
  return 1
}

ticket_checks() {   # $1: the sudo to ask. The listing check, then the plain-sudo behaviour check; 1 if either fails.
  local rc=0
  ticket_gate "$1" || rc=1
  # With the ticket off, no cached ticket is honoured for /usr/bin/true: a success means a ticket is live (or a NOPASSWD
  # rule covers true), and whoever holds a ticket is root and can write the grant file itself. That is a failure.
  if "$1" -n /usr/bin/true >/dev/null 2>&1; then
    echo "FAIL  'sudo -n /usr/bin/true' succeeded: a sudo ticket is honoured (or a NOPASSWD rule covers true), so the ticket is not off. Do not open a window: roll back (--rollback --live) and report"
    rc=1
  fi
  return $rc
}

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
    # The ticket-off line must be proven, or the install is undone: otherwise one Touch ID for any sudo gives every agent root.
    gate_failed=0
    if [ "$live" = 1 ]; then
      "$0" --verify --live || gate_failed=1
    elif [ -x "$(dirname "$fake")/sudo" ]; then   # a test: a fake sudo next to the fake sudo-ask (never reachable when live)
      ticket_gate "$(dirname "$fake")/sudo" || gate_failed=1
    else
      echo "sudo-ask-grant-setup: not live: skipped --verify"
    fi
    if [ "$gate_failed" = 1 ]; then
      echo "sudo-ask-grant-setup: the install did not verify: rolling it back" >&2
      run_root /bin/sh -c "$rollback_body" || echo "sudo-ask-grant-setup: ROLLBACK FAILED: run: $0 --rollback --live" >&2
      echo "sudo-ask-grant-setup: rolled back (drop-in, helper and grant file removed)" >&2
      exit 1
    fi ;;
  ticketchecks)
    if [ "$live" = 1 ]; then ticket_checks /usr/bin/sudo; else ticket_checks "$(dirname "$fake")/sudo"; fi
    exit $? ;;
  rollback)
    run_root /bin/sh -c "$rollback_body"
    echo "sudo-ask-grant-setup: removed the drop-in (so the sudo ticket behaves as before), helper and grant file. $LOGF is kept as the audit record; sudo-ask prompts again." ;;
  verify)
    fail=0
    ok() { echo "ok    $1"; }
    bad() { echo "FAIL  $1"; fail=1; }
    [ -x "$BIN" ] && ok "helper installed" || { bad "helper missing ($BIN)"; exit 1; }
    # A cached machine-wide ticket is what would let `sudo -n /bin/sh -c "<helper> grant 24h"` open a window: say so.
    ticket_checks /usr/bin/sudo || fail=1
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
