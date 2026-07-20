# Step 2: Junior-developer execution plan (Phases B–F + AI stack)

**Audience:** junior-developer-level AI agents executing the remaining
segmentation work. A frontier model designed this plan and the specs it
references; your job is implementation, not architecture.
**Authored:** 2026-07-18. Difficulty is 0–100 from a junior-AI perspective
(higher = more context, more judgment, more ways to silently break things).

## 0. Ground rules (read before every step)

1. **Do not make architecture decisions.** Anything in stayturgid
   `platform-architecture.md` §11, anything touching trust/secrets design,
   and anything this plan marks **OPERATOR GATE** requires the operator.
   If a spec seems wrong, stop and report; do not improvise.
2. **Specs are authoritative:** stayturgid `docs/architecture/site-contract.md`
   (site contract + serverapp adapters), `docs/architecture/adr/005-two-repo-topology.md`,
   this repo's `docs/plans/site-djbclark-step1-segmentation-architecture-v1.md`,
   and `registry/*.yml` (ports/paths authority — check before allocating
   anything; run `bin/registry_lint.py` after editing).
3. **Layout is permanent:** `~/ops/stayturgid` (public product),
   `~/ops/site-djbclark` (private site). Never nest a private repo inside a
   public working tree. Never commit secrets; `secretspec.toml` declares,
   providers store.
4. **stayturgid conventions:** `git fetch origin --prune && git pull --ff-only
origin master` before editing; pre-commit hooks must pass (prettier,
   markdownlint, ansible-lint, typos); branch + PR for every change; read
   `AGENTS.md` + `.cursor/rules/` on session start; end sessions per
   `docs/handoff.md` protocol.
5. **Verify like an operator:** after any launchd/daemon change, curl the
   health endpoint and `launchctl list` the label. After any Ansible change,
   run the relevant `just dryrun-*` / `--check` first. A step is done when
   its acceptance check passes, not when the code exists.
6. **When stuck for >30 min or the diff sprawls beyond the step's file list:
   stop, write up findings, escalate** to the next model tier up.

## 1. Model routing

### 1.1 Difficulty bands → capability tiers

**Note (2026-07-20):** Claude Fable 5 is no longer part of either Claude Pro
plan and is very expensive per-use — do not route to it below unless
nothing else will work. Use Sonnet 5 (`xhigh` effort), Opus 4.8, or
`/code-review ultra` in its place for the 70–100 band.

| Band   | Tier to use                                   | Examples                                                                                                                  |
| ------ | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| 70–100 | Frontier, max effort.                         | Sonnet 5 (`xhigh`), Opus 4.8; final reviews via `/code-review ultra`                                                      |
| 55–69  | Frontier at normal effort or top coding agent | Opus 4.8, Codex (high reasoning), Grok 4 (thinking), Gemini 3 Pro                                                          |
| 40–54  | Strong workhorse                              | Sonnet 5, Codex (medium), Cursor composer, Copilot premium (Sonnet/GPT-5 class), DeepSeek R1 for research-shaped subtasks |
| 0–39   | Cheap/fast                                    | Haiku 4.5, Codex (low), Copilot chat, Gemini Flash, DeepSeek V3, Cursor auto                                              |

### 1.2 Current-quota snapshot (2026-07-19, post-D6 — regenerate with `codexbar usage --format json --provider all` before big runs; it takes ~90 s, run it to a file in the background, never pipe through `head`)

Operator-confirmed correction 2026-07-19: codexbar's `claude` row can lag the
original account — the operator's in-app numbers win when they conflict. New
second-Pro Claude account does not appear in codexbar yet (it will later).

- **Prefer now (operator steer 2026-07-19):** Codex, Cursor, and Antigravity
  carry the room; Grok has room too but is already the regular workhorse —
  spread load off it when Codex/Cursor fit.
- **Codex Plus** (djbclark@gmail.com): weekly 71% used (resets Jul 25
  ~5:17 PM), pace warns 59% deficit / "runs out in 8h" at burst rate, BUT
  386.5 credits banked cushion overruns. Good primary for 40–69 band; don't
  chain many sessions without a recheck.
