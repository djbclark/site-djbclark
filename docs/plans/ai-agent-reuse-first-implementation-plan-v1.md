# Reuse-First AI Agent Engineering

**Status:** Implementation plan in progress  
**Owner:** site-djbclark / Hermes and Herdr integration  
**Date:** 2026-08-06

## Objective

Reduce the tendency of AI coding agents to write bespoke one-off implementations when an existing internal component, open-source project, package, skill, MCP server, or deterministic transformation already solves the problem.

The desired default is:

```text
Search existing software
  -> evaluate fit, maintenance, security, license, and cost
  -> reuse, wrap, extend, or contribute upstream
  -> build new code only when the reuse case is rejected with evidence
```

This is not a rule to add dependencies indiscriminately. Reuse is preferred when it lowers total lifetime cost and risk.

## Key decision

Hermes already provides most of the skill-management capabilities that external candidates would add:

- skill discovery and installation;
- standard `SKILL.md` packaging;
- scanning and deep auditing;
- snapshots and rollback;
- skill usage/provenance tracking;
- curator-based consolidation and archival;
- optional synchronization.

The actual gap is a coherent **reuse-first development methodology** plus repository, library, dependency, and open-source project intelligence.

Nothing except Hermes should write directly into `~/.hermes/skills`. External sources may be reviewed and installed through Hermes's lifecycle, but direct copying or proxy-based mutation is prohibited.

## Decisions on investigated projects

| Project | Decision | Rationale |
| --- | --- | --- |
| Hermes native skills, audit, curator, snapshots | **Use as baseline** | Already provides the safest local skill lifecycle and guarded evolution path. |
| Hermes sync | **Keep disabled** | Current account has no opted-in skills or organization membership; private operational skills should not leave the machine by default. |
| `AMAP-ML/SkillClaw` | **No-go** | Rewrites Hermes configuration, proxies/records model traffic, bypasses Hermes skill scanning, competes with the curator, has reported harness breakage, and has open security issues in the skill-pull path. |
| `obra/superpowers` | **Selective review** | Strong development methodology source; diff against existing Hermes skills before importing overlapping names. Use Hermes tap/install paths, not direct file copy. |
| `anthropics/skills` | **Mine selectively** | `skill-creator`, `mcp-builder`, and the template are useful references; inspect each skill's license before redistribution. |
| `iflytek/skillhub` | **Defer** | Stronger enterprise registry governance, but it is pre-1.0 infrastructure and its direct Hermes installation path bypasses Hermes's scan/provenance lifecycle. Revisit if multi-person RBAC becomes necessary. |
| `RayFernando1337/llm-cursor-rules` | **Reference only** | Opinionated, framework-specific, partly stale, and not packaged as tested skills. |
| `langgptai/awesome-claude-prompts` | **No-go as an input library** | No clear repository license, unstructured/stale content, jailbreak material, and scraped system-prompt material. |

## Staged implementation

### Stage 0 — Baseline and safety invariants

1. Inventory agents, repositories, skills, internal components, package managers, and MCP servers.
2. Measure a representative task set:
   - whether the agent searched the repository first;
   - whether it searched internal and external reuse candidates;
   - new dependency count;
   - new utility/helper code;
   - duplicate implementation rate;
   - test and integration failures;
   - reuse decisions and upstream opportunities.
3. Keep these invariants:
   - no external tool writes directly into `~/.hermes/skills`;
   - Hermes owns install, scan, audit, backup, rollback, and mutation;
   - no automatic cross-user skill sharing for private operational content;
   - new dependencies require evidence and normal repository review.
4. Review the seven currently unmanaged Hermes skills and explicitly adopt or leave each; do not bulk-adopt for cosmetic cleanliness.
5. Investigate the missing curator report noted by `hermes curator status` and report upstream if reproducible.

### Stage 1 — Reuse-first development skill

Create a portable skill for Hermes, Claude Code, Codex, OpenCode, and Herdr. Before non-trivial implementation, it must require the agent to:

1. inspect the current repository architecture, APIs, tests, and examples;
2. search local modules and utilities;
3. search approved internal repositories and components;
4. search existing skills and MCP servers;
5. search package registries and official, version-specific documentation;
6. evaluate candidates for API fit, compatibility, maintenance, security, license, dependency footprint, integration cost, and adoption evidence;
7. choose reuse, wrapping, extension, upstream contribution, or new code;
8. record why existing candidates were rejected before bespoke implementation;
9. validate the selected integration with contract, API, integration, and regression tests.

The skill must explicitly permit new code when reuse is unsafe, abandoned, incompatible, over-complex, or more expensive over its lifetime.

### Stage 2 — Canonical Git-backed skill library

Maintain reviewed shared skills in a private Git repository with:

