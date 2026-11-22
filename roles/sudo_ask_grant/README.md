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
| `files/sudo-ask-granted` | `/usr/local/libexec/sudo-ask-granted`, root:wheel 0755 | The root side: `exec -- CMD` (checks the grant file and the denylist itself, logs, execs), `status [--check -- CMD]`, `grant DURATION` (runs only from the installed path, only when it can prove a fresh authentication, see below), `revoke` (no arguments). `exec` resolves the program once, judges it, and runs exactly that file, with `PATH` (`/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin`, no user-owned directory) and `HOME` fixed (never the caller's). Python 3 run as `-IS` (isolated, no site); every path is hard-coded, no env var or argument moves one. |
| `files/sudo-ask-grant-setup.sh` | run by hand | `--print`, `--check [--diff]` (read-only); install, `--verify`, `--rollback` refuse unless given `--live` (see the guard below). |
| drop-in `/etc/sudoers.d/sudo-ask-grant` | root:wheel 0440 | NOPASSWD for **`exec *`, `status`, `status *` and `revoke ""` only** (`""` = no arguments, never a wildcard; the helper also refuses extra arguments to `revoke`); `Defaults!helper env_reset, timestamp_timeout=0`; and `Defaults:OPERATOR timestamp_timeout=0` (the shared sudo ticket is off, see below). `grant` matches no NOPASSWD line. |
| `/var/db/sudo-ask/grant` | root:wheel 0644 in a root:wheel 0755 dir | `{expires_utc, granted_utc, granted_by_uid, duration_s, nonce}`; written only by `grant`. |
| `/var/db/sudo-ask/audit-stamp` | root:wheel 0644, same dir | The epoch at which the last `status --audit` sweep started (see "Persistence is not bounded by the window"); written only by that sweep. |
| `/var/log/sudo-ask-grant.log` | root:wheel 0600 | one line per grant, revoke, refusal, denylist hit and run (UTC); command text capped at 4096 characters (a refused call, which anyone may make, at 256); rotated through `.log.1` ... `.log.5` above 8 MiB; every record except a refusal is also sent to the unified log (`logger`), which the user cannot rewrite. The client logs `GRANTED-WINDOW` etc. to `~/.local/state/sudo-ask/log`. |
| `bin/sudo-ask` | unchanged install (`~/.local/bin/sudo-ask`) | New subcommands and the window path; with no helper or no window the old dialog path runs unchanged. `sudo-ask -k CMD...` (the approval-probe form bgrun and load-watch use) runs with no dialog and no fresh authentication inside a window, `-k` dropped; outside one it is the normal dialog + `sudo -k`. Every sudo the client runs is `sudo -k CMD` (never leaves a ticket), except two `sudo -n HELPER ...` calls on NOPASSWD lines that only lower privilege or read: `--revoke`'s `revoke` and `--status --audit`'s `status --audit`. |
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
   `--rollback` (which removes the drop-in) restores the exact prior state, and `visudo -cf` checks it before install. **The install checks it, and undoes itself if the check fails**: after installing, the script asks `LC_ALL=C sudo -n -l` (sudo's own answer after reading ALL of sudoers, every drop-in in any order; it needs no password because of the NOPASSWD lines) and reads its two sections apart. In "Matching Defaults entries for OPERATOR" the last `timestamp_timeout` must be 0 (a bare `!timestamp_timeout` counts as 0; a missing line fails). In "Runas and Command-specific defaults" no `Defaults>` entry may mention `timestamp_timeout`, and no `Defaults!` entry (the helper's own included) may carry a value other than 0. The drop-in's own `Defaults!HELPER ... timestamp_timeout=0` line sits last in that second section, which is why the listing is not read as one text. The check fails closed on anything it cannot read: a value outside sudo's number grammar (`0_0`, `0e5`), a quoted value that mentions `timestamp_timeout`, a missing, renamed or duplicated Runas section, a Runas section without the helper's own `Defaults!` line, or an unknown line after the defaults. (sudo prints the first `Defaults!` entry on the same line as the last `Defaults>` entry; the check splits them again, so a `Defaults>` entry elsewhere on the machine does not by itself fail the install.) A failed or unreadable listing fails too, and a failed check removes the drop-in, helper and grant file again (`--verify` runs the same check on demand). **What this proves and what it does not:** it checks that the defaults sudo lists for this user and host say 0. It does not prove behaviour. The behavioural proof is `sudo -v; sudo -n /usr/bin/true; echo exit=$?; sudo -k` (must print `exit=1`), and it is a mandatory step of the reinstall runbook before the first `--grant`. Anything the listing does not show is not covered by it; the behavioural check is.
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
which it cannot satisfy. More exactly, the proof is that a real `sudo -k` was asked, not that it finished authenticating: a real
`/usr/bin/sudo -k HELPER grant 24h` that is still waiting at its prompt passes every check above, so anything root that sits below
such a process (or reuses its pid between two reads) could use it. That needs root already, which is the accepted in-window limit. (b) It assumes `sudo` stays an ancestor of the helper with identical argv (sudo's `use_pty`
monitor) and that sudo's `euid` and saved uid read as 0 while it runs. **Neither has been exercised on the live machine** (no
privileged command was run building this); if either is wrong, `grant` fails closed and the first `sudo-ask --grant` will say so.
(c) `grant` only runs from `/usr/local/libexec/sudo-ask-granted` (a copy elsewhere refuses), and the denylist protects that path.

