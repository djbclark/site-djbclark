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

| Band | Tier to use | Examples |
| --- | --- | --- |
| 70–100 | Frontier, max effort. | Claude Fable 5 (Max); final reviews via `/code-review ultra` |
| 55–69 | Frontier at normal effort or top coding agent | Fable 5 (medium/low), Opus 4.8, Codex (high reasoning), Grok 4 (thinking), Gemini 3 Pro |
| 40–54 | Strong workhorse | Sonnet 5, Codex (medium), Cursor composer, Copilot premium (Sonnet/GPT-5 class), DeepSeek R1 for research-shaped subtasks |
| 0–39 | Cheap/fast | Haiku 4.5, Codex (low), Copilot chat, Gemini Flash, DeepSeek V3, Cursor auto |

### 1.2 Current-quota snapshot (2026-07-18 — recheck with CodexBar before big runs)

- **Abundant now:** Codex Plus (100% weekly + credits) → default workhorse.
  Copilot premium (100%) → second workhorse. Grok Supergrok (94%) → good for
  55–69 band. DeepSeek API ($5) and OpenRouter ($18.90) → cheap overflow +
  research. Poe (300 pts) → occasional second opinions.
- **Ration:** Claude Pro (session-limited) → reserve Fable 5/Opus for 65+
  steps, escalations, and phase-end reviews; use Sonnet 5 sparingly, Haiku
  freely. Cursor (42%) → UI-adjacent or multi-file refactors only.
  Antigravity: Gemini pool only (54%); its Claude/GPT pool is empty.
- **Avoid:** Warp (0 credits), OpenCode weekly pool (exhausted; 5-hour pool
  only for bursts), Zed (predictions only, not agentic).
- Rule of thumb: **route by band first, then pick the cheapest tool in that
  band with quota.** Escalate one band on the second failed attempt.

## 2. Technical risk register (senior findings — do not rediscover these)

| Risk | Guidance |
| --- | --- |
| LiteLLM `auto_router/complexity_router` is **Auto Router v2**, shipped in v1.94.x whose first release cut 2026-07-14 | `uv tool install "litellm[proxy]"` must pin `>=1.94`. If the config is rejected, your LiteLLM is too old — do NOT rewrite the config to older syntax. Docs: docs.litellm.ai/docs/proxy/auto_routing |
| step0 model ID `claude-sonnet-4-20250514` is stale | Use current model IDs at implementation time (e.g. `claude-sonnet-5`); check docs.claude.com |
| MCP package names in step0 (`@shortwave/mcp-server`, `@saner-ai/mcp-server`, `fieldy_mcp`) are **unverified guesses** | Research each vendor's real MCP offering first; some may not exist — report absences to the operator instead of substituting lookalikes (typosquat risk) |
| Goose config path/format varies by version (`~/.config/goose/config.yaml` vs profiles.yaml/json) | Check the installed version's docs before templating |
| landing.py code default port is 8080 (collides with Caddy health); plist passes 8088 | Fixed as part of D4 — change the code default to 8088 |
| The two landing plists are hand-managed today (not Ansible) | D4 makes them Ansible-managed; until then do not "fix" them by hand again |
| `com.stayturgid.openobserve` runs from `~/.local/bin/openobserve` (manual binary), vector from brew | D3/D2 bring both under adapter roles; note current reality when migrating |
| Devices are frequently offline (see landing state) | Any step needing device contact: check reachability first; if offline, do the control-node half and record the device half in handoff.md as pending |

## 3. Phase B — inventory moves to the site repo

**Goal:** stayturgid upstream carries no production identity; this repo's
`inventory/` is the live inventory (multi-site-topology §4 Phases 1–3).

