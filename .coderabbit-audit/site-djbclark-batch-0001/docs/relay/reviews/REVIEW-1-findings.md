# REVIEW-1 — whole-repo code review + fix (2026-07-20)

Reviewer: Claude Fable 5 (Mac GUI, effort High). Scope per the REVIEW-1
baton (`git show 57cad9a:docs/relay/NEXT-PROMPT.md`): mandated carry-forward
deep review (stayturgid #29/#30/#31/#32, AutoJs6 PR#1+debug17, site
D7-ROUTES-E parity) plus whole-repo sweep, compressed to fit the remaining
5h-session budget (session meter was at 82% before Phase 1 started; the
deep-dive core got full attention, the sweep was targeted rather than
exhaustive — see "Coverage" below).

## What was reviewed

- **stayturgid #29 (merge `199ea20`)** — sticky-a11y detect + catastrophic
  2h window + Fire skip-catastrophic. Full diff read: dashboard.py,
  fleet_health_monitor.py (`_audit_scraped_errors` rewrite,
  `_device_log_epoch` syslog format), fleet_health.py
  (`autojs6_a11y_stale` heuristic), comonitor.js, guard.js,
  stayturgid_repair.py, both test files.
- **stayturgid #31 (merge `0053f00`)** — comonitor sticky →
  degraded-not-FAILED, notify-once-per-process. Full diff read.
- **AutoJs6 `4c2c3522..3a0f0696`** — `isMalfunctioning() = hasService() &&
  !hasInstance()`; ensureService/ensureServiceOperational rebind via
  privileged `restartService` with launchSettings + toast fallback;
  onToggleSuccess sticky toast; `stopService(false)` on forcible restart
  (suppresses Settings popup only — behavior fine); LeakCanary off for
  fleet debug (bools.xml). Coherent with the stayturgid side.
- **End-to-end sticky-a11y state machine** — agrees across repos:
  control-side heuristic (Settings-listed + watchdog quiet ≥1800s), device
  Termux nudge (same 1800s band), comonitor degraded-notify-once, guard
  detect with termux-repair + 20s recheck debounce, app-side rebind.
- **stayturgid #30 (merge `c5e52e1`)** — ASCII-only deploy target +
  STALE_PROJECT_MIRRORS `rm -rf` (constant paths, skip-if-target guard,
  single-quoted) + test_ascii_paths.py. Sound.
- **stayturgid #32 (`ab329a5`)** — Choice E: grafana.ini
  domain/root_url/serve_from_sub_path wiring, OO ZO_BASE_URI/ZO_WEB_URL
  plist conditionals, serverapps.py plan_grafana/plan_openobserve
  public-host branches (health_url remap under /oo — correct), site_sync
  `openobserve_http_prefix` context, caddy fragment handle-vs-handle_path
  policy (preserve for grafana/oo, strip for olivetin/vm, catch-all last),
  vector sink + healthcheck URI prefix, discover.py hostname substitution
  (YAML + no-PyYAML fallback parser).
- **site D7-ROUTES-E parity** — generated `stayturgid.caddy` /
  `stayturgid_sinks.yaml` are exact renders of #32 templates with
  `registry/ports.yml` values (3000/5080/1337/8428/8088) and `/oo` prefix.
- **Sweep (targeted)** — stayturgid full gate suite as oracle
  (`just syntax/check/test/lint`); site `bin/registry_lint.py` read line-by-
  line; `secretspec.toml` vs actual env consumption in stayturgid role
  templates; `registry/ports.yml` consistency; front-door + daemon
  verification.

## Fixed (merged, evidence)

1. **stayturgid master was red** — `just check` failed on merged master:
   #29 introduced the device alias `p7a` in a comment in
   `control/bin/fleet_health_monitor.py`, tripping the validate-identity
   drift denylist (site aliases must not appear in the product repo).
   Reworded generically. (CI was green because the drift check derives its
   denylist from the *site* inventory, which CI doesn't have.)
2. **`just lint` failed locally** — ansible-lint, run from
   `examples/consumer-full-fleet/`, follows the example's
   `import_playbook` into `ansible/playbooks/site.yml` but the example
   `ansible.cfg` had no `roles_path` and a `collections_path` that excluded
   the repo's `.ansible/collections` (exactly where the lint recipe
   installs `ansible.posix`). Added `roles_path = ../../ansible/roles` and
   `../../.ansible/collections` to all three consumer examples.
   → Both in **stayturgid PR #33**, merged `6ca9d31`; full local suite
   exit 0 and CI green on the PR head.
3. **secretspec gap** — `serverapp_vector`'s plist embeds
   `OPENOBSERVE_ROOT_EMAIL` from the apply-time env
   (`lookup('env', ...)` in role defaults), but site `secretspec.toml`
   declared only `OPENOBSERVE_ROOT_PASSWORD`; a secretspec-managed apply
   would render an empty Vector sink basic-auth user. Declared the email.
   → site `08409bf`.
4. **registry_lint blind spot** — collision detection keyed on exact
   `(port, bind)`, so the same port under `*` and `127.0.0.1` passed lint
   despite being a real listen conflict. Wildcard binds (`*`, `0.0.0.0`,
   `::`) now conflict with any other bind of the same port. Current
   registry stays clean. → site `08409bf`.

## Flagged, not fixed (judgment / operator decisions)

- **R1-1 (consistency):** #31 softened comonitor's sticky detection to
  degraded/notify-once because `auto.service` flickers null on s24, but
  `guard.js enforce()` still hard-notifies `a11y-stale` per watchdog cycle
  from the same flicker-prone check. Mitigations already present: guard
  re-checks after termux repair + up-to-20s poll, and `notify.show`
  replaces same-tag notifications. No device evidence of guard-path spam;
  changing it would touch a #29/#31 behavior contract — left alone.
  Revisit only with s24 watchdog-log evidence.
- **R1-2 (security, by design):** Choice E exposes OliveTin (action
  executor, no auth) and VictoriaMetrics (unauthenticated admin API incl.
  `/api/v1/admin/tsdb/*`) to the whole tailnet. Grafana/OO carry their own
  logins. Acceptable per the D7-ROUTES-E decision on a single-user
  tailnet; revisit if the tailnet gains users/nodes (Caddy basic_auth or
  Tailscale ACLs on those two paths).
- **R1-3 (nit):** `WATCHDOG_FRESH_SEC = 1800` duplicated as a literal in
  `device/termux/py/stayturgid_repair.py` (cross-referenced by comment;
  device file can't import the control lib — fine as-is).

## Coverage caveats

Phase 2 was targeted, not exhaustive: stayturgid `control/` beyond the
Phase-1 files was exercised via the gate suite rather than read line-by-
line; ansible roles beyond serverapp_{grafana,openobserve,vector} and the
AutoJs6 fleet-patch surface beyond `4c2c3522..3a0f0696` were not re-read.
Phase 4 adversarial re-passes were skipped for budget. A future review
slot can start from this file.

## Verification (wrap-up)

- stayturgid master `6ca9d31`, suite exit 0, CI green, no open PRs,
  checkout on master. site master pushed. AutoJs6 untouched (no source
  changes → no compile check needed).
- Front door after merges: `/grafana/` 302→200, `/oo/` 308→200,
  `/olivetin/` 200, `/vm/` 200 (redirects are the apps' own login/base
  redirects; followed to 200). O-V-G-O daemon processes up (6 procs).
