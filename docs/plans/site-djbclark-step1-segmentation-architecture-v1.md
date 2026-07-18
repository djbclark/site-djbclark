# Step 1: Segmentation Architecture — stayturgid vs. site management

**Status:** Decided (operator decisions 2026-07-18); implementation phased below
**Machines in scope:** M1 MacBook Air (this machine — also the stayturgid
control node), Intel Mac mini, Linux VPSs
**Companion:** `site-djbclark-step0-plan-v1.md` (Goose + LiteLLM stack — see
§9 for revisions this document makes to it)

---

## 1. Context

`~/stayturgid` manages an Android fleet plus the Mac-side software needed for
that, but has accreted general machine management. Meanwhile general machine
services exist outside any config management (immich LaunchDaemon, postgres,
redis, `com.djbclark.system-state-backup`), and a new AI stack (Goose +
LiteLLM) is planned. Two Ansible/brew stacks will now manage the same
physical machine, so segmentation **and mutual visibility** (ports, files,
no duplicate services, no race conditions) must be designed, not hoped for.

stayturgid already designed most of the split for its own domain:

- `stayturgid/docs/architecture/multi-site-topology.md` §4 — public generic
  upstream + private site overlay (`stayturgid-site-<operator>`); Phase 1 is
  "create the private site repo."
- `stayturgid/docs/research/site-identity-source-of-truth-2026-07-14.md` —
  inventory is the sole authority; all machine-consumed derivatives are
  generated projections.
- `stayturgid/docs/architecture/platform-architecture.md` §11 — open operator
  decisions, including #1 (site overlay repo) and #9 (O-V-G-O ports/Caddy).

This document extends that two-layer design to three layers and records the
operator decisions that close stayturgid §11 items #1 and #9 (ownership half).

## 2. Operator decisions (2026-07-18)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Site repo shape | **One private site repo.** `site-djbclark` is the site overlay for stayturgid *and* the home of general machine management. One inventory covers all hosts. |
| 2 | Shared machine infra (Caddy, landing, O-V-G-O) | **Site owns the instances.** The role *code* ships in stayturgid (see decision 5); products are tenants contributing fragments. Ownership is mediated by the **site contract** (§5) so a stayturgid-only user without Ansible/brew knowledge can still bootstrap and update a site dir with one command. |
| 3 | New general-machine roles (Goose/LiteLLM) | ~~Public product repo now~~ **Superseded same day (see 5):** incubate as roles in this repo; extract to a public repo only if they mature into something others want. |
| 4 | Literate programming | **Yes, scoped**: the site contract documents are Entangled literate documents (§6). Product internals stay conventional. |
| 5 | Repo topology (finalized later 2026-07-18) | **Two repos, no third.** Industry research (Puppet control-repo + roles/profiles, Gruntwork modules/live, Flux/Argo app-vs-config repos, Ansible inventory separation) converges on exactly two repo kinds: public product + private site/control repo. Composition glue ships product-side (serverapp adapters, §5a) or site-side (thin wrappers) — never a middle repo. Shared-infra roles and site-contract tooling stay in stayturgid. |
| 6 | Base directory | **`~/ops`** — a plain directory (never itself a repo), user-configurable (`OPS_ROOT`), sibling checkouts: `~/ops/stayturgid`, `~/ops/site-djbclark`. **Private-inside-public nesting is forbidden** by the contract: an allowlist-.gitignore mistake, `git add -f`, or `git clean -ffdx` in a public working tree must never be able to touch site data. |

## 3. The three-layer model

