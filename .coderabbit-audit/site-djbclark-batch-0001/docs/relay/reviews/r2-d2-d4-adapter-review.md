# R2 — D2–D4 adapter clone review

**Date:** 2026-07-19
**Reviewer:** Grok 4.5 (TUI High) — FUND-B R2, correctness/safety must-fix
only; architecture/style deferred to ledger for M1.
**Scope:** stayturgid PRs #20 (vector → `7f7be9a`), #21 (openobserve →
`d506a42`), #22 (landing → `d99b507`); site ledger D2/D3/D4 + live m1-air.
Judged against `docs/design/phase-d-adapter-design-notes.md` §1,
stayturgid `docs/architecture/site-contract.md` §5, and R1 dispositions
(`docs/relay/reviews/r1-d1-adapter-review.md`). No full green suites
re-run (code unchanged this session).

## Verdict

D2–D4 are **sound clones of the R1-corrected D1 template**. **Zero
correctness/safety must-fixes** this session. Live fleet of site-namespace
daemons is healthy; all legacy `com.stayturgid.*` serverapp labels are
persistently disabled with plists retained for rollback/D7. Accepted F4
(second-apply ansible ensure) remains sound across all adapters.

## Checklist (R2 baton requirements)

| Check | Result |
| ----- | ------ |
| R1 MF-1 cloned (bootout **+** `launchctl disable`) for vector, openobserve, landing, landing-discover | **PASS** — all four roles; live `print-disabled` shows all five legacy labels disabled (caddy+D2–D4) |
| Rollback documented (enable then bootstrap legacy) | **PASS** — role comments + D2/D3/D4 ledger lines |
| No dual-bind on 4317/4318, 5080/5081, 8088 | **PASS** — single listener each (`vector`/`openobser`/`Python`) |
| Landing `PORT` default 8088 | **PASS** — `control/landing/landing.py:27` |
| OpenObserve data dir not re-homed | **PASS** — live `ZO_DATA_DIR_PATH` = `~/.local/share/openobserve/data` |
| Inject: vector multi-`--config`; openobserve zero writes; landing inject refused | **PASS** — code + tests |
| Live site labels running; legacy unloaded; sibling health | **PASS** — see Evidence |

## Findings

| Id | Severity | Finding | Refs | Disposition |
| -- | -------- | ------- | ---- | ----------- |
| — | **None (must-fix)** | No correctness/safety defect found that requires a product fix this session. | D2–D4 roles; live probes | **N/A** |
| A-5 | Architecture | Legacy bootout is gated on site label `unloaded` (same as D1). If both legacy and site are somehow loaded mid-failure, disable still heals *login*, but dual-bind persists until manual bootout or next full cutover path. Not live today. | `serverapp_*/tasks/main.yml` bootout `when:` | **Defer M1-R** — consider bootout-legacy-if-loaded regardless of site state (with care for race). |
| A-6 | Architecture | Health URLs / ports hardcoded in `serverapps.py` and role defaults (8088, 5080, 8686) rather than read from site `registry/ports.yml`. Correct for this site; multi-site port remap would desync health checks. | `plan_landing`, `plan_openobserve`, role defaults | **Defer M1-R** |
| A-7 | Architecture | control_node `observability.yml` still templates `com.stayturgid.{vector,openobserve}` (F5 residual extended). Disabled DB mitigates re-arm at login; D7 retires. Do **not** flip `stayturgid_observability_enabled: false` before D7 if that path deletes rollback plists. | `observability.yml`; F5 | **Defer D7 / M1** — same residual class as caddy agents.yml |
| A-8 | Architecture | OpenObserve foreign detect is well-known paths only (no glob of `com.*.openobserve`) — DEVIATION from naive “any unit” reading of §5.3; prevents false inject when another site_ns label exists (or tests with `site_ns: example` on a machine that has `com.djbclark.openobserve`). Documented in D3/D4 ledger. | `serverapps.py` `_openobserve_detect_paths` | **Accepted DEVIATION** — fold into design notes at M1 |
| A-9 | Architecture | Vector foreign detect XDG-only (excludes brew sample `/opt/homebrew/etc/vector/vector.yaml`). DEVIATION ledgered D2. | `serverapps.py` `_vector_detect_paths` | **Accepted DEVIATION** — design notes M1 |
| S-5 | Style | R1 S-2 **fixed** in D2: typed `Refusal` + `_refusals_recoverable_with_force` (kind == `drifted`). | `serverapps.py` | **Closed** |
| S-6 | Style | Landing inject uses refusal kind `forced_own_foreign` for “inject not supported” (kind is a stretch). | `plan_landing` | **Defer M1-Q** — optional new kind `unsupported_mode` |
| S-7 | Style | Role defaults hardcode `serverapp_*_uid: "501"`; live path always passes `os.getuid()` via `-e`. Fine; defaults are misleading for non-501 CI sandboxes. | role `defaults/main.yml` | **Defer M1-Q** |
| S-8 | Style | `landing-discover` LaunchAgent has no `KeepAlive` (StartInterval only). After successful run, `launchctl print` shows `state = not running` with `last exit code = 0` and `run interval = 3600` — **expected**, not a failure. | live print; `landing-discover.plist.j2` | **Informational** — not a defect |

