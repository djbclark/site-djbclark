# F2 — brew-services keep/kill decisions (operator)

**Audit evidence:** [`docs/relay/audits/F2-brew-services-audit.md`](../docs/relay/audits/F2-brew-services-audit.md)  
**Rule:** each KEEP/REMOVE is an operator decision. Agents must not stop production
services without recording the choice here (or in `RESPONSES.md`) and in the ledger.

Record **Accept** (default recommendation) or **Override** with a one-line reason.

| # | Service | Default recommendation | Operator decision | Date / initials |
| --- | --- | --- | --- | --- |
| 1 | `homebrew.mxcl.et` (system) | **KEEP** stayturgid | | |
| 2 | `homebrew.mxcl.et` (user agent error 78) | **REMOVE user agent only** — leave system daemon | | |
| 3 | `homebrew.mxcl.ui-tars` | **KEEP** stayturgid | | |
| 4 | `homebrew.mxcl.postgresql@14` (orphaned) | **REMOVE agent + decide data dir** | | |
| 5 | `postgresql@18` (installed, not started) | **DEFER** — leave off | | |
| 6 | `homebrew.mxcl.redis` | **STOP + uninstall** (empty DB, no consumers) | | |
| 7 | `mariadb` (installed, not started) | **LEAVE STOPPED**; uninstall later if unused | | |
| 8 | `homebrew.mxcl.herdr` | **KEEP** site workstation (no role yet) | | |
| 9 | `homebrew.mxcl.omlx` | **KEEP** site (port 8000; no role yet) | | |

## Suggested commands (only after decision signed)

### 2 — remove user-domain et agent (system daemon stays)

```bash
launchctl bootout "gui/$(id -u)/homebrew.mxcl.et" 2>/dev/null || true
rm -f ~/Library/LaunchAgents/homebrew.mxcl.et.plist
# verify system ET still answers:
nc -z -w 2 127.0.0.1 2022 && echo et-ok
```

### 4 — remove orphaned postgresql@14 agent (preserve data until confirmed)

```bash
launchctl bootout "gui/$(id -u)/homebrew.mxcl.postgresql@14"
rm -f ~/Library/LaunchAgents/homebrew.mxcl.postgresql@14.plist
# data still at /opt/homebrew/var/postgresql@14 (~50MB) — archive or rm only after confirm
```

### 6 — stop and remove redis

```bash
brew services stop redis
brew uninstall redis
# then update registry/ports.yml redis entry + paths.yml brew_services in a follow-up commit
```

### 7 — uninstall mariadb (optional; data loss risk)

```bash
# only if no needed DBs in /opt/homebrew/var/mysql
brew uninstall mariadb
# operator must explicitly delete /opt/homebrew/var/mysql if desired
```

## After any change

```bash
cd ~/ops/site-djbclark
just brew-services-audit
bin/registry_lint.py
# compare listeners before/after; update ledger if a kill was executed
```