| # | Step | Difficulty | AI | Notes |
| --- | --- | --- | --- | --- |
| B1 | Create `inventory/` here: copy live `hosts.yml` + `group_vars/stayturgid.yml` from stayturgid; add site `ansible.cfg` (inventory here, `collections_path` → `~/ops/stayturgid/.ansible/collections` + `ansible_collections/`); add thin `justfile` wrapper exporting `ANSIBLE_CONFIG` | 45 | Codex (high) or Sonnet 5 | Verify: `ansible-inventory --list` from this repo matches the one from stayturgid byte-for-byte (normalize with `jq -S`) |
| B2 | stayturgid: ensure `hosts.yml.example` matches §4.4 generic names; change `ansible.cfg` per §4.7 (no default production inventory); CI copies example before syntax check | 50 | Codex (high); escalate CI wiring to Fable 5 low if the GitHub Actions matrix fights back | Verify: fresh clone + `just check` passes with no live identity present |
| B3 | Move operator docs: `docs/handoff.md` live content + `human/*` → this repo (`docs/handoff.md`); leave upstream stub pointing at multi-site-topology §4 | 30 | Haiku 4.5 or Copilot chat | Pure moves + link fixes; markdownlint will police |
| B4 | Update deploy tooling: `deploy_fleet.py` / justfile accept external `ANSIBLE_CONFIG` (§4.8 Phase 3); default to site repo when present | 55 | Fable 5 (low) or Codex (high) | Touches the deploy path — `just dryrun-termux` + one real `just deploy hosts=<online device>` **OPERATOR GATE** before merge |
| B5 | Scrub pass per §4.6 (production aliases/IPs out of active code; `peers.json.j2` `ssh_user`, `stayturgid_peer_bootstrap.py` defaults, `cf-runagent.cf` IPs → inventory-driven) | 60 | Fable 5 (medium) — this is the 177-file alias-census problem; needs judgment about historical docs vs active code | Do in 2–3 PRs by area; tests keep example fixtures |

**Phase-end review:** Sonnet 5 reads the diff series; `/code-review ultra` if
B5 touched >40 files.

## 4. Phase C — site contract implementation (in stayturgid)

**Spec:** `docs/architecture/site-contract.md` — follow it exactly; its §8
acceptance tests are the definition of done. Suggested order: C1 scaffolding
templates → C2 `site-init` → C3 `site-sync`+lockfile → C4 site-map → C5
Entangled wiring → C6 this repo re-inits as reference consumer.

| # | Step | Difficulty | AI | Notes |
| --- | --- | --- | --- | --- |
| C1 | `control/site_contract/templates/` (site README, ansible.cfg, justfile, gitignore, registry seeds from role defaults) | 40 | Sonnet 5 / Codex (medium) | Registry seeds must derive from role defaults programmatically, not copied literals |
| C2 | `site-init` (apply/dry-run/docs modes, exit codes per spec §2) | 55 | Codex (high) or Fable 5 (low) | Acceptance tests 1, 2, 6 |
| C3 | `site-sync` + lockfile semantics (spec §4) | 65 | Fable 5 (medium); the drift/hash/delete semantics have sharp edges | Acceptance test 3 |
| C4 | `site-map.yml` support (spec §6, fail-closed unknown keys) | 45 | Codex (medium) | Acceptance test 4 |
| C5 | Entangled: `SITE-CONTRACT.md` literate doc tangling into C1 templates + CI check | 55 | Grok 4 (thinking) or Gemini 3 Pro — good doc-shaping models; Fable 5 low to wire CI | Keep scope: contract only (step1 §6) |
| C6 | Re-init this repo via the contract (adopt generated/ area + lockfile without clobbering existing content) | 50 | Sonnet 5 | Dry-run first; diff against current tree must be explainable line-by-line |

**Phase-end review:** Fable 5 (Max) or `/code-review ultra` — this is the
public interface others will depend on.

## 5. Phase D — shared-infra handover (serverapp adapters)

**Spec:** site-contract.md §5. Order matters: D1 caddy (front door) → D2
vector → D3 openobserve → D4 landing → D5 O-V-G-O completion → D6 fragments
→ D7 close-out. Every daemon migration: registry first, adapter role, deploy,
verify health, only then remove the old `com.stayturgid.*` label.

| # | Step | Difficulty | AI | Notes |
| --- | --- | --- | --- | --- |
| D1 | caddy adapter (own+inject modes, import-line verification) + migrate instance to `com.djbclark.caddy` | 60 | Fable 5 (medium) first adapter sets the pattern | **OPERATOR GATE** (public-facing 443). Keep old label until new one serves TLS |
| D2 | vector adapter; split current monolithic `vector.yaml` into product-prefixed fragment components (`stayturgid_*` ids) | 55 | Codex (high) | 0.0.0.0:4318 stays (fleet ingest) — registry already documents why |
| D3 | openobserve adapter (single-owner, §5.3); brew-or-binary install decision goes to operator if brew formula unavailable | 45 | Sonnet 5 / Copilot premium | Data dir migration: verify parquet dir path unchanged |
| D4 | landing: code default port 8080→8088; Ansible-manage both landing plists; add registry drift check to `landing-discover` (diff live scan vs `registry/ports.yml`, badge unregistered listeners) | 45 | Codex (medium) | Closes the hand-managed-plist gap and the 8080 footgun |
| D5 | Install VictoriaMetrics (8428), Grafana (3000), OliveTin (1337) via adapters under site labels; Grafana datasources provisioned from registry endpoints | 55 | Codex (high); Grafana provisioning YAML is fiddly — DeepSeek R1 is fine for drafting dashboards | Ports already registered. OliveTin config is a projection (spec §5.3) |
| D6 | stayturgid tenant fragments: Grafana fleet dashboard, OliveTin actions (`just deploy hosts=X` etc.), Caddy route fragment; generated from inventory via site-sync | 60 | Fable 5 (medium) — inventory→projection templating with real blast radius | OliveTin shell env propagation per ovgo plan §Phase-3 warning |
| D7 | Retire legacy: `dashboard.py`, `fleet_health_monitor.py`, `access_monitor.py` + plists (ovgo plan Phase 1) once Grafana panels cover them; update registry (4097 retired); close §11 #9 (Caddy route naming) with operator | 50 | Sonnet 5 | **OPERATOR GATE** — deletes working monitors; needs operator sign-off that O-V-G-O coverage is adequate |

