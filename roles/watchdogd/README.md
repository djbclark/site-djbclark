# roles/watchdogd

One launchd job, `com.djbclark.watchdogd`, watches every site service. Each
watched service is one file, `~/.config/djbclark/watchdogd.d/<service>.toml`,
rendered from `templates/watchdogd.d/<service>.toml.j2`. The program is
`bin/watchdogd.py` (stdlib only, Homebrew python3 via `/usr/bin/env`).

- Apply: `just watchdogd-apply` · check: `just watchdogd-check` · status: `just watchdogd-status`
- What it would do now, acting on nothing: `just watchdogd-dry-run`
- Log: `~/Library/Logs/watchdogd/watchdogd.log` (2 MB × 3); state:
  `~/.local/state/watchdogd/<service>.json`
- Alerts: `~/.local/bin/hermes-ping`, 20 s timeout, state changes only; an
  undelivered alert is logged as `ALERT NOT DELIVERED`.

## Why

Built 2026-10-06 after one of the six watchdogs it replaces caused a litellm
outage (site-private memory `project_litellm_watchdog_restart_orphans_2026-10-06`):
it restarted a proxy that had already healed; launchd's 5 s ExitTimeOut
SIGKILLed the log filter before it stopped the proxy, so the proxy was
orphaned and kept :4000; cold starts under load took 10 min and were kicked
again; its budget was per finding kind and one clean run wiped it; and a
kickstart that exited 0 counted as success.

## What it replaced

