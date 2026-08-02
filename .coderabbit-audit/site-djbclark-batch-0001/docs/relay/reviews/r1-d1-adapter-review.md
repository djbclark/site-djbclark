# R1 — D1 first-adapter architecture review

**Date:** 2026-07-19
**Reviewer:** Claude Fable 5 (Medium effort) — FUND-B R1, correctness/safety
must-fix only; architecture/style deferred to ledger for M1.
**Scope:** stayturgid PR #17 → master `dc9ffaa` (impl `5055a93`); site
`a6cd64a`; G1 audit flags F1–F6
(`docs/relay/reviews/gate-debt-audit.md`). Judged against
`docs/design/phase-d-adapter-design-notes.md` §1 and stayturgid
`docs/architecture/site-contract.md` §5. No green suites re-run except where
code changed (per G1 handoff note 1).

## Verdict

D1 is a **sound template for D2–D5** with one must-fix safety defect (fixed
this session, stayturgid PR #19 → master `c9e21b7`) and a short deferred
list. G1's 0-failed table stands — nothing in it is a silent must-fix.

## Findings

| Id   | Severity              | Finding                                                                                                                                                                                                                                                                                                                                              | Refs                                                                                   | Disposition                                                                                                                                                                                                                                                                                                                                                                 |
| ---- | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| MF-1 | **Safety — must-fix** | `launchctl bootout` is session-scoped. Legacy `com.stayturgid.caddy.plist` was retained in `~/Library/LaunchAgents` with `RunAtLoad`+`KeepAlive` true and its label **absent from launchd's disabled DB** — at next login both caddies would bootstrap and fight for 80/443/8080; loser crash-loops; front-door state after reboot nondeterministic. | `serverapp_caddy/tasks/main.yml`; verified live via `launchctl print-disabled gui/501` | **FIXED** — PR #19 → `c9e21b7`: role now persistently disables the legacy label whenever its plist remains on disk (heals already-migrated machines on next apply). Applied live: label shows `disabled`, `com.djbclark.caddy` running, /health 200, HTTPS 200, second apply exit 0. Rollback amended (needs `launchctl enable` first) in design notes §1.9 + role comment. |
| A-1  | Architecture          | Own-mode base Caddyfile (`~/.config/<ns>/caddy/Caddyfile`) is re-templated unconditionally; a hand edit there is clobbered without exit 2 (plan does surface `overwrite` vs `skip`). Consistent with control_node precedent (product-owned area), but drift-refusal parity with inject copies is worth considering.                                  | `serverapps.py:345-363`; role `Render own-mode base Caddyfile`                         | **Defer to M1-R.**                                                                                                                                                                                                                                                                                                                                                          |
| A-2  | Architecture          | Design §1.4's "foreign config present when site-map forces own → exit 2" is implemented narrowly: refuses only when site-map `config:` points at the foreign file (i.e. own would actually overwrite it). Forced-own beside an unrelated foreign config proceeds and would fail at bind/health time (exit 1) leaving a KeepAlive-looping agent.      | `serverapps.py:307-322`                                                                | **Defer to M1-R** — defensible reading of "would touch user-owned content"; not live-reachable (no site-map, no foreign config). D2 should pre-check port availability or the design row be clarified.                                                                                                                                                                      |
| A-3  | Architecture          | Inject default `fragment_dir` is the committed `generated/…/fragments/caddy/` itself (copies degenerate to no-ops; import line points at generated). Coherent with the no-copy principle but deviates from §5.3 "auto-detect include location"; undocumented.                                                                                        | `serverapps.py:192-196`                                                                | **Defer to M1-R** (document or implement real auto-detect when an inject-mode site exists).                                                                                                                                                                                                                                                                                 |
| S-1  | Style                 | Dead constant `DEFAULT_CADDY_DETECT_PATHS` (unused; `_caddy_detect_paths` recomputes with XDG).                                                                                                                                                                                                                                                      | `serverapps.py:53-56`                                                                  | **Defer (M1-Q).**                                                                                                                                                                                                                                                                                                                                                           |
| S-2  | Style                 | Exit-2 recoverability gated by substring match `"drifted" in message`, duplicated in `apply_plan` and `run_site_serverapps`. Traced correct today (user-owned refusals never contain "drifted") but fragile; D2 should use a typed refusal kind.                                                                                                     | `serverapps.py:597-604,786-790`                                                        | **Defer (M1-Q); carry note to D2.**                                                                                                                                                                                                                                                                                                                                         |
| S-3  | Style                 | Role `Caddyfile.j2` header lacks real `product_version`/`commit` values (§1.7 format); marker string present so detection works.                                                                                                                                                                                                                     | role `templates/Caddyfile.j2:3`                                                        | **Defer (M1-Q).**                                                                                                                                                                                                                                                                                                                                                           |
| S-4  | Style                 | `_materialize_caddy_own_for_tests` duplicates the role's templates inside the product module (divergence risk); plus no-op `set_fact` self-assignment task in the role.                                                                                                                                                                              | `serverapps.py:658-721`; role task 1                                                   | **Defer (M1-Q).**                                                                                                                                                                                                                                                                                                                                                           |

## G1 flag dispositions (F1–F6)

| Flag | Classification     | Disposition                                                                                                                                                                                                                                                                                                                                                       |
| ---- | ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F1   | Architecture       | site `registry/paths.yml` step1 schema: only consumers are site `bin/registry_lint.py` (passes) and site-sync's best-effort render context (safe_load; unused by the caddy fragment). No correctness/safety impact. **Defer to M1**; migrate when a consumer needs seed-format paths. Not re-opened drive-by per baton.                                           |
| F2   | Closed             | Stale C6 residual text; D1 justfile exports fixed it. No action.                                                                                                                                                                                                                                                                                                  |
| F3   | Closed             | Historical lychee CI flake; current master CI green (and green again on `c9e21b7`, run below). No action.                                                                                                                                                                                                                                                         |
| F4   | Accepted DEVIATION | Second own-mode apply re-invoking the ansible ensure is judged **sound**: §1.4 idempotence holds (exit 0, file actions all skip, ansible tasks no-op), and the ensure gives validate + health verification + daemon healing on every apply — MF-1's heal-on-next-apply relies on exactly this. Fold into design notes at M1.                                      |
| F5   | Mitigated by MF-1  | control_node `agents.yml` re-rendering `com.stayturgid.caddy.plist` no longer re-arms the label at login (disabled DB is keyed by label, survives file re-render; agents.yml never bootstraps it when enabled). Residual: do **not** set `stayturgid_caddy_enabled: false` before D7 — that path deletes+unloads the rollback plist; it is D7's retirement lever. |
| F6   | Style              | No site-map.yml → `mode=own (source=default)` matches spec §5.2 and is printed/auditable. Optional explicit `serverapps.caddy.mode: own` pin deferred; don't churn.                                                                                                                                                                                               |

## D1 architecture review proper (design §1 / site-contract §5)

1. **Mode selection** — conforms: site-map → foreign detect → own; detect
   excludes `~/.config/{stayturgid,<site_ns>}/` and generated-headered files;
   resolved mode+source printed; exit 0/1/2 match §1.4 (incl. dry-run
   reporting exit 2 on refusals). Bare-`off` YAML 1.1 coercion (D1 DEVIATION)
   is handled safely: `False`→`"off"`, bare `true`/`on` rejected with a clear
   error — **accepted**.
2. **Two-layer split** — conforms: fragment is an ordinary `sync_manifest.yml`
   entry rendered by site-sync (ports from registry, StrictUndefined);
   `serverapps.py` plans-then-acts and delegates own-mode lifecycle to the
   `serverapp_caddy` role; base config imports fragments **directly from
   committed `generated/`** (no copy step, single writer).
3. **launchd namespace** — conforms: `com.<site_ns>.caddy` from the
   `site_ns` site fact (validated identifier; no hard-coded site name in
   product); validate-before-activate ordering correct (validate precedes
   plist/bootstrap); legacy plist retained; rollback documented — now
   corrected for the disable step (MF-1).
4. **Live residual risks** — see F4/F5 dispositions; post-fix live state:
   legacy label disabled + unloaded, plist on disk, new label running,
   health + HTTPS 200.
5. **Clone-safety for D2 (vector)** — copy: mode-resolution frame
   (`resolve_app_mode` + site_map keys), exit-code plumbing, plan/apply
   skeleton + refusal semantics, role shape (brew-if-absent → dirs → config
   template → validate → plist → probe/bootstrap/kickstart → legacy bootout
   **+ persistent disable** → health wait), justfile recipe pattern, test
   shape (12 tests in `test_serverapps.py`). Caddy-specific: import-line
   verification (vector instead gets extra `--config` glob args in its
   plist), detect paths, health URL, hostname facts. D2 gotchas: vector is
   currently control_node-managed under `com.stayturgid.vector` — same
   bootout+disable migration applies; component ids must be
   `stayturgid_`-prefixed; `KNOWN_APPS`/`plan_caddy` are caddy-hardcoded, so
   D2 adds per-app dispatch (keep S-2's typed-refusal note in mind).

## Evidence (this session)

- `launchctl print-disabled gui/501` → `"com.stayturgid.caddy" => disabled`
- `launchctl print gui/501/com.djbclark.caddy` → state = running; legacy
  label not loaded; legacy plist still on disk
- `curl http://127.0.0.1:8080/health` → 200; `curl https://mac.greyhound-sidemirror.ts.net/` → 200
- `just site-serverapps mode=apply apps=caddy` exit 0 twice (second run:
  disable task skips)
- stayturgid `just check` → RESULT: PASS (code), exit 0; ansible-lint
  production profile passed on the caddy playbook+role
- PR #19 merged → master `c9e21b7`; branch deleted; checkout on pulled master
