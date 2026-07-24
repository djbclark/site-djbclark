# site-djbclark

> **AI agents (any vendor):** this file is the entry point — the AGENTS.md
> convention that coding agents from multiple vendors check first. Project
> overview: [README.md](README.md). Continuation state for the ongoing
> segmentation/AI-stack work: [docs/relay/NEXT-PROMPT.md](docs/relay/NEXT-PROMPT.md).

Private **site repo** for djbclark's machines (M1 MacBook Air, Intel Mac
mini, Linux VPSs) — the identity/allocation authority paired with the public
product repo [stayturgid](https://github.com/djbclark/stayturgid). Base
layout is three sibling checkouts under `~/ops/`: this repo, `stayturgid`,
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
  [`~/ops/stayturgid/AGENTS.md`](https://github.com/djbclark/stayturgid/blob/master/AGENTS.md)
  (`https://github.com/djbclark/stayturgid/blob/master/AGENTS.md`).
- Private / Mac-wide / not-for-public extras →
  [`~/ops/site-private/AGENTS.md`](https://github.com/djbclark/site-private/blob/master/AGENTS.md)
  (`https://github.com/djbclark/site-private/blob/master/AGENTS.md`).

**Never commit passwords or secrets** (same rule as the other two). IPs and
hostnames for this site are expected here.

**Symlinks** under `~` (`AGENTS.md`, `CLAUDE.md`, other root-level vendor agent
files) and `~/.claude/.../memory` are documented in site-private /
stayturgid — not duplicated here. The supported optional local selector is
`~/ops/.mysite` → this checkout; do not use `.mysite` in GitHub URLs.
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
| [`registry/ports.yml`](registry/ports.yml), [`registry/paths.yml`](registry/paths.yml) | Port/path allocation authorities — check before adding either                                 | As allocations change    |
| [`human/`](human/)                                                                     | Operator-only tasks, credentials checklists, decision records                                 | As needed                |
| `~/ops/stayturgid` (sibling)                                                           | Public product — code, fleet conventions, product policy slice                                | N/A (other repo)         |
| `~/ops/site-private` (sibling)                                                         | Private/generic companion — private policy slice + Claude generic memory                      | N/A (other repo)         |

## Conventions

- Follow the relay protocol (`docs/relay/PROTOCOL.md`) for the ongoing
  segmentation/AI-stack work — read the baton before re-planning.
- `just lint` and `bin/registry_lint.py` gate changes to `registry/`.
- Human-only tasks and operator decisions live under `human/` — do not
  auto-commit changes there without the operator's review; check `git status`
  before committing, since operator-authored files here are sometimes
  mid-edit.
- Site-specific facts (real hostnames, IPs, credentials-adjacent config)
  belong here, never in `stayturgid`.

## Multi-Agent Protocol

Before any edit: `git fetch origin --prune && git pull --ff-only origin master`.
Always commit and push when done. Leave no uncommitted changes you didn't
create. If `git pull` fails with a merge conflict, STOP and report it. Verify
changes are yours before editing — if a file has unrelated modifications from
another agent or the operator, leave it alone and report it.