## Per-adapter review (design §1 / site-contract §5)

### D2 vector

1. **Fragments** — `stayturgid_*` component ids; site-sync manifest; multi
   `--config` args on unit (no copy); validates before activate.
2. **MF-1** — bootout + disable; live disabled; rollback needs `enable`.
3. **0.0.0.0:4318** — retained for fleet ingest (registry note).
4. **API health** — loopback `:8686/health` for own-mode probe (new port
   registered site-side).

### D3 openobserve

1. **Single-owner §5.3** — inject = zero file writes; own = unit only.
2. **Data dir** — fixed at `~/.local/share/openobserve/data` (verified live).
3. **Binary** — install-if-absent, never upgrade.
4. **MF-1** — cloned; live disabled.

### D4 landing

1. **Port footgun** — code default **8088**; caddy-health keeps 8080.
2. **Both agents** — `landing` (KeepAlive) + `landing-discover`
   (StartInterval); both site-namespace; both legacy labels disabled.
3. **Registry drift** — discover badges unregistered listeners when
   `STAYTURGID_SITE_DIR` + PyYAML available (`.venv-test` preferred).
4. **Inject** — correctly refused (product-internal).

## Live residual risks (post-R2)

- **F4** — second own-mode apply still runs ansible ensure: **accepted**
  (healing + health re-check; file actions skip).
- **F5-class** — control_node may re-render legacy observability plists;
  disabled DB prevents login re-arm; retirement is D7.
- **Do not** set `stayturgid_caddy_enabled: false` or wholesale
  observability disable before D7 if that deletes rollback plists.
- **Secrets in launchd env** — OO/vector plists may carry
  `ZO_ROOT_USER_PASSWORD` / `OPENOBSERVE_*` (mode 0644 LaunchAgent
  precedent from control_node). Pre-existing class; empty password live
  today. Not introduced as a D2–D4 regression; tighten at M1 if desired
  (load from env file with 0600).

## Evidence (this session)

- Site labels: `com.djbclark.{caddy,vector,openobserve,landing}` **running**;
  `landing-discover` loaded, interval 3600, last exit 0, state not running
  between runs (expected).
- Legacy: all five `com.stayturgid.{caddy,vector,openobserve,landing,landing-discover}`
  **unloaded** and **disabled**; plists still on disk.
- Health: caddy `/health` 200; HTTPS front door 200; vector `:8686/health`
  200; openobserve `/healthz` 200; landing `:8088/health` 200.
- Single listeners: 8080 caddy; 8088 Python landing; 4317/4318/8686 vector;
  5080/5081 openobserve.
- `PORT = 8088` in `landing.py`; OO data path unchanged.
- Second `just site-serverapps apps=vector` → skip,skip,ansible exit 0.
- No stayturgid product code change this session (review-only).

## Next

D5 — O-V-G-O completion under site ownership (VictoriaMetrics, Grafana,
OliveTin adapters) per step2 plan row D5.