```text
Layer 1 — PRODUCT repos (public, generic, reusable)
  stayturgid            Android fleet product + its control-node software,
                        the shared-infra roles it needs (caddy_gateway,
                        observability O-V-G-O, landing) as serverapp adapters
                        (§5a), and the site-contract tooling
      A product ships: roles/collections, defaults, tenant FRAGMENTS,
      and its own `site-init` / `site-sync` implementing the site contract.
      (Future products — e.g. an extracted AI stack — follow the same shape.)

Layer 2 — SITE repo (private, one per operator)      ← site-djbclark
      Single source of truth for site identity & allocation:
      - ONE Ansible inventory: android devices, macs, VPSs (groups scope stacks)
      - registry/: ports.yml, paths.yml, brew ownership
      - secrets declarations (secretspec pattern, per stack)
      - site playbooks composing products; operator docs; custom roles
      - AI-stack roles (litellm, goose) incubate here (decision 5) —
        the "site-modules" pattern from Puppet control repos
      - generated/<product>/ areas maintained by each product's site-sync

Layer 3 — MACHINE shared infrastructure (single owner + tenants)
      Site instantiates shared daemons (Caddy, landing, Vector aggregator,
      OpenObserve, VictoriaMetrics, Grafana, OliveTin) from product roles.
      Tenants contribute fragments only:
      - Vector conf.d source/transform snippets
      - Grafana dashboard provisioning dirs
      - Caddyfile import snippets (route fragments)
      - OliveTin action files (merged by projection)
      Rule: exactly one stack owns each daemon; everyone else is a tenant.
```

Why site owns Layer 3: the Mac mini and VPSs feed the same monitoring; the
android fleet is one data source among several. The reverse (stayturgid
owning your general-purpose monitoring) is the creep being reversed.

## 4. Coordination contracts (the visibility mechanisms)

1. **Port registry** — `registry/ports.yml` (seeded from live state, this
   repo). Authority for every listen port per host: owner, bind, purpose.
   Products keep *defaults* in role defaults; site inventory overrides; a
   lint script (pre-commit/CI in every repo) flattens effective config and
   fails on collision. Runtime complement: `landing-discover` diffs its live
   scan against the registry → "listening but unregistered" warnings.
2. **Namespace / path ownership** — `registry/paths.yml`. Prefix → owner;
   single writer per file; generated header on every projection; shared
   append-only files (`~/.ssh/authorized_keys`) touched only via per-stack
   marked blocks (stayturgid's ET block is the model).
3. **Brew** — idempotent and machine-global, so list overlap is harmless;
   risks are concurrent runs and cleanup ambiguity. Each stack declares
   formulae in vars; site generates one merged annotated Brewfile projection
   (visibility + safe `brew bundle cleanup`); a `flock` wrapper in the site
   justfile serializes playbook runs per host.
4. **Cross-stack facts** — endpoints one stack provides and another consumes
   (OpenObserve ingest URL, VictoriaMetrics remote_write, Caddy hostname)
   are declared once in site inventory and templated into both stacks. This
   matters more as the fleet moves pull-based: device configs need central
   endpoints, which are site facts, not product facts.
5. **Secrets** — the secretspec pattern stayturgid already uses, one
   `secretspec.toml` per stack, all declared (never valued) in git.

### Namespaces

| Prefix | Owner |
|--------|-------|
| `com.stayturgid.*` launchd, `~/.config/stayturgid/**`, `~/Library/Logs/stayturgid*` | stayturgid |
| `com.djbclark.*` launchd, `~/.config/djbclark/**` | site (already de facto: system-state-backup, hibernate-disk-check) |
| `homebrew.mxcl.*` | brew services; each label claimed by exactly one stack in `registry/paths.yml` |
| `com.<product>.*` (templated `{{ site_ns }}` default) | product roles instantiated by site |

## 5. The site contract (scaffolding + sync)

The mechanism that makes segmentation usable by others, not just us. Every
product ships tooling implementing a common **site contract spec**:

```text
<product> site-init SITENAME [--map site-map.yml] [--docs-only] [--dry-run]
<product> site-sync            [--docs-only] [--dry-run]
```

- **`site-init`** generates `site-SITENAME/` for a user who may know nothing
  about Ansible or brew: inventory skeleton, registry seeded with the
  product's port/path claims, `ansible.cfg` wired to the product checkout,
  justfile wrappers, bootstrap script (installs brew/ansible under the hood),
  README. The tool hides Ansible/brew; it does not avoid them.
- **`site-sync`** re-renders the *product-facing* portion of an existing site
  dir from the currently installed product version. Generated content lives
  under `generated/<product>/` (or marked blocks), never hand-edited; a
  lockfile records the product version last synced. User-owned areas are
  never touched — the site dir is explicitly for the user's custom stuff
  too, including stuff sharing the product's back-end infra (tenant
  fragments are part of the contract).
