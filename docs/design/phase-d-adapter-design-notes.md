# Phase D adapter design notes

**Step:** D0-design (Plan B architecture front-load) · **Authored:** 2026-07-19
by Claude Fable 5 · **Audience:** mid-tier implementers of D1–D8. Decisions
here are made; do not re-decide them. Deviations are allowed (§4) but must be
ledgered. Authoritative companions: stayturgid `docs/architecture/site-contract.md`
§5, ADR 005, `control/site_contract/{site_map.py,site_sync.py,sync_manifest.yml}`.

## 0. Existing surfaces this design consumes (do not invent new config)

- `site_map.py` already validates `serverapps.<app>.{mode,config,fragment_dir}`
  with modes `own|inject|off` for exactly the v1 app set. That IS the config
  surface. The spec §5.2 phrase "site var `serverapp_<app>_mode`" is satisfied
  by the site-map key `serverapps.<app>.mode`; do not add a second knob.
- `site_sync.py` provides plan-then-act, lockfile drift (exit 2), manifest-driven
  rendering under `generated/stayturgid/`, and destination resolution
  (`dir=` → `STAYTURGID_SITE_DIR` → single `site-*` under `OPS_ROOT`). Adapters
  extend this machinery; they do not fork it.
- `ansible/roles/control_node/tasks/observability.yml` + `launchd_ensure.yml`
  are the daemon-lifecycle pattern (plist template → ensure loaded). D2/D3
  refactor from it; D1 clones its shape for caddy.
- Live facts (m1-air, 2026-07-19): caddy runs as LaunchAgent
  `com.stayturgid.caddy`, config `~/.config/stayturgid/Caddyfile`, **no
  `import` line and no fragment dir exist today**. Site labels
  `com.djbclark.*` already exist. `registry/ports.yml` is port authority.

## 1. D1 adapter pattern (the template D2–D5 clone)

### 1.1 Split of responsibilities (decision)

Two layers, one entry point:

1. **Fragment materialization — site-sync (Python).** Product fragments are
   ordinary `sync_manifest.yml` entries rendering into
   `generated/stayturgid/fragments/<app>/`. Lockfile, drift, dry-run, deletes
   all come free. Fragments are rendered for every app regardless of mode
   (rendering is inert; mode gates activation, not rendering).
2. **Daemon lifecycle + activation — `control/site_contract/serverapps.py`**,
   new module, CLI `just site-serverapps [apps=<csv>] [mode=apply|dry-run]`
   in stayturgid. Per app it: resolves mode (§1.2) → plans actions → acts.
   Own-mode install/config/plist work is delegated to the Ansible role
   `serverapp_<app>` (`ansible-playbook` invoked by the module; any Ansible
   failure maps to exit 1). Inject-mode file placement and include-line
   verification are done directly in Python (plan-then-act, §1.3).

One Ansible role per app: `ansible/roles/serverapp_<app>/` (extracted from
`observability.yml` for vector/openobserve in D2/D3; new for caddy in D1).

### 1.2 Mode selection (deterministic, evaluated in this order)

1. `serverapps.<app>.mode` from `site-map.yml` (own/inject/off). `off` = no
   actions, exit 0.
2. Else **inject** if a _foreign_ config exists at the §5.3 detect path
   (site-map `serverapps.<app>.config` overrides the detect path). "Foreign"
   means: file exists AND its first 3 lines do not contain the generated-header
   marker (§1.7) AND it is not under `~/.config/<site_ns>/` or
   `~/.config/stayturgid/` (our own current/legacy deployments must not flip
   the default to inject on re-runs).
3. Else **own**.

Resolved mode is printed in dry-run and apply output (`caddy: mode=own
(source=site-map|detect|default)`) so runs are auditable.

### 1.3 Own vs inject behavior

**Own mode** (role `serverapp_<app>` does all of this):

- `brew install` the formula if absent (never upgrade an existing install).
- Render base config to `~/.config/<site_ns>/<app>/<config-name>` from
  inventory + registry only. For caddy the base config contains
  `import <site_dir>/generated/stayturgid/fragments/caddy/*.caddy` — the
  daemon imports **directly from the committed generated area**; no copy step,
  no second writer. Vector equivalently gets extra `--config` args globbing
  `generated/stayturgid/fragments/vector/*.yaml`.
- Render plist `~/Library/LaunchAgents/com.<site_ns>.<app>.plist` (§1.5), logs
  to `~/.config/<site_ns>/logs/<app>.log`; bootstrap via launchd_ensure
  pattern; then health-check (per-app curl from registry port).
- Validate before activate where the app supports it (`caddy validate`,
  `vector validate`); validation failure = exit 1, nothing bootstrapped.

**Inject mode** (Python, no Ansible):

- Never touches the user's daemon, unit, or base-config _content_.
- Copies rendered fragments from `generated/stayturgid/fragments/<app>/` into
  the app's include location (`serverapps.<app>.fragment_dir` from site-map,
  else §5.3 auto-detect). These copies are plan-then-act with the same
  drift rule: if a previously-placed fragment was hand-edited, exit 2.
