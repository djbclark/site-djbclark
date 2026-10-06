#!/usr/bin/env bash
# Shell-config self-test -- asserts the invariants that ~/.bashrc's comments
# only *describe*. Run after any edit to ~/.bashrc, ~/.bash_profile, or
# ~/.bashrc.local; ~/.claude/hooks/cswap_quota_context.sh also runs it at
# Claude Code session start.
#
# Exit 0 = all invariants hold. Exit 1 = at least one regressed.
#
# Every check here corresponds to a real defect found on 2026-08-17:
#   1. tier-1 output silently corrupted Claude Code hook JSON
#   2. .bashrc.local's raw `export PATH=` shadowed the herdr wrapper
#   3. an installer appended to .bash_profile after `source ~/.bashrc`
#   4. PATH grew 32 -> 46 entries per nested login shell
#
# Deliberately uses only `env -i` clean shells: it must test the CONFIG, not
# whatever environment the caller happens to have inherited.

set -uo pipefail

pass=0 fail=0
# Colorize only on a tty -- this output is also captured into the session-start
# hook's stderr warning, where raw ANSI escapes would render as garbage.
if [ -t 1 ]; then G=$'\033[32m' R=$'\033[31m' N=$'\033[0m'; else G= R= N=; fi
ok()   { printf '  %sok%s   %s\n' "$G" "$N" "$1"; pass=$((pass+1)); }
bad()  { printf '  %sFAIL%s %s\n' "$R" "$N" "$1"; fail=$((fail+1)); }
note() { printf '       %s\n' "$1"; }

CLEAN_LOGIN=(env -i HOME="$HOME" TERM=xterm /bin/bash -lc)
CLEAN_BASHENV=(env -i HOME="$HOME" BASH_ENV="$HOME/.bashrc" /bin/bash -c)

printf '\nshell config self-test\n\n'

# -- 1. Syntax ------------------------------------------------------------
for f in "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.bashrc.local"; do
  [ -f "$f" ] || continue
  if bash -n "$f" 2>/dev/null; then ok "syntax: ${f/#$HOME/\~}"
  else bad "syntax: ${f/#$HOME/\~}"; bash -n "$f" 2>&1 | sed 's/^/       /'; fi
done

# -- 1b. Pure ASCII -------------------------------------------------------
# Unicode in these files (box-drawing rules, em dashes, bullets, arrows --
# even in comments) rendered as garbage on some terminals and made
# grep/diff/file(1) treat them as binary (2026-08-21). ASCII only, enforced
# here so it cannot creep back in. Substitutes: -- for em dash, -> for
# arrow, * for bullet, --- / === for rules.
for f in "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.bashrc.local" \
         "$HOME/.config/bash/selftest.sh"; do
  [ -f "$f" ] || continue
  hits=$(LC_ALL=C grep -n $'[^\t -~]' "$f" 2>/dev/null | head -3)
  if [ -z "$hits" ]; then ok "pure ASCII: ${f/#$HOME/\~}"
  else
    bad "non-ASCII characters in ${f/#$HOME/\~} (first hits below)"
    printf '%s\n' "$hits" | sed 's/^/       > /'
  fi
done

# -- 1c. ~/.bash_profile matches its blessed copy -------------------------
# Companion to the interactive-shell tamper alarm in ~/.bashrc tier 2.
# Installers append to ~/.bash_profile (rustup did); after a deliberate
# edit, re-bless: cp ~/.bash_profile ~/.config/bash/bash_profile.expected
if [ -r "$HOME/.config/bash/bash_profile.expected" ]; then
  if cmp -s "$HOME/.config/bash/bash_profile.expected" "$HOME/.bash_profile"; then
    ok "~/.bash_profile matches its blessed copy"
  else
    bad "~/.bash_profile DRIFTED from its blessed copy"
    diff "$HOME/.config/bash/bash_profile.expected" "$HOME/.bash_profile" 2>&1 | sed 's/^/       > /'
    note "intentional? re-bless: cp ~/.bash_profile ~/.config/bash/bash_profile.expected"
  fi
fi

# -- 2. Tier 1 is silent --------------------------------------------------
# The highest-stakes check: output here corrupts Claude Code hook JSON and
# fails silently, with the blame landing on the hook rather than on .bashrc.
out=$("${CLEAN_BASHENV[@]}" true 2>/dev/null)
if [ -z "$out" ]; then ok "tier 1 is silent on stdout"
else
  bad "tier 1 PRINTS TO STDOUT -- this corrupts Claude Code hook JSON"
  note "offending output:"; printf '%s\n' "$out" | sed 's/^/       > /'
fi