| Old | What it did | Now |
|---|---|---|
| Hermes cron `Gateway Process Health` (`9e0629a2a54d`) | ORPHAN/NOPORT/STALLLOG/UNSUPERVISED for litellm and xai-oauth-bridge; kill + kickstart | `litellm.toml`, `xai-oauth-bridge.toml` |
| `com.djbclark.basic-memory-watchdog` | MCP initialize probe, 5 slow in a row or refused → restart, 3 attempts then give up | `basic-memory-mcp.toml` (same thresholds) |
| `ai.hermes.gateway-restart-watcher` | Carries out restart requests from the gateway-restart Hermes plugin, 600 s cooldown | `hermes-gateway.toml` `[restart_request]` (plist WatchPaths keeps it immediate) |
| `com.djbclark.funnel-healthcheck` + Hermes cron `Funnel Health` (`f821be766a47`) | Funnel probe, quit/reopen Tailscale after 2 all-down runs, 30 min cooldown; cron relayed the log | `funnel.toml` + `bin/funnel_probe.sh` |
| nothing (new, 2026-10-11) | beeper-10000 used to count as up in the funnel probe even at 502 (Beeper's local API off); djbclark: report it on its own, keep Beeper off | `funnel-beeper.toml` (`funnel_probe.sh beeper-10000`, strict: 5xx = down; alert only) |
| Hermes cron `Provider Health Watchdog` (`8486ce778b40`) | Hermes provider probe, every 12 h | `provider-health.toml` (alert only) |
| nothing (new, 2026-10-10) | freeze/kill-on-sight for the Apple daemons `macos/sip-doit-with-sudo.sh` disables: their launchd disable flags do not stop XPC/event activation and bootout is SIP-refused, so the probe (`bin/apple_daemon_ban.sh` + root helper) SIGSTOPs the gui-domain jobs and TERMs the rest every pass | `apple-daemons.toml` |
| nothing (new, 2026-10-15) | every restart stalled: the `apple-daemons` SIGSTOPped daemons cannot act on launchd's SIGTERM (`shutdown_stall_*.shutdownStall` lists them "(suspended)"), the Mac hard-reset ~4 min later, and that dropped the staged kernel-extension rebuild, so the "System software from Apple Inc. was updated, restart" dialog looped | `com.djbclark.shutdown-thaw` LaunchAgent (`bin/shutdown-thaw.sh`, persistent): on launchd's SIGTERM it CONTs + TERMs every stopped process of the user, KILLs stragglers after 3 s |
| nothing (new, 2026-10-15) | the same rebuild is also lost by a power loss or panic (on Apple silicon kcgend builds the AuxKC only during a clean restart; kernelmanagerd then logs "Kcgen roundtrip failed: found an instruction plist but not a checkpoint plist") | `auxkc-heal.toml` (`bin/auxkc_heal.sh` + root helper `files/auxkc_heal_root.sh`): re-arms the kcgen boot with `kmutil load -z` for the bundle ids already in the staged instructions, pings once per boot |
| nothing (new, 2026-10-15; **rule removed 2026-10-19**, operator: no automatic NeoFinder runs, `~/.local/bin/neofinder-update` by hand) | NeoFinder batch volume after a restart or a missed nightly: a shutdown at 00:03 and a boot at 05:00 skipped the 01:15 Jobber run, left the image detached, and macOS re-created Spotlight stores on the real volumes; the probe checks attached + indexed, every other volume off, last nightly < 26 h, and the heal re-attaches + runs the root applier, or starts a catch-up nightly detached; hard offs too (a nightly that died part way counts as missed, budget back after 1 h of health) | `neofinder-batch.toml` + `macos/neofinder/neofinder-batch-watch` |

## `apple-daemons`: freeze-on-sight with a root helper

The probe IS the enforcement (exit 0 healthy, 1 = the root half is broken,
75 = no console user); actions are logged to
`~/Library/Logs/watchdogd/apple-daemon-ban.log`, and *reporting* stays with
the sip script's `--check`. The gui-domain half SIGSTOPs rather than kills:
these daemons are pathological from their first second, so killing them
every pass still burned ~a core in the gaps and fought App Tamer (TERM is
undeliverable to a stopped process; the KILL escalation destroyed App
Tamer's freezes and forced respawns). A frozen job burns no CPU and never
exits, so launchd never respawns it — the only burn window is the ≤60 s
after login/boot, and `--revert` in the sip script CONTs what it froze.
siriactionsd (the Shortcuts / App Intents backend) joined the frozen set
2026-10-15; App Tamer had been stopping it with no visible side effect. Later that day
sharingd (AirDrop/Handoff; KeepAlive, so only a freeze sticks) and contactsd (in the
per-user `user/<uid>` domain, the ban script's `USER_FREEZE_LABELS`) were frozen at the
operator's request, and knowledgeconstructiond (nightly Apple Intelligence pipeline,
four CPU-limit diagnostics Oct 9-12) joined the TERM set, and duetexpertd, mediaanalysisd,
campo (Siri AI.app), visualintelligenced, siriknowledged and intelligenceplatformd joined
the frozen set (operator: disable everything in that family; header of the sip script);
then BiomeAgent and chronod (frozen) and coreduetd (system half, TERMed; the installed
root helper must be re-copied when its list changes).
triald/helpd/sirittsd/knowledgeconstructiond (short one-shots) and the system-domain half (cloudd, triald.system, spindump,
tailspind run as root; modelmanagerd and modelcatalogd are flag-only, never killed) are TERMed. The five Apple Intelligence daemons (generativeexperiencesd,
intelligencecontextd, intelligenceflowd, modelmanagerd, modelcatalogd) are flag-only:
clients reactivate them in ~1 s. watchdogd
itself stays a user LaunchAgent, so root comes from a fixed root-owned
helper through exactly one sudoers line. One-time manual install (the role
stays become-free):

```bash
sudo mkdir -p /usr/local/libexec/djbclark
sudo install -o root -g wheel -m 0755 \
  ~/ops/site-djbclark/roles/watchdogd/files/apple_daemon_ban_root.sh \
  /usr/local/libexec/djbclark/apple_daemon_ban_root.sh
sudo install -o root -g wheel -m 0440 \
  ~/ops/site-djbclark/roles/watchdogd/files/sudoers.apple-daemon-ban \
  /etc/sudoers.d/apple-daemon-ban
sudo visudo -cf /etc/sudoers.d/apple-daemon-ban
```

The helper must stay root-owned (a user-writable copy at that path would
make the sudoers grant a root shell), and re-run both `install` lines after
editing `files/apple_daemon_ban_root.sh`. Label lists live in three places
that must stay in step: `macos/sip-doit-with-sudo.sh` (the flags),
`bin/apple_daemon_ban.sh` (gui half) and the root helper (system half).

## `shutdown-thaw` and `auxkc-heal`: unclean restarts (2026-10-15)

Found when the kext "restart needed" dialog survived a restart: the frozen
daemons stalled the shutdown, the hard reset lost the staged rebuild. Two
pieces, both in this role:

1. **`shutdown-thaw`** is a second LaunchAgent, `com.djbclark.shutdown-thaw`,
   kept alive by launchd (the watchdog itself is a StartInterval job, alive a
   few seconds per minute, so it cannot see a shutdown). launchd SIGTERMs
   every gui job when a logout, restart or shutdown begins; the script's TERM
   trap SIGCONTs and SIGTERMs every stopped process of the user, SIGKILLs any
   still alive after 3 s, logs to `~/Library/Logs/watchdogd/shutdown-thaw.log`
   and exits. Test without rebooting: `sleep 1000 & kill -STOP $!`, then
   `launchctl kill TERM gui/$(id -u)/com.djbclark.shutdown-thaw`; the sleep
   is gone and KeepAlive has restarted the agent.
2. **`auxkc-heal`** covers the restarts nothing can make clean (power loss,
   panic, a stall from some other cause). The probe `bin/auxkc_heal.sh` runs
   every minute; when a kcgen instructions plist is staged but the kcgen boot
   is not armed (`nvram one-time-boot-command`), the machine has been up
   over 2 min and this boot was not yet checked, it calls the root helper,
   which confirms with `bputil -d` that no AuxKC exists and re-runs
   `kmutil load -z -b <id>` for the bundle ids in the staged instructions
   (only kexts the operator already approved; `-z` skips the approval check
   that OK answered). That re-arms the kcgen boot; the probe pings once per
   boot that a clean restart is needed. Same root-helper pattern and the same
   one-time manual install as `apple-daemons`:

```bash
sudo install -o root -g wheel -m 0755 \
  ~/ops/site-djbclark/roles/watchdogd/files/auxkc_heal_root.sh \
  /usr/local/libexec/djbclark/auxkc_heal_root.sh
sudo install -o root -g wheel -m 0440 \
  ~/ops/site-djbclark/roles/watchdogd/files/sudoers.auxkc-heal \
  /etc/sudoers.d/auxkc-heal
sudo visudo -cf /etc/sudoers.d/auxkc-heal
```

## Rules every service gets (bin/watchdogd.py `decide`)

1. **Cold-start grace** (`policy.grace_s`): no restart while the launchd
   instance, or the last action, is younger than that. An ORPHAN is still killed.
2. **Stress** (`watchdogd.toml`): restarts are deferred while load per CPU or
   swap is over the threshold. Strays and port orphans are still killed. A
   rule with `policy.ignore_stress = true` acts anyway: for a heal that the
   post-boot load would otherwise defer for several passes (neofinder-batch,
   2026-10-15: Spotlight indexing is that load).
3. **Real probe**: a timeout is *slow*, refused or 5xx is *down*, each with its
   own consecutive threshold. An unexpected 4xx means the probe is wrong, not
   the service: alerted once, never a restart. A log stall signature counts
   only while the probe also fails.
4. **Budget** per service (`max_restarts`), returned only after
   `healthy_reset_s` (6 h) of unbroken health.
5. **Pending verification** after each restart; `UNVERIFIED` if the probe
   still fails once the grace has passed.
6. **Strays**: processes matching `strays.match` with ppid 1 that are not
   launchd's current instance, its descendants, or any launchd job, are killed
   (SIGTERM, SIGKILL after `term_wait_s`) and reported. A stray holding the
   port is the ORPHAN case. With no launchd instance nothing is killed
   (UNSUPERVISED: maybe an intentional manual fallback).

## Schema: `watchdogd.d/<service>.toml`

```toml
name = "litellm"          # default: the file name
enabled = true
interval_s = 120          # probe interval; a pass runs every 60 s

[launchd]                 # omit for non-launchd things (funnel)
label = "com.djbclark.litellm"
plist = "~/Library/LaunchAgents/com.djbclark.litellm.plist"  # for bearer_from_plist_env
port = 4000               # ORPHAN / UNSUPERVISED / NOPORT checks

[probe]
kind = "http"             # http | tcp | unix | command | none
method = "POST"
url = "http://127.0.0.1:4000/v1/chat/completions"
headers = { "Content-Type" = "application/json" }
bearer_from_plist_env = "LITELLM_MASTER_KEY"   # read at run time, never stored here
body = '{"model": "watchdogd-mock", ...}'
ok_status = ["200"]       # codes or ranges, e.g. "200-499"
expect_body = '"OK"'
# tcp: host, port · unix: path ({launchd_pid} substituted), expect
# command: command = [...], skip_exit_codes = [75]  (exit 0 ok, timeout slow)
timeout_s = 30

[policy]
slow_before_action = 3
down_before_action = 2
grace_s = 900
action = "kickstart"      # kickstart | command (with command = [...]) | alert
min_action_interval_s = 0
max_restarts = 3
healthy_reset_s = 21600
renotify_s = 21600        # repeat BUDGET EXHAUSTED at most this often
ignore_stress = false     # true: act even under machine stress (rule 2)

[stall]                   # optional
log = "~/Library/Logs/litellm/litellm.log"
pattern = 'Prisma DB reconnect failed \((?P<count>\d+) consecutive\)'
min_count = 3             # compared with the named group "count"

[strays]                  # optional
match = 'regex on the full command line'
term_wait_s = 20

[restart_request]         # optional: act on a JSON request file
file = "~/.hermes/state/gateway_restart_request.json"
max_age_s = 3600
cooldown_s = 600
cooldown_file = "~/.hermes/state/gateway_restart_cooldown.json"
command = ["~/.local/bin/hermes", "gateway", "restart"]   # run detached
env = { HERMES_HOME = "~/.hermes" }
unset_env = ["_HERMES_GATEWAY"]

[notify]                  # optional overrides: down, recovered, exhausted
recovered = "{name} RECOVERED: {detail}"
```

No secrets in these files: `bearer_from_plist_env` reads a value from the
service's own plist when the probe runs.

## PATH

Until the reboot that makes the launchd user PATH live (site-private memory
`project_launchd_inherit_path_after_reboot`), the plist sets an explicit PATH
with Homebrew first (`watchdogd_service_path`). Afterwards set
`watchdogd_inherit_path: true`.