**Accepted limit (operator ruling): a window can be extended from inside itself.** An open window runs agent code as root
(see below), and root can write the grant file directly: it can extend the window or open a new one with no Touch ID. Nothing
in the helper can prevent that; the checks above stop an agent that is NOT yet root from opening or extending a window, and
anyone who holds a sudo ticket is root (only layer 1, the ticket being off, stops a ticket holder; layers 2 and 3 do not). `revoke` ends
a window only if nothing persistent was left behind. `sudo-ask --status` shows the expiry **in the grant file itself** and warns
when it is later than the expiry recorded when the window was granted (that record is in the user's own state directory, so
it is a hint, not a proof); `revoke` prints the expiry the file really had.

`revoke` needs no authentication on purpose: it only lowers privilege, so an agent or the operator can end a window
from a panic button without a sensor. It takes no arguments (the sudoers line is `revoke ""`, the helper also refuses
extras).

`--verify` checks this on the installed system: it runs the ticket check above, and it FAILS if a plain `sudo -n /usr/bin/true` succeeds (with the ticket off no cached ticket is honoured, so a success means a live ticket or a NOPASSWD rule for `true`); then, with the ticket dropped,
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

`exec` runs the realpath it judged for the **top-level** program and the **top-level** script word, so a link switched
afterwards changes nothing there. A program or script typed **inside** something else (a wrapper such as `nohup`, `nice`,
`timeout`, `env`; `sh -c` text; `find -exec`; `xargs`; a script named inside `sh -c`) is run by the path as typed, so it is
covered by a link check instead: such a path prompts when any component of it (walked lexically from the working directory)
is a symbolic link that sits in a directory the invoking user can write (the user could repoint it between the check and
the run, for example during a `sleep`), or contains `..`. A script typed as the top-level argument gets the same link check
(stricter than needed there, on purpose). What this does not cover: a program that is a real file in a directory the user
cannot write is safe; one in a directory the user can write already prompts by the realpath rule above.

The helper's own `PATH` for resolving and running programs is `/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin`.
`/opt/homebrew/bin` and `/opt/homebrew/sbin` are left out: the invoking user owns them, so a bare name inside `sh -c` or a
wrapper that is found only there after the check could be created there while the command sleeps. A bare name that exists
only there is "not found", which means the dialog (it would have prompted anyway: Homebrew's Cellar is user-owned).
Consequence for a root program started in a window: it does not find Homebrew tools by bare name.

System tools in `/usr/bin`, `/bin`, `/sbin`, `/usr/sbin`, `/usr/libexec` run without a prompt; anything under `/opt/homebrew`
prompts. A test copies the helper to a temp "~/g" and runs `python3 ~/g grant 24h`: it prompts (adversary MED-3).

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
  symbolic) and any copy or move (`cp ditto rsync mv pax tar cpio install scp`) of a setuid or setgid file. For `chmod`
  the mode is the first word that is not one of BSD chmod's real option clusters (`-[HLPRfhvECNiI]+`; `--` ends them), so
  `-x,u+s`, `-w,+s` and `-x+s` count as modes. For `install` the `-m` is read out of BSD install's getopt clusters
  (`-pm 4755`, `-Sm4755`, `-pm4755`, also `--mode`). Extracting an archive as root restores owners and setuid files from
  it, so inside a window these prompt: `tar`/`bsdtar`/`gtar`/`gnutar` extracting (`-x`, `--extract`, `--get`, a cluster such as
  `-xpf`, old-style `xf`) unless **both** `--no-same-owner` and `--no-same-permissions` are given; `pax -r`; `cpio -i` and
  `-p`; `ditto -x` and `-k` alone (extract; `-c`, with or without `-k`, creates); `unzip` unless its leading options include
  `-l`, `-t`, `-v`, `-p` or `-Z`. Listing and creating (`tar -tf`/`-cf`, `pax -w`, `ditto -c`, `cpio -o`) run. This is a
  judgment on the options of these named programs, not a parse of every extractor: others (`xar`, `7z`, `jar`, `pkgutil`,
  `installer`, `hdiutil`) are not looked at, and a setuid file made by a program the helper cannot see inside is what the
  sweep below reports afterwards. Writes to
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