**Phase-end review:** `/code-review ultra` on the stayturgid adapter series;
operator smoke-tests every web UI through Caddy.

## 6. Phase E — AI stack (roles in this repo)

Follow step0 **as amended** (header note + risk register above).

| # | Step | Difficulty | AI | Notes |
| --- | --- | --- | --- | --- |
| E1 | `roles/litellm`: uv tool install (pin ≥1.94), config template (Auto Router v2 syntax verified against docs), `com.djbclark.litellm` plist, secretspec entries, port 4000 | 50 | Codex (high); verify router config against live docs, not memory | Verify: `curl :4000/v1/models`; a SIMPLE and a REASONING prompt route to different tiers (check LiteLLM logs) |
| E2 | `roles/goose`: brew cask + CLI, provider config pointed at `http://127.0.0.1:4000` model `smart-router` | 40 | Sonnet 5 / Copilot premium | Config path per installed version (risk register) |
| E3 | MCP servers for Goose: research real packages (Shortwave, Saner.ai, Fieldy, filesystem), template extensions config | 55 | Grok 4 (thinking) or DeepSeek R1 for the research; Codex for the templating | Report nonexistent servers to operator; **never install a guessed package name** |
| E4 | First-run + human steps doc ("API Keys – Human Step" checklist per step0 §5/§7) | 25 | Haiku 4.5 | **OPERATOR GATE**: operator enters keys + MCP auth |
| E5 | Extend to mac mini (Intel: `/usr/local` prefix — stayturgid's `stayturgid_homebrew_prefix` pattern is the reference) and VPSs (systemd user units instead of launchd) | 60 | Fable 5 (medium) for the cross-platform role refactor; Codex thereafter | New hosts enter `inventory/` + `registry/ports.yml` first |

## 7. Phase F — adopt unmanaged machine services

| # | Step | Difficulty | AI | Notes |
| --- | --- | --- | --- | --- |
| F1 | `system-state-backup` + `hibernate-disk-check` scripts + plists → site roles (files into this repo, plists templated) | 30 | Haiku 4.5 / Codex (low) | Scripts live in `~/.local/bin` today |
| F2 | brew-services audit: postgres@14 (currently failing, exit 78), redis, mariadb, herdr, omlx — per service: needed? adopt (registry + role) or remove | 40 | Sonnet 5 for the audit doc; **OPERATOR GATE** for each keep/kill decision | Update `registry/paths.yml` brew_services claims |
| F3 | Immich LaunchDaemon (system domain, dedicated user at /opt/services/immich) → site role | 55 | Fable 5 (low) — system-domain launchd + service user is unforgiving | Port registration for immich web |
| F4 | Merged-Brewfile projection + `flock` serialization wrapper in the site justfile (step1 §4.3) | 45 | Codex (medium) | Compare against `~/system-state/Brewfile` snapshot |

## 8. Standing verification (every PR, both repos)

- `bin/registry_lint.py` (this repo) — wire into pre-commit here (difficulty
  15, Haiku); stayturgid CI gains a job that checks its role-default ports
  against a checked-in copy of its own claims (difficulty 35, Codex medium).
- stayturgid: `just check && just lint && just test`.
- Anything touching a daemon: health-curl + `launchctl print` evidence pasted
  into the PR.

## 9. Escalation & final review

- Two failed attempts at a step → escalate one band; a step that grows beyond
  its listed files → stop and split.
- Each phase ends with the review noted above; the **project-level final
  review** (all phases) is a frontier senior pass: Fable 5 (Max) reading
  step1 + this doc + the diffs, or `/code-review ultra` per repo.
