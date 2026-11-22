# roles/sudo_ask_grant

A timed **approval window** for `sudo-ask`: one Touch ID opens it; while it is open every agent's
`sudo-ask CMD...` runs as root with no dialog and no Touch ID, except commands on a denylist, which
still get the normal dialog + Touch ID. (Operator ruling 2026-11-22.)

```
sudo-ask --grant [DURATION]   # dialog + Touch ID; 30m, 2h, 8h, 1d (units s m h d); default 8h; 60s..24h
sudo-ask --revoke             # no Touch ID needed (it only lowers privilege); ends the window now
sudo-ask --status             # exit 0 open / 1 not; time shown in America/New_York, 12-hour AM/PM
```

`grant`, `revoke` and `status` without the dashes work only when no program of that name is on PATH.

## Pieces

| Piece | Where it ends up | What it does |
|---|---|---|
| `files/sudo-ask-granted` | `/usr/local/libexec/sudo-ask-granted`, root:wheel 0755 | The root side: `exec -- CMD` (checks the grant file and the denylist itself, logs, execs), `status [--check -- CMD]`, `grant DURATION` (runs only from the installed path, only when it can prove a fresh authentication, see below), `revoke` (no arguments). `exec` resolves the program once, judges it, and runs exactly that file, with `PATH` and `HOME` fixed (never the caller's). Python 3 run as `-IS` (isolated, no site); every path is hard-coded, no env var or argument moves one. |
| `files/sudo-ask-grant-setup.sh` | run by hand | `--print`, `--check [--diff]` (read-only); install, `--verify`, `--rollback` refuse unless given `--live` (see the guard below). |
| drop-in `/etc/sudoers.d/sudo-ask-grant` | root:wheel 0440 | NOPASSWD for **`exec *`, `status`, `status *` and `revoke ""` only** (`""` = no arguments, never a wildcard; the helper also refuses extra arguments to `revoke`); `Defaults!helper env_reset, timestamp_timeout=0`; and `Defaults:OPERATOR timestamp_timeout=0` (the shared sudo ticket is off, see below). `grant` matches no NOPASSWD line. |
| `/var/db/sudo-ask/grant` | root:wheel 0644 in a root:wheel 0755 dir | `{expires_utc, granted_utc, granted_by_uid, duration_s, nonce}`; written only by `grant`. |
| `/var/log/sudo-ask-grant.log` | root:wheel 0600 | one line per grant, revoke, refusal, denylist hit and run (UTC); command text capped at 4096 characters (a refused call, which anyone may make, at 256); rotated through `.log.1` ... `.log.5` above 8 MiB; every record except a refusal is also sent to the unified log (`logger`), which the user cannot rewrite. The client logs `GRANTED-WINDOW` etc. to `~/.local/state/sudo-ask/log`. |
| `bin/sudo-ask` | unchanged install (`~/.local/bin/sudo-ask`) | New subcommands and the window path; with no helper or no window the old dialog path runs unchanged. `sudo-ask -k CMD...` (the approval-probe form bgrun and load-watch use) runs with no dialog and no fresh authentication inside a window, `-k` dropped; outside one it is the normal dialog + `sudo -k`. Every sudo the client runs is `sudo -k CMD` (never leaves a ticket), except `--revoke`'s `sudo -n HELPER revoke`. |
| `bin/approval-gate` | `~/.local/bin/approval-gate` (symlink, like `sudo-ask`) | The ONE place that decides whether a window covers a gate: `status`, `check --gate NAME [--max-ttl S] [-- CMD...]` (exit 0 covered, 1 must prompt), `ask --gate NAME --reason TEXT -- CMD...`. `sudo-ask` and `bgrun` call it and reimplement nothing. |
| `config/approval-gates.toml` | the repo | The registry of gates, see below. |

## approval-gate and its registry

`bin/approval-gate` reads the grant file (world-readable, so no sudo) through the installed root helper's own plain
functions (`read_grant`, `evaluate`; it loads `/usr/local/libexec/sudo-ask-granted` only if root-owned and not
group/world-writable), so the window rules and the denylist exist once. Library vs CLI: a CLI, because the callers are bash
(`sudo-ask`, `bgrun`) and agents in other tools (`djbclark-ade`'s `load-watch`); the Python-importable `decide()` is there for
tests. `check` prints `ttl=` (seconds, the window's remainder capped by the gate's `max_ttl` and `--max-ttl`),
`expires_epoch=` and `expires_utc=`; exit 0 covered, 1 prompt, 2 usage. An unknown gate, an `always-prompt` gate, a closed or
damaged window, a missing helper and a denylisted `-- CMD` are all 1. The registry is convenience policy, not a security
boundary: the boundary is the root helper, which re-checks the window and denylist itself.

`config/approval-gates.toml`, one `[[gate]]` per gate, four keys: `name`; `owner` (repo-relative file that implements the
gate); `policy` (`window-ok`: an open window may stand in for the prompt; `always-prompt`: never); `max_ttl` (seconds a grant
made on the window's strength may last, `0` = until the window ends; always capped at the window's end). Seeded with
`sudo-ask`, `bgrun-approve-local` (1 h), `bgrun-ticket`, and one `always-prompt` entry per denylist class. Python < 3.11
parses the file with a small built-in reader for exactly this subset.

bgrun: `approve-local` (one-shot token) and tickets ask `~/.local/bin/approval-gate` first. Covered: no dialog, no Touch ID, no
sudo (the plain `sudo -k /usr/bin/true` fallback included), a token or ticket never outlives the window, and `--ask` skips the
duration chooser (a ticket until the window's end). `bin/tired` and `sudo-askpass-osascript` are not changed yet (follow-up).

## Why an agent cannot open or extend a window

Agents run as the operator, so they can run the NOPASSWD lines. Those lines cannot write the grant
file: `grant` matches no NOPASSWD entry, so sudo asks for a password / Touch ID. The grant file and its
directory are root-owned and not group/world writable. The helper refuses a file that is not root-owned, is
group/world writable, is a symlink, is damaged, is dated in the future, has a duration over 24h or an expiry
more than 24h away (a tampered far-future file), or is expired. Anything doubtful means "no window": `sudo-ask`
shows the dialog. The helper re-checks the denylist itself and never trusts the caller.

**Fresh authentication (adversary MED-1).** This Mac has a machine-wide sudo ticket (`/etc/sudoers.d/10-timestamp-global`).
That is the root cause: `timestamp_timeout=0` on the helper covers only the helper's own path, so one authentication
anywhere (a plain `sudo` an agent triggered, a Touch ID prompt for something else) leaves a ticket every process of the
user can ride, including `sudo -n /bin/sh -c '<helper> grant 24h'`. Three layers close that:

1. **The ticket is switched off** (operator ruling). The setup script's install mode puts
   `Defaults:OPERATOR timestamp_timeout=0` in the same drop-in. A later drop-in wins over an earlier one, so this beats
   `10-timestamp-global` without editing or deleting it: nothing else is touched, there is no second file to back up,
   `--rollback` (which removes the drop-in) restores the exact prior state, and `visudo -cf` checks it before install. **The install proves it works**, or undoes itself: after installing, the script asks `sudo -n -l` (sudo's own answer after reading ALL of sudoers, every drop-in in any order; it needs no password because of the NOPASSWD lines) and requires the last `timestamp_timeout` it lists to be 0. A later file that overrides the line, a missing or unreadable listing, or a value other than 0 fails the check, and a failed check removes the drop-in, helper and grant file again (`--verify` runs the same check on demand).
   (The alternative, removing `10-timestamp-global`, is root-only 0440 and would need a byte-exact root-side backup and
   restore; it also changes the file for every user.) `--print`, `--check` and `--diff` show it. After install, one
   `sudo -v` followed by `sudo -n true` must still ask.
2. `sudo-ask` runs its own sudo as `sudo -k CMD` (and `--grant` as `sudo -k HELPER grant DUR`): sudo ignores any
   cached ticket and does not leave one.
3. `grant` itself proves the authentication from the process tree, exactly. A process writes its own argv and its own
   executable path onto its stack and can put anything there, so those are only claims. Every ancestor is therefore
   judged by what **the kernel holds**: the executable path (`proc_pidpath`) is `/usr/bin/sudo`, the kernel name
   (`comm`) is `sudo`, and the effective and saved uids are 0 (sudo is setuid root; a user process never has that). The
   claims are read too (`proc_pidinfo` for the real uid and start time, `sysctl KERN_PROCARGS2` for the argument words, no
   `ps`, no word splitting) and the start time is read before and after to catch a reused pid. A link that claims to be
   sudo while the kernel says otherwise refuses at once, and any read error refuses. `grant` also requires to have been
   started by the exact installed path, not a link to it. What is accepted: the chain of ancestors is **all
   `/usr/bin/sudo`**, and the outermost one has argv exactly `[/usr/bin/sudo, -k, /usr/local/libexec/sudo-ask-granted,
   grant, DURATION]` with the real uid equal to `SUDO_UID` and not 0. So a nested sudo, a `-p 'x -k'` prompt, a shell or
   any other program between sudo and the helper, a window that is already running (`exec` chain), or a sudo started by
   another uid all refuse (exit 75, logged `GRANT-REFUSED`). It fails closed: an unreadable process, a pid that changed, or a
   missing sudo ancestor means no grant.

Limits, stated plainly: (a) the proof is that sudo was told to ignore the cached ticket (so it asked for authentication), not
that a person touched the sensor; an agent that runs `sudo -k <helper> grant` itself still meets the Touch ID prompt,
which it cannot satisfy. (b) It assumes `sudo` stays an ancestor of the helper with identical argv (sudo's `use_pty`
monitor) and that sudo's `euid` and saved uid read as 0 while it runs. **Neither has been exercised on the live machine** (no
privileged command was run building this); if either is wrong, `grant` fails closed and the first `sudo-ask --grant` will say so.
(c) `grant` only runs from `/usr/local/libexec/sudo-ask-granted` (a copy elsewhere refuses), and the denylist protects that path.

**Accepted limit (operator ruling): a window can be extended from inside itself.** An open window runs agent code as root
(see below), and root can write the grant file directly: it can extend the window or open a new one with no Touch ID. Nothing
in the helper can prevent that; the checks above stop an agent that is NOT yet root from opening or extending a window, and
anyone who holds a sudo ticket is root (layer 1, the ticket being off, is what stops that; layers 2 and 3 do not). `revoke` ends
a window only if nothing persistent was left behind. `sudo-ask --status` shows the expiry **in the grant file itself** and warns
when it is later than the expiry recorded when the window was granted (that record is in the user's own state directory, so
it is a hint, not a proof); `revoke` prints the expiry the file really had.

`revoke` needs no authentication on purpose: it only lowers privilege, so an agent or the operator can end a window
from a panic button without a sensor. It takes no arguments (the sudoers line is `revoke ""`, the helper also refuses
extras).

`--verify` proves this on the installed system: it warns if a sudo ticket is cached (and prints how to see the ticket is off); then, with the ticket dropped,
`sudo -n helper grant` must fail, `sudo -n -l helper revoke` must be allowed and `... revoke extra` refused (a sudoers
question, nothing is revoked), `status` must work, and `exec` with no window must exit 75.

## Agent-writable code prompts, even in a window (ruling 1)

The denylist is not a sandbox, because root running code an agent can edit is root for the agent. So inside a window,
`exec` refuses (and `sudo-ask` shows the dialog + Touch ID) when:

- the program, after realpath, lives where the invoking user (`SUDO_UID`) can write it: it or any directory above it is
  owned by that user, group-writable in one of the user's groups, or world-writable; everything under `/tmp`,
  `/private/tmp`, `/var/folders`, `/var/tmp` counts as writable. An unknown invoking user, or a stat error, counts as
  writable (prompt);
- an interpreter or shell is given a script (`python3 x.py`, `sh x.sh`, `perl x.pl`) that is agent-writable, missing, not a
  regular file, or is `/dev/stdin` / `/dev/fd/N`; or loads code that cannot be checked (`python -m`, `node -r/--import`,
  `perl -M` with unusual characters, inline `-c`/`-e`);
- `make`, `gmake`, `just`, `xcodebuild` or `git` runs in an agent-writable working directory (they read Makefile,
  justfile, hooks from there);
- the program or script was created or changed at or after the moment the window was granted (ctime or mtime): a file the
  window's own commands wrote is never run;
- the location is on a `nosuid` volume (an attached image), or, when the helper runs as root, the kernel says the user
  can write it (a child that has dropped to the user checks the file and every directory above it, so ACLs and
  `noowners` volumes count);
- the script is a library module of an interpreter (`site-packages`, `lib/python3.x`, a `Python3.framework`, Perl or Ruby
  library trees, `node_modules`): those are root-owned programs that run code from their arguments (`timeit`, `pdb`,
  `http.server` ...).

`exec` runs the realpath it judged, for the program and for the script, so a link switched afterwards changes nothing.

System tools in `/usr/bin`, `/bin`, `/sbin`, `/usr/sbin`, `/usr/libexec` and root-owned Homebrew paths run without a prompt.
A test copies the helper to a temp "~/g" and runs `python3 ~/g grant 24h`: it prompts (adversary MED-3).

## The denylist (still dialog + Touch ID inside a window)

Checked on the resolved program (realpath, so a symlink to `visudo` is `visudo`) and on every
argument path (realpath, case-insensitive, relative to the caller's directory), after unwrapping
`env`, `nice`, `nohup`, `time`, `command`, `timeout`, `sudo`, `sh -c`/`bash -c` (parsed with a
conservative tokenizer), `env -S`, `xargs`, `find -exec`.

- Programs: `visudo`, `csrutil`, `nvram`, `tccutil`; `diskutil` unless the verb is read-only (so every
  `erase*`, `partitionDisk`, `apfs delete*` prompts); `dscl` / `dseditgroup` / `sysadminctl` unless read-only
  (users, groups, admin membership); `security` unless a read-only verb (login keychain);
  `rm`/`chmod`/`chown`/`chgrp -R` on `/`, a top-level directory or a home directory; `--no-preserve-root`.
- Persistence paths (writes): `/Library/LaunchDaemons`, `/Library/LaunchAgents`, `/Library/StartupItems`, `/etc/periodic`,
  `/usr/lib/cron`, `/var/at`, `/etc/paths` and `/etc/paths.d`, the root shell startup files (`/etc/zshenv`, `zprofile`, `zshrc`,
  `profile`, `bashrc`), `/var/root`, `/etc/ssh`, `SecurityAgentPlugins`, `ld.so.conf`; `launchctl bootstrap|load|enable|submit|
  asuser|kickstart`; `crontab` anything but `-l`.
- Paths (writes, and anything not read-only): `/etc/sudoers`, `sudoers.d`, `sudo.conf`, `/etc/pam.d`,
  `/var/db/sudo-ask`, the helper and `/usr/local/libexec` + `/usr/local/sbin` (which hold the helper,
  the sudo-secretspec broker and its wrapper), `/var/db/dslocal`, TCC databases, keychains, `/dev/disk*`;
  an ancestor of one of these (`/`, `/etc`, `/usr/local`) as the target of a non-read-only command.
- Programs that run a command or script given in their own arguments or input (operator ruling, hardening): `awk`, `nawk`,
  `gawk`, `mawk`, `sqlite3`, `vi`, `vim`, `ex`, `view`, `vimdiff`, `nvim`, `ed`, `emacs`, `less`, `more`, `man`, `m4`, `zip`,
  `dtrace`, `lldb`, `leaks`, `xctrace`, and the wrappers `taskpolicy`, `sandbox-exec`, `xcrun`, `launchctl bsexec`; `tar`
  with `-I`, `-F`, `--use-compress-program`, `--to-command`, `--checkpoint-action`, `--info-script`; `rsync` with `-e`,
  `--rsh`, `--rsync-path`, `--daemon`; `scp`/`sftp` with `-S`, `-D`, `-F` or `-o` carrying a command or proxy; `git` with
  `-c`, `-C`, `--git-dir`, `--work-tree`, `--exec-path`, `--config-env`, with `difftool`, `mergetool`, `filter-branch`,
  `bisect`, `submodule`, `rebase`, `daemon`, `hook`, `help`, with `config` unless it only reads, and with
  `--upload-pack`, `--receive-pack`, `--exec`, `--config`, `--template`, `-O`.
- Persistence beyond the paths above: `chmod`/`install -m`/`rsync --chmod` that sets a setuid or setgid bit (octal or
  symbolic) and any copy or move (`cp ditto rsync mv pax tar cpio install scp`) of a setuid or setgid file; writes to
  `/usr/local/bin`, `/Library/PrivilegedHelperTools`, `/Library/Preferences/com.apple.loginwindow` (and `defaults write`
  to that domain: `LoginHook`/`LogoutHook` run as root); every `Program`/`ProgramArguments` target named by a plist in
  `/Library/LaunchDaemons` and `/Library/LaunchAgents`, read at check time; a write through a link whose target is one
  of the protected paths (the link is judged by where it leads, and a root-owned file with another owner's hard link is
  refused).
- Added fail-closed extras (operator: trim if too broad): `fdesetup`, `passwd`, `pwpolicy`, `profiles`,
  `systemsetup`, `sntp`, `ntpdate`, `date SET` (the clock bounds the window), `su`, `ssh`, `tmux`,
  `screen`, `expect`, `script`, `at`, `chroot`, `osascript`, `launchctl submit|asuser`, `newfs_*`, `mkfs*`,
  `fdisk`, `gpt`, `asr`, interpreters with inline code (`python -c`, `perl -e`, ...), a shell reading stdin.
- Prompts when a wrapper's inner command cannot be parsed confidently: `$`, backticks, globs, braces,
  `cd`/`eval`/`source`, newlines, here-docs, subshells, `PATH=`/`IFS=` assignments, `xargs` feeding a
  command that is not read-only, `find -exec` without a terminator.
- Read-only programs (`ls cat grep stat ...`) may read protected paths; "read-only" is judged on the REAL program
  (a link named `cat` pointing at `cp` is `cp`). A root-owned file with other hard links is refused as an argument.
  `find -f PATH` counts PATH as a start path; an acting `find` with `-L`/`-H` prompts. Every `dseditgroup -o` must be
  `read`/`checkmember`. `#` and `$` anywhere in `sh -c` text prompt.

## What an agent can and cannot do during a window

Cannot, as long as it is not already root: open or extend a window (a fresh Touch ID is needed, see above). Cannot: run a denylisted command without the
dialog; run an unchecked program or a script it can edit without the dialog (ruling 1); change the grant file, the
helper, the drop-in, PAM, sudoers or the secretspec broker through a command line the helper can parse; run when the
log cannot be written. Can: end the window (`revoke`, no sensor needed).

**An open window runs agent code as root.** Say it that way and decide accordingly. **The denylist is hardening, not a
boundary.** It is a guard rail for the commands agents type: it removes the obvious ways to turn a window into permanent
root, and it cannot be complete. A root-owned system tool that can be driven to do anything (a package manager's
post-install hook, `installer`, `pkgutil`, `brew` from a root-owned prefix, `defaults write` to a system domain, a language
runtime given a program in its arguments) can be used to persist or to extend privilege. Open a window only for work you
are willing to give root, and prefer short ones. Approval is always Touch ID, never typed or pasted text.

**Persistence is not bounded by the window.** Ending the window does not undo what root did during it: a setuid file, a
launchd job, a login hook or a changed root-owned program stays. So `--revoke` (and `sudo-ask --status --audit`, any
time) runs a sweep and prints what changed since the grant: setuid/setgid files under `/usr/local`, `/opt`,
`/Applications`, `/Library`, root's and the user's home, the temp dirs and the volumes, and every launchd
`Program`/`ProgramArguments` target or plist changed since. It is a best-effort list, with a time limit, not a proof; read it
after every window and treat a finding as an incident.

## Install and roll back (operator, Touch ID)

```
roles/sudo_ask_grant/files/sudo-ask-grant-setup.sh --print        # what will be installed, with hashes
roles/sudo_ask_grant/files/sudo-ask-grant-setup.sh --check --diff # installed vs repo, read-only
just sudo-ask-grant-setup                                          # ONE sudo-ask dialog; root re-hashes its copies (--live)
just sudo-ask-grant-verify                                         # grant/revoke need auth; exec refuses with no window (--live)
just sudo-ask-grant-rollback                                       # remove drop-in (ticket behaves as before), helper, grant file, log kept (--live)
ln -s ../../ops/site-public-djbclark/bin/approval-gate ~/.local/bin/approval-gate   # once, for bgrun (sudo-ask finds it by itself)
```

**The `--live` guard.** Install, `--verify` and `--rollback` change or probe the real machine, so the script refuses
(exit 2, before any privileged call) unless you pass `--live`. The one exception is for tests: install and `--rollback` also
run when the `sudo-ask` they would call resolves (realpath) inside a temp directory, i.e. a fake. `--verify` always needs
`--live`. (Reason: a test once ran the install mode with a fake `sudo-ask` that the shell's PATH reordering ignored, and the
real installer ran; see the PR's Threat notes.) A test must name its fake by absolute path or set PATH inside the test
process, never rely on the shell's PATH.

The install dialog shows the two source files' SHA-256 prefixes; root copies both files to a
root-owned temp directory, re-hashes them, runs `visudo -cf` and only then installs, so a file swapped
after approval cannot be installed. Rollback leaves `sudo-ask` prompting as before.

## Tests

`tests/test_sudo_ask_grant.py` (`just test`; the process-tree proof is tested against real child processes): duration grammar, every grant-file failure (expired,
future-dated, >24h, wrong owner, writable, symlink, damaged), each denylist class, wrapper unwrapping and
unparseable wrappers, case-insensitive paths, `main()` modes against a temp boundary (the installed helper
has no test hook: the test patches module constants in-process), the sudoers rule shape (`revoke ""`, no `grant`), ruling 1 (agent-writable code prompts, the MED-3 copy of the helper), the fresh-authentication proof (sudo with and without `-k`, nearest sudo decides), `revoke` with and without arguments, and the
client as a patched copy driven by absolute-path fakes (including a fake `approval-gate` and the `-k` probe form), the
setup script's `--live` guard (refusals, and a temp-dir fake that only logs). `tests/test_approval_gate.py`: the registry,
the ttl caps, the denylist through the gate, a missing or untrusted helper, the CLI exit codes, `ask`'s two exec targets.
`tests/test_bgrun_window.py`: bgrun with a fake gate in a throwaway HOME. Nothing in the suite calls real `sudo`, touches
`/var/db`, `/etc` or `/usr/local`, or runs a real install, verify or rollback.
