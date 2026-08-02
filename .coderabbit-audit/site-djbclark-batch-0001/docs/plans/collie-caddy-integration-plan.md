# Collie Caddy Integration Plan

## Objective

Collie (Herdr mobile web UI, AltanS/collie v0.20.2) is installed and running
but served via standalone `tailscale serve` on `mac.greyhound-sidemirror.ts.net`,
bypassing the site's Caddy TLS front door. This creates two paths to the
machine (Caddy on ports 80/443, Tailscale Serve on the tailnet interface :443).
The goal is to bring Collie under Caddy so there's one TLS termination point.

## Current Setup (as installed 2026-07-29)

### Files and locations

| Item | Path |
|---|---|
| Collie source | `~/.collie/` |
| Herdr plugin | `herdr.collie` (linked via `herdr plugin link ~/.collie`) |
| Config `.env` | `~/.config/herdr/plugins/config/herdr.collie/.env` |
| LaunchAgent plist | `~/Library/LaunchAgents/com.djbclark.collie.plist` |
| Wrapper script | `~/.collie/scripts/launchd-wrapper.sh` |
| Bridge logs | `~/.collie/logs/stdout.log`, `~/.collie/logs/stderr.log` |
| Tailscale serve | `https://mac.greyhound-sidemirror.ts.net/` → `http://127.0.0.1:8787` |

### LaunchAgent (`com.djbclark.collie.plist`)

- **Program:** `/bin/bash ~/.collie/scripts/launchd-wrapper.sh`
- **WorkingDirectory:** `~/.collie`
- **Environment (from plist):** `HOME`, `PATH`, `HERDR_SOCKET_PATH`, `HERDR_PLUGIN_CONFIG_DIR`, `COLLIE_PORT`, `COLLIE_ROOT`
- **Environment (from `.env`, sourced by wrapper):** `COLLIE_PORT`, `COLLIE_VAPID_PUBLIC`, `COLLIE_VAPID_PRIVATE`, `COLLIE_VAPID_SUBJECT`
- **KeepAlive:** On failure (restarts on crash, 5s throttle)
- **RunAtLoad:** true (starts at login)

### Wrapper script (`launchd-wrapper.sh`)

```bash
#!/bin/bash
set -euo pipefail
CONFIG_DIR="${HERDR_PLUGIN_CONFIG_DIR:-$HOME/.config/herdr/plugins/config/herdr.collie}"
if [ -f "${CONFIG_DIR}/.env" ]; then
  set -a; . "${CONFIG_DIR}/.env"; set +a
fi
COLLIE_ROOT="${COLLIE_ROOT:-$HOME/.collie}"
export HERDR_SOCKET_PATH="${HERDR_SOCKET_PATH:-$HOME/.config/herdr/herdr.sock}"
export COLLIE_STATE_DIR="${COLLIE_STATE_DIR:-${COLLIE_ROOT}/data}"
export HERDR_PLUGIN_CONFIG_DIR="$CONFIG_DIR"
exec /opt/homebrew/bin/bun run "${COLLIE_ROOT}/bridge/index.ts"
```

The `.env` is sourced by the wrapper rather than inlined in the plist so config
can be updated without `launchctl bootout`/`launchctl bootstrap`.

### Web Push / VAPID

VAPID keys generated via `bunx web-push generate-vapid-keys`. Stored in
`.env`:
- `COLLIE_VAPID_PUBLIC` — public key
- `COLLIE_VAPID_PRIVATE` — private key
- `COLLIE_VAPID_SUBJECT` — `mailto:djbclark@gmail.com`

Push is enabled on the bridge with 0 saved subscriptions (pending PWA install on phone).

### VAPID keys ↔ 1Password / secretspec

The VAPID keys are currently in a plain `.env` file (local-only, gitignored).
A separate ticket covers the full secretspec → 1Password Service Account
migration: `../../../site-private/memory/project_secretspec_onepassword_integration.md`
(in the ops-worktrees main checkout: `~/ops/site-private/memory/...` or
`~/src/ops-worktrees/main/site-private/memory/...`).

## The Caddy Integration

### Why

Currently two HTTPS paths serve this machine:

1. **Caddy** (com.djbclark.caddy) — ports 80 (redirect) + 443 (HTTPS) on the
   physical network interface. Serves the main site.
2. **Tailscale Serve** (tailscaled) — intercepts the tailnet's :443 on the
   Tailscale virtual interface. Serves Collie.

While these don't conflict (Tailscale Serve operates at a different network
layer), having two ingress paths is messy long-term. Caddy should be the sole
TLS front door.

### How

The bridge listens on `http://127.0.0.1:8787` (loopback only). Caddy can proxy
to it via a `handle` or `reverse_proxy` directive.

**Option A: Caddy handles it directly**

Add to Caddyfile (path-based or subdomain-based):

```caddy
mac.greyhound-sidemirror.ts.net {
    # Existing site config...
    
    handle /collie/* {
        reverse_proxy 127.0.0.1:8787
    }
}
```

Then remove the `tailscale serve --bg 8787` mapping:

```bash
tailscale serve --https=443 off
```

Update the Collie config to set `COLLIE_PUBLIC_HOSTS` to the magic DNS name
(host-header validation). Re-point the tailnet URL.

**Option B: Subdomain approach**

If Caddy handles a broader set of services, a subdomain per service:

```
collie.mac.greyhound-sidemirror.ts.net {
    reverse_proxy 127.0.0.1:8787
}
```

**Option A (path-based)** is simpler for the current one-machine setup.

### Steps

- [ ] Update Caddyfile in site-djbclark to proxy for Collie
- [ ] Set `COLLIE_PUBLIC_HOSTS=mac.greyhound-sidemirror.ts.net` in `.env`
- [ ] Remove `tailscale serve --https=443 off` (or `tailscale serve --bg 0`)
- [ ] Verify: `curl https://mac.greyhound-sidemirror.ts.net/collie/` returns Collie UI
- [ ] Update the Collie `.env` to remove `COLLIE_PORT` and `COLLIE_HOST` if Caddy determines routing
- [ ] Update port registry `registry/ports.yml` to note Collie on 8787

### Port registry update

Add to `~/ops/site-djbclark/registry/ports.yml` under mac:

```yaml
- {port: 8787,  bind: "127.0.0.1", owner: site, service: collie-bridge, status: active,
   note: "Com.djbclark.collie launchd agent; proxied via Caddy from tailnet hostname"}
```

## Appendix: session reference

The Collie install was done on 2026-07-29 by the Hermes agent in a Telegram
session with Dan. Key decisions made during installation:
- **launchd** used instead of Collie's nohup fallback (macOS best practice)
- **Simple .env** for VAPID keys (deferred secretspec migration to separate ticket)
- **tailscale serve** used as initial ingress (will be moved behind Caddy per this ticket)
- Service accounts tested: confirmed this 1Password plan supports them
- VAPID keys generated with `bunx web-push generate-vapid-keys`
- Tailscale MagicDNS name: `mac.greyhound-sidemirror.ts.net`
