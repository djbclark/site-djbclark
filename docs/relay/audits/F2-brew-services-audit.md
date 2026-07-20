# F2 — brew-services audit (m1-air control node)

**Date:** 2026-07-20  
**Host scope:** `m1-air` only (E5 mini/VPS remain `offline_unprovisioned`).  
**Session:** Phase F step F2 (audit-first; no F3/F4).  
**Evidence snapshot:** live `brew services list` + `launchctl` + listeners (session start); F1
captures at `/opt/homebrew/var/system-state/brew-services.txt` and
`~/system-state/brew-services.txt` (both 2026-07-20 11:16 local) match live brew list.

## Method

1. `brew services list` (canonical Homebrew service table).
2. `launchctl list | rg homebrew.mxcl` (catches labels brew no longer owns, e.g. orphaned
   `postgresql@14`, custom `ui-tars`).
3. Formula presence: `brew list --formula` for postgres/redis/mariadb/herdr/omlx/et.
4. Listeners: `lsof`/`nc` on 2022, 5432, 3306, 6379, 8000, 8081.
5. Cross-check: `registry/paths.yml` `brew_services`, `registry/ports.yml`, stayturgid
   ET/VLM docs (`system/homebrew.mxcl.et`, `homebrew.mxcl.ui-tars`).

**No production service was stopped this session.** Keep/kill recommendations are defaults
for operator sign-off (`human/F2-BREW-SERVICES-DECISIONS.md`).

## Live inventory (2026-07-20)

### `brew services list` (excerpt)

| Name | Status | User / domain | Notes |
| --- | --- | --- | --- |
| et | **error 78** | root, **user** plist path | User LaunchAgent fails; **system LaunchDaemon** is the real server |
| herdr | **started** | djbclark | Unix-domain sockets only |
| omlx | **started** | djbclark | `127.0.0.1:8000` |
| redis | **started** | djbclark | `127.0.0.1:6379` (+ `::1`) |
| mariadb | none | — | Formula installed; service never started |
| postgresql@18 | none | — | Formula installed; service not started |
| caddy, grafana, vector, victoriametrics, … | none | — | Site owns `com.djbclark.*` equivalents (Phase D) |

### Extra `homebrew.mxcl.*` labels (launchd, not all in brew list)

| Label | State | Evidence |
| --- | --- | --- |
| `homebrew.mxcl.et` (gui/501) | not running, last exit **78** | Conflicts with system-domain etserver |
| `homebrew.mxcl.et` (system LaunchDaemon) | **running** as root PID ~547 | `nc 127.0.0.1 2022` OK; netstat `*.2022 LISTEN` |
| `homebrew.mxcl.ui-tars` | **running** | llama-server `127.0.0.1:8081`; custom plist (not a brew formula) |
| `homebrew.mxcl.postgresql@14` | thrashing / exit **78** | Formula **uninstalled**; binary path missing; data dir remains |
| `homebrew.mxcl.herdr` | running | `herdr server`; sockets under `~/.config/herdr/` |
| `homebrew.mxcl.omlx` | running | omlx-server since ~3d; port 8000 |
| `homebrew.mxcl.redis` | running | redis 8.8.0; `PING` → PONG; **DBSIZE 0** |

### Formula install state

| Formula | Installed? | Notes |
| --- | --- | --- |
| `et` | yes | Eternal Terminal server |
| `postgresql@14` | **no** | Orphaned agent + `/opt/homebrew/var/postgresql@14` (~50 MB) |
| `postgresql` / `postgresql@18` | yes | Linked @18; var dir ~39 MB; service not started |
| `redis` | yes | |
| `mariadb` | yes | var `/opt/homebrew/var/mysql` ~143 MB (default system DBs + `test`) |
| `herdr` | yes | homebrew-core; AI coding workspace manager |
| `omlx` | yes | tap `jundot/omlx`; local MLX LLM server |
| `ui-tars` | **n/a** | Not a formula; stayturgid-managed LaunchAgent label |

## Per-service audit table