- **Cursor** (monthly, resets Aug 2): two pools roughly half left (58% and
  51% used); one pool exhausted. Good secondary for agentic/multi-file work
  (Composer 2.5, Grok 4.5, or API-pool models).
- **Antigravity:** primary pool 47% used (refreshes ~2 d); secondary pool
  99.5% used — usable again for the primary-pool models.
- **Copilot premium:** ~11% used — abundant for 40–54 band.
- **Grok Supergrok:** 45% used — healthy, but regularly drawn on; treat as
  alt, not default.
- **Claude original account** (djbclark@gmail.com, operator-reported
  2026-07-19, overrides codexbar): session 44% used (resets ~4 h); all
  models weekly 52% used, **Fable 5 weekly 74% used** — Fable 5 is available
  on this account again but thin (resets Fri 5:59 AM). **Claude new
  second-Pro account:** ~70% of Fable weekly left — still the preferred
  account for Fable sessions (reviews, design, escalations).
- **Avoid:** OpenCode Go (weekly 100%, monthly 92% used), Warp (0 credits —
  flipped back to avoid), Zed (predictions only). DeepSeek API ($4.99) and
  OpenRouter remain cheap overflow; Poe for second opinions.
- Rule of thumb: **route by band first, then pick the cheapest tool in that
  band with quota.** Escalate one band on the second failed attempt. Right
  now that means: Codex/Cursor/Copilot for anything below the 70+ band,
  Grok as alternate, Fable 5 escalations on the new account first (original
  account's 26% Fable remainder is the backup).

## 2. Technical risk register (senior findings — do not rediscover these)

| Risk                                                                                                                  | Guidance                                                                                                                                                                                               |
| --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| LiteLLM `auto_router/complexity_router` is **Auto Router v2**, shipped in v1.94.x whose first release cut 2026-07-14  | `uv tool install "litellm[proxy]"` must pin `>=1.94`. If the config is rejected, your LiteLLM is too old — do NOT rewrite the config to older syntax. Docs: docs.litellm.ai/docs/proxy/auto_routing    |
| step0 model ID `claude-sonnet-4-20250514` is stale                                                                    | Use current model IDs at implementation time (e.g. `claude-sonnet-5`); check docs.claude.com                                                                                                           |
| MCP package names in step0 (`@shortwave/mcp-server`, `@saner-ai/mcp-server`, `fieldy_mcp`) are **unverified guesses** | Research each vendor's real MCP offering first; some may not exist — report absences to the operator instead of substituting lookalikes (typosquat risk)                                               |
| Goose config path/format varies by version (`~/.config/goose/config.yaml` vs profiles.yaml/json)                      | Check the installed version's docs before templating                                                                                                                                                   |
| landing.py code default port is 8080 (collides with Caddy health); plist passes 8088                                  | Fixed as part of D4 — change the code default to 8088                                                                                                                                                  |
| The two landing plists are hand-managed today (not Ansible)                                                           | D4 makes them Ansible-managed; until then do not "fix" them by hand again. (vector/openobserve are NOW Ansible-managed via the merged `observability.yml` — this row is landing-only since 2026-07-18) |
| `just validate-identity` runs warn-only with 193 known violations                                                     | Do not flip to hard-fail before B5 completes; do not "fix" violations drive-by outside B5's PRs                                                                                                        |
| Virtualenvs embed absolute interpreter paths                                                                          | `.venv-test` broke when the repo moved to `~/ops` (rebuilt); if a venv errors with "bad interpreter", `rm -rf` it and rerun `just test-venv` — never edit shebangs by hand                             |
| Devices are frequently offline (see landing state)                                                                    | Any step needing device contact: check reachability first; if offline, do the control-node half and record the device half in handoff.md as pending                                                    |

## 2.5 Branch consolidation status (2026-07-18, post-merge)

All prior work branches are merged into stayturgid master (merge commits
`9651a45`, `e54c894`, `fb797aa`, `f199000`); old worktrees/checkouts are
deleted. What this changes for the steps below:

- **Done — identity SSoT (was platform-arch Phases 0–2):**
  `control/lib/site_identity.py` + `control/bin/validate_site_identity.py` +
  `just validate-identity` (in `just check`/CI, **warn-only**, 193 known
  violations); `cf-runagent.cf` templated from inventory; `peers.json.j2`
  ssh_user, peer-bootstrap `--ssh-user`, adb path defaults, and the Play
  email default all de-hardcoded.
- **Done — observability infra (was logging Phase 1):** vector + openobserve
  are now **Ansible-managed** (`ansible/roles/control_node/tasks/observability.yml`
  - plist/config templates) under `com.stayturgid.*` labels. Supersedes part
    of the "hand-managed" risk row (landing is still hand-managed).
- **Done — on-device structured logging (was logging Phase 2):** `log.js`,
  `stayturgid_repair.py`, `control/lib/logging.py` dual-write JSONL + atomic
  `state.json`; JS/Python tests merged and passing (full `just test` green).
- **Done — just standardization:** `_impl`/`-legacy`/positional-host recipe
  pattern across `just/fleet.just`; conventions in `docs/just_standards.md`.
- **Plan-only (NOT implemented):** edge OTel collector on Termux
  (`docs/operations/plans/logging/` 01/02 done, Phase-3 otelcol rollout
  pending → new step D8 below). stayturgid-internal roadmap
  (platform-architecture §10) Phases 3–7 map to: P3→D5, P4→D8 (otelcol
  supersedes "edge Vector"), P5→D7, P6→B3+B5, P7→§11 #4/5 (operator).

## 3. Phase B — inventory moves to the site repo

**Goal:** stayturgid upstream carries no production identity; this repo's
`inventory/` is the live inventory (multi-site-topology §4 Phases 1–3).

| #   | Step                                                                                                                                                                                                                                                                                                             | Difficulty | AI                                                                                                             | Notes                                                                                                                        |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| B1  | Create `inventory/` here: copy live `hosts.yml` + `group_vars/stayturgid.yml` from stayturgid; add site `ansible.cfg` (inventory here, `collections_path` → `~/ops/stayturgid/.ansible/collections` + `ansible_collections/`); add thin `justfile` wrapper exporting `ANSIBLE_CONFIG`                            | 45         | Codex (high) or Sonnet 5                                                                                       | Verify: `ansible-inventory --list` from this repo matches the one from stayturgid byte-for-byte (normalize with `jq -S`)     |
| B2  | stayturgid: ensure `hosts.yml.example` matches §4.4 generic names; change `ansible.cfg` per §4.7 (no default production inventory); CI copies example before syntax check                                                                                                                                        | 50         | Codex (high); escalate CI wiring to Fable 5 low if the GitHub Actions matrix fights back                       | Verify: fresh clone + `just check` passes with no live identity present                                                      |
| B3  | Move operator docs: `docs/handoff.md` live content + `human/*` → this repo (`docs/handoff.md`); leave upstream stub pointing at multi-site-topology §4                                                                                                                                                           | 30         | Haiku 4.5 or Copilot chat                                                                                      | Pure moves + link fixes; markdownlint will police                                                                            |
| B4  | Update deploy tooling: `deploy_fleet.py` / justfile accept external `ANSIBLE_CONFIG` (§4.8 Phase 3); default to site repo when present                                                                                                                                                                           | 55         | Fable 5 (low) or Codex (high)                                                                                  | Touches the deploy path — `just dryrun-termux` + one real `just deploy hosts=<online device>` **OPERATOR GATE** before merge |
| B5  | Scrub pass per §4.6 — the code fixes (`peers.json.j2`, peer-bootstrap, `cf-runagent.cf`, adb defaults) are **already merged**; remaining work is the 193 violations `just validate-identity` reports (docs, tests, tools). Exit criterion: flip validate-identity from warn-only to hard-fail in `just check`/CI | 55         | Fable 5 (medium) — needs judgment about historical docs vs active code; the validator's report is the worklist | Do in 2–3 PRs by area; tests keep example fixtures (RFC 5737 / §4.1 names)                                                   |

**Phase-end review:** Sonnet 5 reads the diff series; `/code-review ultra` if
B5 touched >40 files.

## 4. Phase C — site contract implementation (in stayturgid)

**Spec:** `docs/architecture/site-contract.md` — follow it exactly; its §8
acceptance tests are the definition of done. Suggested order: C1 scaffolding
templates → C2 `site-init` → C3 `site-sync`+lockfile → C4 site-map → C5
Entangled wiring → C6 this repo re-inits as reference consumer.

| #   | Step                                                                                                                  | Difficulty | AI                                                                                                                                                                                                            | Notes                                                                               |
| --- | --------------------------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| C1  | `control/site_contract/templates/` (site README, ansible.cfg, justfile, gitignore, registry seeds from role defaults) | 40         | Codex (medium) / Copilot premium — Claude quota tight, save Sonnet 5 for after reset                                                                                                                          | Registry seeds must derive from role defaults programmatically, not copied literals |
| C2  | `site-init` (apply/dry-run/docs modes, exit codes per spec §2)                                                        | 55         | Codex (high) or Grok 4 (thinking) — escalate to Fable 5 (low) only after Claude session/weekly resets                                                                                                         | Acceptance tests 1, 2, 6                                                            |
| C3  | `site-sync` + lockfile semantics (spec §4)                                                                            | 65         | Grok 4 (thinking) or Codex (high) now; the drift/hash/delete semantics have sharp edges and genuinely want Fable 5 (medium) judgment — schedule this step after the Claude session/weekly reset if not urgent | Acceptance test 3                                                                   |
| C4  | `site-map.yml` support (spec §6, fail-closed unknown keys)                                                            | 45         | Codex (medium)                                                                                                                                                                                                | Acceptance test 4                                                                   |
| C5  | Entangled: `SITE-CONTRACT.md` literate doc tangling into C1 templates + CI check                                      | 55         | Grok 4 (thinking) or Gemini 3 Pro — good doc-shaping models, both have quota; wire CI with Codex (low) instead of Fable 5 while Claude is rationed                                                            | Keep scope: contract only (step1 §6)                                                |
| C6  | Re-init this repo via the contract (adopt generated/ area + lockfile without clobbering existing content)             | 50         | Copilot premium (Sonnet-class) or Cursor composer — reserve actual Claude Sonnet 5 for after reset                                                                                                            | Dry-run first; diff against current tree must be explainable line-by-line           |

**Phase-end review:** Fable 5 (Max) or `/code-review ultra` — this is the
public interface others will depend on.

## 5. Phase D — shared-infra handover (serverapp adapters)

**Spec:** site-contract.md §5. Order matters: D1 caddy (front door) → D2
vector → D3 openobserve → D4 landing → D5 O-V-G-O completion → D6 fragments
→ D7 close-out. Every daemon migration: registry first, adapter role, deploy,
verify health, only then remove the old `com.stayturgid.*` label.

| #   | Step                                                                                                                                                                                                                                                                                                                                                         | Difficulty | AI                                                                                                                                                                                                    | Notes                                                                                                                                    |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | caddy adapter (own+inject modes, import-line verification) + migrate instance to `com.djbclark.caddy`                                                                                                                                                                                                                                                        | 60         | Grok 4 (thinking) or Codex (high) now — first-adapter judgment genuinely wants Fable 5 (medium); schedule after Claude reset if timing allows                                                         | **OPERATOR GATE** (public-facing 443). Keep old label until new one serves TLS                                                           |
| D2  | vector adapter: start from the merged `observability.yml` + `vector.yaml.j2` (already Ansible-managed); split into product-prefixed fragment components (`stayturgid_*` ids) and relabel to site namespace                                                                                                                                                   | 45         | Codex (high)                                                                                                                                                                                          | 0.0.0.0:4318 stays (fleet ingest) — registry already documents why                                                                       |
| D3  | openobserve adapter: start from merged `observability.yml` + `openobserve.plist.j2`; relabel to site namespace (single-owner, §5.3)                                                                                                                                                                                                                          | 40         | Copilot premium / Codex (medium) — hold Sonnet 5 for after reset                                                                                                                                      | Data dir migration: verify parquet dir path unchanged; secretspec already declares OPENOBSERVE_ROOT_PASSWORD                             |
| D4  | landing: code default port 8080→8088; Ansible-manage both landing plists; add registry drift check to `landing-discover` (diff live scan vs `registry/ports.yml`, badge unregistered listeners)                                                                                                                                                              | 45         | Codex (medium)                                                                                                                                                                                        | Closes the hand-managed-plist gap and the 8080 footgun                                                                                   |
| D5  | Complete O-V-G-O (= stayturgid roadmap P3, executed under **site** ownership per ADR 005 — not under stayturgid labels as that roadmap assumed): install VictoriaMetrics (8428), Grafana (3000), OliveTin (1337) via adapters under site labels; Grafana datasources provisioned from registry endpoints; "Fleet Control Room" dashboard                     | 55         | Codex (high); Grafana provisioning YAML is fiddly — DeepSeek R1 is fine for drafting dashboards                                                                                                       | OpenObserve already running/managed (D3). Ports already registered. OliveTin config is a projection (spec §5.3)                          |
| D6  | stayturgid tenant fragments: Grafana fleet dashboard, OliveTin actions (`just deploy hosts=X` etc.), Caddy route fragment; generated from inventory via site-sync                                                                                                                                                                                            | 60         | Grok 4 (thinking) or Codex (high) now; genuinely wants Fable 5 (medium) judgment for the inventory→projection blast radius — schedule after Claude reset if not urgent                                | OliveTin shell env propagation per ovgo plan §Phase-3 warning                                                                            |
| D7  | Retire legacy (= stayturgid roadmap P5): `dashboard.py`, `fleet_health_monitor.py`, `access_monitor.py` + plists once Grafana panels cover them; repoint `just health` at VictoriaMetrics/Grafana; update registry (4097 retired); close §11 #9 (Caddy route naming) with operator                                                                           | 50         | Copilot premium / Cursor composer — hold Sonnet 5 for after reset                                                                                                                                     | **OPERATOR GATE** — deletes working monitors; needs operator sign-off that O-V-G-O coverage is adequate                                  |
| D8  | Edge OTel collector rollout (= roadmap P4, per `docs/operations/plans/logging/` Phase-3 design): `termux_userland` deploys `otelcol-contrib` linux_arm64 via Mac-side download cache; `otel-config.yaml.j2` tails `repair.jsonl`/`watchdog.jsonl` with memory_limiter 100MB, batch 30s, OTLP HTTP to the Mac's Vector (4318); `start-otelcol.sh` boot script | 60         | Grok 4 (thinking) or Codex (high) for the role work now; devices frequently offline — deploy to one reachable device first; escalate to Fable 5 (medium) after reset if the fleet rollout gets gnarly | **OPERATOR GATE** for fleet-wide deploy. Verify: logs from a device appear in OpenObserve search (5080) after an offline/reconnect cycle |
| D9  | Logging Phase-2 close-out: verify dual-write (`*.log` + `*.jsonl`) and `state.json` behavior on-device; confirm `scrape_errors` parses both formats; record any Fire OS path deviations                                                                                                                                                                      | 30         | Codex (low) / Copilot chat — skip Haiku 4.5 for now, it shares the rationed Claude pool                                                                                                               | Mostly verification + small fixes; tests already merged                                                                                  |

**Phase-end review:** `/code-review ultra` on the stayturgid adapter series;
operator smoke-tests every web UI through Caddy.

## 6. Phase E — AI stack (roles in this repo)

Follow step0 **as amended** (header note + risk register above).

| #   | Step                                                                                                                                                                     | Difficulty | AI                                                                                                                                                   | Notes                                                                                                         |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| E1  | `roles/litellm`: uv tool install (pin ≥1.94), config template (Auto Router v2 syntax verified against docs), `com.djbclark.litellm` plist, secretspec entries, port 4000 | 50         | Codex (high); verify router config against live docs, not memory                                                                                     | Verify: `curl :4000/v1/models`; a SIMPLE and a REASONING prompt route to different tiers (check LiteLLM logs) |
| E2  | `roles/goose`: brew cask + CLI, provider config pointed at `http://127.0.0.1:4000` model `smart-router`                                                                  | 40         | Copilot premium — hold Sonnet 5 for after reset                                                                                                      | Config path per installed version (risk register)                                                             |
| E3  | MCP servers for Goose: research real packages (Shortwave, Saner.ai, Fieldy, filesystem), template extensions config                                                      | 55         | Grok 4 (thinking) or DeepSeek R1 for the research; Codex for the templating                                                                          | Report nonexistent servers to operator; **never install a guessed package name**                              |
| E4  | First-run + human steps doc ("API Keys – Human Step" checklist per step0 §5/§7)                                                                                          | 25         | Copilot chat / Gemini Flash / DeepSeek V3 — Haiku 4.5 shares the rationed Claude pool, skip it for now                                               | **OPERATOR GATE**: operator enters keys + MCP auth                                                            |
| E5  | Extend to mac mini (Intel: `/usr/local` prefix — stayturgid's `stayturgid_homebrew_prefix` pattern is the reference) and VPSs (systemd user units instead of launchd)    | 60         | Grok 4 (thinking) or Codex (high) for the cross-platform refactor now; escalate to Fable 5 (medium) after the Claude reset if it needs more judgment | New hosts enter `inventory/` + `registry/ports.yml` first                                                     |

## 7. Phase F — adopt unmanaged machine services

| #   | Step                                                                                                                                                | Difficulty | AI                                                                                                                                                                                 | Notes                                              |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| F1  | `system-state-backup` + `hibernate-disk-check` scripts + plists → site roles (files into this repo, plists templated)                               | 30         | Codex (low) / Copilot chat — skip Haiku 4.5, it shares the rationed Claude pool                                                                                                    | Scripts live in `~/.local/bin` today               |
| F2  | brew-services audit: postgres@14 (currently failing, exit 78), redis, mariadb, herdr, omlx — per service: needed? adopt (registry + role) or remove | 40         | Copilot premium / Codex (medium) for the audit doc — hold Sonnet 5 for after reset; **OPERATOR GATE** for each keep/kill decision                                                  | Update `registry/paths.yml` brew_services claims   |
| F3  | Immich LaunchDaemon (system domain, dedicated user at /opt/services/immich) → site role                                                             | 55         | Grok 4 (thinking) or Codex (high) now — system-domain launchd + service user is unforgiving and genuinely wants Fable 5 (low) judgment; do after the Claude reset if timing allows | Port registration for immich web                   |
| F4  | Merged-Brewfile projection + `flock` serialization wrapper in the site justfile (step1 §4.3)                                                        | 45         | Codex (medium)                                                                                                                                                                     | Compare against `~/system-state/Brewfile` snapshot |

## 8. Standing verification (every PR, both repos)

- `bin/registry_lint.py` (this repo) — wire into pre-commit here (difficulty
  15, Haiku); stayturgid CI gains a job that checks its role-default ports
  against a checked-in copy of its own claims (difficulty 35, Codex medium).
- stayturgid: `just check && just lint && just test`.
- Anything touching a daemon: health-curl + `launchctl print` evidence pasted
  into the PR.

## 9. Session chaining

Work proceeds via the relay protocol: `docs/relay/PROTOCOL.md` defines the
baton (`docs/relay/NEXT-PROMPT.md` — always the next prompt to paste, with
its recommended AI) and the ledger. Every session ends by regenerating the
baton for the next step from this plan.

## 10. Escalation & final review

- Two failed attempts at a step → escalate one band; a step that grows beyond
  its listed files → stop and split.
- Each phase ends with the review noted above; the **project-level final
  review** (all phases) is a frontier senior pass: `/code-review ultra` per
  repo, or Sonnet 5 at `xhigh` effort reading step1 + this doc + the diffs
  (**not Fable 5** — no longer part of either Claude Pro plan and very
  expensive per-use as of 2026-07-20; only use it if nothing else works).
