# macos

What in this folder cuts the RAM and CPU macOS spends on its own background
daemons, and how to install that on a Mac that does not have the rest of
`~/ops`.

`just install` loads the watchdog itself: `com.quiet-mac.enforce`, every 60
seconds, and `com.quiet-mac.thaw` at shutdown. It does not need
[`roles/watchdogd`](../roles/watchdogd/README.md). On this machine that role's
`apple-daemons` rule also enforces the same list. [`sip-doit-with-sudo.sh`](sip-doit-with-sudo.sh)
is the older flag applier and is not required. The lists are the same file,
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
3. **Apple Intelligence models are not downloaded.** `just install` opens
   the restrictions profile and waits while you approve it in System Settings.
   Since macOS 11 the `profiles` command cannot install a configuration
   profile, so that approval is a click. The profile points the model-asset
   URLs at `127.0.0.1:9`. Those models are the multi-gigabyte part. See
   [`no-apple-intelligence/README.md`](no-apple-intelligence/README.md).

`launchctl disable` is set too. It survives a reboot on disk, and it is the
part a later run can check. On this macOS it does **not** stop launchd from
starting the job when something sends it an XPC. That was measured
2026-10-10: the flags were already set, and launchd had still launched
`suggestd` 22 times and `triald` 148 times since boot. The 60-second
watchdog is the part that holds. `just install` loads it as
`com.quiet-mac.enforce`. A Mac does not need `roles/watchdogd` first. If
that agent is missing, `just doctor` reports an error and `just install`
loads it.

## What gets frozen, killed, or left alone

The full list, with the reason on each line, is
[`quiet/daemons.tsv`](quiet/daemons.tsv).

| Action | Meaning | Examples |
| --- | --- | --- |
| `freeze` | `SIGSTOP`. No CPU, no respawn, RAM stays at the size it had. | `suggestd`, `photoanalysisd`, `mediaanalysisd`, `sharingd`, `spotlightknowledged`, `weatherd`, `contactsd` |
| `term` | `SIGTERM`, then `SIGKILL`. RAM is released. Used for short jobs. | `triald`, `helpd`, `sirittsd`, `knowledgeconstructiond`, and the root jobs `cloudd`, `spindump`, `tailspind` |
| `flag` | Disable flag only. Killing them comes back within about a second, or `SIGSTOP` is refused. | `generativeexperiencesd`, `intelligencecontextd`, `intelligenceflowd`, `coreduetd`, `modelmanagerd`, `modelcatalogd`, `UsageTrackingAgent` |

Root jobs are never frozen. A stopped root process stalls shutdown, and the
thaw agent only sees this user's processes.

These jobs are deliberately absent from the freeze list:

- **`BiomeAgent`.** A stopped `BiomeAgent` keeps the Mach port and never
  answers. The sudo password sheet waits forever on that XPC, so a cold
  `sudo` never prompts. Put back 2026-11-08.
- **`chronod`.** Notification Center waits synchronously for the widget service.
  Suspending it prevents Notification Center from opening on macOS 27.2.
- **`intelligenceflowd`.** Same class of bug: a stopped XPC service hangs
  its clients. It is flag-only.
- **`UsageTrackingAgent`.** `kill -STOP` returns "operation not permitted"
  (seen 2026-11-15, pid had been running five days). The disable flag is set.
  The process keeps running.

## What you give up

This is the policy used on this Mac. It is a real loss of features, not a
tune-up. The table further down is one row per daemon.

- iCloud does not sync (`cloudd`, user and system). Run `just revert` before
  signing into an Apple ID.
