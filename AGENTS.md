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
- Human-only tasks and operator decisions live under `human/` — do not
  auto-commit changes there without the operator's review; check `git status`
  before committing, since operator-authored files here are sometimes
  mid-edit.
- Site-specific facts (real hostnames, IPs, credentials-adjacent config)
  belong here, never in `stayturgid`.

### Versioned deploy releases

The three `${OPS_ROOT:-~/ops}` deploy checkouts advance only to coordinated
stable GitHub Releases tagged `ops-vMAJOR.MINOR.PATCH`; never deploy with a raw
`git pull origin master`. This repo owns the release/deploy procedure and
guarded memory synchronization:

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

### Modern CLI tool policy (any vendor AI, any of the three repos)

Homebrew-installed machine-wide, decided 2026-07-24 by testing candidates
from [ComposioHQ/awesome-agent-clis](https://github.com/ComposioHQ/awesome-agent-clis)
and [thegdsks/awesome-modern-cli](https://github.com/thegdsks/awesome-modern-cli)
head-to-head against the incumbents. Source of truth for the package list:
[`brew/fragments/agent-cli-tools.yml`](brew/fragments/agent-cli-tools.yml)
(stack `agent-cli-tools` in [`generated/Merged-Brewfile`](generated/Merged-Brewfile)).
Prefer these when shelling out:

| Use case               | Use                                                                                          | Not                          | Why                                                                                                                                                                                                  |
| ---------------------- | -------------------------------------------------------------------------------------------- | ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| search file text       | `rg`                                                                                         | `grep`, `ag`, `ack`, `ugrep` | benchmarked on stayturgid (799 files): rg 0.03s vs ag 0.57s vs ugrep 1.09s vs ack 3.13s for the same search; only rg/ugrep support `--json`, rg won on speed so ag/ugrep/ack weren't kept            |
| find files             | `fd`                                                                                         | `find`                       | respects `.gitignore`, simple glob syntax, faster                                                                                                                                                    |
| view files in shell    | `bat`                                                                                        | `cat`                        | line numbers + syntax highlighting                                                                                                                                                                   |
| find/replace           | `sd`                                                                                         | `sed`                        | plain regex, no backslash-escaping hell                                                                                                                                                              |
| list directories       | `eza`                                                                                        | `ls`                         | saner default columns/colors, git-aware                                                                                                                                                              |
| cut/select columns     | `hck`                                                                                        | `awk`/`cut`                  | simple `-f`/`-d` flags — `choose` was tried too but isn't packaged in Homebrew (only `choose-gui`/`choose-rust` exist under different names), so skipped                                             |
| git diffs/pager        | `delta` (set globally as `core.pager` + `interactive.diffFilter` in gitconfig)               | raw `git diff`               | syntax-highlighted, line-numbered hunks                                                                                                                                                              |
| JSON                   | `jq` (Homebrew build at `/opt/homebrew/bin/jq`, ahead of macOS-system `/usr/bin/jq` on PATH) | —                            | newer jq (1.8.x) vs system's 1.7.1                                                                                                                                                                   |
| YAML query/edit        | `yq`                                                                                         | inline python/`grep` on YAML | jq-style query syntax for the ansible/registry/brew-fragment YAML these repos actually have                                                                                                          |
| ad-hoc JSON API calls  | `xh`                                                                                         | raw `curl`                   | pretty-prints + colorizes JSON by default (verified against `curl` on local grafana/ollama endpoints) instead of a manual `\| jq` follow-up; `curl` is still right for uploads/non-JSON/complex auth |
| spelling in docs/prose | `typos` (already installed) — run before finalizing AGENTS.md/docs edits                     | manual proofreading          | catches misspellings for free; ran clean on all three repos' AGENTS.md as of 2026-07-24                                                                                                              |

**Tried and rejected:** `difftastic` (structural diff) — tested head-to-head
against `delta` on a reordered/reformatted dict-key diff; it did not
reconstruct the reorder any more cleanly than delta's word-diff, so no
demonstrated token win over the already-adopted `delta`. Not installed.

These govern **raw shell/bash use** — Codex, other bash-first agents, and
this operator's terminal. They do **not** change Claude Code's own dedicated
tools (`Read`/`Edit`/`Grep`/`Glob`), which stay preferred over shelling out
to any of the above when an equivalent dedicated tool exists; this table only
governs the Bash-tool fallback path and agents without those dedicated tools.

### Structural/semantic code search — `ast-grep` and `semgrep`

**Goal is tokens, not raw speed.** `rg` (and Claude Code's dedicated `Grep`
tool) only match text/regex per line — the agent still has to _read_ every
hit and manually reason about which are real (multi-line calls get missed
entirely; string literals containing the pattern text are false positives).
`ast-grep` and `semgrep` parse actual syntax, so the tool itself does that
filtering — fewer, cleaner hits, less context spent verifying matches.
Verified 2026-07-24: searching for `subprocess.run(..., shell=True, ...)` in
a file with a real multi-line call plus a decoy string literal containing
`"shell=True"`, `rg` returned both (agent has to discard the string by
hand); `ast-grep`/`semgrep` returned only the real, correctly-reconstructed
call.

**Use structural search instead of `rg`/`Grep` whenever the query is about
code shape, not literal text** — e.g. "find all calls to X regardless of
argument order/formatting/line breaks," refactors, or security-pattern
scanning (bare `except`, `shell=True`, hardcoded secrets, SQL string
concatenation, etc.). This applies even inside Claude Code, since the
built-in `Grep` tool has the same text-only limitation as `rg` — shell out
via Bash to `ast-grep`/`semgrep` for structural queries instead.

- **`ast-grep`** (aliased `sg`, but prefer the unaliased `ast-grep` — `sg` is
  the deprecated name) — general-purpose structural search _and rewrite_,
  any language, no rule file needed for one-off queries:
  ```
  ast-grep run -p 'subprocess.run($$$ARGS, shell=True)' -l python .   # search
  ast-grep run -p 'foo($ARG)' -r 'bar($ARG)' -l python . -U           # rewrite, apply without confirmation
  ast-grep run -p 'foo($ARG)' -r 'bar($ARG)' -l python . -i           # rewrite, interactive confirm per hit
  ```
  `$FOO` matches one node, `$$$FOO` matches zero-or-more (e.g. arg lists).
- **`semgrep`** — same structural matching, but its real strength is the
  huge existing registry of security/correctness rules (already used by the
  `security-review` skill) rather than one-off patterns:
  ```
  semgrep --lang python --pattern 'subprocess.run(..., shell=True, ...)' --metrics off .   # one-off pattern
  semgrep --config p/security-audit --metrics off .                                        # registry ruleset
  ```
  `...` is semgrep's wildcard for "any args here."

Both were installed and benchmarked head-to-head against the same repo
before adoption — see
[`memory/reference_agent_cli_tool_policy.md`](https://github.com/djbclark/site-private/blob/master/memory/reference_agent_cli_tool_policy.md)
in site-private for the full evaluation notes.

## Multi-Agent Protocol

Before any edit in a source task worktree:
`git fetch origin --prune && git pull --ff-only origin master`.
Always commit and push when done. Leave no uncommitted changes you didn't
create. If `git pull` fails with a merge conflict, STOP and report it. Verify
changes are yours before editing — if a file has unrelated modifications from
another agent or the operator, leave it alone and report it.