- **`--docs-only`** emits the human-readable document describing exactly what
  would be created and the manual steps — for users who refuse automation.
  With Entangled (§6) this is nearly free: the contract *is* a document.
- **`--dry-run`** lists actions without performing them.
- **`site-map.yml`** — for users with an existing Ansible layout: maps the
  locations the product expects (inventory path, group_vars, config dirs)
  onto the user's structure; `site-sync` writes through the mapping.

A stayturgid-only user runs stayturgid's `site-init` and gets everything they
need. A site consuming multiple products has one `generated/<product>/` area
per product in one site dir. `site-djbclark` itself is the reference consumer.

### 5a. Serverapp adapters (per-app composition contract)

For each shared serverapp a product depends on (caddy, vector, openobserve,
victoriametrics, grafana, olivetin), the product ships an **adapter role**
with two modes:

- **Own-the-daemon** (no existing user config detected): the role installs
  and runs the daemon with a config layout that reserves a user-extensible
  fragment directory (Debian `conf.d` pattern). The user's later custom
  fragments drop in beside the product's.
- **Inject-only** (user config exists — the **default** in that case): the
  role leaves the user's daemon alone and injects the product's fragments
  into the user's config via the app's *native* include mechanism
  (Caddyfile `import`, vector multi-config/conf.d, Grafana provisioning
  dirs, OliveTin config merge projection). `site-map.yml` maps expected
  locations onto non-conventional layouts. Mode is overridable via site vars.

This is the Puppet roles/profiles insight applied per-daemon: the adapter
(profile) ships with the product that needs the app; the site repo's thin
wrappers pick modes and supply identity. No third repo is needed to hold
this glue — that location would be novel, unmaintained territory; adapters
next to the product that depends on them is the industry norm.

## 6. Literate programming: Entangled, scoped