- Photos face and scene analysis, Visual Look Up, and Live Text stop.
- Spotlight's semantic and "related content" results stop. Filename search
  does not use Spotlight. It uses `plocate`, and NeoFinder if you install it.
  See [File search](#file-search).
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

Needs Homebrew, `python3` (3.9 or newer; Homebrew's is the one the agent is
given), and `just`. An administrator password or Touch ID is asked once, for
the root-owned helper and one sudoers file. If a nightly plocate service is
not already loaded, the same install starts Homebrew's plocate service,
which is a second administrator prompt.

```sh
cd macos
just install        # flags, fixer, thaw, root helper, system flags, plocate, Apple Intelligence profile
just doctor         # errors, warnings, and a nag if sudo or the profile was skipped
just status         # desired state, then errors and warnings
just check          # silent and exit 0 when the daemon policy holds; else exit 1
just system-flags   # only the system-domain flags (the sudo step)
just upgrade        # re-run install when this checkout is newer
just recovery       # how to open Recovery on this Mac; does not reboot
just profile        # open the Apple Intelligence profile again and print the steps
```

Version **1.1.0** is the constant in `quiet/quiet_mac.py`. `just install`
writes it to `~/.local/libexec/quiet-mac/VERSION`. `just upgrade` refuses to
replace a newer installed copy with an older checkout. When the versions
match, `just upgrade` still runs `just install`, and that run only repairs
drift.

`just install` is safe to repeat. The second run does not rewrite a file
whose bytes already match, does not reload an agent whose plist did not
change, and does not open the administrator dialog when the root helper and
sudoers file already match this tree. It does not open System Settings when
the Apple Intelligence profile is already installed. It still empties the CoreSpotlight
semantic caches (a no-op when they are already empty) and asks the root
helper to re-assert the system flags.

It copies the kit to `~/.local/libexec/quiet-mac/` and the root half to
`/usr/local/libexec/quiet-mac/`. The root helper and its policy file are
root-owned. The sudoers file allows exactly four commands: the helper,
the revert helper, `/usr/bin/mdutil -a -i off`, and `/usr/bin/profiles list`.
The last one is how `just doctor` sees this computer-level profile. An
unprivileged `profiles list` does not.

If the dialog is denied, the user half stays installed and `just doctor`
keeps reporting the missing system flags. A notification is posted at most
once every six hours until those flags are set. `just status` and
`just check` print the same nag. The 60-second fixer prints it too, on any
pass whose root helper fails.

Nothing here needs Recovery. `just recovery` prints the steps anyway, and
picks the Apple silicon steps or the Intel steps from `uname -m`. The
one-quiet-session SIP dance in [`sip-doit-with-sudo.sh`](sip-doit-with-sudo.sh)
is the only reason to use them, and that quiet ends at the next login.

### Apple Intelligence profile

`just install` opens
[`no-apple-intelligence/no-apple-intelligence.mobileconfig`](no-apple-intelligence/no-apple-intelligence.mobileconfig)
and waits until `com.djbclark.no-apple-intelligence` shows up. A later install
that finds it already installed does not open System Settings.

The clicks, on this Mac (macOS 15 and later, including macOS 27):

1. System Settings opens to General → Device Management. On macOS 13 and 14 that pane is Privacy & Security → Profiles. On macOS 12 and earlier it is System Preferences → Profiles.
2. In the Downloaded section, double-click "No Apple Intelligence (djbclark)". macOS drops a downloaded profile after about 8 minutes. Run `just install` again if it is gone.
3. Review the list, then click Continue or Install.
4. Click Install on the confirmation sheet.
5. Approve with Touch ID or the administrator password. Enter and Esc do not install it.

`just install` keeps waiting for about 8 minutes, then stops. `just doctor` reports the profile missing after that, and posts at most one notification every six hours. `just profile` prints the same steps and opens the file again. `just factory` tries to remove the profile. If that command cannot, delete it in the same Device Management pane.

The payload leaves Xcode code completion, Photos Clean Up, and inline text predictions alone.

### Not part of just install

These stay optional. Naming the recipe is what runs it.

1. NeoFinder catalogues: `just neofinder-install`. It refuses when NeoFinder.app is absent. plocate is the file-name search install always sets up.
2. `just corner-rescue`, `just graft-hook`, `just hourly-updates`, `just otp`, and `just mds-clients`. The last one only reports who is talking to `mds`.
3. `net-watch` and `stagger-login`. Those plists are installed by their own programs, outside this justfile.
4. `sip-doit-with-sudo.sh`, including its SIP-off bootout. That unload lasts until the next login. `just recovery` prints how to open Recovery and says to leave SIP on.
5. The rest of `roles/watchdogd` (litellm, the funnel, auxkc, and this site's other service rules). The diet's own watchdog is `com.quiet-mac.enforce`, and `just install` loads it when it is not already loaded.

### What the 60-second watchdog repairs

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

### Factory

`just factory` is the as-shipped Apple restore:

1. It continues every stopped process of this user. It does not terminate them.
2. It enables every disable flag in [`quiet/daemons.tsv`](quiet/daemons.tsv), including the system-domain ones. That step is one administrator dialog.
3. It turns Spotlight indexing back on (`mdutil -a -i on`).
4. It tries to remove the `com.djbclark.no-apple-intelligence` profile. If the command cannot, delete it in System Settings → Privacy & Security → Profiles.
5. It removes the quiet-mac agents and the root helper.
6. On a machine that has the site watchdog, it sets `enabled = false` in `~/.config/djbclark/watchdogd.d/apple-daemons.toml` so the next watchdog pass does not freeze the daemons again. A later site deploy can turn that rule back on.

It leaves plocate, NeoFinder, and Homebrew installed. Those are not Apple features. Emptied CoreSpotlight semantic caches are not restored. Apple rebuilds them. The site shutdown thaw stays loaded, because a leftover stopped process would stall the next reboot, and the thaw does nothing while the machine is up.

`just revert` is the smaller undo: flags on, quiet-mac removed, Spotlight left however it was.

## File search

Spotlight indexing of the real disks stays off, so `mdfind` does not search
them. Two replacements exist. NeoFinder is optional. plocate is part of this
kit.

### plocate (required)

`just install` requires Homebrew. It installs `plocate` if the `plocate`
command is missing (`brew install plocate`, and the `ylluminate/utilities`
tap if the formula is not already available). It starts Homebrew's nightly
service (`brew services start plocate`, label `sh.brew.plocate`) only when
no nightly is already loaded.

A nightly that already exists is left alone. On this Mac that is
`com.djbclark.plocate-updatedb`, which rebuilds
`/opt/homebrew/var/lib/plocate/plocate.db` at 03:30. Adding the Homebrew
service as well would index twice. `just doctor` warns when the database is
missing or older than 36 hours.

Search file names, not file contents:

```sh
plocate -i NAME
```

The index can be a day old. It still works when NeoFinder is installed:
plocate searches real paths from last night, including files no catalogue
has listed, and it does not need the NeoFinder batch volume to be mounted.
It does not search inside files. For that, `rg` with a path.

### NeoFinder (optional)

Do not assume NeoFinder is installed. `just neofinder-install` checks for
`NeoFinder.app` and stops if it is absent, with a pointer at `plocate -i`.
When the app is present, that recipe runs the setup in
[`neofinder/justfile`](neofinder/justfile): the batch disk image, the
root-owned index applier, the saved search, and the `~/.local/bin` links.
Full detail is [`neofinder/README.md`](neofinder/README.md).

NeoFinder catalogues become a small tree of aliases and zero-byte stubs on
`/Volumes/NeoFinderBatch`. Spotlight indexes only that volume, during an
update you start by hand (`just neofinder-nightly`). Nothing schedules it.
Finder and `mdfind` then search the tree:

```sh
mdfind -onlyin /Volumes/NeoFinderBatch 'kMDItemUserTags == "nf-image"'
mdfind -onlyin /Volumes/NeoFinderBatch 'kMDItemNFRealSize > 1000000000'
```

Offline disks show up as stubs. plocate only knows paths that were mounted
when its database was built. While a NeoFinder update is actually running
(01:00–05:45, the nightly lock, or the exporter process), quiet-mac does
not turn Spotlight indexing off. A Mac without NeoFinder has no such window.

## Upside and downside of each daemon

The upside is the memory or CPU that stops. The downside is the feature that
stops with it. `SIGSTOP` does not free RAM the process already holds.

| Label | Action | Upside | Downside |
| --- | --- | --- | --- |
| `com.apple.suggestd` | freeze gui | Stops the long-lived suggester. Killing it was measured to burn about a core in the respawn gaps. | Proactive suggestions and share-sheet suggestions stop. |
| `com.apple.cloudd` | freeze gui | Stops this user's iCloud daemon growing. | iCloud Drive, Photos, and Mail sync for this user stop. `just revert` before signing into an Apple ID. |
| `com.apple.photoanalysisd` | freeze gui | Face and scene analysis is a large CPU and RAM job. | Photos faces, scenes, and Memories stop updating. The library itself stays. |
| `com.apple.siriactionsd` | freeze gui | Long-lived. Killing it respawns it. | Shortcuts automations and App Intents stop. |
| `com.apple.sharingd` | freeze gui | KeepAlive. A kill comes straight back. | AirDrop, Handoff, Universal Clipboard, and Continuity Camera stop. |
| `com.apple.duetexpertd` | freeze gui | Sibling of suggestd. Same growth pattern. | CoreDuet personalization stops. |
| `com.apple.mediaanalysisd` | freeze gui | Visual analysis is a large resident job. | Visual Look Up, Live Text, and Photos object search stop. |
| `com.apple.campo` | freeze gui | KeepAlive, and it wakes `generativeexperiencesd`. | The Siri AI app stays down. |
| `com.apple.visualintelligenced` | freeze gui | Stops Visual Intelligence from staying resident. | Visual Intelligence stops. |
| `com.apple.siriknowledged` | freeze gui | Stops the Siri knowledge store growing. | Siri answers that need that store stop. |
| `com.apple.intelligenceplatformd` | freeze gui | Stops the on-device knowledge platform growing. | On-device knowledge features that use it stop updating. |
| `com.apple.homeenergyd` | freeze gui | Stops grid-forecast sync. | Home energy suggestions stop. Home control itself is a different daemon. |
| `com.apple.geoanalyticsd` | freeze gui | Stops Maps analytics. | Apple gets fewer Maps analytics. Maps still opens. |
| `com.apple.analyticsagent` | freeze gui | Stops the Mac Analytics collector. | Sharing analytics with Apple from this agent stops. |
| `com.apple.inputanalyticsd` | freeze gui | Stops keyboard and input analytics. | Those analytics stop. Typing still works. |
| `com.apple.proactiveeventtrackerd` | freeze gui | Stops proactive event tracking. | Proactive event suggestions stop. Calendar still works. |
| `com.apple.feedbackd` | freeze gui | Stops Feedback Assistant staying around. | Filing a Feedback Assistant report from this agent stops. |
| `com.apple.ap.adprivacyd` | freeze gui | Stops ad-privacy metric collection. | Personalized-ad metrics stop. |
| `com.apple.ap.promotedcontentd` | freeze gui | Stops promoted-content fetches. | Promoted content in Apple apps stops. |
| `com.apple.tipsd` | freeze gui | Stops Tips staying resident. | The Tips app stops updating. |
| `com.apple.UsageTrackingAgent` | flag gui | A disable flag is recorded. `kill -STOP` returns "operation not permitted" (seen 2026-11-15), so a freeze never lands. | The process keeps running, so the memory win is small. Screen Time may miss samples if the flag is honored. |
| `com.apple.knowledge-agent` | freeze gui | Stops the knowledge-store agent. | Knowledge features that use this agent stop. |
| `com.apple.weatherd` | freeze gui | Stops weather refresh. | Weather stops updating. |
| `com.apple.financed` | freeze gui | Stops stocks refresh. | Stocks stops updating. |
| `com.apple.studentd` | freeze gui | Stops Classroom and Schooltime background work. | Classroom and Schooltime features stop. |
| `com.apple.businessservicesd` | freeze gui | Stops Apple Business background sync. | Apple Business services that use it stop. |
| `com.apple.betaenrollmentagent` | freeze gui | Stops the beta-enrollment UI agent. | Beta enrollment UI from this agent stops. An installed beta keeps running. |
| `com.apple.spotlightknowledged` | freeze gui | Stops the semantic Spotlight daemon. | Spotlight's semantic and related-content results stop. Filename search is plocate, or NeoFinder if you install it. |
| `com.apple.spotlightknowledged.updater` | freeze gui | Stops the semantic index updater. | The semantic index stops updating. The file index is not this process. |
| `com.apple.spotlightknowledged.importer` | freeze gui | Stops the semantic importer. | New semantic embeddings are not imported. |
| `com.apple.triald` | term gui | Short one-shot. TERM releases its RAM instead of leaving it frozen. | Apple's experiment treatments stop applying. |
| `com.apple.helpd` | term gui | Short one-shot. TERM releases its RAM. | In-app Help Viewer content may not load. |
| `com.apple.sirittsd` | term gui | Idle-exits on its own. TERM releases the voices it loaded. | Spoken Content and Siri voices stop. |
| `com.apple.knowledgeconstructiond` | term gui | Nightly one-shot. TERM releases its RAM. | The on-device knowledge pipeline does not run. |
| `com.apple.generativeexperiencesd` | flag gui | Clients respawn a kill within about a second, so a kill saves nothing. | Writing Tools stop when the flag is honored. |
| `com.apple.intelligencecontextd` | flag gui | Clients respawn a kill within about a second. | Apple Intelligence context features stop when the flag is honored. |
| `com.apple.intelligenceflowd` | flag gui | Left running on purpose. A freeze hangs clients, including sudo's password sheet. | The live process stays, so the memory win is the flag, not a freeze. Do not SIGSTOP it. |
| `com.apple.contactsd` | freeze user | The Contacts store lives in the user domain and stays resident. | Contacts, and Mail address lookup, stop. A lookup that hangs is this freeze. |
| `com.apple.cloudd` | term system | The system iCloud daemon is TERM'd, which releases its RAM. It is never frozen: a stopped root process stalls shutdown. | System-side iCloud sync stops, on top of the user `cloudd` freeze. |
| `com.apple.triald.system` | term system | System half of experiment treatments. TERM releases its RAM. | System-side experiment treatments stop. |
| `com.apple.coreduetd` | flag system | Root half of CoreDuet; Mach IPC clients respawn a kill, so killing it only churns. | Root-side CoreDuet stays disabled at boot, but runs (~12 MB) when poked by XPC. |
| `com.apple.spindump` | term system | Hang reports spike CPU and RAM. TERM releases that. | Hang reports are not written, so a later diagnosis has less to read. |
| `com.apple.tailspind` | term system | Stall reports spike CPU and RAM. | Stall reports are not written. Same diagnostic loss as spindump. |
| `com.apple.modelmanagerd` | flag system | `coreaudiod` respawns a kill immediately, so the flag is the only lever. | On-device model loads that need this daemon do not start. Audio still plays. |
| `com.apple.modelcatalogd` | flag system | Same respawn problem as the model manager. | The model catalog does not start. |
| `com.apple.audioanalyticsd` | flag system | A kill is respawned by `coreaudiod`. | Audio analytics stop. Playback continues. |
| `com.apple.betaenrollmentd` | flag system | The daemon is not needed for a beta that is already installed. | Beta-enrollment checks from this daemon stop. |
| `com.apple.liquiddetectiond` | flag system | Stops liquid-detection telemetry. | Liquid-detection reports are not sent. The hardware itself is unchanged. |
| `com.apple.PerfPowerTelemetryClientRegistrationService` | flag system | Stops power-telemetry registration. | Apple's power telemetry from this service stops. The battery menu still works. |
| `com.apple.rtcreportingd` | flag system | Stops realtime telemetry reports. | Those reports are not sent. |
| `com.apple.osanalytics.osanalyticshelper` | flag system | Stops the OS analytics helper. | Analytics forwarding stops. Local crash logs from ReportCrash are a different process. |

`BiomeAgent` is not in the table. Stopping it keeps a Mach port that never
answers, and the sudo password sheet waits forever. It was put back on
2026-11-08.

## Recovery

`just recovery` prints these steps for the CPU this Mac is running on. It
does not reboot, and it does not change SIP.

Apple silicon: shut down, hold the power button until Loading startup
options appears, click Options, then Continue, then Utilities → Terminal.

Intel: restart and immediately hold Command-R until the Apple logo or a
spinning globe, then Utilities → Terminal. If Command-R finds nothing, hold
Option-Command-R for internet Recovery.

Leave SIP on. `sip-doit-with-sudo.sh` is not required for this diet.
`just install` sets the same disable flags, and `com.quiet-mac.enforce`
freezes or TERMs on the same list every 60 seconds. With SIP off, `launchctl
bootout` unloads Apple's jobs for this login only. They come back at the
next login, including when the flags are still set. That was measured on
2026-10-10. Turning SIP off does not make the standing diet stronger, and
the Mac is without System Integrity Protection until you turn it back on.

## On this machine, with ~/ops

This Mac also runs `roles/watchdogd`. That is not a prerequisite. A checkout
with no watchdogd still gets `com.quiet-mac.enforce` and `com.quiet-mac.thaw`
from `just install`. On this Mac both watchdogs run. Each treats an
already-stopped pid as a no-op. The site path is `bin/apple_daemon_ban.sh`
plus `roles/watchdogd/files/apple_daemon_ban_root.sh`, installed under
`/usr/local/libexec/djbclark/`. The portable path is a different directory
and a different sudoers file (`/etc/sudoers.d/quiet-mac`), so they do not
overwrite each other. `com.djbclark.shutdown-thaw` is the site thaw.
`com.quiet-mac.thaw` is the one install loads. Either one is enough to allow
freezes.

`just status` and `just doctor` report state. They do not freeze or disable.
A missing 60-second watchdog is an error. `just install` loads it. While
system flags are unset they also post at most one notification every six
hours.

Each pass of `bin/apple_daemon_ban.sh` also re-asserts the gui and user
disable flags (a macOS update clears them; on 2026-11-15 only `suggestd`
still had one) and runs `quiet-mac empty-stores`, so a semantic cache over
50 MiB is emptied by the site watchdog without a person in the loop.
`just install` empties those caches even when they are under the cap, and
`just empty-stores` does the over-cap pass by hand. System-domain flags
need root: `just system-flags`, or `just install`, or
`sudo macos/sip-doit-with-sudo.sh`. The site script's `--check` prints only
on a regression and always exits 0. `just check` exits 1 on a regression so
a shell can see it.

NeoFinder stays optional: [`neofinder/README.md`](neofinder/README.md),
`just neofinder-install`.

Who is keeping `mds` busy, as a diagnostic (it does not stop `mds`):
[`mds-xpc-clients/`](mds-xpc-clients/).

## What is in this folder

Every top-level entry, and where it is operated from. `just install` is only
the memory diet. The other recipes do not run unless you name them.

| Path | Covered by |
| --- | --- |
| [`quiet/`](quiet/) | `just install`, `doctor`, `status`, `check`, `enforce`, `upgrade`, `system-flags`, `empty-stores`, `recovery`, `snapshot`, `revert`, `factory`, `uninstall` |
| [`justfile`](justfile) | this list |
| [`README.md`](README.md) | this file |
| [`neofinder/`](neofinder/README.md) | `just neofinder-install`, `neofinder-status`, `neofinder-nightly`, `neofinder-stop`. The four names at the top of this folder (`neofinder-stub-export.py` and the rest) are symlinks into that directory. |
| [`no-apple-intelligence/`](no-apple-intelligence/README.md) | `just profile` installs it. `just factory` tries to remove it. |
| [`sip-doit-with-sudo.sh`](sip-doit-with-sudo.sh) | Historical site applier for the same flags. Not required. `just install` sets the flags and loads the 60-second watchdog. SIP-off `bootout` lasts until the next login. |
| [`corner-rescue/`](corner-rescue/) | `just corner-rescue` |
| [`graft-hook-timeout-fix/`](graft-hook-timeout-fix/) | `just graft-hook` |
| [`hourly-updates/`](hourly-updates/) | `just hourly-updates`. The per-app scripts live in `bin/hourly-updates.d/`, outside this folder. |
| [`otp-to-clipboard/`](otp-to-clipboard/) | `just otp` |
| [`mds-xpc-clients/`](mds-xpc-clients/) | `just mds-clients`. Diagnostic only. It does not stop `mds`. |
| [`net-watch/`](net-watch/) | plist only. Installed by `net-watch install`. Behaviour: [`docs/net-watch.md`](../docs/net-watch.md). |
| [`stagger-login/`](stagger-login/) | plist only. The program is `bin/stagger-login-sync-agent`, outside this folder. |
| [`athena-kerberos/`](athena-kerberos/README.md) | moved to [athena-mac](https://forgejo.mit.edu/djbclark/athena-mac). Nothing to install. |
| [`graft/`](graft/) | code-index cards for this folder. Not a tool. |
