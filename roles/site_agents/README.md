# site_agents — control-node maintenance LaunchAgents (Phase F1)

Adopts hand-managed LaunchAgents into Ansible-managed site roles. Scripts
install to `~/.local/bin`; plists render to
`~/Library/LaunchAgents/com.<site_ns>.*`.

## What it manages

| Agent | Label | Schedule | Output |
| ----- | ----- | -------- | ------ |
| system-state-backup | `com.{{ site_ns }}.system-state-backup` | Daily 12:00 + RunAtLoad | `{{ homebrew_prefix }}/var/system-state` + mirror `~/system-state` |
| hibernate-disk-check | `com.{{ site_ns }}.hibernate-disk-check` | Every 1800s + RunAtLoad | macOS notification when `/` free GB < threshold (default 25) |
| cswap-auto | `com.{{ site_ns }}.cswap-auto` | KeepAlive (long-running) | Auto-switches Claude Code accounts near rate limits |
| aiuse | `com.{{ site_ns }}.aiuse` | Every 180s + RunAtLoad | `aiuse sample`: collects hourly when idle, every 15 min when quota moved, every 3 min in a burst; snapshots under `~/.cache/aiuse/snapshots`, token ledger under `~/.cache/aiuse/ledger` |
| jobber | `homebrew.mxcl.jobber` | RunAtLoad (daemon) | Jobber daemon executing `~/.jobber` jobs (e.g. `brew-fast-upgrade` nightly at 03:10 with `onError: Continue` — `brew upgrade --greedy` of everything (nothing may be pinned; casks needing sudo wait for a run from a terminal; the `paseo` cask is held, see the script's `held_casks`), npm globals and uv tools, then restarts any `brew services` daemon or user launchd job left running a deleted binary; `mac-dns-apply` nightly at 03:30, `landing-health` hourly, `chrome-cache-trim` 4×/day on a pass with Chrome quit) |
| hermes-dashboard | `com.{{ site_ns }}.hermes-dashboard` | KeepAlive | Hermes web dashboard on Tailscale `:9119` (Android app). See [docs/reference/hermes-dashboard.md](../../docs/reference/hermes-dashboard.md) |
| s1-ingest | `com.{{ site_ns }}.s1-ingest` | Every 900s + RunAtLoad, background priority; **off unless `site_agents_s1_ingest_enabled: true`** (false removes the plist and boots the job out) | `bin/s1_cycle.py`: `s1_claude.py scan`, `s1_hermes.py sink`, `s1_search.py index` into the S1 store, one line per step in `~/.local/share/s1-evidence/cycle.log`; skips while `maintenance.lock` exists. `fleet-watch` pages when a producer goes 6 h stale while this plist is installed |

## Fleet-watch acknowledgement escalation

The existing five-minute `fleet-watch check` also runs `relay.py --sweep`,
using `FLEET_WATCH_RELAY` or `~/src/djbclark-ade/skills/session-finder/relay.py`.
Each `OVERDUE ack ID: ...` line produces one `hermes-ping` naming the sender,
target, ID and age. No model or agent message is used for this check.
`~/.local/state/fleet-watch/ack-overdue.json` records successful notices by ID;
updates use an atomic replacement under a lock. Failed pings are retried.
`relay.py --pending --json` removes ledger entries only when their expectation
is gone, including keeping entries for retained acknowledged records. Missing,
failed or empty sweeps are logged; other fleet checks continue. A failed pending
list preserves the ledger. The launchd sender label stays `fleet-watch`.
The inspected relay usage does not yet list `--no-ack`, so existing relay sends
retain their current flags and exit-code handling.

## APFS compression job (`apfs-compress`)

Weekly Jobber job (Sunday 04:30) that re-applies APFS (decmpfs) compression with
`afsctool` to caches that keep receiving uncompressed files: `~/Library/pnpm/store`,
`~/.cache/uv`, and the Android SDK (`platforms`, `build-tools`, `ndk`, `sources`,
`cmake`; never `system-images`, whose files are mostly incompressible and over
afsctool's 2 GB per-file limit). Measured 2026-10-13: pnpm -43%, uv -28%, Android
-22% to -31%. Needs `afsctool` (brew); a host without it exits 0. Runs niced, and
skips a cache while its tooling is active. For uv "active" means any `uv` process
other than the long-lived servers in `site_agents_apfs_compress_uv_keep`, because
`uv run` holds the cache lock for its whole life. Undo: `afsctool -d <path>`. Do
not point it at cow pastures or other APFS-cloned trees: compressing a clone
rewrites it and breaks the sharing.

It also compresses cold agent transcripts (`site_agents_apfs_compress_cold_dirs`:
`~/.claude/projects`, `~/.codex/sessions`, `~/.grok/sessions`, `~/.copilot/session-state`,
`~/.local/state/acp-run`): only jsonl/json/log/txt files untouched for 7+ days and not
open for write (one `lsof` snapshot). mtime and logical size are preserved, so
readers that resume by offset or detect change by size/mtime are unaffected. Never
add live SQLite stores (hermes state.db, opencode.db, cursor chats, s1-evidence).

## SQLite vacuum job (`sqlite-vacuum`)

Weekly Jobber job (Sunday 05:00) that runs an in-place `VACUUM` on the app
databases in `site_agents_sqlite_vacuum_dbs`, because SQLite never shrinks a file
by itself (2026-10-13: FolderSync 463 MB to 0.3 MB, a Zed backup 257 MB to 0.4 MB,
both 99.9% free pages). A file is vacuumed only when at least 30% of its pages are
free, at least 50 MB would come back, no process has it (or its `-wal`/`-shm`) open,
and the volume has room for the temporary copy. So the live stores on the list
(`opencode.db`, Zed, Basic Memory, `~/.superbrain-server/superbrain.db`, whose app now prunes old usage events daily) are picked up on a week when their app is closed;
a busy one is simply retried. Before each VACUUM it takes an APFS clone when there
is room; afterwards it runs `integrity_check` and compares per-table row counts, and
keeps the clone and exits 1 (Jobber notifies) if either fails. Dry run:
`~/.local/bin/sqlite-vacuum --dry-run <paths>`; the script lives in
`roles/site_agents/files/sqlite-vacuum`, tests in `tests/test_sqlite_vacuum.py`.

## Chrome cache policy + trim

Two complementary halves, both macOS-only (the `chrome-cache` tasks):

1. **Disk cache cap (policy).** `site_agents_chrome_cache_defaults` writes
   `DiskCacheSize` (512 MiB) and `MediaCacheSize` (256 MiB) into the
   `com.google.Chrome` user defaults — the documented macOS policy route
   (Chromium "Mac Quick Start"; no MDM needed). This bounds the HTTP/media disk
   cache under `~/Library/Caches/Google/Chrome`. It is a *hint*, not a hard cap,
   and Chrome must be restarted to pick it up (`chrome://policy` shows the
   effective values). Google's rule of thumb is one order of magnitude between
   free disk and cache; 512 MiB is deliberately below that.
2. **Profile caches (Jobber).** `chrome-cache-trim` clears the caches the policy
   does *not* cover — `Service Worker/CacheStorage`, `Service Worker/ScriptCache`,
   `Code Cache`, `GPUCache`, `GrShaderCache`, `ShaderCache`, `DawnCache` — under
   `~/Library/Application Support/Google/Chrome/<profile>/` and the same
   subdirs under `~/Library/Caches/Google/Chrome/<profile>/` (where the V8
   `Code Cache` lives; the HTTP `Cache_Data` there is policy-bounded and left
   alone). It runs 4×/day and skips any pass with Chrome running, so it only
   ever clears a quit browser.

## Jobber Notifications (`jobber-notify`)

Job failures in Jobber trigger `~/.local/bin/jobber-notify`, which implements three notification sinks:

1. **Option A: macOS Desktop Notifications (`osascript`)** — Native macOS banner alert on job failure.
2. **Option B: Telegram / Hermes Alerting** — Posts HTML alert with job status, hostname, and error details to Telegram (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_HOME_CHANNEL`).
3. **Option C: Log Sinks & Filesystem Capture** — Jobber `filesystem` sink + structured JSON records in `~/.local/state/jobber/notifications.log` (14-day retention).

**What 'red' means for landing-health:**
`landing-health` is Jobber → `~/.local/bin/landing-health` → `stayturgid/control/landing/discover.py --health-check`. It fails only when a **must-be-up** Mac listener (or a `dashboard: true` launchd job) is not accepting TCP. Offline phones (`group: devices`/`android`), unmanaged apps, and `must_be_up: false` registry rows are **expected-offline** and must not page. Jobber's notify snippet is stderr-only: the wrapper merges stdout+stderr and strips the `site directory` announce so the page shows `Summary:` / `Expected-offline:`. Diagnose with `landing-health` or `python3 control/landing/discover.py --health-check` from `~/ops/stayturgid` (do not treat a hang on SSH to p7a/hd8 as an outage). Set `must_be_up: false` on ephemeral or deliberately disabled site-owned ports instead of leaving them as default-up.



Homebrew prefix follows the LiteLLM / stayturgid pattern: Apple Silicon
`/opt/homebrew`, Intel `/usr/local` (from `ansible_facts.architecture`).

## Apply

```bash
cd ${OPS_ROOT:-~/ops}/site-djbclark
just site-agents-apply          # first apply
just site-agents-check          # dry-run (ansible --check)
just site-agents-status         # launchctl print all labels
```

Playbook targets `localhost` (control node). No secrets required.

### aiuse configuration safety

For a fresh installation, the role seeds
`~/.config/aiuse/config.toml` with snapshot persistence and automatic history
learning. It never edits an existing user configuration. A legacy
`services.yaml` is left alone when it is the only config file, so older aiuse
installations keep working. If both files exist, the role stops before it
touches the LaunchAgent; migrate the YAML settings to TOML and remove the YAML
file first.

## Manual one-shot

Safe to run by hand; system-state-backup only overwrites capture files on
success (does not clobber good snapshots on partial failure):

```bash
~/.local/bin/system-state-backup.sh
~/.local/bin/hibernate-disk-check   # notifies only when below threshold
# cswap-auto is a long-running agent; use cswap auto --once for a single tick:
cswap auto --once
```

## Rollback

Boot out the site labels (stops scheduled runs):

```bash
uid=$(id -u)
launchctl bootout "gui/$uid/com.djbclark.system-state-backup"
launchctl bootout "gui/$uid/com.djbclark.hibernate-disk-check"
launchctl bootout "gui/$uid/com.djbclark.cswap-auto"
launchctl bootout "gui/$uid/com.djbclark.aiuse"
```

s1-ingest is rolled back through its flag, not by hand: set
`site_agents_s1_ingest_enabled: false` and apply (`just site-agents-apply --tags
s1-ingest`), which boots the job out and removes its plist.

To restore pre-F1 hand-managed copies after apply replaced them:

```bash
git -C ${OPS_ROOT:-~/ops}/site-djbclark checkout HEAD~1 -- \
  roles/site_agents/files/hibernate-disk-check \
  roles/site_agents/templates/system-state-backup.sh.j2
# Re-render/install manually or re-run an older playbook revision, then:
launchctl bootstrap "gui/$uid" ~/Library/LaunchAgents/com.djbclark.system-state-backup.plist
launchctl bootstrap "gui/$uid" ~/Library/LaunchAgents/com.djbclark.hibernate-disk-check.plist
```

**Note:** After the first F1 apply, the live scripts under `~/.local/bin` are
the role-managed copies; pre-F1 hand edits are overwritten.

## Verification checklist

```bash
just site-agents-apply
just site-agents-apply    # second run: changed=0
just site-agents-status
~/.local/bin/system-state-backup.sh
~/.local/bin/hibernate-disk-check
gtail ~/.local/state/cswap-auto.log    # check it's polling
```

Expected: all four labels loaded in `gui/<uid>`; system-state LAST_RUN.txt updated;
`~/system-state` mirror refreshed; cswap-auto shows periodic polling output;
aiuse has written `~/.local/state/aiuse.log` and (with persist) files under
`~/.cache/aiuse/snapshots`.

## How to add a new LaunchAgent

All site LaunchAgents follow a three-layer pattern: **defaults → template → task**,
wired through the `launchagent.yml` sub-task for idempotent bootstrap lifecycle.

### 1. Add defaults (`defaults/main.yml`)

Define paths, label, and configurable settings under a `site_agents_<name>_`
namespace. Keep to the pattern:

```yaml
# --- my-agent ---------------------------------------------------------------
site_agents_my_label: "com.{{ site_ns }}.my-agent"
site_agents_my_plist: >-
  {{ site_agents_launchagents_dir }}/{{ site_agents_my_label }}.plist
site_agents_my_log: "{{ site_agents_state_dir }}/my-agent.log"
site_agents_my_error_log: "{{ site_agents_state_dir }}/my-agent.error.log"
site_agents_my_some_config: 60       # configurable knob
```

Reuse the shared variables: `site_agents_home`, `site_agents_bin_dir`,
`site_agents_state_dir`, `site_agents_launchagents_dir`, `site_agents_uid`.

### 2. Create the plist template (`templates/<name>.plist.j2`)

Two common patterns:

**KeepAlive server** (long-running daemon, e.g., cswap-auto):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{{ site_agents_my_label }}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/binary</string>
        <string>--flag</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>30</integer>
    <key>StandardOutPath</key>
    <string>{{ site_agents_my_log }}</string>
    <key>StandardErrorPath</key>
    <string>{{ site_agents_my_error_log }}</string>
</dict>
</plist>
```

**Scheduled interval** (periodic cron-like job, e.g., hibernate-disk-check):
```xml
    <key>StartInterval</key>
    <integer>1800</integer>
    <!-- or: StartCalendarInterval with Hour/Minute -->
    <key>RunAtLoad</key><true/>
    <!-- no KeepAlive for interval jobs -->
```

Copy the label and log paths from defaults; use `{{ }}` Jinja2 syntax for values.

### 3. Add tasks (`tasks/main.yml`)

Two steps — render the plist then bootstrap it:

```yaml
- name: Render my-agent LaunchAgent
  ansible.builtin.template:
    src: my-agent.plist.j2
    dest: "{{ site_agents_my_plist }}"
    mode: "0644"
  register: _my_plist

- name: Manage my-agent LaunchAgent
  ansible.builtin.include_tasks: launchagent.yml
  vars:
    _agent_label: "{{ site_agents_my_label }}"
    _agent_plist_path: "{{ site_agents_my_plist }}"
    _agent_plist: "{{ _my_plist }}"
    _agent_script: "{{ site_agents_my_plist }}"
```

The `launchagent.yml` sub-task handles:
- Probing current launchd state
- Booting out when the plist changed (to pick up new config)
- Bootstrapping when unloaded
- Kickstarting when only the script (not plist) changed

For agents that install an executable script (like system-state-backup), use
`ansible.builtin.template` or `ansible.builtin.copy` to place the script first,
then pass its register (`_my_script`) as `_agent_script` instead of the plist path.

### 4. Update `just site-agents-status`

Add a status check block to the `justfile`:

```just
@if launchctl print "gui/$(id -u)/com.{{ site_ns }}.my-agent" >/dev/null 2>&1; then \
  echo "launchd: loaded (com.{{ site_ns }}.my-agent)"; \
else \
  echo "launchd: not loaded (com.{{ site_ns }}.my-agent)"; \
fi
```

### 5. Deploy

```bash
just site-agents-check   # dry-run first
just site-agents-apply   # deploy
just site-agents-status  # verify
```