Per operator preference, [Entangled](https://entangled.github.io/) — not
org-mode tangling — because the source format is Markdown (renders on
GitHub), the tool is pip/uv-installable, and sync is bidirectional (edits to
tangled files stitch back into the document).

**Scope discipline:** literate programming is used for the **site contract
documents only** — `SITE-CONTRACT.md` in each product, whose fenced code
blocks tangle into the scaffold templates, bootstrap script, and mapping
examples. `--docs-only` = render the document; `site-init` = copy tangled
output. The contract is bounded, doc-heavy, and slow-churning — the ideal
literate artifact. Product internals (roles, playbooks, control scripts) stay
conventional: high-churn code under tangling burdens every contributor and
agent with the Entangled toolchain for little gain. CI runs
`entangled tangle --check` (or equivalent) to keep document and tangled files
in sync. Influences: dotfiles.natsukium.com, thartman83/literate-playbooks,
Red Hat "Zen of Ansible" (playbooks as documentation).

## 7. What moves where

| Item (today) | Destination |
|---|---|
| Live fleet inventory, `group_vars/stayturgid.yml`, `docs/handoff.md`, operator docs | site-djbclark (stayturgid Phase 1, per its §4.2) |
| Caddy, landing, vector aggregator, openobserve (com.stayturgid.\*) | Site-owned instances from product-repo roles; stayturgid becomes tenant (fragments) |
| O-V-G-O remaining components (VictoriaMetrics, Grafana, OliveTin — not yet installed) | Land directly under site ownership; never install under stayturgid |
| Goose + LiteLLM (step0 plan) | Roles incubate in site-djbclark (decision 5); extract to a public repo only if they mature |
| hermes-agent, opencode-web | Stay in stayturgid for now (fleet-ops flavored); revisit after Phase C |
| Unmanaged machine services (immich, postgres, redis, mariadb, system-state-backup, hibernate-disk-check) | Gradually adopt into site-djbclark |
| `~/stayturgid_work`, `~/stayturgid.d` scratch checkouts | Moved to `~/ops/scratch/` 2026-07-18 (unmodified); deletion is operator's call. Note `stayturgid_work` sits on branch `just-standardization` and contains the old FIRERPA CA key pair |

## 8. Migration phases

- **Phase A — Coordination first (this repo, no service moves):** land
  `registry/ports.yml` (seeded — done), `registry/paths.yml`, conventions;
  add the collision lint; wire `landing-discover` drift check (in
  stayturgid, reading this repo's registry path from a site fact).
- **Phase B — stayturgid Phase 1:** move live inventory + operator docs
  here; stayturgid upstream scrubs per its §4.6. `just deploy` runs with
  `ANSIBLE_CONFIG` from this repo.
- **Phase C — Site contract:** write `SITE-CONTRACT.md` (Entangled) +
  `site-init`/`site-sync` in stayturgid; site-djbclark becomes the
  reference consumer.
- **Phase D — Shared infra handover:** serverapp adapter roles (§5a:
  caddy_gateway, landing, observability) built in stayturgid; site
  instantiates them; migrate daemon instances to site-owned labels;
  stayturgid contributes tenant fragments. Complete O-V-G-O under site
  ownership.
- **Phase E — AI stack:** goose/litellm roles authored in this repo per
  revised step0 (§9); deploy to M1 Air; extend to mini/VPSs.
- **Phase F — Adoption:** fold unmanaged machine services into site
  management, one at a time.

Phases A–B need nothing new invented and remove the most immediate risk
(uncoordinated ports/files). C is the biggest design lift (the contract). D
is mostly relabeling + moving templates between repos.

## 9. Revisions to the step0 (Goose + LiteLLM) plan

1. No standalone `~/ai-stack/ansible` tree — roles are authored in this repo
   (e.g. `roles/litellm`, `roles/goose`). `~/ai-stack` may remain as a
   runtime directory only.
2. launchd label `local.litellm` → templated `com.{{ site_ns }}.litellm`
   (here: `com.djbclark.litellm`).
3. Port 4000 confirmed free on the M1 Air today and now **registered** in
   `registry/ports.yml`. If Goose on the mini should reach LiteLLM, bind
   changes from 127.0.0.1 to Tailscale + a Caddy route fragment — a site
   decision recorded in the registry either way.
4. Secrets via the secretspec pattern, not ad-hoc zshrc/Keychain wrappers.
5. Verification section gains: registry lint passes; landing shows the new
   service as registered.

## 10. Open items

1. ~~Product repo name~~ **Resolved 2026-07-18: no third repo** (decision 5).
   Research record — every mature ecosystem uses exactly two repo kinds,
   public product + private site/control, with glue product- or site-side:
   [Puppet control-repo contents](https://github.com/puppetlabs/best-practices/blob/master/control-repo-contents.md),
   [Puppet roles & profiles](https://www.puppet.com/docs/puppet/7/roles_and_profiles_example),
   [Gruntwork infrastructure-live](https://docs.gruntwork.io/2.0/docs/overview/concepts/infrastructure-live/),
   [Flux repository structure](https://fluxcd.io/flux/guides/repository-structure/),
   [Ansible sample setup](https://docs.ansible.com/projects/ansible/latest/tips_tricks/sample_setup.html).
   (Also: `+` is invalid in GitHub repo names and Galaxy namespaces, so the
   candidate `stayturgid+site` could not have existed as proposed.)
2. **Port range policy** — keep documenting ad-hoc ports vs. reserving
   ranges per stack for future allocations (registry works either way).
3. **stayturgid §11 items** not closed here: #2 (IP vs MagicDNS), #3
   (devices.conf format), #4–8, #10.
4. Landing default-port footgun: `landing.py` defaults to 8080 (collides
   with Caddy health if run without `--port`); fix default to 8088 when
   landing moves to the product repo.
