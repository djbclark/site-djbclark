# Herdr brew service (site Mac)

Keep the Herdr **server** running as a Homebrew LaunchAgent so panes and
agents survive closing Ghostty. Attach with `herdr` / `h` only; do not rely on
a one-off foreground process for the herd.

## Live process

| Item | Value |
| ---- | ----- |
| Formula | `herdr` (site-claimed in `brew/fragments/site.yml`) |
| LaunchAgent | `homebrew.mxcl.herdr` |
| Program | `/opt/homebrew/opt/herdr/bin/herdr server` |
| KeepAlive / RunAtLoad | true (Homebrew plist) |
| API socket | `~/.config/herdr/herdr.sock` (Unix domain, **no TCP port**) |
| Logs | `/opt/homebrew/var/log/herdr.log` |
| Config | `~/.config/herdr/config.toml` (on-box; not in this repo) |

### Operator commands

```bash
# From this repo
just herdr-status
just herdr-start      # brew services start herdr
just herdr-stop
just herdr-restart
just herdr-reload     # herdr server reload-config (no process restart)

# Or raw Homebrew / herdr CLI
brew services start herdr
brew services info herdr
herdr status
herdr server reload-config
```

Shell aliases (when `~/.bashrc` is loaded): `h`, `hs`, `hreload`, `hstop`.

## Registry

**Ports (`registry/ports.yml`):** Herdr does not listen on TCP. It cannot own a
numeric port row (lint requires 1–65535 and a real listen). Documented as a
**UDS-only** note under the brew-services section so discovery/landing do not
expect an HTTP probe.

**Paths (`registry/paths.yml`):**

- `brew_services`: `homebrew.mxcl.herdr` → `claimed_by: site`
- Site prefixes: `~/.config/herdr/**`, `/opt/homebrew/var/log/herdr.log`

## Dashboard (OliveTin)

Site actions in [`olivetin/user-actions.yaml`](../../olivetin/user-actions.yaml)
(`user_herdr_*`):

| Action id | Title |
| --------- | ----- |
| `user_herdr_status` | Herdr — status |
| `user_herdr_start` | Herdr — brew services start |
| `user_herdr_stop` | Herdr — brew services stop |
| `user_herdr_restart` | Herdr — brew services restart |
| `user_herdr_reload_config` | Herdr — reload config |

UI: https://mac.greyhound-sidemirror.ts.net/olivetin/ (or loopback
`http://127.0.0.1:1337`).

After editing user actions:

```bash
just site-sync
```

That reprojects `~/.config/djbclark/olivetin/config.yaml` (single writer).

Landing catalog (`services.json` / discover) only lists **TCP/HTTP** targets
from the port registry. UDS services like Herdr show up via **OliveTin**, not
as a landing URL.

## Related

- Workstation keyboard/mouse/agent config guide (if present on your branch):
  `docs/reference/herdr-workstation.md`
- Upstream: https://herdr.dev/docs/
- F2 keep decision: `human/F2-BREW-SERVICES-DECISIONS.md`
