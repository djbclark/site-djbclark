# roles/sudo_ask_grant

A timed **approval window** for `sudo-ask`: one Touch ID opens it; while it is open every agent's
`sudo-ask CMD...` runs as root with no dialog and no Touch ID, except commands on a denylist, which
still get the normal dialog + Touch ID. (Operator ruling 2026-11-22.)

```
sudo-ask --grant [DURATION]   # dialog + Touch ID; 30m, 2h, 8h, 1d (units s m h d); default 8h; 60s..24h
sudo-ask --revoke             # Touch ID; ends the window now
sudo-ask --status             # exit 0 open / 1 not; time shown in America/New_York, 12-hour AM/PM
```

`grant`, `revoke` and `status` without the dashes work only when no program of that name is on PATH.

## Pieces

| Piece | Where it ends up | What it does |
|---|---|---|
| `files/sudo-ask-granted` | `/usr/local/libexec/sudo-ask-granted`, root:wheel 0755 | The root side: `exec -- CMD` (checks the grant file and the denylist itself, logs, execs), `status [--check -- CMD]`, `grant DURATION`, `revoke`. Python 3 run as `-IS` (isolated, no site); every path is hard-coded, no env var or argument moves one. |
| `files/sudo-ask-grant-setup.sh` | run by hand | `--print`, `--check [--diff]`, install, `--verify`, `--rollback`. |
| drop-in `/etc/sudoers.d/sudo-ask-grant` | root:wheel 0440 | NOPASSWD for **`exec *`, `status`, `status *` only**; `Defaults!helper timestamp_timeout=0`. |
| `/var/db/sudo-ask/grant` | root:wheel 0644 in a root:wheel 0755 dir | `{expires_utc, granted_utc, granted_by_uid, duration_s, nonce}`; written only by `grant`. |
| `/var/log/sudo-ask-grant.log` | root:wheel 0644 | one line per grant, revoke, refusal, denylist hit and run (UTC). The client logs `GRANTED-WINDOW` etc. to `~/.local/state/sudo-ask/log`. |
| `bin/sudo-ask` | unchanged install (`~/.local/bin/sudo-ask`) | New subcommands and the window path; with no helper or no window the old dialog path runs unchanged. |

## Why an agent cannot open or extend a window

Agents run as the operator, so they can run the NOPASSWD lines. Those lines cannot write the grant
file: `grant` and `revoke` match no NOPASSWD entry, so sudo asks for a password / Touch ID, and the
drop-in sets `timestamp_timeout=0` for the helper so a cached sudo ticket never stands in for one.
`sudo-ask --grant` also runs `sudo -k` first. The grant file and its directory are root-owned and
not group/world writable. The helper refuses a file that is not root-owned, is group/world writable,
is a symlink, is damaged, is dated in the future, has a duration over 24h or an expiry more than 24h
away (a tampered far-future file), or is expired. Anything doubtful means "no window": `sudo-ask`
shows the dialog. The helper re-checks the denylist itself and never trusts the caller.

`--verify` proves this on the installed system: with no cached ticket, `sudo -n helper grant` and
`revoke` must fail, `status` must work, and `exec` with no window must exit 75.

## The denylist (still dialog + Touch ID inside a window)

Checked on the resolved program (realpath, so a symlink to `visudo` is `visudo`) and on every
argument path (realpath, case-insensitive, relative to the caller's directory), after unwrapping
`env`, `nice`, `nohup`, `time`, `command`, `timeout`, `sudo`, `sh -c`/`bash -c` (parsed with a
conservative tokenizer), `env -S`, `xargs`, `find -exec`.

- Programs: `visudo`, `csrutil`, `nvram`, `tccutil`; `diskutil` unless the verb is read-only (so every
  `erase*`, `partitionDisk`, `apfs delete*` prompts); `dscl` / `dseditgroup` / `sysadminctl` unless read-only
  (users, groups, admin membership); `security` unless a read-only verb (login keychain);
  `rm`/`chmod`/`chown`/`chgrp -R` on `/`, a top-level directory or a home directory; `--no-preserve-root`.
- Paths (writes, and anything not read-only): `/etc/sudoers`, `sudoers.d`, `sudo.conf`, `/etc/pam.d`,
  `/var/db/sudo-ask`, the helper and `/usr/local/libexec` + `/usr/local/sbin` (which hold the helper,
  the sudo-secretspec broker and its wrapper), `/var/db/dslocal`, TCC databases, keychains, `/dev/disk*`;
  an ancestor of one of these (`/`, `/etc`, `/usr/local`) as the target of a non-read-only command.
- Added fail-closed extras (operator: trim if too broad): `fdesetup`, `passwd`, `pwpolicy`, `profiles`,
  `systemsetup`, `sntp`, `ntpdate`, `date SET` (the clock bounds the window), `su`, `ssh`, `tmux`,
  `screen`, `expect`, `script`, `at`, `chroot`, `osascript`, `launchctl submit|asuser`, `newfs_*`, `mkfs*`,
  `fdisk`, `gpt`, `asr`, interpreters with inline code (`python -c`, `perl -e`, ...), a shell reading stdin.
- Prompts when a wrapper's inner command cannot be parsed confidently: `$`, backticks, globs, braces,
  `cd`/`eval`/`source`, newlines, here-docs, subshells, `PATH=`/`IFS=` assignments, `xargs` feeding a
  command that is not read-only, `find -exec` without a terminator.
- Read-only programs (`ls cat grep stat ...`) may read protected paths.

## What an agent can and cannot do during a window

Cannot: open, extend or end a window; run a denylisted command without the dialog; change the grant
file, the helper, the drop-in, PAM, sudoers or the secretspec broker through a command line the
helper can parse; run when the log cannot be written.

Can: everything else as root, for up to the window. **The denylist is a guard rail for the commands
agents type, not a sandbox.** A script an agent wrote (`sudo-ask python3 x.py`, `sh x.sh`, a compiled
binary) runs unchecked, so in a window a determined agent has root, including persistence
(LaunchDaemons, new users via a script, ssh keys) that outlives the window. Open a window only for
work you are willing to give root, and prefer short ones. Approval is always Touch ID, never typed or pasted
text.

## Install and roll back (operator, Touch ID)

```
roles/sudo_ask_grant/files/sudo-ask-grant-setup.sh --print        # what will be installed, with hashes
roles/sudo_ask_grant/files/sudo-ask-grant-setup.sh --check --diff # installed vs repo, read-only
just sudo-ask-grant-setup                                          # ONE sudo-ask dialog; root re-hashes its copies
just sudo-ask-grant-verify                                         # grant/revoke need auth; exec refuses with no window
just sudo-ask-grant-rollback                                       # remove drop-in, helper, grant file (log kept)
```

The install dialog shows the two source files' SHA-256 prefixes; root copies both files to a
root-owned temp directory, re-hashes them, runs `visudo -cf` and only then installs, so a file swapped
after approval cannot be installed. Rollback leaves `sudo-ask` prompting as before.

## Tests

`tests/test_sudo_ask_grant.py` (`just test`): duration grammar, every grant-file failure (expired,
future-dated, >24h, wrong owner, writable, symlink, damaged), each denylist class, wrapper unwrapping and
unparseable wrappers, case-insensitive paths, `main()` modes against a temp boundary (the installed helper
has no test hook: the test patches module constants in-process), the sudoers rule shape, and the
client as a patched copy driven by absolute-path fakes. Nothing in the suite calls real `sudo`, touches
`/var/db`, `/etc` or `/usr/local`, or runs the setup script's install, verify or rollback modes.
