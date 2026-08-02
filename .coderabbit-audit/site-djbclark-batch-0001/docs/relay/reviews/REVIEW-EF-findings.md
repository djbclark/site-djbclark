# REVIEW-EF — Phase E + Phase F close-out review (2026-07-20)

Reviewer: Claude Fable 5 (Mac GUI, cswap account 2, djbclark@mit.edu, effort
Medium). Scope: site-djbclark commits E1 through F4
(`94ba256`/`a3280a6`..`89f03f6`), plus linked docs/registry/roles. Out of
scope per baton: F2 keep/kill execution, Immich app restore, mini/VPS deploy.

## What was reviewed

- **Full diff, E1→F4** (`git diff 08409bf..89f03f6`, 61 files, +4101/-163):
  `roles/{litellm,goose,immich,site_agents}`, `playbooks/{litellm,goose,
  immich,site_agents}.yml`, `bin/brew_flock.py`,
  `bin/project_merged_brewfile.py`, `bin/sudo-askpass-osascript`,
  `brew/fragments/*.yml`, `registry/{ports,paths}.yml`, `secretspec.toml`,
  `justfile`, `inventory/hosts.yml`, `human/*`, the three F-phase audits.
- **E1 LiteLLM** (`roles/litellm`): loopback-bind assert
  (`litellm_bind == '127.0.0.1'`, fail-closed), secret-bearing plist/unit
  mode 0600 + `no_log: true`, bootout-on-plist-change / kickstart-on-config-
  change pattern (Darwin `service_darwin.yml`) matching the D-phase MF-3/
  MF-4 convention, version-floor assert for Auto Router v2, disk-cache extra
  probed and verified.
- **E5 multi-host** (`playbooks/litellm.yml`, `inventory/hosts.yml`,
  `roles/litellm/tasks/service_linux.yml`): `mac-mini-intel` and
  `vps-primary` are `site_host_status: offline_unprovisioned` and hit
  `meta: end_host` in `pre_tasks` before `gather_facts`/SSH — confirmed no
  SSH attempt is possible against unreachable hosts. Linux systemd --user
  path mirrors the Darwin secret-mode/reload pattern; currently unreachable
  code (no online Linux host yet) but correct as written.
- **E2 Goose** (`roles/goose/tasks/main.yml`): collision-refuse pattern on
  both `config.yaml` and the custom-provider JSON (site-managed-marker
  search before any overwrite), directories 0700, files 0600, Fieldy
  extension defaults `enabled: false` (verified in both
  `roles/goose/defaults/main.yml:47` and the rendered
  `roles/goose/templates/config.yaml.j2:39` — confirmed live via
  `just goose-status`).
- **E3 MCP research**: spot-checked that no invented package names made it
  into the templates — only the real `@modelcontextprotocol/server-
  filesystem` and Fieldy's documented remote endpoint are wired;
  Shortwave/Saner remain comment-stub-only per the ledger's claim.
- **E4 SecretSpec**: `secretspec.toml` diff adds only declarations (no
  values); live `~/ops/stayturgid/.env` is `0600` (confirms the R3-1 fix
  from the prior review still holds); grepped the full E1→F4 diff and the
  human docs for key-shaped strings (`sk-`, `AKIA`, `ghp_`, `xox[bp]-`) —
  none found.
- **F1 site_agents** (`system-state-backup.sh.j2`): `capture()` uses an
  atomic mktemp+mv pattern so a failing capture never clobbers a good one;
  the only `rm -f` is tmp-file cleanup on failure; `rsync -a --delete`
  mirrors a dedicated capture dir (`~/system-state`) — not a broader
  home-directory delete.
- **F2 brew-services audit**: confirmed **no** `brew services stop` /
  `launchctl bootout` / uninstall ran against any production service —
  `docs/relay/audits/F2-brew-services-audit.md` "Destructive stops: none"
  matches `human/F2-BREW-SERVICES-DECISIONS.md` (all 9 rows still blank,
  awaiting operator sign-off) and the actual live `brew services list`
  state today (et error 78 user agent, postgresql@14 orphaned agent, redis
  started — all unchanged from the F2 session).
- **F3 Immich** (system-domain LaunchDaemons, `become: true`,
  `owner: root, group: wheel, mode: 0644`): `immich_app_present` correctly
  drives `_immich_want_running`; with `app/` absent, `launchdaemon.yml`
  boots out (if loaded) then `launchctl disable`s both labels — never
  bootstraps. Live-verified this session: both labels `print-disabled`
  → disabled, not loaded, ports 3001-3003 closed, health unreachable
  (expected). Plist filenames (`com.immich.plist`,
  `com.immich.machine.learning.plist`) match `registry/paths.yml` exactly.
  No secrets in either template (paths/ports only).