- Verifies the include mechanism exists (caddy: `import` line covering the
  fragment_dir glob). Missing → **exit 2** with the exact line to add;
  own mode adds it itself (it owns the base config).
- openobserve/victoriametrics inject = "reuse endpoint from registry only",
  zero file writes (spec §5.3). olivetin has no inject; its config is a
  projection (§2).

**Off mode:** fragments stay rendered in generated/ but nothing activates
them; any previously-placed inject copies are listed for deletion (plan shows
them; apply removes only files carrying our generated header).

### 1.4 Exit-code contract (matches site-sync)

| Code | Meaning for `site-serverapps`                                                                                                                 |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| 0    | success / no-op (idempotent re-run must return 0 with all `skip`)                                                                             |
| 1    | precondition or execution failure: missing tool/formula, bad map, unregistered port, config validation failure, Ansible/health failure        |
| 2    | would touch user-owned content: drifted placed fragment, missing include line in inject mode, foreign config present when site-map forces own |

Exit 2 never partial-writes; `--force-generated` recovers only
generated-headered files, exactly as in site-sync.

### 1.5 launchd namespace rule

- Label: `com.<site_ns>.<app>`. `site_ns` is a **site fact**: key `site_ns`
  in `inventory/group_vars/all.yml` (D1 adds `site_ns: djbclark` for this
  site; site-init seeds it from `sitename` for future sites). Roles must read
  the fact — never hard-code `djbclark` in stayturgid.
- gui-domain LaunchAgent (matches every existing daemon here), `KeepAlive`
  true for servers, plist path `~/Library/LaunchAgents/<label>.plist`.
- Product-internal agents (adb-reconnect, watchdogs) keep `com.stayturgid.*`;
  only the shared serverapps of contract §5 move to the site namespace.

### 1.6 Fragment dir layout

```text
generated/stayturgid/fragments/
  caddy/stayturgid.caddy          # routes for product UIs (one file, all routes)
  vector/stayturgid_sources.yaml  # component ids prefixed stayturgid_ (§5.3)
  vector/stayturgid_sinks.yaml
  grafana/datasources/stayturgid.yaml
  grafana/dashboards/stayturgid-fleet.json
  olivetin/stayturgid_actions.yaml  # projection input, not a live config (§2)
```

One file per app per concern (not per host — hosts are rows inside a file);
keeps the manifest stable when inventory changes (§2 blast radius).

### 1.7 Generated-header format

First line of every rendered fragment/config (comment leader per syntax;
JSON files carry it in a top-level `"_generated"` string instead):

```text
# GENERATED by stayturgid site-sync — DO NOT EDIT (drift → site-sync exit 2)
# template: control/site_contract/sync_templates/fragments/<app>/<file>.j2
# product_version: {{ product_version }} commit: {{ product_commit }}
```

