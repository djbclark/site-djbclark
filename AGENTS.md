# site-djbclark

> **AI agents (any vendor):** this file is the entry point — the AGENTS.md
> convention that coding agents from multiple vendors check first. Project
> overview: [README.md](README.md). Continuation state for the ongoing
> segmentation/AI-stack work: [docs/relay/NEXT-PROMPT.md](docs/relay/NEXT-PROMPT.md).

Private **site repo** for djbclark's machines (M1 MacBook Air, Intel Mac
mini, Linux VPSs) — the identity/allocation authority paired with the public
product repo [stayturgid](https://github.com/djbclark/stayturgid). Base
layout is three sibling checkouts under `${OPS_ROOT:-~/ops}/`: this repo, `stayturgid`,
and `site-private`.

## Memory & documentation policy (this repo's slice)

There is **no single canonical policy copy**. Each sibling's `AGENTS.md` owns
its slice; read all three for a full picture. Cross-repo: filesystem path **and**
absolute GitHub URL.

**This repo (`site-djbclark`) owns:**

- Non-sensitive **site-specific** practice that other stayturgid operators might
  still benefit from seeing or adapting (relay protocol, registry discipline,
  LiteLLM/brew site notes, segmentation plans under `docs/`).
- Live inventory, credentials-adjacent config, hostnames/IPs for **this** site
  (never upstream into public stayturgid).

**Point elsewhere:**

- Durable **stayturgid product** rules/lessons →
  [`${OPS_ROOT:-~/ops}/stayturgid/AGENTS.md`](https://github.com/djbclark/stayturgid/blob/master/AGENTS.md)
  (`https://github.com/djbclark/stayturgid/blob/master/AGENTS.md`).
- Private / Mac-wide / not-for-public extras →
  [`${OPS_ROOT:-~/ops}/site-private/AGENTS.md`](https://github.com/djbclark/site-private/blob/master/AGENTS.md)
  (`https://github.com/djbclark/site-private/blob/master/AGENTS.md`).

**Never commit passwords or secrets** (same rule as the other two). IPs and
hostnames for this site are expected here.

**Symlinks** under `~` (`AGENTS.md`, `CLAUDE.md`, other root-level vendor agent
files) and `~/.claude/.../memory` are documented in site-private /
stayturgid — not duplicated here. The supported optional local selector is
`${OPS_ROOT:-~/ops}/.mysite` → this checkout; do not use `.mysite` in GitHub URLs.
stayturgid discovery excludes `site-private`, prints the selected path/source,
and creates a missing private-companion directory without Git or secrets.

Topology background:
[stayturgid multi-site-topology.md §4.10](https://github.com/djbclark/stayturgid/blob/master/docs/architecture/multi-site-topology.md#410-the-third-repo-opssite-private).

## Where documentation goes

| Location                                                                               | What goes here                                                                                | Update cadence           |
| -------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------ |
| [`README.md`](README.md)                                                               | Project overview, LiteLLM/brew/OliveTin/Caddy operational notes                               | Rare                     |
| [`AGENTS.md`](AGENTS.md) (this file)                                                   | Agent entry + **this site's slice** of the three-way memory/docs policy                       | Rare                     |
| [`docs/relay/NEXT-PROMPT.md`](docs/relay/NEXT-PROMPT.md)                               | Current baton for the segmentation/AI-stack relay — which AI, exact prompt                    | Every relay step         |
| [`docs/relay/PROTOCOL.md`](docs/relay/PROTOCOL.md)                                     | Rules for the relay process itself                                                            | Rare                     |
| [`docs/relay/LEDGER.md`](docs/relay/LEDGER.md)                                         | History of relay steps                                                                        | Every relay step         |
| [`docs/plans/`](docs/plans/)                                                           | Architecture + phased execution plans for this site's segmentation work                       | As plans evolve          |
| [`docs/reference/available-ai-models.md`](docs/reference/available-ai-models.md)       | Catalog of available AI models/accounts for this operator — quote full rows when recommending | As accounts/plans change |
| [`docs/reference/herdr-workstation.md`](docs/reference/herdr-workstation.md)           | Multi-vendor Herdr workstation usage (keys, mouse, agents, worktrees) — config is on-box `~/.config/herdr/` | When Herdr config/workflow changes |
| [`docs/reference/herdr-brew-service.md`](docs/reference/herdr-brew-service.md)         | Herdr brew service (persistent server), registry claim, OliveTin dashboard actions            | When service/registry changes |
| [`docs/reference/kimi-k3-routing-research.md`](docs/reference/kimi-k3-routing-research.md) | Decision doc: Kimi K3 as a Herdr-routable model (issue #36) — trial, not standing infra yet   | Rare; revisit after a real trial |
| [`docs/reference/gemini-opencli-bridge.md`](docs/reference/gemini-opencli-bridge.md) | Hermes-facing localhost Gemini bridge via OpenCLI (issue #105) — install, bind, security boundary | When OpenCLI version/setup changes |
| [`docs/operations/sessions/`](docs/operations/sessions/)                               | Durable session handoffs (e.g. herdr workstation); prefer these over chat-only wrap-ups       | Each handoff             |
| [`registry/ports.yml`](registry/ports.yml), [`registry/paths.yml`](registry/paths.yml) | Port/path allocation authorities — check before adding either                                 | As allocations change    |
| [`human/`](human/)                                                                     | Operator-only tasks, credentials checklists, decision records                                 | As needed                |
| `${OPS_ROOT:-~/ops}/stayturgid` (sibling)                                              | Public product — code, fleet conventions, product policy slice                                | N/A (other repo)         |
| `${OPS_ROOT:-~/ops}/site-private` (sibling)                                            | Private/generic companion — private policy slice + Claude generic memory                      | N/A (other repo)         |

## Conventions

- Follow the relay protocol (`docs/relay/PROTOCOL.md`) for the ongoing
  segmentation/AI-stack work — read the baton before re-planning.
- `just lint` and `bin/registry_lint.py` gate changes to `registry/`.
- **Run tests with `just test`** (or `just lint` for the unittest sweep), never
  a bare `python3 -m pytest` / `-m unittest`. Both recipes run under
  `uv run --with pytest --with pyyaml`; the system interpreter has no pytest,
  so a bare run dies on `import pytest` in `tests/test_hindsight_candidates.py`
  before a single test executes, which looks like a repo failure and is not one.
- Human-only tasks and operator decisions live under `human/` — do not
  auto-commit changes there without the operator's review; check `git status`
  before committing, since operator-authored files here are sometimes
  mid-edit.
- Site-specific facts (real hostnames, IPs, credentials-adjacent config)
  belong here, never in `stayturgid`.

### Versioned deploy releases

**Retired 2026-08-23 by operator decision.** The `${OPS_ROOT:-~/ops}`
checkouts are now worked in directly with ordinary git (edit, commit to
`master`, push). Coordinated `ops-vMAJOR.MINOR.PATCH` releases and
`just ops-memory-sync` are no longer required — the latter's release-gating
precondition is exactly what was retired, and it had been failing for this
repo because of it. See "Where work happens" in `~/CLAUDE.md`.

This repo still owns the release/deploy tooling, now optional:

```bash
just ops-release-claim-status
just ops-release-claim-begin 1.0.0 cut   # multi-agent reservation
just ops-release-check 1.0.0
just ops-release-deploy 1.0.0              # exclusive flock while mutating ~/ops
just ops-release-claim-end --version 1.0.0
just ops-release-status
just ops-memory-sync
```

Concurrent agents must not cut/deploy overlapping versions — use the claim +
flock helpers (`bin/ops_release_lock.py`). See
[docs/OPS-RELEASES.md](docs/OPS-RELEASES.md). Development synchronization
inside `~/src/ops-worktrees/` still uses `master`; that is not a deployment.

### `research/` — data-directory exception (added 2026-08-17)

`research/` holds research/plan document packages and is **live data, not
code**: like `site-private/memory/`, it is exempt from the
branch/PR/worktree/release flow. Commit changes to it directly to `master`,
in place, in the `~/ops/site-djbclark` deploy checkout — run
`just ops-memory-sync` first (it now guards both data dirs), make a
research-only commit, push immediately, leave the tree clean. The exemption
is enforced by the `DATA_DIRS` mapping in `bin/deploy_ops_release.py`; it is
narrow — everything else in this repo still uses the release flow.

**This repo is public.** Nothing containing secrets or private-only context
may land under `research/`; that material belongs in `site-private`. Each
package gets its own subdirectory (first: `research/autonomy/`, the
2026-08-16 unattended-continuous-AI-coding plan).

### Tooling: modern CLI tools and structural search

Which modern CLI tools to prefer (and their older equivalents), plus how to
use `ast-grep` and `semgrep` for structural search, now live in
**[docs/tooling-policy.md](docs/tooling-policy.md)** — moved 2026-08-24
because it is reference material and this file loads every session.

> **If you cannot read `docs/tooling-policy.md`, say so rather than falling
> back on habit.** It is a normal file in this repository; not being able to
> open it means your checkout or file access is broken, and the operator
> wants to know.

Short version: prefer `rg` over `grep`, `fd` over `find`, `ast-grep` for
structural code search, and `gh` over raw API calls.

## Multi-Agent Protocol

Before any edit in a source task worktree:
`git fetch origin --prune && git pull --ff-only origin master`.
Always commit and push when done. Leave no uncommitted changes you didn't
create. If `git pull` fails with a merge conflict, STOP and report it. Verify
changes are yours before editing — if a file has unrelated modifications from
another agent or the operator, leave it alone and report it.