- **F4 Merged-Brewfile + flock** (`bin/project_merged_brewfile.py`,
  `bin/brew_flock.py`): projector is read-only (never shells out to
  `brew install`/`uninstall`/`bundle cleanup` — grepped, confirmed absent);
  `brew_flock.py`'s `fcntl.flock` acquire/release is correctly scoped in a
  `try/finally`, `--nonblock` and `--timeout` paths both tested logically
  sound (EX_TEMPFAIL 75 / 124 timeout).
- **Registry consistency**: `registry/ports.yml` and `registry/paths.yml`
  cross-checked against every role's actual rendered paths/ports/labels —
  no drift found. `bin/registry_lint.py` clean (wildcard-vs-specific bind
  collision detection from REVIEW-1 is unaffected by this phase's changes).

## Mechanical checks (this session, live)

| Check | Result |
| --- | --- |
| `bin/registry_lint.py` (via `uv run`) | `registry-lint: OK` |
| `just brew-project` | unchanged `generated/Merged-Brewfile` (2 taps, 19 formulae, 2 casks) |
| `just brew-diff` | exit 0; claimed present 23, missing 0, live-only 160 (informational, no cleanup) |
| `just litellm-status` | launchd loaded; `/v1/models` → gpt-4o-mini, gpt-4o, claude-sonnet-5, gpt-5.5, smart-router |
| `just goose-status` | 1.43.0; `litellm-local`/`smart-router`; filesystem+fieldy(disabled) extensions; files 0600/0700 |
| `just site-agents-status` | both `com.djbclark.{system-state-backup,hibernate-disk-check}` loaded |
| `just immich-status` | both labels disabled/not loaded; ports closed; health unreachable (expected — app absent) |
| D7 endpoints via loopback | grafana :3000→301, oo :5080→404 (base path is `/oo/`, expected), olivetin :1337→200, vm :8428→200 |
| D7 endpoints via HTTPS front door | `/` 200, `/grafana/` 302, `/oo/` 308, `/olivetin/` 200, `/vm/` 200 — all following-redirect success codes, matches D7-ROUTES-E/REVIEW-1 baseline |
| `git status` | clean throughout |

## Findings

**None.** No correctness or safety findings survived this review. Every
secret-bearing render is mode 0600 with `no_log: true` on the render task;
every daemon-state-changing role gates destructive actions (bootout/disable)
on plist-changed or want-running flags, never unconditionally; F2's
audit-only constraint held with zero live drift since the F2 session; no
secret values or key-shaped strings are committed anywhere in E1–F4.

## Architecture / style notes (not must-fix, no action taken)

- `roles/litellm/tasks/service_linux.yml` is currently dead code (no online
  Linux host) — correct as written, will get its first live exercise
  whenever `vps-primary` joins the tailnet. Nothing to fix now.
- F2's registry claims (`herdr`, `omlx` → `site`) still have no Ansible
  role — audit-only by design (step2 §7 F2 scope), unchanged from the F2
  session.
- `registry/paths.yml`'s F1 flag (step1-schema residual, carried since D1)
  remains open; still architecture/style, not re-litigated here per the
  FUND-B quality bar and REVIEW-1/M1-R/R3's prior deferrals of the same
  class of finding.

## Coverage

This was a full read of the E1–F4 diff (not a targeted sample) plus live
verification of every daemon/service touched in the phase. Not re-read:
code predating E1 (already covered by REVIEW-1/R3) and the AutoJs6/device
fleet (out of scope — E/F phases don't touch device code). No adversarial
re-pass beyond the checks above; nothing surfaced that would motivate one.

## Verdict

**Phases E and F are closed with no must-fix work outstanding.** Remaining
items are all pre-existing operator-gated residuals, unchanged by this
review:

1. F2 keep/kill sign-off (`human/F2-BREW-SERVICES-DECISIONS.md`) —
   operator decision, not mechanically resolvable.
2. F3 Immich app restore (`/opt/services/immich/app` missing) — out of
   band, native installer / operator action.
3. E5 mini/VPS coming online — needs the hosts on the tailnet first.

None of these block calling Phase E/F complete. Next baton hands these
three off as an explicit residual-operator baton rather than continuing
the AI relay chain, per step2 §10 (project-level final review is separate
and may wait).
