# macos

What in this folder cuts the RAM and CPU macOS spends on its own background
daemons, and how to install that on a Mac that does not have the rest of
`~/ops`.

On this machine the same policy is also enforced by
[`roles/watchdogd`](../roles/watchdogd/README.md) (`apple-daemons`, every 60
seconds) and by [`sip-doit-with-sudo.sh`](sip-doit-with-sudo.sh) (the durable
`launchctl disable` flags). The lists are the same file,
[`quiet/daemons.tsv`](quiet/daemons.tsv). `tests/test_quiet_mac.py` fails if
the copies drift.

## What actually saves memory

A stopped process keeps the RAM it already holds. `SIGSTOP` stops it from
allocating more, and launchd does not start a second copy, because the job
has not exited. The saving is the growth that never happens.

Measured on this Mac (2026-11-15): 16 stopped Apple processes were holding
about 11 MiB RSS between them. `suggestd` was 704 KB. They were frozen before
they could balloon. Killing the same daemons every minute does not get there.
A 2026-10-10 trial left `suggestd` burning about a core in the gaps, and each
respawn allocates again.

Three other levers are larger than the frozen RSS:

1. **Spotlight indexing stays off** (`mdutil -a -i off`). `mds` and
   `mds_stores` stay small because they are not crawling every volume. The
   on-disk file index is left in place. Indexing is turned back off within a
   minute if a reboot or a volume mount enables it.
2. **CoreSpotlight semantic caches are emptied** once they pass 50 MiB.
   These are embeddings, not the file index. On 2026-11-15
   `~/Library/Metadata/CoreSpotlight/DocumentProcessing` was about 1.0 GiB,
   over that cap. The file index (`index.spotlightV3`) is not touched.
3. **Apple Intelligence models are not downloaded.** The restrictions
   profile below points the model-asset URLs at `127.0.0.1:9`. Those models
   are the multi-gigabyte part. The profile is a separate, one-time approval
   in System Settings. See
   [`no-apple-intelligence/README.md`](no-apple-intelligence/README.md).

`launchctl disable` is set too. It survives a reboot on disk, and it is the
part a later run can check. On this macOS it does **not** stop launchd from
starting the job when something sends it an XPC. That was measured
2026-10-10: the flags were already set, and launchd had still launched
`suggestd` 22 times and `triald` 148 times since boot. The 60-second fixer
is the part that holds.

## What gets frozen, killed, or left alone

The full list, with the reason on each line, is
[`quiet/daemons.tsv`](quiet/daemons.tsv).

| Action | Meaning | Examples |
| --- | --- | --- |
| `freeze` | `SIGSTOP`. No CPU, no respawn, RAM stays at the size it had. | `suggestd`, `photoanalysisd`, `mediaanalysisd`, `sharingd`, `spotlightknowledged`, `chronod`, `weatherd`, `contactsd` |
| `term` | `SIGTERM`, then `SIGKILL`. RAM is released. Used for short jobs. | `triald`, `helpd`, `sirittsd`, `knowledgeconstructiond`, and the root jobs `cloudd`, `coreduetd`, `spindump`, `tailspind` |
| `flag` | Disable flag only. Killing them comes back within about a second, or `SIGSTOP` is refused. | `generativeexperiencesd`, `intelligencecontextd`, `intelligenceflowd`, `modelmanagerd`, `modelcatalogd`, `UsageTrackingAgent` |

Root jobs are never frozen. A stopped root process stalls shutdown, and the
thaw agent only sees this user's processes.

Two jobs are deliberately absent from the freeze list:

- **`BiomeAgent`.** A stopped `BiomeAgent` keeps the Mach port and never
  answers. The sudo password sheet waits forever on that XPC, so a cold
  `sudo` never prompts. Put back 2026-11-08.
- **`intelligenceflowd`.** Same class of bug: a stopped XPC service hangs
  its clients. It is flag-only.
- **`UsageTrackingAgent`.** `kill -STOP` returns "operation not permitted"
  (seen 2026-11-15, pid had been running five days). The disable flag is set.
  The process keeps running.

## What you give up

This is the policy used on this Mac. It is a real loss of features, not a
tune-up.

- iCloud does not sync (`cloudd`, user and system). Run `just revert` before
  signing into an Apple ID.
- Photos face and scene analysis, Visual Look Up, and Live Text stop.
- Spotlight's semantic and "related content" results stop. Filename search
  of an indexed volume still works. On this Mac the only indexed volume is
  the NeoFinder batch image; see [`neofinder/README.md`](neofinder/README.md).
- Siri, Shortcuts automations, App Shortcuts, widgets, Weather, Stocks,
  Tips, Screen Time stats, AirDrop, Handoff, Universal Clipboard, and
  Contacts stop.
- Writing Tools and on-device Apple Intelligence stay off. Xcode's code
  completion, Photos Clean Up, and inline text predictions are not in the
  profile and are not in the freeze list.
- A frozen XPC service makes its callers wait. A share sheet or a Mail
  address lookup that hangs is the symptom. `just revert` continues the
  process.

## Shutdown thaw

A stopped process never acts on the `SIGTERM` launchd sends at logout,
restart, or shutdown. On 2026-10-15 that stalled every restart for about
four minutes and then hard-reset the Mac.

`just install` loads `com.quiet-mac.thaw` with the freezer. It stays running.
When launchd signals it at shutdown, it continues every stopped process of
this user, sends `SIGTERM`, and `SIGKILL`s anything still alive after three
seconds. The site watchdog's `com.djbclark.shutdown-thaw` does the same job.
Either one is enough. `just enforce` will not freeze anything unless one of
them is loaded.