- portable `SKILL.md` files;
- agent-specific adapters;
- source and license metadata;
- owners and lifecycle status;
- version and changelog;
- validation scripts and smoke tests;
- provenance and compatibility notes;
- deprecation and rollback information.

Hermes should consume the canonical repository through a tap/install mechanism so skills retain Hermes scanning, provenance, update, and audit behavior. Do not synchronize by `rsync`, direct file copying, or an external daemon writing into the Hermes directory.

### Stage 3 — Repository and library intelligence

Add read-only retrieval capabilities in this order:

1. local symbol, AST, dependency-manifest, test, and example search;
2. GitHub MCP for repository, issue, pull-request, and source context;
3. Context7 for version-specific library documentation and examples;
4. package registry metadata;
5. deps.dev for dependency graphs and package insights;
6. OSV/OSV-Scanner for known vulnerabilities;
7. OpenSSF Scorecard for open-source project health;
8. Sourcegraph MCP if the number of private repositories justifies it.

The output must include evidence links, versions, licenses, validation commands, and reasons for recommendation—not just a semantic similarity score.

### Stage 4 — Reuse broker and decision record

Build a lightweight read-only CLI or MCP service with operations such as:

```text
reuse_search
inspect_candidate
compare_candidates
record_reuse_decision
```

Search priority:

1. current repository;
2. organization repositories;
3. internal package registries;
4. approved upstream projects;
5. major package registries;
6. general GitHub search;
7. unverified search results.

Every substantial AI-generated change should be able to include a short reuse assessment:

```markdown
## Reuse assessment

Searched:
- current repository
- internal component catalog
- package registries
- relevant upstream projects

Selected:
- ...

Alternatives rejected:
- ...

Reason for new code, if applicable:
- ...

Upstream contribution considered:
- yes/no; reason
```

The initial broker must recommend and explain only. It must not install packages or modify source automatically.

### Stage 5 — Promote repeated solutions

When materially similar bespoke code appears more than once:

1. detect and compare the implementations;
2. extract a shared library, service, skill, MCP server, template, or recipe;
3. add tests, ownership, and documentation;
4. migrate consumers;
5. publish it internally;
6. upstream the general portion where appropriate.

### Stage 6 — Prefer deterministic transformations

Use OpenRewrite, codemods, generated clients, schema generators, shared templates, Renovate, or Dependabot for repeatable transformations and dependency maintenance. Agents should select, configure, and verify these tools rather than regenerate equivalent changes independently in every repository.

### Stage 7 — Controlled learning loop

Only after the catalog, decision records, tests, ownership, and rollback are established should agent-created improvements be fed back into the shared library:

```text
observed solution or failure
  -> candidate skill/component improvement
  -> reviewed Git change
  -> automated validation
  -> human approval
  -> versioned release
  -> agent-specific installation
```

Hermes's native curator remains the first evolution mechanism. It should not be supplemented by a second unattended mutator of the same skill tree.

## Success metrics

Measure outcomes rather than instruction compliance:

- reuse-decision quality when a suitable candidate existed;
- percentage of tasks that search existing code before implementation;
- duplicate utility/helper implementations;
- new dependencies per task and their subsequent health;
- integration/API correctness;
- test and regression rate;
- time to first reuse search;
- number of internal components adopted;
- number of useful upstream contributions;
- maintenance incidents attributable to bespoke agent code;
- percentage of recommendations with verifiable source, version, license, and validation evidence.

## Research sources

- [Hermes Skills Hub](https://hermes-agent.nousresearch.com/docs/skills/)
- [Hermes Agent](https://github.com/NousResearch/hermes-agent)
- [Agent Skills specification](https://github.com/agentskills/agentskills)
- [Aider repository map](https://aider.chat/docs/repomap.html)
- [Context7](https://github.com/upstash/context7)
- [GitHub MCP Server](https://github.com/github/github-mcp-server)
- [Sourcegraph Code Search](https://sourcegraph.com/docs/code-search)
- [deps.dev](https://deps.dev/)
- [OSV-Scanner](https://github.com/google/osv-scanner)
- [OpenSSF Scorecard](https://github.com/ossf/scorecard)
- [OpenRewrite](https://github.com/openrewrite/rewrite)
- [SkillClaw](https://github.com/AMAP-ML/SkillClaw)
- [SkillHub](https://github.com/iflytek/skillhub)
- [Superpowers](https://github.com/obra/superpowers)
- [llm-cursor-rules](https://github.com/RayFernando1337/llm-cursor-rules)
- [awesome-claude-prompts](https://github.com/langgptai/awesome-claude-prompts)
- [CodeRAG-Bench](https://arxiv.org/abs/2406.14497)
- [RepoCoder](https://arxiv.org/abs/2303.12570)
