# Agent skill library — evaluation and implementation plan (v1)

| | |
|---|---|
| **Status** | Implementation plan — **in progress** |
| **Tracking issue** | [#99](https://github.com/djbclark/site-djbclark/issues/99) |
| **Scope** | Claude Code, Codex, OpenCode, Herdr |
| **Evidence date** | 2026-08-06 — all GitHub figures pulled live via `gh api` on that date |
| **Hermes** | Out of scope here. Hermes is running its own evaluation; see [§4](#4-note-for-the-hermes-side). |

Primary-source evaluation of seven skill-management / prompt-library / skill-evolution
projects, and a proposed Git-backed canonical skill library. Nothing was installed and no
agent configuration was modified in producing this document.

---

## 0. What the research actually found

Three findings reframe the question:

1. **There is a governed spec now.** `SKILL.md` + YAML frontmatter is a published
   specification at <https://agentskills.io/specification>, backed by
   [`agentskills/agentskills`](https://github.com/agentskills/agentskills) (Apache-2.0) with a
   reference validator (`skills-ref validate ./my-skill`).
   `anthropics/skills/spec/agent-skills-spec.md` is now a one-line pointer to it.
   **Format portability is a solved problem** — no product purchase is required for it.

2. **The governance layer a registry product would sell us, this suite already runs.**
   Coordinated annotated tags and published GitHub Releases (`ops-vMAJOR.MINOR.PATCH`),
   `just ops-release-check/deploy/status`, PR review, and a forward-only rollback policy.
   That is precisely what SkillHub provides (semantic versioning, review gates, audit log,
   rollback). Adopting it would mean running a second, weaker governance system in parallel.

3. **Exactly one candidate is a no-go on safety grounds** — and it is the one that markets
   itself hardest as the answer: SkillClaw.

### Current inventory (read-only, 2026-08-06)

| Agent | Skills dir | Count |
|---|---|---|
| Claude Code | `~/.claude/skills` | 13 (`baton`, `coderabbit-feeder`, `composio-cli`, `handoff`, `herdr`, `herdr-orchestration`, `ralph-tui-*` ×5, `resume`, `session-handoff`) |
| Codex | `~/.codex/skills` | absent / empty |
| OpenCode | `~/.config/opencode` | config only, no skills tree |
| Hermes | `~/.hermes/skills` | 27 category dirs / 98 curator-managed skills |

Plus the published [`djbclark/claude-orchestration-skills`](https://github.com/djbclark/claude-orchestration-skills)
(public, MIT), currently kept in sync **by hand** under the standing rule that every
substantive internal skill edit is applied and pushed to the public repo as well. **That
manual sync burden is the strongest single argument for building the pipeline in [§2](#2-proposed-architecture).**

---

## 1. Evaluation

Category legend: **1** discovery/marketplace · **2** packaging/portability · **3** registry+versioning ·
**4** cross-agent sync · **5** session tracing/feedback · **6** auto evolution/dedup · **7** dev methodology

| Project | Cats | License | Releases | Contributors | Issues (closed/open) | CI | Last real code | Daemon / intercept | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| [agentskills/agentskills](https://github.com/agentskills/agentskills) | 2 | Apache-2.0 | **none** | — | 48 open | **none found** | 2026-08-04 | no | **GO** |
| [obra/superpowers](https://github.com/obra/superpowers) | 2,7 | MIT | 11 (v5.0.4 → v6.2.0) | 38 | 13 / 24 | **none in tree** | 2026-07-27 | no | **GO** (selective) |
| [anthropics/skills](https://github.com/anthropics/skills) | 1,2 | **none at root**; per-skill | 0 | 13 | 1067 open | n/a | 2026-07-24 | no | **GO** (mine only) |
| [iflytek/skillhub](https://github.com/iflytek/skillhub) | 1,2,3 | Apache-2.0 | 19 (v0.2.1 → v0.2.15) | 30 | 26 / 15 | **18 workflows** | 2026-08-06 | **server** | **DEFER** |
| [RayFernando1337/llm-cursor-rules](https://github.com/RayFernando1337/llm-cursor-rules) | — | MIT (API) vs "attribution" (README) | 0 | 1 | 1 open | none | **2025-11-26** | no | **MINE ONLY** |
| [langgptai/awesome-claude-prompts](https://github.com/langgptai/awesome-claude-prompts) | — | **NONE** | 0 | 5 | 20 open | none | **2026-02-28** | no | **NO-GO** |
| [AMAP-ML/SkillClaw](https://github.com/AMAP-ML/SkillClaw) | 3,4,5,6 | MIT | **0 releases, 0 tags** | 10 | **4 / 29** | **lint only** | **2026-06-06** | **MITM proxy + daemon** | **NO-GO** |

Star counts are deliberately excluded from the verdict logic. Two illustrations of why:
`awesome-claude-prompts` has 5.4k stars and no license; SkillHub runs
`claim-issue-reward.yml` and `statistic-member-reward.yml` — a **paid contribution
programme**, which mechanically inflates stars, forks and contributor counts. SkillHub's
engineering evidence is strong *independently*; its popularity metrics are not evidence.

### 1.1 Agent Skills spec + `skills-ref` — the linchpin

- **Does today:** defines required `name` (≤64 chars, lowercase/digits/hyphens, must match
  parent dir) and `description` (≤1024); optional `license`, `compatibility`, `metadata`
  (string→string map — the conventional home for `version`), experimental `allowed-tools`.
  Conventional `scripts/`, `references/`, `assets/`. Progressive disclosure budget: ~100
  tokens of metadata always loaded, <5000-token body on activation, resources on demand;
  keep `SKILL.md` under 500 lines. Ships `skills-ref validate`.
- **Does not:** define a registry protocol, version resolution, signing, or sync. `version`
  is a convention inside `metadata`, not a first-class field.
- **Risk:** no releases and no CI workflows in the tree — **pin to a commit SHA**, do not
  track `main`.

### 1.2 obra/superpowers — GO, selectively, and copy the layout

- **Does today:** 14 methodology skills (`brainstorming`, `writing-plans`, `executing-plans`,
  `test-driven-development`, `systematic-debugging`, `subagent-driven-development`,
  `dispatching-parallel-agents`, `using-git-worktrees`, `requesting-code-review`,
  `receiving-code-review`, `verification-before-completion`,
  `finishing-a-development-branch`, `writing-skills`, `using-superpowers`) plus a
  session-start hook so they trigger automatically.
- **The part we actually want is the repo layout.** One canonical `skills/` tree plus thin
  per-harness adapters in a single repo: `.claude-plugin/`, `.codex-plugin/`,
  `.cursor-plugin/`, `.kimi-plugin/`, `.opencode/plugins/superpowers.js`,
  `.pi/extensions/superpowers.ts`, `.agents/plugins/marketplace.json`, `hooks/`, and
  `scripts/sync-to-codex-plugin.sh`. This is exactly the architecture in [§2](#2-proposed-architecture),
  already proven across ~11 harnesses — the strongest prior art in this review.
- **Does not:** provide a registry, version resolution, telemetry, or skill *learning*.
- **Config / traffic / daemon:** none. No model-traffic interception, no data collection.
- **Maturity caveat:** 11 releases with semver discipline and a `.version-bump.json`, but
  **no `.github/workflows` found in the tree** — releases are cut by `scripts/bump-version.sh`
  with no CI gate. 24 open vs 13 closed issues. Commercial support via Prime Radiant
  (`sales@primeradiant.com`).
- **Collision warning:** `test-driven-development`, `requesting-code-review`, `plan` and
  `spike` already exist as directory names in `~/.hermes/skills`. Diff before importing.
- **License:** MIT (Jesse Vincent, 2025) — clean to adapt with attribution.

### 1.3 anthropics/skills — mine, don't depend on

- **Does today:** 18 reference skills, a `template/SKILL.md`, and a
  `.claude-plugin/marketplace.json` so `/plugin marketplace add anthropics/skills` works
  natively in Claude Code. The genuinely useful ones here are **`skill-creator`** and
  **`mcp-builder`**.
- **Does not:** version, sync, evolve or govern anything. README explicitly disclaims the repo
  as *"provided for demonstration and educational purposes only."*
- **License — read carefully.** There is **no LICENSE file at the repo root** (GitHub's
  license API returns 404). The README states most skills are Apache-2.0 **but**
  `skills/docx`, `skills/pdf`, `skills/pptx`, `skills/xlsx` are **source-available, not open
  source**. A `THIRD_PARTY_NOTICES.md` exists. Check the individual skill folder before
  copying; do not redistribute those four.

### 1.4 iflytek/skillhub — real infrastructure, wrong problem

- **Does today:** self-hosted enterprise skill registry (Java 21 + React 19,
  Docker Compose / Kubernetes / Helm). Semantic versions with `beta`/`stable` tags and
  `latest` tracking; team namespaces with Owner/Admin/Member RBAC; review and promotion
  gates; audit logging; full-text search; API tokens. CLI: `npm i -g @astron-team/skillhub`.
- **Maturity is genuinely good** — 2338 files, ~573 test files, **18 CI workflows** including
  `pr-tests.yml`, `pr-e2e.yml`, `security.yml`, `pr-helm-chart.yml`, `publish-images.yml`;
  19 releases on a ~2-week cadence (2026-04-01 → 2026-07-30); 26 closed vs 15 open issues —
  the best resolution ratio in this review. A real engineering org, not a demo.
- **Does not:** collect session data, intercept traffic, or evolve skills. Registry only.
- **Why defer anyway:**
  - **Pre-1.0 (v0.2.15)** — the API contract is not stable.
  - Requires a persistent server. Per the standing scheduling-tier policy this laptop is a
    frequently-off control node; a registry that must be up to install a skill fits badly.
  - **Duplicates governance we already have** — semantic versions, review gates, audit trail
    and rollback are what `ops-vX.Y.Z` + PRs + `git log` already provide.
  - **Supply chain:** documented quick-start is
    `curl -fsSL https://imageless.oss-cn-beijing.aliyuncs.com/runtime.sh | sh` — piping a
    shell script from a third-party Aliyun OSS bucket. Plus GHCR images and an npm CLI.
- **Revisit trigger:** a multi-person team needing RBAC over private skills. Then SkillHub is
  the correct answer.

### 1.5 RayFernando1337/llm-cursor-rules — source material only

14 loose markdown / `.mdc` files (`swift.md`, `nextjs14-typescript-tailwind.md`,
`Tailwind-v4.mdc`, `optimization-principles.md`, `generate-claude.md`, `generate-agents.md`,
plus `marketing/`, `productivity/`, `sub-agents/`).

**Not installable as skills** — no `SKILL.md`, no frontmatter, no directory-per-skill layout.
**Stale:** last commit **2025-11-26**, single contributor, 18 commits total; the `nextjs14-*`
content is pinned to a superseded Next.js generation and is now actively misleading.
**License is ambiguous:** GitHub reports MIT, README asks only for attribution — MIT governs
(the LICENSE file wins), but honour the attribution request.
Worth mining `optimization-principles.md` and the `generate-claude.md` / `generate-agents.md`
meta-prompts as *ideas*. Everything else is stale or better covered by Superpowers.

### 1.6 langgptai/awesome-claude-prompts — refuse

- **No license at all.** GitHub's license API returns 404; no LICENSE file exists (root holds
  only `.gitignore`, `README.md`, `claudecode/`, `imgs/`). Under default copyright this is
  **all rights reserved** — it cannot lawfully be redistributed or relicensed into a skill
  library, and contributors never agreed to outbound terms either.
- **Not structured:** one 148 KB / 2977-line README. No per-item files, no frontmatter.
- **Not current:** last commit 2026-02-28; bulk of content dates to 2023–2025.
- **Actively unsafe content:** the index includes **"DAN for Claude 2"** (a jailbreak) and
  **"system prompt and tools from claude code"** (scraped system prompts). A jailbreak that
  auto-loads via skill-description matching is a live risk, not a theoretical one.
- Content is prompts, not skills — wrong artifact type even setting the above aside.

### 1.7 AMAP-ML/SkillClaw — refuse

**Research status is explicit.** [arXiv 2604.08377](https://arxiv.org/abs/2604.08377)
(Ma, Yang, Ji, Wang, Wang, Hu, Huang, Chu), submitted 2026-04-09, **v1 only**, flagged
**"Work in progress"**, evaluated on `WildClawBench` against Qwen3-Max. It reached #2 on
Hugging Face Daily Papers — an attention signal, not a production signal.

**What it does:** a local **client proxy** on port 30000 exposing `/v1/chat/completions` and
`/v1/messages` that **intercepts every agent request and records session artifacts**, plus an
optional `evolve_server` that reads sessions from shared storage (Alibaba OSS / S3 / local /
Nacos), rewrites skills, and writes them back. Multi-user "collective evolution" means
session-derived skills from many users land in one shared bucket.

**Disqualifying findings:**

1. **Two open, unpatched, PoC-backed path-traversal bugs in the skill-install path**, both
   filed 2026-08-03, both at **zero comments**:
   - [#69](https://github.com/AMAP-ML/SkillClaw/issues/69) — `SkillHub.pull_skills` builds the
     local target with `os.path.join(skills_dir, skill_name)` where `skill_name` comes
     verbatim from the remote `manifest.jsonl`; `../` in the manifest `name` writes outside
     `skills_dir`.
   - [#68](https://github.com/AMAP-ML/SkillClaw/issues/68) — `normalize_bundle_rel_path`
     rejects `.`/`..`/empty but **not absolute paths**; `pathlib` discards the root when the
     right operand is absolute, so a poisoned bundle writes to any absolute path.

   Both are reachable **on a normal skill pull**. In a system whose entire value proposition
   is pulling skills from shared storage that other users write to, this is arbitrary file
   write from a semi-trusted source.

2. **It rewrites agent configuration.** Its README states plainly: *"On startup, SkillClaw
   rewrites `~/.hermes/config.yaml` to point Hermes at the local proxy."* It similarly
   auto-configures Codex and Claude Code profiles.

3. **It is a man-in-the-middle on all model traffic**, and records it. With
   subscription/OAuth-backed models this is both a privacy exposure and a provider-ToS
   question.

4. **Testing is not real.** 19 test files exist, but the only CI workflow is `lint.yml`,
   which runs `ruff check` / `ruff format --check` and **never runs the tests**.

5. **Maintenance is thin and unresponsive.** 4 closed vs 29 open issues (~12% closure); of 20
   open issues sampled, only 5 have any reply. Last substantive code commit **2026-06-06** —
   the 2026-08-06 commit is a docs announcement for a different project. No releases, no
   tags; install is `git clone` + `bash scripts/install_skillclaw.sh`.

6. **Already reported breaking a harness:**
   [#61 "Broke the Harness"](https://github.com/AMAP-ML/SkillClaw/issues/61) (2026-07-25) —
   unanswered.

The *idea* — post-task evolution, dedup, cross-agent pollination — is sound and worth
reimplementing behind our own review gates. The implementation is not adoptable.

### 1.8 Does any mature product provide safe automatic skill evolution today?

**Not as a third-party product worth installing — no.** SkillClaw is the only candidate that
attempts it and fails on safety and maintenance. SkillHub explicitly does not (it is a
registry). Superpowers and anthropics/skills do not attempt it.

The nearest *safe* implementation that exists today is **Hermes' own built-in curator**,
already running on this machine, and its safety design is the one to copy: it never touches
bundled or hub-installed skills, never auto-deletes (archive only), snapshots the skills tree
before every run, supports `pin` to exempt a skill, and has an explicit `rollback`.
**If we build evolution, copy that design — not SkillClaw's.**

---

## 2. Proposed architecture

**Principle: the repo is the registry.** No server, no daemon, no traffic interception.
Distribution is a build step, and every agent's skills dir is a *derived artifact*, never a
source of truth.

```text
ops-djbclark suite (existing release train)
└── skills-canon/                    # new dir in an existing repo, or a new suite repo
    ├── skills/                      # ← THE ONLY SOURCE OF TRUTH
    │   └── <skill-name>/
    │       ├── SKILL.md             # agentskills.io spec; metadata.version, metadata.owner
    │       ├── references/  scripts/  assets/
    ├── adapters/                    # per-agent emitters (pattern borrowed from superpowers)
    │   ├── claude-code/             # → ~/.claude/skills + .claude-plugin/marketplace.json
    │   ├── codex/                   # → ~/.codex/skills
    │   ├── opencode/                # → OpenCode plugin/skills path
    │   └── herdr/                   # → orchestration-visible subset
    ├── policy/
    │   ├── allowlist.yaml           # which skills go to which agent
    │   └── vendored.lock            # upstream SHA + license for every imported skill
    ├── scripts/{validate,plan,apply,doctor}.sh
    └── .github/workflows/validate.yml
```

### Five guarantees, each mapped to existing machinery

| Guarantee | Mechanism |
|---|---|
| **Validation** | `skills-ref validate` (pinned SHA) on every skill, in CI and pre-commit. Plus: name↔dirname match, frontmatter lint, `SKILL.md` <500 lines, no secrets, `metadata.version` present, license present for vendored skills. |
| **Review** | Task worktree under `~/src/ops-worktrees/` → PR → existing review path. **Never edit in `~/ops`.** |
| **Versioning** | Two levels — per-skill `metadata.version` (semver, bumped in the PR that changes it) and suite-level `ops-vX.Y.Z`. The release tag *is* the lockfile. |
| **Sync** | `plan.sh` (default) renders adapter output to a staging dir and prints a diff vs live. `apply.sh` requires explicit per-agent opt-in, takes a timestamped backup first, and refuses to run if the target has untracked local edits. **Dry-run is the default; apply is always deliberate.** |
| **Rollback** | Follows existing policy — forward-only patch release, never retag. Plus a local escape hatch: `apply.sh` backups let a bad sync be reverted without waiting for a release. |

### Drift, not overwrite

`doctor.sh` reports three states per skill per agent:

- **in sync**
- **locally modified** — an agent-side edit not present in canon. Surface it and offer to
  promote it into a PR; **never silently clobber**.
- **stale** — canon is newer.

This is the mechanism that replaces the current manual "remember to push the same fix to the
public repo" rule.

### Vendoring third-party skills

Anything imported from Superpowers or anthropics/skills lands under `skills/` with
`vendored.lock` recording upstream repo, commit SHA, license and import date, and
`metadata.upstream` in its frontmatter. A periodic job diffs upstream and opens a PR. This
keeps attribution correct (MIT/Apache both require it) and makes "what did we change vs
upstream" answerable.

### What replaces a registry product

Nothing needs to. Search is `rg` over `skills/`. Distribution is `git pull` + `apply.sh`.
Access control is repo visibility. Audit log is `git log`. Promotion gates are PR review.
Semantic versioning is tags. The only thing genuinely lost is a web UI and full-text search
across a large corpus — irrelevant at 13–100 skills, decisive at 10,000.

---

## 3. Pilot plan

**Hard constraints for every phase:** no changes under `~/ops`; no modification of any
agent's production config; no daemon; no network service; dry-run by default; every write
backed up first.

**Phase 0 — read-only inventory (no writes at all).**
Enumerate `~/.claude/skills`, `~/.codex/skills`, OpenCode, and
`djbclark/claude-orchestration-skills`. Produce a dedupe report (name collisions,
near-duplicate descriptions), a spec-compliance report by running `skills-ref validate`
**against a temp copy**, and a divergence report between `~/.claude/skills` and the published
public repo. *Exit criterion:* exact counts of duplicated and non-compliant skills.
This phase alone probably pays for the project — it directly answers the manual-sync question.

**Phase 1 — canonical repo in a task worktree.**
Create `skills-canon/`, import **copies** of the Claude Code skills, add `skills-ref`
validation + CI, open a PR. No agent reads from it yet. *Exit:* CI green, merged, first
`ops-vX.Y.Z` including it published.

**Phase 2 — adapters in plan-only mode.**
Implement `adapters/claude-code` and `adapters/codex`; `plan.sh` writes to `build/<agent>/`
and prints a diff against the live dir. **`apply.sh` is not written yet.**
*Exit:* the `claude-code` plan is a clean **no-op diff** against `~/.claude/skills` — proving
canon faithfully reproduces current reality before it is ever allowed to write.

**Phase 3 — opt-in apply, one agent, reversible.**
Enable `apply.sh` for **Codex first** (no skills dir today, so the blast radius is creating
files where none exist), then Claude Code, then OpenCode. Each step: backup → apply → verify →
hold one week before the next agent. *Exit per agent:* skills load, no regressions,
`doctor.sh` clean.

**Phase 4 (optional, later) — evolution, borrowed not bought.**
Only after Phases 0–3 are stable. Copy Hermes' curator safety model: propose-only (opens a
PR, never writes), never touches vendored skills, archive-not-delete, explicit pin list. A
skill-evolution proposal that must survive PR review is safe in a way a write-back loop
structurally cannot be.

**Kill criteria:** abandon if Phase 2's no-op diff cannot be achieved (canon cannot represent
reality), or if adapter maintenance exceeds the manual-sync burden it replaces.

---

## 4. Note for the Hermes side

Hermes is evaluating separately and is **not** tracked by [#99](https://github.com/djbclark/site-djbclark/issues/99).
Two findings from this research are worth passing along, because they change the shape of any
Hermes integration:

- **Hermes already implements six of the seven capability categories natively** —
  `hermes skills {browse,search,install,inspect,audit,publish,snapshot,tap}`, `hermes sync`
  (currently `feature_enabled: false`, so nothing is leaving the machine), and
  `hermes curator` (auxiliary-model consolidation, 98 managed skills, snapshot-before-run,
  archive-not-delete, `pin`/`rollback`). The only real gap is category 7, dev methodology.
- **Integration should be a tap, not a file copy.** `hermes skills install` carries a
  `--force` flag documented as *"Install despite blocked scan verdict"*, and
  `hermes skills audit --deep` performs AST-level analysis on Python files — so Hermes gates
  skills at install time. Anything that writes directly into `~/.hermes/skills` (SkillHub's
  `npx clawhub --dir`, SkillClaw's `pull_skills`, a naive rsync adapter) **bypasses that
  gate** and gets no hub provenance, which also makes the curator treat it as unmanaged.

---

## 5. Go / no-go

| Candidate | Decision | Rationale |
|---|---|---|
| **Agent Skills spec + `skills-ref`** | ✅ **GO — adopt now** | The portability answer; free and vendor-neutral. Pin to a SHA (no releases, no CI). |
| **obra/superpowers** | ✅ **GO — selective import + copy the layout** | MIT, actively released; its multi-harness adapter pattern is the blueprint for [§2](#2-proposed-architecture). Diff the 4 name collisions first. |
| **anthropics/skills** | ✅ **GO — mine only, per-skill license check** | Take `skill-creator`, `mcp-builder`, `template/`. No root LICENSE; docx/pdf/pptx/xlsx are source-available — do not redistribute those. |
| **RayFernando1337/llm-cursor-rules** | 🟡 **MINE ONLY — low priority** | 8 months stale, framework content rotted. Convert 2–3 ideas by hand; do not install or track. |
| **iflytek/skillhub** | ⏸️ **DEFER — revisit if a team forms** | Well-engineered, but pre-1.0, needs a server, duplicates the governance the ops release train already provides. |
| **langgptai/awesome-claude-prompts** | ❌ **NO-GO** | No license (all rights reserved), unstructured, stale, ships a jailbreak and scraped system prompts. |
| **AMAP-ML/SkillClaw** | ❌ **NO-GO** | "Work in progress" paper; two open unpatched path-traversal bugs on the skill-pull path; rewrites agent config; MITM proxy on all model traffic; tests not run in CI; 12% issue closure. |

**Net recommendation:** adopt the *spec*, copy the *layout*, mine the *content*, and build the
registry out of git and the release train already in use. Buy nothing, install no daemon, and
let Phase 0's inventory decide how much of the rest is worth doing.

---

## 6. Uncertainties and unverified assumptions

- **Not verified:** whether `test-driven-development` / `requesting-code-review` in
  `~/.hermes/skills` are vendored copies of the Superpowers skills of the same name, or
  independent. Contents were not diffed. Affects import collision handling.
- **Not verified:** OpenCode's exact skills-directory path and loading semantics.
  `~/.config/opencode/` exists with config and `node_modules` but no skills tree; Superpowers
  ships an `.opencode/plugins/superpowers.js` adapter. The adapter target path in
  [§2](#2-proposed-architecture) is an assumption.
- **Not verified:** Codex's skills-directory semantics. `~/.codex/skills` does not currently
  exist; SkillClaw's README asserts it is the native default and Superpowers ships a
  `.codex-plugin/plugin.json` — consistent, but untested here.
- **Not tested:** `skills-ref validate` was not run (nothing was installed). Its behaviour is
  taken from the published spec page.
- **Inference, not fact:** that SkillHub's reward workflows inflate its star/fork/contributor
  counts. The workflows exist and are named for rewards; the causal effect is an inference.
- **Point-in-time:** all issue counts, release dates and commit dates are as of 2026-08-06.
  SkillClaw #68/#69 could be patched at any time — recheck before revisiting that verdict.
- **Superpowers CI:** no `.github/workflows` was found in the recursive tree listing. Workflows
  may live on another branch, or releases may be gated another way.