# -- 3. Tier 1 does not change parsing behavior ---------------------------
# failglob in a non-interactive shell aborts scripted commands on any
# unmatched glob. It belongs strictly in tier 2.
if "${CLEAN_BASHENV[@]}" '[[ -o noglob ]] || shopt -q failglob nullglob 2>/dev/null' 2>/dev/null; then
  bad "tier 1 changed globbing (failglob/nullglob/noglob) -- breaks scripted calls"
else
  ok "tier 1 leaves globbing at bash defaults"
fi

# -- 4. herdr wrapper precedence (the self-closure defense) ---------------
# Must hold in BOTH shell flavors: the wrapper blocks a self-targeted pane
# close, and it only works if it resolves ahead of ~/.local/bin/herdr.
if [ -x "$HOME/.herdr-wrapper/bin/herdr" ]; then
  for flavor in login bashenv; do
    case $flavor in
      login)   got=$("${CLEAN_LOGIN[@]}"   'command -v herdr' 2>/dev/null) ;;
      bashenv) got=$("${CLEAN_BASHENV[@]}" 'command -v herdr' 2>/dev/null) ;;
    esac
    if [ "$got" = "$HOME/.herdr-wrapper/bin/herdr" ]; then
      ok "herdr resolves to the wrapper ($flavor shell)"
    else
      bad "herdr resolves to '${got:-nothing}' ($flavor shell), not the wrapper"
      note "self-closure defense is DISABLED -- something re-prepended a dir"
      note "ahead of ~/.herdr-wrapper/bin. Look for a raw 'export PATH=' in"
      note "~/.bashrc.local or an installer append in ~/.bash_profile."
    fi
  done

  # The hard case: a PATH inherited from an ancestor process where
  # ~/.local/bin ALREADY precedes the wrapper dir. An idempotent prepend
  # sees the wrapper "already present" and leaves it losing; only a
  # force-to-front prepend recovers. Every shell on this machine was in
  # this state before 2026-08-17, so processes started back then still are.
  hostile="$HOME/.local/bin:$HOME/.herdr-wrapper/bin:/usr/bin:/bin"
  got=$(env -i HOME="$HOME" PATH="$hostile" BASH_ENV="$HOME/.bashrc" \
          /bin/bash -c 'command -v herdr' 2>/dev/null)
  if [ "$got" = "$HOME/.herdr-wrapper/bin/herdr" ]; then
    ok "herdr wrapper wins even from a hostile inherited PATH"
  else
    bad "herdr resolves to '${got:-nothing}' from a hostile inherited PATH"
    note "the wrapper prepend must be a RAW force-to-front prepend, not"
    note "__path_prepend -- the idempotent version cannot fix a bad inherit."
  fi

  # ~/.zshrc maintains its own copy of this invariant (zsh can't source
  # ~/.bashrc -- the helpers use bash-only constructs). Not the active shell,
  # but anything that DOES start a zsh must not silently lose the wrapper.
  if command -v zsh >/dev/null 2>&1 && [ -f "$HOME/.zshrc" ]; then
    got=$(env -i HOME="$HOME" TERM=xterm zsh -ic 'command -v herdr' 2>/dev/null)
    if [ "$got" = "$HOME/.herdr-wrapper/bin/herdr" ]; then
      ok "herdr resolves to the wrapper (zsh interactive)"
    else
      bad "herdr resolves to '${got:-nothing}' in zsh -- ~/.zshrc ordering broke"
    fi
  fi
fi

# -- 5. No duplicate PATH entries -----------------------------------------
dups=$("${CLEAN_LOGIN[@]}" 'printf %s "$PATH"' 2>/dev/null | tr ':' '\n' | sort | uniq -d)
if [ -z "$dups" ]; then ok "login PATH has no duplicate entries"
else
  bad "login PATH has duplicate entries -- __path_dedup is not running last"
  printf '%s\n' "$dups" | sed 's/^/       > /'
fi

# -- 6. PATH and INFOPATH are stable under nesting ------------------------
# herdr panes spawn login shells inside login shells; neither may grow.
n1=$("${CLEAN_LOGIN[@]}" 'printf %s "$PATH"' 2>/dev/null | tr ':' '\n' | wc -l | tr -d ' ')
n2=$("${CLEAN_LOGIN[@]}" 'bash -lc "printf %s \"\$PATH\""' 2>/dev/null | tr ':' '\n' | wc -l | tr -d ' ')
if [ "$n1" = "$n2" ] && [ "$n1" -gt 0 ] 2>/dev/null; then
  ok "PATH stable under nesting ($n1 entries at both depths)"
else
  bad "PATH grows when shells nest: $n1 -> $n2 entries"
fi

