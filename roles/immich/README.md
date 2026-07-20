# immich — system-domain LaunchDaemons (Phase F3)

Adopts the unmanaged Immich **system** LaunchDaemons into a site Ansible role.

## Live survey (2026-07-20, m1-air)

| Fact | Value |
| --- | --- |
| Installer | Unofficial native macOS pkg **v2.2.3** (`immich-native-macos`) |
| Service user | `immich` uid **9999**, shell `/sbin/nologin` |
| Root | `/opt/services/immich` (exists; **`app/` tree missing**) |
| Labels | `com.immich`, `com.immich.machine-learning` |
| Plists | `/Library/LaunchDaemons/com.immich.plist`, `com.immich.machine.learning.plist` |
| Pre-F3 state | Loaded, **last exit 78 EX_CONFIG** (missing `/opt/services/immich/app/start.sh`), KeepAlive thrash |
| Listeners | **none** on 3001/3002/3003 |
| Postgres | not listening (Immich needs DB; not started this step) |

Restoring the full Immich application (re-run native pkg / rebuild app under
`/opt/services/immich/app`) is **out of band** for F3. This role owns
LaunchDaemon content and lifecycle; it does not reinstall Node/Python app bits
or commit DB passwords.

## Label decision (DEVIATION recorded)

**Keep `com.immich` / `com.immich.machine-learning`** with site-managed plist
content — do **not** rename to `com.<site_ns>.immich*`.

Reasons:

1. Matches the unofficial installer’s plists, `updatepaths.sh`, and `uninstall.sh`.
2. System-domain service predates site_ns; ownership is the role + registry.
3. Relabeling while `app/` is absent is pure churn.

Site LaunchAgent pattern (`com.djbclark.*`) remains for **user-domain** agents
(LiteLLM, site_agents, Phase D serverapps). Immich is system domain + dedicated
user.

## Ports (registry)

| Port | Bind | Service | Status until healthy |
| --- | --- | --- | --- |
| 3001 | 127.0.0.1 | immich-web | planned |
| 3002 | 127.0.0.1 | immich-microservices | planned |
| 3003 | 127.0.0.1 | immich-machine-learning | planned |

Do **not** open Immich on Tailscale/public without an auth story (REVIEW-1).

## What the role does

1. Asserts Darwin + service user probe.
2. Detects whether `app/start.sh` and `app/machine-learning/start.sh` exist.
3. Ensures `/var/log/immich` (owned by `immich` when user exists).
4. Renders improved LaunchDaemon plists (logs, PATH, WorkingDirectory,
   ThrottleInterval 30s, HOME under `/opt/services/immich/home`).
5. **If app missing:** `launchctl bootout` + **`launchctl disable`** both labels
   (stops EX_CONFIG KeepAlive thrash). Plists stay on disk (site-managed).
6. **If app present:** enable + bootstrap; optional HTTP
   `GET /api/server/ping` on :3001.
7. Does **not** delete old plists in a destructive “swap” (same paths; content
   is site-templated in place). Does **not** drop the `immich` user or data dirs.

Requires **privilege escalation** (`become`) for `/Library/LaunchDaemons` and
`launchctl` system domain.

## Apply

```bash
cd ~/ops/site-djbclark
# System domain needs root — use ask-become-pass or SUDO_ASKPASS
just immich-apply -- --ask-become-pass
just immich-apply -- --ask-become-pass   # second: changed=0 for plists when stable
just immich-check -- --ask-become-pass
just immich-status
```

Non-interactive GUI password helper (macOS):

```bash
export SUDO_ASKPASS="$PWD/bin/sudo-askpass-osascript"
export ANSIBLE_BECOME_ASK_PASS=False
# ansible become with -A style via ansible.cfg / --become-method sudo
just immich-apply -e ansible_become_pass=unused  # prefer:
ansible-playbook playbooks/immich.yml --become --ask-become-pass
```

Or:

```bash
SUDO_ASKPASS=./bin/sudo-askpass-osascript sudo -A true   # prime / test dialog
just immich-apply -- --become
```

## Status / health

```bash
just immich-status
# launchctl print system/com.immich
# launchctl print system/com.immich.machine-learning
# launchctl print-disabled system | rg immich
curl -fsS --max-time 5 http://127.0.0.1:3001/api/server/ping || true
```

Expected **with app absent (current):** labels **disabled** (or not thrashing);
ports closed; curl fails. Expected **with app restored:** labels loaded/running;
ping 200; flip ports.yml status `planned` → `active`.

## Rollback

Stop site-managed daemons and restore **pre-F3 plist files** if you archived
them (role overwrites in place — archive first if you need byte-identical
restore):

```bash
# Prefer: re-apply previous git revision of the role, then:
sudo launchctl bootout system/com.immich 2>/dev/null || true
sudo launchctl bootout system/com.immich.machine-learning 2>/dev/null || true
# If you saved originals before first F3 apply:
# sudo cp /path/to/archive/com.immich.plist /Library/LaunchDaemons/
# sudo cp /path/to/archive/com.immich.machine.learning.plist /Library/LaunchDaemons/
sudo launchctl enable system/com.immich
sudo launchctl enable system/com.immich.machine-learning
sudo launchctl bootstrap system /Library/LaunchDaemons/com.immich.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.immich.machine.learning.plist
```

**Safe stop without deleting plists** (matches “disable on retire” spirit when
app is gone):

```bash
sudo launchctl bootout system/com.immich
sudo launchctl bootout system/com.immich.machine-learning
sudo launchctl disable system/com.immich
sudo launchctl disable system/com.immich.machine-learning
```

Do **not** run the native `uninstall.sh` from this role — it drops the DB user
and deletes `/opt/services/immich`.

## Restoring the application (operator, later)

1. Ensure Postgres + Redis (and ports registry claims) for Immich consumers.
2. Reinstall via the native pkg or rebuild into `/opt/services/immich/app`
   (never commit DB passwords; `env` file stays host-local mode 0600).
3. `just immich-apply -- --ask-become-pass` → enable + bootstrap.
4. Health: `curl -fsS http://127.0.0.1:3001/api/server/ping`
5. Flip `registry/ports.yml` immich entries `planned` → `active`; re-lint.

## Secrets

No secrets in git. DB password lives only in host `/opt/services/immich/env`
(or recreated on reinstall). Do not template that file from the site repo.
