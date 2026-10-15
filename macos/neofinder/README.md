# NeoFinder → Spotlight

Use [NeoFinder](https://www.cdfinder.de/) catalogues as the Mac's file
search instead of Spotlight's own index.

**Why:** Spotlight's background indexers keep crawling every mounted
volume, even when settings say they are off. Here they index nothing on
the Mac itself. NeoFinder already catalogues every disk, so its catalogues
are turned into a small tree of searchable files on one dedicated volume.
Spotlight indexes only that tree, and Finder search, saved searches and
`mdfind` work on it as usual.

## How it works

1. **Export.** `neofinder-stub-export.py` reads NeoFinder's catalogues over
   AppleScript and is read-only on the NeoFinder side. It writes one entry
   per catalogued file onto the batch volume `/Volumes/NeoFinderBatch`, a
   sparse disk image.
   1. **Real file mounted:** the entry is a Finder alias to it.
   2. **Real file offline:** the entry is a zero-byte stub. Its Finder
      comment records where the real file lives.
2. **Searchable attributes on every entry.**
   1. **Finder tags:** a kind tag (`nf-image`, `nf-video`, …), size tags
      (`nf-over1gb`, …), `nf-offline`, and the real file's own tags.
   2. **`kMDItemNFRealSize`:** the real size, as a number.
   3. **Dates:** the real file's last-opened date, and NeoFinder's
      creation date for stubs.
3. **Nightly upkeep.** A [Jobber](https://github.com/dshearer/jobber) job,
   `neofinder-nightly`, runs from 01:15 and stops by 05:45.
   1. It turns indexing off and detaches the image, compacts it
      (`hdiutil compact` hands freed space back to the disk), and
      attaches it again.
   2. It re-copies tags, sizes and last-opened
      dates from the real files (`retag`).
   3. It asks NeoFinder for stub creation dates (`stub-dates`).
   4. It turns Spotlight indexing back on for the batch volume and leaves
      it attached, so it stays searchable until the next run. Steps 2 and
      3 stop by 05:30 to leave room for this.
4. **Spotlight everywhere else stays off.** Every other volume is held at
   `mdutil -a -i off`. `../sip-doit-with-sudo.sh` disables the other noisy
   Apple background daemons, including Spotlight's semantic-search ones,
   and `just services-status` reports any that come back.

## Install

```sh
cd macos/neofinder
just install   # image, root applier + sudoers line, Jobber job, saved search
just status    # everything at a glance
just services  # optional: disable the Apple background daemons (Touch ID)
```

Every recipe is idempotent, so running `just install` again changes only
what differs. Touch ID is asked for only when the root-owned part changed.

Requirements:

1. NeoFinder, running for exports and stub dates.
2. Homebrew `python@3.12` with PyObjC (`pyobjc-framework-Cocoa`), needed
   to write aliases.
3. `just` and Jobber.
4. `sudo-ask`, for the Touch ID steps.

Add the **NF Recents** saved search to the Finder sidebar once, by hand
(File › Add to Sidebar). macOS has no command line for sidebar items.

## Day to day

| Recipe | What it does |
|---|---|
| `just status` | Read-only overview: grant, Jobber, image, index state, item count, last nightly run, daemons |
| `just nightly` | Tonight's job, now |
| `just attach` / `just detach` | Attach the image, or turn indexing off and detach it |
| `just index-on` / `just index-off` | Turn Spotlight indexing on or off for the batch volume, without Touch ID |
| `just export …` | The exporter (`--list`, `--catalog NAME`, `status`, `pause`, …) |
| `just agent-install` / `just agent-remove` | Install or remove the exporter's own LaunchAgent for scheduled exports |
| `just window` | Hands-on search window: index, search, press Enter to tear down. Its teardown turns indexing off, so run `just index-on` afterwards |
| `just setup` / `just unsetup` | Install or remove the root applier and its sudoers line |

Example searches, in Finder or with `mdfind`:

```sh
mdfind -onlyin /Volumes/NeoFinderBatch 'kMDItemNFRealSize > 1000000000'   # over 1 GB
mdfind -onlyin /Volumes/NeoFinderBatch 'kMDItemUserTags == "nf-image"'    # every image
mdfind -onlyin /Volumes/NeoFinderBatch 'kMDItemUserTags == "nf-offline"'  # disk not mounted
```

## The one privileged step

Turning indexing on needs root (`mdutil -i on`). The nightly job gets
root without a prompt through one narrow path.

1. **The applier:** `neofinder-spotlight-index` is installed root-owned at
   `/usr/local/libexec/`.
2. **What it accepts:** only `on`, `off` and `status`. It takes no paths
   and reads no environment.
3. **What it touches:** only `/Volumes/NeoFinderBatch`, and only when that
   mount point is backed by the image named in the root-owned
   `/etc/neofinder-spotlight-index.conf`.
4. **The grant:** `/etc/sudoers.d/neofinder-spotlight-index` allows exactly
   those three commands, without a password, for the installing user.

`neofinder-index-setup.sh` (`just setup`) installs all three files. It
checks the sudoers line with `visudo -c` first, and it does nothing when
everything is already current.

## Restarts and downtime

A restart at any point breaks the resting state: the image is detached,
a nightly in flight dies, a missed 01:15 is never re-run by Jobber, and
macOS 27 creates fresh Spotlight stores on the real volumes and starts
indexing them (seen 2026-10-15 after a shutdown at 00:03 and a boot at
05:00). The site watchdog (`roles/watchdogd`, rule `neofinder-batch`)
runs `neofinder-batch-watch probe` every two minutes:

1. **Healthy:** image attached and indexed, every other volume off, last
   nightly under 26 hours old. A nightly or catch-up in progress counts
   as healthy.
2. **Heal** (`neofinder-batch-watch heal`, after two failed probes, at
   most every 15 minutes): a missed nightly starts `nightly --index`
   detached (about 12 minutes; every step is idempotent, so a run cut
   off part way is simply redone); anything else is `attach` plus the
   root applier `on`.
3. **Where to look:** `just status` (the `watch:` line is the probe's
   verdict), `~/Library/Logs/watchdogd/neofinder-batch.log` (actions),
   `neofinder-batch-catchup.log` beside it (a catch-up's output).
4. **Hard offs** (a forced reset after a shutdown stall, power loss, a
   panic) are healed the same way, because nothing depends on a clean
   shutdown. The probe reads live state and the logs, never a pid or lock
   file. A nightly that died part way leaves a `nightly: start` line with
   no closing `nightly: retag=` line, and that counts as missed. Only a
   closing line with `indexed=1` counts as a finished nightly. Logs are
   read with `grep -a`, so NUL bytes left by a power loss do not hide
   them. Before a catch-up, the heal turns off Spotlight on the real
   volumes if a boot turned it on. The exporter holds an `flock` for the
   whole nightly, which the kernel drops on any death, so Jobber's 01:15
   run skips while a catch-up is still running.

`just watchdogd-apply` at the repo root installs or updates the rule.

## Files

| File | Role |
|---|---|
| `neofinder-stub-export.py` | Exporter, `retag`, `stub-dates`, `nightly`. Its docstring holds the measured limits and design decisions |
| `neofinder-spotlight-batch.sh` | Hands-on search window: index, hold, tear down |
| `neofinder-spotlight-index` | The root-owned applier (`on`/`off`/`status`) |
| `neofinder-index-setup.sh` | Installs the applier, its config and the sudoers line, idempotently |
| `neofinder-batch-watch` | watchdogd `probe`/`heal`: re-attach, re-index and catch up a missed nightly after a restart |
| `nf-recents.savedSearch` | The NF Recents saved search |
| `neofinder-stub-export.example.toml` | Example exporter config |
| `neofinder-stub-export.plist.template` | The exporter's LaunchAgent template |
| `justfile` | Installs and manages all of the above |

The Jobber job lives in `roles/site_agents/templates/jobber.yaml.j2`.
`just jobber` applies it.

## Known limits

1. **Offline volumes can't be opened.** An offline file is a stub. Its
   comment says where the real file is, and NeoFinder knows the rest.
2. **Media metadata isn't copied yet.** EXIF, music, GPS and text content
   aren't on the entries; only names, kinds, sizes, tags and dates are.
3. **A restart detaches the batch volume** and, on this macOS, brings
   Spotlight back on the real volumes. The watchdog heals both within a
   few minutes ("Restarts and downtime" above).
4. **Finder's Recents can't list aliases.** The NF Recents saved search
   stands in for it.
   Its list view, newest-opened first, is kept in Finder's own preferences
   (`SearchRecentsViewSettings`), not in the `.savedSearch` file. On a new
   Mac, open it once and choose View > as List, then sort by Date Last Opened.
5. **SIP blocks unloading Spotlight's server** (`mds`). The policy instead
   keeps every other volume's indexing off.
6. **Some names never become searchable.** Spotlight skips any path with
   a dot-name component (`.git`, `.cache`, and everything under them);
   search those in NeoFinder itself. It also skipped every `.sql` stub
   here (macOS 27; macOS 26+ user reports describe a similar `.sql`
   regression), so the exporter names those entries `<name>.sql.nf`,
   which Spotlight indexes. A name search for `x.sql` still finds them.