# INFOPATH has no dedup pass, so its prepend must be guarded in ~/.bashrc.
i1=$("${CLEAN_LOGIN[@]}" 'printf %s "$INFOPATH"' 2>/dev/null)
i2=$("${CLEAN_LOGIN[@]}" 'bash -lc "printf %s \"\$INFOPATH\""' 2>/dev/null)
if [ "$i1" = "$i2" ]; then
  ok "INFOPATH stable under nesting"
else
  bad "INFOPATH grows when shells nest -- its prepend in ~/.bashrc lost its guard"
  note "depth 1: $i1"
  note "depth 2: $i2"
fi

# -- 7. Expected head of PATH ---------------------------------------------
# Catches installer appends to ~/.bash_profile, which land after
# `source ~/.bashrc` and so outrank every deliberate ordering decision.
want_head="$HOME/.herdr-wrapper/bin"
got_head=$("${CLEAN_LOGIN[@]}" 'printf %s "${PATH%%:*}"' 2>/dev/null)
if [ "$got_head" = "$want_head" ]; then ok "PATH head is the herdr wrapper dir"
else
  bad "PATH head is '$got_head', expected '$want_head'"
  note "likely an installer appended 'export PATH=' to ~/.bash_profile."
  note "Move it into ~/.bashrc's __path_prepend list and delete it there."
fi

# -- 8. System PATH survives a hostile/minimal starting environment -------
# `brew shellenv` replaces PATH wholesale when it can't see PATH in its own
# subprocess environment. Shells launched by launchd/cron with a minimal
# env hit exactly that, and would lose /usr/bin and /bin.
for probe in \
  "env -i HOME=$HOME TERM=xterm /bin/bash -lc" \
  "env -i HOME=$HOME TERM=xterm /bin/bash -ic" \
  "env -i HOME=$HOME BASH_ENV=$HOME/.bashrc /bin/bash -c"
do
  label=$(printf '%s' "$probe" | sed 's/.*bash //')
  missing=
  for sysdir in /usr/bin /bin /usr/sbin; do
    $probe "case \":\$PATH:\" in *:$sysdir:*) exit 0;; *) exit 1;; esac" 2>/dev/null \
      || missing="$missing $sysdir"
  done
  if [ -z "$missing" ]; then ok "system dirs present from a bare env (bash $label)"
  else bad "system dirs MISSING from a bare env (bash $label):$missing"; fi
done

# "." on PATH means every cd into an untrusted tree is a code-execution risk.
if "${CLEAN_LOGIN[@]}" 'case ":$PATH:" in *:.:*|*::*) exit 1;; *) exit 0;; esac' 2>/dev/null; then
  ok "PATH contains no '.' or empty component"
else
  bad "PATH contains '.' or an empty component (both mean current directory)"
fi

# -- 9. Inlined `brew shellenv` has not drifted ---------------------------
# ~/.bashrc reproduces brew shellenv literally to avoid spawning brew on
# every shell. If Homebrew changes what it exports, that copy goes stale.
# Compare against the real thing (slow, but this is a self-test).
if [ -x /opt/homebrew/bin/brew ]; then
  real=$(env -i HOME="$HOME" PATH=/usr/bin:/bin /bin/bash -c '
      eval "$(/opt/homebrew/bin/brew shellenv bash)" >/dev/null 2>&1
      printf "%s|%s|%s|%s\n" "$HOMEBREW_PREFIX" "$HOMEBREW_CELLAR" \
                             "$HOMEBREW_REPOSITORY" "$INFOPATH"' 2>/dev/null)
  ours=$("${CLEAN_BASHENV[@]}" '
      printf "%s|%s|%s|%s\n" "$HOMEBREW_PREFIX" "$HOMEBREW_CELLAR" \
                             "$HOMEBREW_REPOSITORY" "$INFOPATH"' 2>/dev/null)
  # INFOPATH is compared by prefix, not exactly: brew appends to whatever
  # INFOPATH it inherits, so the exact string depends on the invoking
  # environment and an exact match makes this check flaky. Prefix still
  # catches the drift that matters (changed prefix, or dropped entirely).
  real="${real%|*}|${real##*|}"; real="${real%%|/opt/homebrew/share/info*}|INFOPATH-ok"
  ours="${ours%|*}|${ours##*|}"; ours="${ours%%|/opt/homebrew/share/info*}|INFOPATH-ok"
  if [ "$real" = "$ours" ]; then ok "inlined brew shellenv matches brew's own output"
  else
    bad "inlined brew shellenv has DRIFTED from brew's own output"
    note "brew says : $real"
    note "bashrc has: $ours"
    note "re-inline from: brew shellenv bash"
  fi
  # brew must outrank /usr/bin -- they share many names (python3, git, curl).
  if "${CLEAN_LOGIN[@]}" '
      p=":$PATH:"; hb="${p%%:/opt/homebrew/bin:*}"; us="${p%%:/usr/bin:*}"
      [ ${#hb} -lt ${#us} ]' 2>/dev/null; then
    ok "/opt/homebrew/bin outranks /usr/bin"
  else
    bad "/opt/homebrew/bin does NOT outrank /usr/bin -- brew tools are shadowed"
  fi
fi

# -- 10. Key tools still resolve where they should ------------------------
# Guards the collision decisions documented in ~/.bashrc's PATH section.
check_resolves_contains() {
  local got; got=$("${CLEAN_LOGIN[@]}" "command -v $1" 2>/dev/null)
  case "$got" in
    *"$2"*) ok "$1 -> $got" ;;
    "")    bad "$1 does not resolve at all" ;;
    *)     bad "$1 -> $got (expected to contain $2)" ;;
  esac
}
check_resolves() {  # name expected-prefix
  local got; got=$("${CLEAN_LOGIN[@]}" "command -v $1" 2>/dev/null)
  case "$got" in
    "$2"*) ok "$1 -> $got" ;;
    "")    bad "$1 does not resolve at all" ;;
    *)     bad "$1 -> $got (expected under $2)" ;;
  esac
}
check_resolves brew  /opt/homebrew/bin
check_resolves cargo /opt/homebrew/opt/rustup/bin
# Android SDK tools are appended, not prepended (2026-10-06): its old sqlite3 must
# not shadow macOS sqlite3, and adb comes from Homebrew (same release).
check_resolves adb /opt/homebrew/bin
check_resolves sqlite3 /usr/bin
check_resolves grok  "$HOME/.local/bin"
check_resolves opencode "$HOME/.opencode/bin"
check_resolves aiuse "$HOME/.local/bin"