Cannot, outside a window and without a sudo ticket: open or extend a window (a fresh Touch ID is needed, see above). Inside a window
it is root through `exec` and can (the accepted limit above). Cannot: run a denylisted command without the
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
time) runs a sweep and prints what changed since the grant: setuid/setgid files (each root with `find -xdev`, so a
different volume inside one is not entered) under exactly these: `/usr/local`, `/opt`, `/Applications`, `/Library`,
`/private/etc`, `/private/var/db`, `/private/var/root`, `/private/tmp`, `/private/var/tmp`, `/Users/Shared`, each volume
directly under `/Volumes` (listed when the sweep runs; links such as the boot volume's are skipped) and the invoking user's home,
and every launchd `Program`/`ProgramArguments` target or plist changed since. **Not swept:** `/private/var/folders`, other
users' homes, everything else on the data volume outside the roots above, and anything on a volume mounted below one
of these roots. It is a best-effort list, not a proof; read it
after every window and treat a finding as an incident.

Limits on the sweep, because `status --audit` has a NOPASSWD sudoers line (any agent can call it, with no window) and runs
a root `find`: each root gets at most 60 s and all roots together at most 120 s (a root not reached is printed as skipped,
incomplete); a second `status --audit` within 60 s of the start of the last one is refused (exit 75, no `find`, one
`REFUSED(...)` log line), and so is one that starts while another is running. The time of the last sweep is kept in the
root-owned `/var/db/sudo-ask/audit-stamp` under an exclusive lock; a stamp or directory that is not root-owned and
non-writable makes the sweep refuse. `--status --audit` with no grant time known runs no sweep and uses no slot. `--revoke`
sweeps only when a grant file existed (it is a NOPASSWD line too, so it cannot be a free way to start sweeps) and is not
subject to the one-a-minute limit, which keeps the end-of-window report; a second `revoke` with no grant file prints that it
skipped the sweep.

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

`tests/test_sudo_ask_grant.py` (`just test`; the process-tree proof is tested against real child processes; the setuid, archive, link,
sweep-root and sweep-limit rules of the follow-up have their own tests, each checked with a mutant): duration grammar, every grant-file failure (expired,
future-dated, >24h, wrong owner, writable, symlink, damaged), each denylist class, wrapper unwrapping and
unparseable wrappers, case-insensitive paths, `main()` modes against a temp boundary (the installed helper
has no test hook: the test patches module constants in-process), the sudoers rule shape (`revoke ""`, no `grant`), ruling 1 (agent-writable code prompts, the MED-3 copy of the helper), the fresh-authentication proof (sudo with and without `-k`, nearest sudo decides), `revoke` with and without arguments, and the
client as a patched copy driven by absolute-path fakes (including a fake `approval-gate` and the `-k` probe form), the
setup script's `--live` guard (refusals, and a temp-dir fake that only logs). `tests/test_approval_gate.py`: the registry,
the ttl caps, the denylist through the gate, a missing or untrusted helper, the CLI exit codes, `ask`'s two exec targets.
`tests/test_bgrun_window.py`: bgrun with a fake gate in a throwaway HOME. Nothing in the suite calls real `sudo`, touches
`/var/db`, `/etc` or `/usr/local`, or runs a real install, verify or rollback.