That thaw continues **every** stopped process of the user, including one you
stopped yourself. A stopped process of any kind stalls shutdown.

## Install without ~/ops

Needs `python3` (3.9 or newer; Homebrew's is the one the agent is given) and
`just`. An administrator password or Touch ID is asked once, for the
root-owned helper and one sudoers file.

```sh
cd macos
just install    # flags, 60s fixer, shutdown thaw, root helper
just status     # what is frozen, store sizes, whether the agents are loaded
just check      # silent and exit 0 when healthy; prints and exits 1 on a regression
just profile    # open the Apple Intelligence profile; approve it in System Settings
```

`just install` is safe to repeat. It copies the kit to
`~/.local/libexec/quiet-mac/` and the root half to
`/usr/local/libexec/quiet-mac/`. The root helper and its policy file are
root-owned. The sudoers line allows exactly three commands, with no
arguments: the helper, the revert helper, and `/usr/bin/mdutil -a -i off`.

Approve the profile separately:

System Settings → Privacy & Security → Profiles. The payload id is
`com.djbclark.no-apple-intelligence`. Removing the profile undoes it.

### What the 60-second fixer repairs

`com.quiet-mac.enforce` runs `quiet-mac enforce` at login and every 60
seconds. Each pass:

1. Sets any gui or user disable flag that has been cleared (a macOS update
   does this).
2. `SIGSTOP`s a freeze-list job that is running, and `SIGTERM`s a term-list
   job. A job that is already stopped is left stopped.
3. Asks the root helper to do the same for the system-domain list. The
   helper is `sudo -n` with no password.
4. Turns Spotlight indexing off on every volume, unless a NeoFinder batch
   window is in progress on this machine (01:00–05:45, or the nightly lock
   is held). A Mac without NeoFinder has no window.
5. Empties a CoreSpotlight semantic store that has grown past 50 MiB.

`just check` reports a job that has been running unfrozen for more than two
minutes, a missing disable flag, Spotlight indexing that came back, or a
semantic store over the cap. The fixer is what clears those. A flag-only
daemon that is running is healthy.

Logs: `~/Library/Logs/quiet-mac/`. One line per action. A pass that finds
nothing to do still prints a one-line summary to the launchd log.

### Undo

```sh
just revert      # enable the flags, continue frozen jobs, remove quiet-mac
just uninstall   # remove quiet-mac and continue frozen jobs; leave the flags set
```

`uninstall` stops the fixer. Launchd will start the daemons again the next
time something asks for them. The flags alone do not hold them down. Use
`revert` when you want the features back.

## On this machine, with ~/ops

The site watchdog already freezes and TERMs on the same list, and
`com.djbclark.shutdown-thaw` already thaws at shutdown. You do not need
`just install` here for the freeze. `just status` and `just check` are
read-only and safe either way.

`just install` on this Mac adds a second fixer next to that watchdog. Both
treat an already-stopped pid as a no-op. The site path is
`bin/apple_daemon_ban.sh` plus
`roles/watchdogd/files/apple_daemon_ban_root.sh`, installed under
`/usr/local/libexec/djbclark/`. The portable path is a different directory
and a different sudoers file (`/etc/sudoers.d/quiet-mac`), so they do not
overwrite each other.

Each pass of `bin/apple_daemon_ban.sh` also re-asserts the gui and user
disable flags (a macOS update clears them; on 2026-11-15 only `suggestd`
still had one) and runs `quiet-mac empty-stores`, so a semantic cache over
50 MiB is emptied by the site watchdog without `just install`. System-domain
flags still need root: `sudo macos/sip-doit-with-sudo.sh`. Flags still go through `sudo sip-doit-with-sudo.sh` (apply),
which also empties those caches even when they are under the cap.
`--status` / `--check` / `--revert` are unchanged. `--check` is the report
the site cron reads: it prints only on a regression and always exits 0.
`just check` exits 1 on a regression so a shell can see it.

NeoFinder, for people who want filename search while Spotlight indexing of
the real disks stays off: [`neofinder/README.md`](neofinder/README.md).
`just -f neofinder/justfile install`.

Who is keeping `mds` busy, as a diagnostic (it does not stop `mds`):
[`mds-xpc-clients/`](mds-xpc-clients/).

## Other tools in this folder

These do not change memory use.

| Path | What it is |
| --- | --- |
| [`athena-kerberos/`](athena-kerberos/README.md) | Moved to [athena-mac](https://forgejo.mit.edu/djbclark/athena-mac) |
| [`corner-rescue/`](corner-rescue/) | Top-left hot corner that recovers a stuck fullscreen space |
| [`graft-hook-timeout-fix/`](graft-hook-timeout-fix/) | LaunchAgent that repairs the graft hook timeout in `~/.claude/settings.json` |
| [`hourly-updates/`](hourly-updates/) | Hourly LaunchAgent; the per-app scripts live in `bin/hourly-updates.d/` |
| [`net-watch/`](net-watch/) | LaunchAgent plist for the home-link watchdog. Behaviour: [`docs/net-watch.md`](../docs/net-watch.md) |
| [`otp-to-clipboard/`](otp-to-clipboard/) | Copies a one-time code from a notification banner |
| [`stagger-login/`](stagger-login/) | Spreads login items so they do not all start at once |
| [`sip-doit-with-sudo.sh`](sip-doit-with-sudo.sh) | The flag applier described above, including the recoveryOS SIP wrappers |
