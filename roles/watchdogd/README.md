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
| Hermes cron `Provider Health Watchdog` (`8486ce778b40`) | Hermes provider probe + `hermes doctor`, every 12 h | `provider-health.toml` (alert only) |

## Rules every service gets (bin/watchdogd.py `decide`)

1. **Cold-start grace** (`policy.grace_s`): no restart while the launchd
   instance, or the last action, is younger than that. An ORPHAN is still killed.
2. **Stress** (`watchdogd.toml`): restarts are deferred while load per CPU or
   swap is over the threshold. Strays and port orphans are still killed.
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
