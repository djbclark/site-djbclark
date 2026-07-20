# F3 — Immich LaunchDaemon → site role (m1-air)

**Date:** 2026-07-20  
**Host scope:** `m1-air` only.  
**Session:** Phase F step F3.

## Live survey (before)

| Item | Finding |
| --- | --- |
| Installer | Unofficial native macOS **v2.2.3** (`~/Documents/GitHub/immich-native-macos`) |
| User | `immich` uid 9999, `/sbin/nologin` |
| Paths | `/opt/services/immich` present; **`app/` missing** (only `home/` remnants) |
| Labels | `system/com.immich`, `system/com.immich.machine-learning` |
| Plists | `/Library/LaunchDaemons/com.immich.plist`, `com.immich.machine.learning.plist` |
| State | Loaded, last exit **78 EX_CONFIG**, KeepAlive thrash |
| Ports 3001/3002/3003 | closed |
| Docker / brew formula | none |

## Design choices

1. **Keep `com.immich.*` labels** (DEVIATION from `com.<site_ns>.*`) — native installer contract; ownership via role + registry.
2. Site-managed improved plists (logs, PATH, WorkingDirectory, ThrottleInterval).
3. **When app absent:** bootout + `launchctl disable` (stop thrash). Do not reinstall app this step.
4. Ports **3001/3002/3003** `127.0.0.1` registered **planned** until HTTP health.
5. Pre-F3 plists archived under `docs/relay/audits/f3-immich-pre-plists/` (rollback originals).
6. No secrets in git; no Tailscale/public bind (REVIEW-1).

## Live apply evidence

| Check | Result |
| --- | --- |
| First apply | exit 0; plists rendered; both labels bootout+disabled; `changed=6` |
| Re-apply (after disabled-fact fix) | exit 0; **`changed=0`** |
| `print-disabled` | `"com.immich" => disabled`, `"com.immich.machine-learning" => disabled` |
| `launchctl print system/com.immich*` | not loaded (expected when disabled/bootout) |
| Ports | 3001/3002/3003 closed |
| HTTP | `:3001/api/server/ping` unreachable (app absent) |
| `bin/registry_lint.py` | OK |
| ansible-lint production | Passed on role + playbook |

## Rollback

```bash
sudo launchctl bootout system/com.immich 2>/dev/null || true
sudo launchctl bootout system/com.immich.machine-learning 2>/dev/null || true
sudo cp docs/relay/audits/f3-immich-pre-plists/com.immich.plist /Library/LaunchDaemons/
sudo cp docs/relay/audits/f3-immich-pre-plists/com.immich.machine.learning.plist /Library/LaunchDaemons/
sudo launchctl enable system/com.immich
sudo launchctl enable system/com.immich.machine-learning
sudo launchctl bootstrap system /Library/LaunchDaemons/com.immich.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.immich.machine.learning.plist
```

(Without `app/`, re-enable will return to exit-78 thrash — only for true rollback of plist content.)

## Residuals

- Restore `/opt/services/immich/app` out of band; ensure Postgres/Redis; re-apply; flip ports `planned` → `active`.
- F2 operator gates still open (`human/F2-BREW-SERVICES-DECISIONS.md`).
- E5 mini/VPS still `offline_unprovisioned`.