# The Orca defect of 2026-08-21: panes inherit the daemon's PATH, where
# /opt/homebrew/bin already outranks ~/.local/bin, and the idempotent
# prepend left aiuse resolving to a broken Homebrew copy. The tier-1
# ordering list must force its order onto an inherited PATH
# (__path_prepend_force), not merely ensure presence.
if [ -x "$HOME/.local/bin/aiuse" ]; then
  hostile="/opt/homebrew/bin:$HOME/.local/bin:/usr/bin:/bin"
  got=$(env -i HOME="$HOME" PATH="$hostile" BASH_ENV="$HOME/.bashrc" \
          /bin/bash -c 'command -v aiuse' 2>/dev/null)
  if [ "$got" = "$HOME/.local/bin/aiuse" ]; then
    ok "aiuse beats Homebrew even from a hostile inherited PATH"
  else
    bad "aiuse resolves to '${got:-nothing}' from a hostile inherited PATH"
    note "the tier-1 ordering list must use __path_prepend_force, not the"
    note "idempotent __path_prepend -- it cannot fix a bad inherit."
  fi
fi

# -- 10b. No alias may shadow a name Orca defines as a function -----------
# Orca's generated bash rcfile defines codex() and omp() wrappers AFTER
# sourcing this config. bash alias-expands function names at parse time, so
# an alias on either name is a syntax error at every Orca pane launch --
# even inside an if-branch that never runs (2026-08-21).
if env -i HOME="$HOME" TERM=xterm /bin/bash -ic \
     'eval "codex() { :; }; omp() { :; }"' 2>/dev/null; then
  ok "no alias blocks Orca's rcfile function definitions (codex, omp)"
else
  bad "an alias on codex or omp breaks Orca's generated bash rcfile parse"
  note "keep these as functions (or other names) in ~/.bashrc tier 2."
fi

# OpenCode only accepts --auto for its TUI and `run`; prepending it to
# administrative subcommands makes the CLI print root help and exit 1.
if env -i HOME="$HOME" TERM=xterm /bin/bash -ic \
     'opencode debug info >/dev/null 2>&1'; then
  ok "opencode wrapper leaves administrative subcommands untouched"
else
  bad "opencode wrapper breaks administrative subcommands"
  note "default --auto only for the TUI and run, not debug/mcp/upgrade/etc."
fi

# -- 11. JAVA_HOME sanity --------------------------------------------------
jh=$("${CLEAN_LOGIN[@]}" 'printf %s "${JAVA_HOME:-}"' 2>/dev/null)
if [ -z "$jh" ]; then
  note "JAVA_HOME unset (openjdk@25 not installed) -- Android Gradle builds will fail"
elif [ -d "$jh" ]; then ok "JAVA_HOME points at an existing JDK"
else bad "JAVA_HOME='$jh' does not exist"; fi

# -- Summary --------------------------------------------------------------
printf '\n%d passed, %d failed\n\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