**Decision — no sync timestamp in file bodies** (spec §5.4 says "and sync
time"; deliberately deviated, §5): a timestamp would change every render,
breaking the idempotent-second-run no-op and making every sync a git diff.
Sync time lives only in `.lockfile.yml`. The marker string `GENERATED by
stayturgid` (or `"_generated"`) is the detection token used by §1.2/§1.3.

### 1.8 Manifest wiring and render context

- Each fragment is a normal `sync_manifest.yml` entry
  (`path: generated/stayturgid/fragments/caddy/stayturgid.caddy`,
  `template: fragments/caddy/stayturgid.caddy.j2`).
- `_site_render_context` grows two keys: `ports` (parsed
  `registry/ports.yml` mapping) and `inventory_hosts` (sorted host list with
  per-host vars from the mapped inventory). StrictUndefined stays on —
  a fragment referencing an unregistered port fails loudly (exit 1). Port and
  label values come only from registry/inventory (§5.4); role defaults seed
  registries at site-init time only.

### 1.9 D1 migration sequence — no-cutover rule + rollback

Caddy holds 80/443, so old and new labels cannot listen concurrently. The
no-cutover rule here means: **the old plist is never deleted in the session
that stands up the new label**, and the rollback is two known commands.

1. Render new base config (`~/.config/djbclark/caddy/Caddyfile`, with import
   line) + fragments; `caddy validate --config` it. Old daemon untouched.
2. `curl -fsS http://127.0.0.1:8080/health` (pre-check, old daemon healthy).
3. `launchctl bootout gui/501/com.stayturgid.caddy` (plist stays on disk),
   then `launchctl disable gui/501/com.stayturgid.caddy` — bootout alone is
   session-scoped; without the disable, next login re-bootstraps the retained
   plist and both labels fight for 80/443 (R1 must-fix amendment, 2026-07-19).
4. `launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.djbclark.caddy.plist`
5. Verify: health curl again, plus one real HTTPS request through the
   Tailscale front door, plus `launchctl print gui/501/com.djbclark.caddy`
   state = running. Record all three in the ledger.
6. **Rollback (documented + kept working; R1-amended for the disable step):**
   `launchctl bootout gui/501/com.djbclark.caddy && launchctl enable gui/501/com.stayturgid.caddy && launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.stayturgid.caddy.plist`
7. Retiring the old plist + `~/.config/stayturgid/Caddyfile` happens in a
   _later_ session (D7), after ≥1 day of new-label operation.

D2–D5 clone steps 1–7 with their app's health check; apps without a port
conflict (grafana, victoriametrics, olivetin — new installs) skip 2–3 and
simply bootstrap under the site label.

## 2. D6 projection design (inventory → fragments)

- Projections are **pure functions of (inventory, registry)**: no live-system
  probes, no timestamps, hosts sorted by name, stable JSON/YAML key order.
  Same inputs ⇒ byte-identical outputs ⇒ site-sync no-op.
- **Write set is closed:** a D6 sync may only create/overwrite/delete files in
  `generated/stayturgid/fragments/{caddy,grafana,olivetin}/` plus the
  lockfile. `serverapps.py` must refuse (exit 1) a plan touching anything
  else. A single host add/remove/rename therefore rewrites at most: 1 caddy
  fragment, 1–2 grafana files, 1 olivetin actions file.
- **Containment:** generated/ is committed, so the review loop is
  `site-sync mode=dry-run` → apply → `git diff` → commit. Implementer rule:
  if the diff touches more files than the closed set above, stop — that is a
  projection bug, not a bigger edit.
- **OliveTin single-writer merge:** live `config.yaml` (own mode, under
  `~/.config/<site_ns>/olivetin/`) is projected from
  `fragments/olivetin/stayturgid_actions.yaml` + user file
  `<site_dir>/olivetin/user-actions.yaml` (user area, optional). site-sync is
  the only writer of the live file; user file is never modified. Action `id`s
  are prefixed `stayturgid_` vs `user_` — collisions are exit 1.
- Grafana dashboard JSON: pinned datasource UIDs (constants in the template),
  panel ids derived from sorted host index — a one-host edit diffs as one
  panel block, reviewable.
- Drift on any projected file (hand edit) is the standard exit 2; recovery is
  `--force-generated` after review, same as every generated file.

## 3. D8 rollout order (edge otelcol)

Design per step2 plan row D8 (otelcol-contrib linux_arm64, filelog tail of
`repair.jsonl`/`watchdog.jsonl`, memory_limiter 100MB, batch 30s, OTLP HTTP
to Mac vector 0.0.0.0:4318). Rollout decisions:

1. **Mac-side first, no device contact:** role downloads pinned
   otelcol-contrib release (version + sha256 checked in) into a Mac cache dir;
   verify vector 4318 listening and OpenObserve 5080 answering.
2. **Config decision — persistent checkpoints:** filelog receiver uses the
   `file_storage` extension (checkpoint dir under the app's Termux data dir)
   so offsets survive restarts; without this the offline/reconnect verify
   below is meaningless (restart would re-send or skip).
3. **One-device-first (hard rule):** probe reachability; deploy to exactly
   one online device. Do not loop inventory in the first apply.
4. **Pilot verify (both must pass before any second device):**
   a. Live path: append a marker line to `repair.jsonl` on-device; marker
   visible in OpenObserve search (5080) ≤ 60 s (2× batch interval).
   b. Offline/reconnect: stop otelcol (or drop network), append a second
   marker, restart/reconnect; marker appears ≤ 60 s after reconnect.
5. **Offline devices:** skip without failing the run; record per-device
   pending status in the ledger/handoff. The role is idempotent — rerun on
   next contact completes them. Never block D8 on fleet-wide reachability.
6. **Fleet rollout:** after pilot passes, remaining reachable devices one at
   a time, live-path verify (4a) each; full offline-cycle verify (4b) only on
   the pilot.
7. **Rollback per device:** remove start-otelcol.sh from the boot script and
   kill the process; Mac ingest path is unaffected (vector/openobserve keep
   running regardless).

## 4. Deviation protocol (relaxed bar, FUND-B)

- These notes are guidance with decided defaults, not law. If a decision
  proves awkward in implementation, the implementer may deviate **and must**
  append to the step's ledger Notes: `DEVIATION: <what> — <why>` so M1-R can
  re-judge every deviation against this document.
- Not deviatable: exit-code meanings (§1.4), never-touch-user-content (§1.3),
  the no-cutover/rollback rule (§1.9), one-device-first (§3.3), and the
  closed write set (§2). Conflicts with these = stop and escalate.
- Implementers do not edit this document; it stays the Fable-5 baseline that
  M1-R diffs reality against.

## 5. Deliberate spec deviations decided in this document

1. site-contract §5.4 "generated header … and sync time": header carries
   version+commit only; sync time is lockfile-only (§1.7 rationale:
   idempotence and diff noise; acceptance test "second run is a no-op" wins).
2. site-contract §5.2 "site var `serverapp_<app>_mode`": realized as the
   already-implemented `serverapps.<app>.mode` site-map key (§0); no separate
   variable is introduced.
