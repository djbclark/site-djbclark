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
   1. It attaches the image if it isn't attached.
   2. It turns indexing off, then re-copies tags, sizes and last-opened
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

## Files

| File | Role |
|---|---|
| `neofinder-stub-export.py` | Exporter, `retag`, `stub-dates`, `nightly`. Its docstring holds the measured limits and design decisions |
| `neofinder-spotlight-batch.sh` | Hands-on search window: index, hold, tear down |
| `neofinder-spotlight-index` | The root-owned applier (`on`/`off`/`status`) |
| `neofinder-index-setup.sh` | Installs the applier, its config and the sudoers line, idempotently |
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
3. **After a reboot,** the batch volume stays detached until the next
   01:15 run, or until `just attach && just index-on`.
4. **Finder's Recents can't list aliases.** The NF Recents saved search
   stands in for it.
   Its list view, newest-opened first, is kept in Finder's own preferences
   (`SearchRecentsViewSettings`), not in the `.savedSearch` file. On a new
   Mac, open it once and choose View > as List, then sort by Date Last Opened.
5. **SIP blocks unloading Spotlight's server** (`mds`). The policy instead
   keeps every other volume's indexing off.
