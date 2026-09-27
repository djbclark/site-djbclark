# Hermes web dashboard (site Mac)

KeepAlive LaunchAgent so the Android Hermes app can reach this Mac over
Tailscale after a reboot or a closed Terminal. Not the stayturgid fleet
dashboard (`com.stayturgid.dashboard` on loopback :4097).

## Live process

| Item | Value |
| ---- | ----- |
| LaunchAgent | `com.djbclark.hermes-dashboard` |
| Program | `~/.local/bin/hermes dashboard --host 100.113.53.87 --port 9119 --no-open --skip-build` |
| KeepAlive / RunAtLoad | true |
| Bind | Tailscale `100.113.53.87:9119` (not LAN, not loopback) |
| URL | `http://100.113.53.87:9119` |
| Auth | Nous OAuth and/or `dashboard.basic_auth` in `~/.hermes` (never git) |
| Logs | `~/.hermes/logs/dashboard.log`, `dashboard.error.log` |
| Role | `roles/site_agents` |

### Operator commands

```bash
cd ${OPS_ROOT:-~/ops}/site-djbclark
just site-agents-apply --tags hermes-dashboard
just site-agents-status
launchctl print "gui/$(id -u)/com.djbclark.hermes-dashboard"
curl -sS http://100.113.53.87:9119/api/status
```

Do not run `hermes dashboard --stop` from a live gateway session if this job
is loaded — launchd will restart it. Boot it out instead:

```bash
launchctl bootout "gui/$(id -u)/com.djbclark.hermes-dashboard"
```

## Registry

**Ports (`registry/ports.yml`):** `mac` host, port `9119`, bind `100.113.53.87`,
owner `site`, service `hermes-dashboard`.

Claim the port here before binding anything else to 9119. Hermes' own default
dashboard port is 9119; this row is why that default is allowed on this host.
