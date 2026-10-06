# Tracked mirrors of the bash startup files

Live copies under `~/` and `~/.config/bash/` are **canonical** — this
directory only versions them, the same rule as [`../claude/`](../claude/) and
the root `CLAUDE.md` distribute-and-symlink convention. Update both together.

| Mirror           | Live path                    |
| ---------------- | ---------------------------- |
| `bashrc`         | `~/.bashrc`                  |
| `bash_profile`   | `~/.bash_profile`            |
| `selftest.sh`    | `~/.config/bash/selftest.sh` |
| `zshrc`          | `~/.zshrc`                   |

`~/.bashrc.local` is optional and currently absent. If it is recreated, add
its `bashrc.local` mirror here at the same time.

The session-start hook that runs `selftest.sh` is mirrored separately at
[`../claude/hooks/cswap_quota_context.sh`](../claude/hooks/cswap_quota_context.sh).

## The structure, in one paragraph

`~/.bashrc` is the single load-bearing file. `~/.bash_profile` is a stub that
does nothing but source it, and `~/.bashrc.local` holds machine-local
overrides. `~/.bashrc` has exactly two sections split by a guard:

- **Tier 1** (above the guard) — PATH and exported env. Runs in *every*
  shell, including scripts and Claude Code's Bash tool, which reads this file
  via `BASH_ENV` (see `~/.claude/settings.json`) and nothing else. Must be
  silent and must not change parsing/globbing behavior.
- **Tier 2** (below the guard) — aliases, functions, prompt, completion, fzf,
  `shopt`. Interactive shells only.

Tier-1 rules apply in full inside `~/.bashrc.local`, which is sourced from
tier 1.

## Why it looks like this

Before 2026-08-17 the same content was spread over three tiers, with
`~/.bash_profile` holding "login-only" PATH and env. That third tier was not
load-bearing — non-login shells inherit their environment from the launching
login shell — so it existed only as an extra place to guess wrong about. It
produced real defects:

1. **The herdr self-closure-defense wrapper was disabled.**
   `~/.bashrc.local` did a raw `export PATH="$HOME/.local/bin:$PATH"` *after*
   `~/.bashrc` had prepended `~/.herdr-wrapper/bin`, so `herdr` resolved to
   the real binary in every shell on the machine. The "wrapper must resolve
   first" rule was asserted in three files' comments and enforced by none.
2. **An installer append outranked everything.** `rustup` appended
   `export PATH=...` to `~/.bash_profile` *after* its `source ~/.bashrc`
   line, putting it at the head of PATH.
3. **PATH grew without bound when shells nested** (32 → 46 entries per
   level). Herdr panes spawn login shells inside login shells.

The fixes are structural rather than one-off:

- `__path_prepend` / `__path_append` are **idempotent** — a directory already
  on PATH stays where it is, so first claim wins. A second prepend of the
  same dir can no longer reorder anything, which is what caused (1), and
  nesting no longer duplicates entries, which is (3).
- **The herdr wrapper is the deliberate exception**: a raw force-to-front
  prepend, positioned *after* the `~/.bashrc.local` source and dead last
  before `__path_dedup` — so a stray raw prepend in local overrides (the
  original defect) is structurally neutralized, not merely detected. Idempotence is right for everything else but
  wrong there — a shell inheriting a PATH where `~/.local/bin` already
  precedes the wrapper dir would see the wrapper "already present" and leave
  it in the losing position. That is not hypothetical: it is the state every
  shell on this machine was in before the fix, and any process still running
  from before it is in that state now. `__path_dedup` removes the duplicate
  lower entry. The self-test covers this with an explicitly hostile
  inherited PATH.
- `__path_dedup` runs last in tier 1 as a backstop for things that prepend
  unconditionally and aren't ours to change.
- `brew shellenv` is **inlined** rather than executed. It spawned brew (Ruby)
  plus `path_helper` on every shell — ~40ms that tier 1 would otherwise pay
  on every agent Bash-tool call. `selftest.sh` asserts the inlined values
  still match `brew shellenv`'s real output so it cannot drift silently.
- A **baseline PATH seed + `export PATH`** runs before the Homebrew block.
  `brew shellenv` reads PATH from its own subprocess environment; when PATH
  is unset or unexported (launchd, cron, `env -i bash`) it emits an
  unconditional assignment that drops `/usr/bin` and `/bin` entirely.

(2) cannot be prevented — installers append where they append. It is
*detected* instead: `selftest.sh` asserts the expected head of PATH.

## Changing any of this

Edit the live file, then run:

```bash
~/.config/bash/selftest.sh
```

It checks tier-1 silence and parsing neutrality, herdr wrapper precedence in
both shell flavors, PATH duplicates and nesting stability, the expected head
of PATH, system dirs surviving a bare environment, `brew shellenv` drift,
Homebrew outranking `/usr/bin`, and the tool-resolution decisions the PATH
ordering encodes.

`~/.claude/hooks/cswap_quota_context.sh` also runs it at Claude Code session
start, but only when one of the config files is newer than the last passing
run — so the usual cost is a single `stat`. Failures are reported on
**stderr**, because the hook's stdout carries its JSON payload.

Then copy the changed files into this directory and commit both together.

### A note on verifying changes

The PATH ordering encodes real collision decisions — `herdr`, `cargo`,
`rustc`, `grok`, `agent`, `composio`, `opencode`, `aiuse`, `tg` all exist in
more than one directory on PATH. When reordering, diff the full resolution
map rather than spot-checking:

```bash
env -i HOME="$HOME" TERM=xterm bash -lc '
  IFS=:; for d in $PATH; do [ -d "$d" ] || continue
    for f in "$d"/*; do [ -x "$f" ] && [ ! -d "$f" ] && basename "$f"; done
  done' | sort -u > /tmp/names.txt
env -i HOME="$HOME" TERM=xterm bash -lc '
  while read -r n; do echo "$n -> $(command -v "$n")"; done < /tmp/names.txt'
```

The 2026-08-17 consolidation was validated this way: 2596 command names, and
exactly one changed — `herdr`, from `~/.local/bin` to the wrapper, which was
the point.