| Service | Running? | Port / bind | Needed? | Port conflict? | Registry (pre-F2) | **Recommendation** |
| --- | --- | --- | --- | --- | --- | --- |
| **et** | Yes (system daemon) | **2022** `*` | **Yes** — stayturgid fleet ET / `check_et_mac` / `et_mac.py` uses `system/homebrew.mxcl.et` | User agent exit 78 is dual-load noise, not a port fight with other stacks | `claimed_by: stayturgid` | **KEEP (stayturgid).** Leave system LaunchDaemon. Operator: remove or stop **user** `~/Library/LaunchAgents/homebrew.mxcl.et.plist` so brew services stops reporting error 78. Do not adopt into site. |
| **ui-tars** | Yes | **8081** `127.0.0.1` | **Yes** — stayturgid VLM | No | `claimed_by: stayturgid` | **KEEP (stayturgid).** Already product-owned; not a brew formula. |
| **postgresql@14** | No (exit 78) | none (was 5432) | **No** evidence of current consumers; last clean shutdown **2026-06-27**; formula gone | Orphan KeepAlive wastes launchd retries | `unmanaged` failing | **REMOVE agent (operator gate).** `launchctl bootout gui/$(id -u)/homebrew.mxcl.postgresql@14` + delete plist. **Preserve** data dir until operator confirms no needed DBs, then `rm -rf /opt/homebrew/var/postgresql@14` or archive. Do **not** reinstall @14 without a named app. |
| **postgresql@18** | No | none | Unknown future | No | (was absent) | **DEFER — leave installed, service off.** No port claim until something needs Postgres. Prefer site role later over brew services start ad-hoc. |
| **redis** | Yes | **6379** `127.0.0.1`/`::1` | **No** site/stayturgid consumer found; **DBSIZE 0**; only redis-cli clients during audit. Logs show hourly localhost HTTP probes (“SECURITY ATTACK” / cross-protocol) — noise, not app traffic | No (loopback + protected-mode) | `unmanaged` port 6379 | **Default: STOP + remove formula (operator gate)** unless operator has a personal app. After stop: drop ports.yml redis claim or mark retired. If keep for future cache: claim `site` + document who writes. |
| **mariadb** | No | none (3306 free) | **No** running service; data dir has default `mysql`/`sys`/`test` only | No | (was comment-only) | **Default: leave stopped.** Uninstall formula + data only after operator confirms no local apps need MySQL-compatible server. Do not `brew services start` without a named consumer. |
| **herdr** | Yes | **none** (UDS: `~/.config/herdr/herdr.sock`) | **Yes** as operator workstation tooling (AI coding workspace manager) | No | `unmanaged` | **KEEP — claim `site` (workstation).** No Ansible role this step (audit-first). Optional later: document in site README / thin role if plist must be rendered. |
| **omlx** | Yes | **8000** `127.0.0.1` | **Likely** — local Apple Silicon LLM (models discovered; API key auth on); distinct from LiteLLM :4000 and UI-TARS :8081 | Identifies former `TODO-identify` on 8000 | `unmanaged` | **KEEP — claim `site`.** Register port 8000 as `omlx`. No role this step. Note: HTTP probe timed out mid-session (process up ~3d) — operator may want restart if models hang; not a stop decision. |

## Registry actions taken in F2 (non-destructive)

- `paths.yml` `brew_services`: accurate notes; claim **herdr** + **omlx** → `site`; add **mariadb** + **postgresql@18** as unmanaged/deferred; mark **postgresql@14** remove-candidate; refresh **et** dual-domain note.
- `ports.yml`: **8000** owner → `site`, service `omlx` (was TODO-identify); redis note points at F2 remove recommendation; postgres/mariadb comments updated.
- **No** `brew services stop` / uninstall without operator ledger sign-off.
- just recipe `brew-services-audit` for re-survey.

## Design notes (if adopting later)

| Keep candidate | Future ownership | Implementation sketch (not this session) |
| --- | --- | --- |
| herdr | site | Optional: ensure formula present + LaunchAgent from brew; do not template secrets. |
| omlx | site | Role would template `homebrew.mxcl.omlx` or `com.djbclark.omlx` + port assert 8000 loopback; API key via SecretSpec if required. |
| redis (only if operator vetoes remove) | site | Port 6379 already in ports.yml; role = brew services start redis + bind loopback. |
| postgresql@18 (only if app appears) | site | Initdb + port 5432 claim + never dual-run with mariadb on same use-case without naming. |

## Operator decision checklist

See **`human/F2-BREW-SERVICES-DECISIONS.md`**. Each KEEP/REMOVE should be recorded there (or in
`human/RESPONSES.md`) before any stop/uninstall runs.

## Self-verification (this session)

| Check | Result |
| --- | --- |
| Live `brew services list` | et error 78; herdr/omlx/redis started; mariadb/postgresql@18 none |
| `nc 127.0.0.1 2022` | open (system etserver) |
| `redis-cli PING` / `DBSIZE` | PONG / 0 |
| `lsof` 8000 / 8081 / 6379 | omlx / llama-server / redis-server |
| 5432 / 3306 | not listening |
| `bin/registry_lint.py` | run after registry edits |
| Destructive stops | **none** |

## Carry-forward

- F3 Immich LaunchDaemon next (step2 §7).
- E5 mini/VPS LiteLLM still planned until hosts join tailnet.
- REVIEW-1: OliveTin/VM unauthenticated on single-user tailnet — do not widen.
- LiteLLM cold start ~30–90s; missing-key storms can wedge the process.
