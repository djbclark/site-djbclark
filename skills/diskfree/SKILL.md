---
name: diskfree
description: >-
  Walk the operator through freeing disk space on this Mac: measure read-only
  with dust/gdu (never du/find), show a ranked table, confirm each category,
  then reclaim regenerable caches (npm, pnpm, go, cargo, gradle, uv) without
  breaking a live build, trim browser caches, run APFS compression, drop stale
  local/CCC snapshots, make sure workspace copies are cow pastures and gc the
  merged ones, and check the classic hogs (device backups, Xcode, Docker, Arq,
  /nix, Trash). Use for "disk is full", "free up space", "what is eating
  disk", or before a big download or build.
---

# diskfree — freeing disk space, safely

Loop: **measure read-only → present a ranked table → get a go per category →
delete → re-measure**. macOS/APFS is the machine class in play; on Linux skip
the APFS-compression and snapshot steps.

Proven playbook: this chain of sessions took this Mac from 5.75 GB free to
~64 GB (2026-10-13), and earlier ~40 GB from three stale CCC snapshots
(2026-10-02). Sources are listed at the bottom; they carry the measured
numbers.

## Ground rules

1. **Size with `dust` or `gdu`, never `du`/`find`** — on these trees `du`/`find`
   time out (>120 s repeatedly, 2026-10-11). Follow symlinks when a tree is one
   (`~/.codex/sessions` is): `dust` follows by default; use `du -skL` by hand.
   **Low-load rule (djbclark, 2026-10-25):** a `dust` of all of `~` indexed 5.2M
   files / 314 GiB logical (cow pastures count in full), ran 30+ min and added to a
   load of 24. Never scan `~` or `~/src`. Size one named directory at a time,
   sequentially, each as `~/ops/site-private/bin/bg nice -n 19 dust -d 1 -n 15 <dir>
   > /tmp/diskfree-<name>.out 2>&1` (run in the background, output to a file; `bg`
   is the load gate and utility QoS). Run `load-watch admit` first and skip the step
   while it says hot. Run it from `cd /tmp` (2026-10-25: `bg` refused with exit 3 from inside a CI repo such as djbclark-ade). Never `BG_LOAD_WAIT=0`, never `taskpolicy -b`. Cheap numbers
   first (`df`, `tmutil`, `cow stats`, a tool's own size command). Taking longer is fine.
   **`~/Library` needs `-X "Mobile Documents" -X CloudStorage -X "Group Containers"`** (2026-10-25: an unexcluded `dust` sat 1 h 32 min at 0% CPU in iCloud Drive; Google Drive's CloudStorage holds the Arq backup data, never touch it).
2. **Freed space can be pinned by a snapshot.** APFS only reclaims blocks when
   no snapshot references them. Before declaring a delete "didn't work", check
   `tmutil listlocalsnapshots /System/Volumes/Data` (step 5).
3. **Nothing mid-build, nothing that belongs to another live agent.** Check
   before deleting (the trust rule cuts both ways — peers' running work is the
   operator's): `pgrep -fl` for the tool, `lsof` for open files. When unsure,
   ask the operator or the session that owns it. **Re-check in the same command
   as the delete** (`pgrep ... || rm ...`): an idle check made when you asked the
   question is stale by the time the answer comes back (2026-10-20).
4. **Never `rm -rf ~/.cache` or `~/.cargo` wholesale** — clear per tool (step 2).
5. Ask before each destructive step; one category per confirmation. Never
   delete: live SQLite/WAL stores (`~/.local/share/s1-evidence`, hermes
   `state.db`, `opencode.db`), cow-pasture trees, `~/nfbatch.sparseimage`
   (live NeoFinder nightly image — it already `hdiutil compact`s itself), or a
   CCC snapshot while its backup is running.

## 1. Measure (read-only)

```bash
df -h /System/Volumes/Data
cow stats                    # pastures: logical vs on-disk (cheap)
tmutil listlocalsnapshots /System/Volumes/Data
jobber list | rg 'apfs-compress|chrome-cache-trim'
~/src/djbclark-ade/bin/load-watch admit --json     # proceed only while status is ok
# then ONE directory at a time (rule 1), e.g. ~/.cache, ~/Library/Caches,
# ~/Library/Application\ Support, ~/.cargo, ~/Downloads, ~/Library:
~/ops/site-private/bin/bg nice -n 19 dust -d 1 -n 15 ~/.cache > /tmp/diskfree-cache.out 2>&1
```

Present a table — path, size, reclaimable-by, risk — and get a go. If space is
critical (single-digit GB), do the fastest safe wins first (cargo
`target-shared`, npm/go caches, Trash, stale snapshots); compression is
thorough but slow.

## 2. Regenerable caches (confirm each, then delete)

| Tool | Command | Preconditions |
| --- | --- | --- |
| npm | `npm cache clean --force` (`~/.cache/npm`) | none |
| pnpm | `pnpm store prune` | none (compression also works, step 4) |
| go modules | `go clean -modcache` | **never plain `rm -rf`**: files are mode 0444, a plain rm fails halfway and leaves a broken tree |
| go build | `go clean -cache` | no go build running |
| cargo shared targets | `pgrep -x cargo >/dev/null \|\| pgrep -x rustc >/dev/null \|\| pgrep -f maturin >/dev/null \|\| rm -rf ~/.cargo/target-shared` | no `cargo`/`rustc`/`maturin` running **at the moment of the delete**: the guard is in the same command, never only at question time (2026-10-20: a delete approved minutes earlier broke a live maturin build) — this was 56 GB once |
| pre-commit | `rm -rf ~/.cache/pre-commit` | none |
| pip | `pip cache purge` | none |
| gradle | `rm -rf ~/.cache/gradle` | **idle only**: `pgrep -fl 'GradleWrapperMain\|gradle-wrapper.jar'` empty AND `~/.local/state/gradle-slot/STATUS` shows no holder (one build at a time machine-wide); mostly jars, so compression gains little — deleting is the move, but it forces full re-downloads; **it also deletes the linked `init.d` scripts (machine slot, shared remote cache): run `~/ops/site-djbclark/bin/gradle-limits link` right after (2026-10-25)** |
| uv | prefer compression (step 4); `uv cache clean` clears ~14 GB → re-downloads | no uv agent running; `uv run` holds a shared flock on `~/.cache/uv/.lock` for its whole life, so "idle" means no uv process except the long-lived servers (`uv_keep` list in `~/.local/bin/apfs-compress`) |
| Android SDK | `sdkmanager --uninstall` unused system-images/emulators | none |
| Homebrew | `brew cleanup -s` | none |
| Trash | `rm -rf ~/.Trash/*` | operator confirmed nothing wanted in there |

## 3. Browsers

- Chrome's HTTP/media cache is policy-capped (`DiskCacheSize` 512 MiB /
  `MediaCacheSize` 256 MiB) — leave `~/Library/Caches/Google/Chrome`'s
  `Cache/Cache_Data` alone.
- Profile caches the policy does **not** cover (Service Worker, V8 Code Cache,
  GPU/shader): quit Chrome, then run `~/.local/bin/chrome-cache-trim` (Jobber
  runs it 4×/day whenever Chrome is quit; it skips while Chrome runs).
- `~/Library/Application Support/Google/Chrome/OptGuideOnDeviceModel` —
  Chrome's on-device model, has reached GBs and stale dated subdirs; removable
  with Chrome quit (it may re-download). Ask first.
- Sweep `dust -d 2 ~/Library/Caches` for other apps' strays (updaters,
  Electron apps) — the 2026-10-11 pass took ~3.9 GB from ten targets.

## 4. APFS compression (afsctool)

- A weekly Jobber job (`apfs-compress`, site-djbclark `roles/site_agents`,
  Sun 04:30) re-compresses pnpm store, uv cache, Android SDK and cold agent
  transcripts. A manual pass is safe any time: `~/.local/bin/apfs-compress`
  (skips paths whose tools are active, nice'd, skips files saving <10%).
  Measured: pnpm −43%, uv −28%, Android −22..−31%, cold transcripts −30..−55%.
- **Never compress** live SQLite/WAL stores or cow-pasture / APFS-clone trees
  (rewriting a clone breaks block sharing). Files >2 GB are skipped.
- Estimate savings by compressing a **scratch copy** (`afsctool -fvv <dir>`
  only reports existing compression — it cannot estimate). Undo any path with
  `afsctool -d <path>`. mtime and logical size are preserved.

## 5. Snapshots (the invisible hogs)

- `tmutil listlocalsnapshots /System/Volumes/Data` — every local snapshot,
  including `com.bombich.ccc.transient.*` (Carbon Copy Cloner safety snaps).
- A CCC transient snapshot **pins freed blocks until its running backup
  finishes** — during a backup, deletes/compression make free space look flat
  or shrinking. Not a leak; do not delete it mid-backup.
- Stale snapshots (no backup running, hours old): deleting three stale CCC
  snapshots once returned ~40 GB (2026-10-02). Confirm CCC/backup idle
  (`pgrep -fl 'Carbon Copy Cloner\|ccc'`), then with the operator's go:
  `tmutil deletelocalsnapshots <name>` per snapshot. Re-measure after.

## 6. cow pastures — make sure copies ARE pastures

Clones of the same repo are the duplicate gigabytes this hunt is about; a
pasture shares them with APFS `clonefile(2)` (measured: 36.5 GB logical in
4.4 GB on disk across 10 pastures).

1. `cow stats` — logical vs on-disk. If you find a **plain duplicate clone**
   of a big repo (a human or agent did `git clone` where an isolated
   workspace was needed — stale Hermes clones/worktrees once held 3.6 GB),
   propose replacing it with a pasture: `cow-pasture create <name> --source
   <repo>` (scrubs gitignored secrets, handles `uchg`, pre-trusts Claude;
   `--orca` for Orca workers). Never pastures from `~/ops/*` (deployment
   checkouts — the wrapper refuses).
2. Reclaim merged work: `cow gc --merged --dry-run`, and with the operator's
   go, for real. Remove an arbitrary one with `cow-pasture remove <name>`
   (plain `cow remove` exits 0 having removed nothing on a bad name — `ls`
   after).
3. Never delete or APFS-compress a live pasture tree — its blocks are shared
   with the source; rewriting breaks the sharing and can multiply usage.
4. New agent workspaces on primaries under `~/src`, `~/orca/projects`,
   `~/.hermes` should be pastures from the start — see the `cow-workspaces`
   skill.

## 7. Classic hogs checklist (if present)

- iOS device backups: `~/Library/Application Support/MobileSync/Backup`
- Xcode: `~/Library/Developer/Xcode/DerivedData`; `xcrun simctl delete
  unavailable`
- Docker/OrbStack: the VM disk (`Docker.raw`, `~/Library/Group
  Containers/*.docker`, `~/.orbstack`), then `docker system prune` — reclaim
  inside the app first, the disk file rarely shrinks on its own
- Arq: local cache under `~/Library/Application Support/Arq` and
  `~/Library/Caches/Arq` are fair game; the real backup data ("Arq Backup
  Data") lives on Google Drive (CloudStorage path) — **never** touch it from
  the filesystem; pruning backup history is an in-app decision. An Arq-related
  incident once took this Mac from 3.8 GB to 84 GB available (2026-08-03).
- `/nix` if it exists and nothing uses it (removed on this Mac 2026-10-02)
- Old installers/DMGs/ISOs in `~/Downloads`

## 8. Close out

1. `df -h /System/Volumes/Data` again; if it didn't move, find the pinning
   snapshot (step 5) before re-deleting anything.
2. Recurring hygiene is already codified — don't hand-roll launchd jobs:
   `apfs-compress` (weekly) and `chrome-cache-trim` (4×/day) live in
   site-djbclark `roles/site_agents` and run via Jobber. One-off manual
   deletes do not recur; if the operator wants a recurring trim for a new
   path, that's a `roles/site_agents` change.
3. Record what was deliberately **kept** and why (e.g. gradle cache held by an
   active slot holder) — those decisions are the next session's context.

## Sources (this machine's measured history)

- `~/src/one-offs/docs/handoffs/HANDOFF_standalone-3913_apfs-compression-and-disk-cleanup_2026-10-13_3913.md`
  — emergency cleanup 5.75 → 64 GB, the `apfs-compress` job, afsctool traps
- `~/ops/site-private/memory/handoffs/site-djbclark/HANDOFF_standalone-b62a_chrome-cache-policy-cleanup_2026-10-11_f905.md`
  — safe-cache audit, Chrome policy, Jobber home
- `~/ops/site-private/memory/reference_apfs_compression_afsctool_2026-10-13.md`,
  `reference_chrome_disk_cache_policy_2026-10-11.md`,
  `feedback_go_module_cache_readonly.md`, `feedback_gradle_one_at_a_time.md`
- `cow-workspaces` skill; `~/ops/site-djbclark/roles/site_agents/README.md`
