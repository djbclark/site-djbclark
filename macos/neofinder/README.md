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
3. **Updates, by hand only.** `~/.local/bin/neofinder-update` (`just
   nightly`) runs one update; nothing is scheduled since 2026-10-19, when
   the Jobber job and the watchdog rule were removed because Spotlight
   indexing the volume was a CPU hog. `~/.local/bin/neofinder-stop`
   (`just stop`) undoes it. An update:
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
just install   # image, root applier + sudoers line, saved search, ~/.local/bin links
just status    # everything at a glance
just services  # optional: disable the Apple background daemons (Touch ID)
```

Every recipe is idempotent, so running `just install` again changes only
what differs. Touch ID is asked for only when the root-owned part changed.

Requirements:

1. NeoFinder, running for exports and stub dates.
2. Homebrew's unversioned `python3` (its newest `python@`) with PyObjC
   (`pyobjc-framework-Cocoa`), needed to write aliases. After Homebrew moves
   `python3` to a new minor, reinstall it: `uv pip install --python
   /opt/homebrew/bin/python3 --break-system-packages pyobjc-framework-Cocoa`.
3. `just`.
4. `sudo-ask`, for the Touch ID steps.

Add the **NF Recents** saved search to the Finder sidebar once, by hand
(File › Add to Sidebar). macOS has no command line for sidebar items.

## Day to day

| Recipe | What it does |
|---|---|
| `just status` | Read-only overview: grant, image, index state, item count, last update, daemons |
| `just nightly` | One update, now (`neofinder-update`); leaves the volume attached and indexed |
| `just stop` | Stop a running update, index off and detach, then Spotlight off on every volume and the Apple daemons, Touch ID only if they drifted (`neofinder-stop`) |
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

Turning indexing on needs root (`mdutil -i on`). An update gets
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

Nothing re-attaches or re-indexes the batch volume after a restart since
2026-10-19 (operator: no scheduled or automatic runs). A restart leaves the
image detached, and a running update dies; its `flock` dies with it, so the
next `neofinder-update` just starts. On this macOS a boot can also turn
Spotlight back on for the real volumes (seen 2026-10-15); `neofinder-stop`
turns it off again.

The watchdog rule that used to heal all this (`neofinder-batch`, calling
`neofinder-batch-watch probe`/`heal`) is removed from
`roles/watchdogd/defaults/main.yml`; its template is kept, so re-adding the
name there and running `just watchdogd-apply` restores it.

## Files

| File | Role |
|---|---|
| `neofinder-stub-export.py` | Exporter, `retag`, `stub-dates`, `nightly`. Its docstring holds the measured limits and design decisions |
| `neofinder-spotlight-batch.sh` | Hands-on search window: index, hold, tear down |
| `neofinder-spotlight-index` | The root-owned applier (`on`/`off`/`status`) |
| `neofinder-index-setup.sh` | Installs the applier, its config and the sudoers line, idempotently |
| `neofinder-update` / `neofinder-stop` | `just nightly` / `just stop` by hand; `just links` symlinks them into `~/.local/bin` |
| `neofinder-batch-watch` | Former watchdogd `probe`/`heal` (rule removed 2026-10-19) |
| `nf-recents.savedSearch` | The NF Recents saved search |
| `neofinder-stub-export.example.toml` | Example exporter config |
| `neofinder-stub-export.plist.template` | The exporter's LaunchAgent template |
| `justfile` | Installs and manages all of the above |

The Jobber job (`roles/site_agents/templates/jobber.yaml.j2`) was removed
2026-10-19; `just jobber` only re-renders that file.

## Known limits

1. **Offline volumes can't be opened.** An offline file is a stub. Its
   comment says where the real file is, and NeoFinder knows the rest.
2. **Media metadata isn't copied yet.** EXIF, music, GPS and text content
   aren't on the entries; only names, kinds, sizes, tags and dates are.
3. **A restart detaches the batch volume** and, on this macOS, can bring
   Spotlight back on the real volumes. Nothing heals either on its own;
   run `neofinder-stop` ("Restarts and downtime" above).
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
