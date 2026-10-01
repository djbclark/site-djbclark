# Prompt: apply the djbclark / frdminc / Graft development toolchain to a repo

Version 5 (2026-10-01). Supersedes `CLAUDE_APPLY_DJBCLARK_TOOLING_Version4.md`.
Written for `Kuriboh493/perp-option-pricer`; the target-specific facts are
confined to §P0 and §12 so the rest can be reused for another repo.

## Preamble (for the human; not part of the prompt)

Here is a prompt you could choose to drop into an **Opus 5.5 session at high
effort** in Claude Code. It orchestrates: the Opus session plans, integrates,
commits and talks to you, and it hands mechanical work to Haiku and Sonnet
subagents, so most of the tokens are spent on the cheaper models.

Alternatively, tell Claude to **read the prompt, consider it, and take no
action yet**, and then ask it to extract a subset that fits roughly the number
of tokens, the amount of money (only if you are on API pay-as-you-go, which I
strongly advise against for this; use a subscription plan and its session
windows instead), or the session time you are willing to spend. Good natural
cut points are the phase boundaries in §3: for example "§1 to §6 only, no
backport, no CI, no CodeRabbit" is a quarter of the work and leaves the repo
strictly better than before.

Practical notes before you paste it:

1. Start the session in a clean checkout of the target repo on its default
   branch, with `git status` clean, and run `/model` to confirm Opus is
   selected. Set effort to high (`/effort high` where the installed version
   offers it; otherwise it is the default for Opus).
2. The prompt assumes Claude Code 2.1.x (October 2026). It tells the
   orchestrator to verify every version-specific detail against the live docs
   at https://code.claude.com/docs/ before relying on it.
3. Everything that needs an account, a password or a decision from you is
   deferred to one interactive phase (§12), one step at a time, so you can walk
   away during the autonomous phases.
4. Nothing outside git is changed without a backup and a restore recipe (§15).
   Read §15.4 at the end to see how to undo any of it.
5. It is long on purpose. A long, specific prompt costs a few thousand input
   tokens once and saves many round trips of clarification; the token rules in
   §0.5 are where the real savings are.

What changed from Version 4, so you can diff the intent rather than the text:
Graft's install and commit policy follow its current upstream README; the
subagent definitions use the current frontmatter fields (`effort`,
`permissionMode`, `maxTurns`, `memory`) and the `fable` alias is explicitly
excluded; a new §0.6 activates a curated set of Claude Code skills and plugins
and explains each one to you; `AGENTS.md` is now the canonical agent file with
a one-line `CLAUDE.md` importing it, because Claude Code only auto-loads
`CLAUDE.md`; the `tendcf` reference was corrected (it uses `core.hooksPath`,
not the pre-commit framework); doc links point at `code.claude.com`; the
missing §14 is gone and sections are renumbered.

---

## The prompt (paste from here down)

### Apply the djbclark / frdminc / Graft development toolchain to `Kuriboh493/perp-option-pricer`

You are Claude Code, running as the **orchestrator** in a local checkout of
https://github.com/Kuriboh493/perp-option-pricer (default branch `main`).

Do the work; do not just propose it. Follow the phase order in §3 and the
orchestration plan in §0. Anything you cannot do yourself goes into the
**interactive phase** (§12), where you guide the user **one step at a time**.

Priorities, in order: **(1) don't break anything, (2) get good results,
(3) use as few tokens as possible.**

## P0. Facts about the target (verify them; do not trust them blindly)

- Primary language: Python (NumPy, SciPy, Pandas, PyArrow). Scripts run from
  their own folders: `common/`, `perps/`, `prediction-markets/`.
- `perps/index.html` is a standalone, dependency-free HTML app with inline CSS
  and a large inline JavaScript pricing engine. It is real source code.
- About 90 GB of downloaded research data lives in git-ignored `data/` and
  `reports/` directories. Tools must never scan it, and CI must never download
  it.
- A root `README.md` exists. No license file has been found.
- The user's GitHub login is `Kuriboh493`. They already have read access to the
  private `djbclark/coderabbit-feeder` repo.

### Global safety rule: back up before touching anything outside git

Before you edit, overwrite, move or delete **any file that is not tracked by
git**, back it up first (§15). This covers files inside the target repo and
outside it: `~/.zshrc`, `~/.gitconfig`, `~/.claude/*`, `.git/hooks/*`,
LaunchAgent plists, anything under `~/.config/`, untracked or ignored files in
any checkout, and tool config directories. Files tracked in git are already
recoverable through git and need no copy, but never discard uncommitted changes
to them.

---

## 0. Orchestration: built-in Claude Code subagents

### 0.1 Confirm what the installed Claude Code supports

Run `claude --version`, open `/agents`, and read the current docs:
https://code.claude.com/docs/en/sub-agents and
https://code.claude.com/docs/en/skills. Confirm, and adapt §0.3 if anything
differs:

- project subagents live in `.claude/agents/<name>.md` (user-level ones in
  `~/.claude/agents/`), with YAML frontmatter `name`, `description` (both
  required), and optional `tools`, `disallowedTools`, `model`,
  `effort` (`low` | `medium` | `high` | `xhigh` | `max`), `permissionMode`,
  `maxTurns`, `skills`, `memory`, `background` and `hooks`;
- `model` accepts the family aliases `haiku`, `sonnet`, `opus` and `fable`, a
  full model ID, or `inherit`. **Never use `fable`** in these definitions: it
  is the most expensive tier and this work does not need it. If the user's plan
  includes it and they ask for it on a specific judgment call, that is their
  decision;
- independent subagents run in parallel (default cap 20, env
  `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`), each in its own context window, and
  only the final reply returns to you.

**Agent teams** (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`,
https://code.claude.com/docs/en/agent-teams) are still experimental and off by
default. Do **not** enable them; plain subagents are enough here. Use them only
if plain subagents prove insufficient, and then only with user approval and a
backup of any settings file you change (§15).

No external orchestrator (Herdr, Orca, Ralph TUI, Beads) is used.

### 0.2 Working rules for orchestration

Adapted from https://github.com/djbclark/claude-orchestration-skills (public;
read its `README.md` and `plugins/*/skills/*/SKILL.md` for detail; ignore its
Herdr/Ralph/Beads mechanics and its djbclark-specific paths).

1. **The orchestrator orchestrates.** Delegate mechanical and bounded work to
   subagents. Keep only planning, integration, judgment calls, commits and the
   interactive phase in the main session.
2. **Scope is the safety control.** Every delegation states: goal, exact files
   or paths allowed to change, files that must not change, commands allowed,
   what "done" means, and the reply format. Subagents doing research are
   read-only.
3. **Verify independently.** A subagent's "done" or "all green" is a claim, not
   a fact. Check it before accepting: rerun the command, inspect `git diff`,
   compare golden values. Status reports can be wrong in both directions.
4. **One writer per area.** Never let two writers touch the same file or
   worktree. Parallel writers need disjoint paths, or separate git worktrees
   (`git worktree add`) that the orchestrator integrates.
5. **Only the orchestrator commits, pushes and talks to the user.** Subagents
   never run `git commit`, `git push`, `gh pr`, account or settings changes,
   or interactive prompts.
6. **Handoff file.** Keep an untracked progress file at
   `~/.local/state/perp-tooling-work/HANDOFF.md`: current phase, done and
   pending steps, open decisions, commit SHAs, baseline status. Update it after
   every phase and before any context compaction (`/compact`), so a fresh
   session (`claude --continue` or `--resume`) can pick up with
   `Read HANDOFF.md and continue`. Claude Code's own auto-memory
   (`~/.claude/projects/<project>/memory/`) is a complement, not a substitute:
   it is not guaranteed to hold the exact resume state. If the
   `session-handoff` plugin from §0.6 is installed, use its Tier 1 pointer
   instead of a hand-rolled file and say so in the final report.

### 0.3 Subagents to create

Create these files under `.claude/agents/` in the target repo. They are useful
after this setup too; keep and commit them, and mention them in `AGENTS.md`.

| Agent | Model / effort | Tools | Job |
|---|---|---|---|
| `scout` | haiku / medium | Read, Grep, Glob, Bash (read-only commands), WebFetch | Inventory a repo or directory; extract specific config facts from a reference repo; return compact structured findings |
| `installer` | haiku / low | Bash | Check and install tools from §1; return a table of tool → version → status |
| `researcher` | sonnet / medium | Read, Grep, Glob, WebFetch, WebSearch | Find tools for uncovered formats (§2), exact current install commands, and docs questions |
| `config-writer` | sonnet / medium | Read, Edit, Write, Bash | Write the tool configuration files assigned to it, and nothing else |
| `test-author` | opus / high | Read, Edit, Write, Bash | Write characterization and golden tests (§5) |
| `backport-worker` | sonnet / medium | Read, Edit, Write, Bash | Apply one tool's fixes to the paths assigned to it (§7) |
| `numeric-reviewer` | opus / high | Read, Grep, Bash (read-only) | Review diffs to numerical code and the pricer for any change in meaning |
| `verifier` | sonnet / low | Read, Bash (read-only checks) | Run named `just` recipes and baseline comparisons; report pass/fail and exact failures |
| `docs-writer` | sonnet / medium | Read, Edit, Write | README, AGENTS.md, the skill, CHANGELOG, contributor docs |
| `fork-auditor` | opus / high | Read, Grep, Glob, Bash (read-only) | Find and classify environment-specific hardcoding (§14.1) |
| `fork-generalizer` | sonnet / medium | Read, Edit, Write, Bash | Generalize one forked repo in its own checkout (§14.3) |

Each file's body is its instructions. Include the §0.2 rules that apply, its
reply format (§0.5), and the reminder that it never commits, pushes or changes
accounts or settings. Give read-only agents `permissionMode: plan` or a
`disallowedTools` list covering Edit and Write, and set `maxTurns` on the
cheap ones so a confused Haiku run cannot loop. Example:

```markdown
---
name: verifier
description: Runs named quality gates and baseline comparisons and reports exact results. Use after any change.
tools: Read, Bash
disallowedTools: Edit, Write, NotebookEdit
model: sonnet
effort: low
maxTurns: 30
---
Run only the commands you are given. Do not edit files. Report each command,
its exit code, and the exact failing lines (at most 40 per command). Compare
baseline output against tests/baseline/BASELINE.md and list every difference.
Never say "passed" without showing the command's exit code.
```

### 0.4 Parallelism plan

Run independent work in parallel; keep anything with dependencies or shared
files sequential.

| Phase | In parallel | Must stay sequential |
|---|---|---|
| Inspect (§4) | one `scout` per reference repo, plus one `scout` for the target; `installer` starts at the same time | none |
| Install (§1–§2) | `installer` runs while scouts work; `researcher` handles uncovered formats | nothing installs into the target repo until inspection is done |
| Skills and plugins (§0.6) | none (settings files; orchestrator only) | after backups (§15) exist |
| Forks (§14) | one `fork-auditor`, then one `fork-generalizer` per repo, each in its own checkout | forking, pushing and approvals go through the orchestrator and the user |
| Baseline (§5) | Python tests and HTML/JS tests by separate `test-author`s, if their files are disjoint | the baseline run and recording, after both finish |
| Configure (§6) | several `config-writer`s, each owning distinct files | the orchestrator integrates `justfile` and `.pre-commit-config.yaml`, since they reference everything |
| Backport (§7) | read-only checks of one tool's output can run in parallel | **tool after tool, one at a time**, each followed by baseline verification and numeric review |
| Docs and CI (§8–§11) | `docs-writer` and the CI-workflow writer in parallel | license questions (interactive) |
| Interactive (§12) and feeder (§13) | none | everything, one step at a time |

### 0.5 Token budget rules

- Route by difficulty: Haiku for inventories, installs and version checks;
  Sonnet for configuration, docs and forks; Opus only for baseline tests,
  numerical review and the hardcoding audit. Set `effort` per agent as in
  §0.3; `max` and `xhigh` are never needed here.
- Subagents return **compact structured summaries** (tables or bullet lists,
  at most about 150 lines), with file paths and line numbers instead of pasted
  file contents.
- Read narrowly. Use the Graft MCP tools or `graft ask`/`graft skeleton` once
  the graph is built, `ast-grep`, `rg` and file line ranges instead of whole
  files. Never read the data directories.
- Write facts down once, in `HANDOFF.md` or `tests/baseline/BASELINE.md`, and
  point subagents at them instead of re-explaining.
- Don't re-run full suites when a targeted recipe answers the question, but
  always run the full baseline after each backport step.
- Keep failure output short: show the first failing lines, not entire logs.
- Don't delegate trivial one-command tasks; a subagent call has overhead.
- Run `/cost` (or read `/context`) at each phase boundary and note it in
  `HANDOFF.md`; the final report wants a per-phase estimate (§16).

### 0.6 Claude Code skills and plugins to activate, then explain

These are optional accelerators for the user's day-to-day work in this repo
after the setup. Install them **project-scoped where the mechanism allows**,
so the repo carries them and a fresh clone picks them up, and back up
`~/.claude/settings.json` and `.claude/settings.json` first (§15). Confirm
the current commands against https://code.claude.com/docs/en/plugins before
running them. Nothing here sends code anywhere; plugins are prompt and hook
bundles that run inside the user's own session.

**Built in to Claude Code (nothing to install; confirm each exists with
`/help`):**

| Command | What it does | When the user should reach for it |
|---|---|---|
| `/init` | Drafts a `CLAUDE.md` from the codebase | Not needed here (§8 writes `AGENTS.md`); use only to compare its draft against ours |
| `/code-review [low\|medium\|high]` | Reviews the current diff or a PR for correctness bugs; `ultra` runs a billed multi-agent cloud review | Before pushing any non-trivial change; `ultra` only for big risky branches |
| `/simplify` | Cleans up the changed code for reuse and simplicity without hunting bugs | After a feature works and before review |
| `/security-review` | Security pass over the current changes | Anything that touches input parsing, file handling or subprocesses |
| `/fewer-permission-prompts` | Scans transcripts and adds a read-only allowlist to `.claude/settings.json` | After a few sessions, when prompts get annoying |
| `/compact`, `--continue`, `--resume` | Context compaction and session resume | Long sessions; pair with `HANDOFF.md` |
| `/cost`, `/context` | Token and cost view | At phase boundaries |
| `/loop`, `/schedule` | Recurring local prompt; scheduled cloud routines | Only if the user wants unattended runs; not part of this setup |

**From the official marketplace** (`/plugin marketplace add
anthropics/claude-plugins-official` if it is not already known; then
`/plugin install <name>@claude-plugins-official`). Install the first group;
offer the second:

| Plugin | Install? | What it gives this repo |
|---|---|---|
| `commit-commands` | yes | `/commit`, `/commit-push-pr`: consistent commit messages and PR creation |
| `pr-review-toolkit` | yes | Specialised PR review agents (tests, error handling, type design, simplification); complements CodeRabbit with an in-session pass |
| `security-guidance` | yes | Pattern warnings on edits plus an LLM diff review on stop, catching injection, hardcoded secrets and similar in Claude-written code |
| `claude-md-management` | yes | Audits and maintains `AGENTS.md`/`CLAUDE.md` so §8 stays accurate as the repo evolves |
| `pyright-lsp` | yes | Python language server for Claude's own edits (type-aware navigation); `uv tool install pyright` or `bun add --dev pyright` as it requires |
| `typescript-lsp` | yes | Same for the inline JavaScript and any `.ts` tests |
| `skill-creator` | yes | Creates and evaluates skills; use it to write and validate `.claude/skills/dev-tooling` in §8 |
| `session-report` | yes | Local HTML report of token use per session; feeds the §16 cost note |
| `claude-code-setup` | offer | Analyses the repo and recommends hooks, skills and subagents; a good second-opinion pass after this prompt finishes |
| `hookify` | offer | Turn "never do X again" into a hook from a markdown rule; useful once the user has seen a repeated mistake |
| `code-simplifier` | offer | Agent form of `/simplify` for larger refactors |
| `feature-dev` | offer | Explore, design, implement, review workflow for new features |
| `ralph-loop` | no (mention only) | Self-repeating loops; not appropriate until the baseline and gates exist and the user has used the plain workflow for a while |

**From djbclark's orchestration marketplace** (public, MIT):

```text
/plugin marketplace add djbclark/claude-orchestration-skills
/plugin install session-handoff@claude-orchestration-skills
```

`session-handoff` provides the Tier 1 pointer file and a `PreCompact` hook
that checkpoints before compaction. Its hook needs copying into the hooks
directory and registering in `settings.json` (read its README); do that only
with the user's approval and a backup. Do not install `herdr-orchestration`
or `ralph-tui-orchestration`; they need tools this setup does not use.

**From Matt Pocock's skills marketplace** (public):

```text
/plugin marketplace add mattpocock/skills
/plugin install mattpocock-skills@mattpocock
```

Worth having for this repo: `tdd` (red-green-refactor, matches the §8 testing
rules), `diagnosing-bugs` (a disciplined loop for "it's wrong and I don't know
why", good for numerical regressions), `writing-for-agents` (when editing
`AGENTS.md` or the skill), `research` (captures findings as a markdown file in
the repo) and `code-review` (standards-vs-spec review). The rest are harmless
but unused.

**Graft's own wiring** (hooks, statusline and MCP server) is installed by
`graft init` in §6, not here.

**Explain each one to the user.** In the interactive phase (§12, step 2)
walk through the installed set one item at a time: what it is, the command
or trigger, when to use it, when not to, and how to remove it (`/plugin
uninstall <name>@<marketplace>`; the backup manifest for settings files). Ask
after each whether to keep it. Record the final set in `AGENTS.md` (§8 item
3) so other agents and future sessions know what is available.

---

## 1. Tool inventory

Install **everything in this section, even for languages and formats the repo
does not use yet**, so the tools are ready when they are needed. Check first
(`<tool> --version`) and skip anything already installed at a suitable version.
Never use `sudo pip install`.

### 1.1 Homebrew first

- **Homebrew**: https://brew.sh/ , the macOS package manager used for nearly
  everything below.

```bash
brew --version || /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
# If `brew` is not found afterwards:
eval "$(/opt/homebrew/bin/brew shellenv)"   # Apple Silicon
eval "$(/usr/local/bin/brew shellenv)"      # Intel
```

The Homebrew installer may ask for the macOS password. If it does, hand that
step to the user in the interactive phase. If the installer offers to add
`brew shellenv` to a shell profile, back that file up first (§15).

### 1.2 Install everything with Homebrew (one command)

```bash
HOMEBREW_NO_AUTO_UPDATE=1 brew install \
  git gh uv just oven-sh/bun/bun node \
  ruff pre-commit gitleaks typos-cli semgrep \
  shellcheck shfmt biome lychee dotenv-linter actionlint \
  openjdk coreutils caddy \
  ripgrep fd bat sd eza hck git-delta jq yq xh ast-grep

# Lighthouse and Puppeteer need a Chrome-family browser:
ls "/Applications/Google Chrome.app" >/dev/null 2>&1 || brew install --cask google-chrome

# Python CLIs installed as isolated global tools:
uv tool install ansible-lint
uv tool install pyinilint

# Graft (agent context graph); confirm the package name against the upstream README first (§1.3):
npm install -g @nanonets/graft
```

### 1.3 What each tool is, where it lives, and how it is installed

**Core workflow**

| Tool | Website | Install | What it does |
|---|---|---|---|
| Git | https://git-scm.com/ | `brew install git` | Version control |
| GitHub CLI `gh` | https://cli.github.com/ | `brew install gh` | GitHub from the terminal: repos, PRs, Actions, forks, collaborators |
| uv | https://docs.astral.sh/uv/ | `brew install uv` | Python interpreters, virtual environments, locked dependencies (`uv.lock`) |
| just | https://just.systems/ | `brew install just` | Command runner (`just test`, `just check`, …). `just --fmt --check` is the justfile linter/formatter |
| Bun | https://bun.sh/ | `brew install oven-sh/bun/bun` | Installs and runs repo-local JS tooling (`bunx`), with `bun.lock` |
| Node.js | https://nodejs.org/ | `brew install node` | Needed by Puppeteer, Lighthouse, Graft and npm-based tools |
| pre-commit | https://pre-commit.com/ | `brew install pre-commit` (also a locked project dev dependency) | Manages pinned git hooks |

**Python quality** (locked project dev dependencies, installed with `uv sync`)

| Tool | Website | What it does |
|---|---|---|
| pytest | https://docs.pytest.org/ | Test runner |
| Ruff | https://docs.astral.sh/ruff/ (also `brew install ruff`) | Lint, import sorting, formatting |
| mypy | https://mypy.readthedocs.io/ | Static type checking |
| Bandit | https://bandit.readthedocs.io/ | Python security lint |
| yamllint | https://yamllint.readthedocs.io/ | YAML lint |

**Docs, text and configuration**

| Tool | Website | Install | What it does |
|---|---|---|---|
| Prettier + prettier-plugin-toml + prettier-plugin-ini | https://prettier.io/ , https://github.com/un-ts/prettier | `bun add --dev` | Formatting for Markdown, TOML, INI, HTML, CSS and YAML |
| markdownlint-cli | https://github.com/DavidAnson/markdownlint-cli | `bun add --dev` | Markdown lint |
| typos | https://github.com/crate-ci/typos | `brew install typos-cli` | Spell check for source and docs |
| dotenv-linter | https://dotenv-linter.github.io/ | `brew install dotenv-linter` | Lints `.env` / `.env.example` |
| pyinilint | https://pypi.org/project/pyinilint/ | `uv tool install pyinilint` | Lints `.ini` files |
| lychee | https://lychee.cli.rs/ | `brew install lychee` | Link checker (run offline for docs) |

**HTML, CSS, JavaScript and web: include all of these** (modeled on `djbclark/stayturgid`)

| Tool | Website | Install | What it does |
|---|---|---|---|
| html-validate | https://html-validate.org/ | `bun add --dev html-validate` | Offline HTML structure and accessibility-markup lint |
| Nu HTML Checker (vnu-jar) | https://validator.github.io/validator/ | `bun add --dev vnu-jar` (needs Java: `brew install openjdk`; list it in `trustedDependencies`) | W3C-grade HTML validation |
| Stylelint + stylelint-config-standard | https://stylelint.io/ | `bun add --dev` | CSS lint, including inline `<style>` blocks |
| Biome | https://biomejs.dev/ | `brew install biome` | JS/TS/CSS lint and format |
| TypeScript `tsc` | https://www.typescriptlang.org/ | `bun add --dev typescript` | Type-checks JS through `checkJs` |
| pa11y | https://pa11y.org/ | `bun add --dev pa11y` | Accessibility audit of the rendered page |
| Puppeteer | https://pptr.dev/ | `bun add --dev puppeteer` | Headless browser smoke tests (page loads, no JS errors, finite outputs) |
| Lighthouse | https://developer.chrome.com/docs/lighthouse | `bunx lighthouse` (needs Chrome) | Full-page performance, accessibility and best-practices audit |

**Shell, CI, infrastructure and security**

| Tool | Website | Install | What it does |
|---|---|---|---|
| ShellCheck | https://www.shellcheck.net/ | `brew install shellcheck` | Shell static analysis (`-S warning`) |
| shfmt | https://github.com/mvdan/sh | `brew install shfmt` | Shell formatting (`-i 2 -ci`) |
| actionlint | https://github.com/rhysd/actionlint | `brew install actionlint` | Lints GitHub Actions workflows. Not used in the reference repos; added under the "same spirit" rule (§2) because this repo will have workflows |
| ansible-lint | https://ansible.readthedocs.io/projects/lint/ | `uv tool install ansible-lint` | Ansible lint (for when Ansible appears) |
| Caddy | https://caddyserver.com/ | `brew install caddy` | Only `caddy fmt` is used, for Caddyfiles |
| Gitleaks | https://github.com/gitleaks/gitleaks | `brew install gitleaks` | Secret scanning (`--redact`) |
| Semgrep | https://semgrep.dev/ | `brew install semgrep` | Structural search and curated security rules (see the gate policy in §6) |
| GNU coreutils | https://www.gnu.org/software/coreutils/ | `brew install coreutils` | `gtimeout` and other GNU tools for hooks |

**Agent and contributor CLI utilities** (from `site-djbclark`'s
`brew/fragments/agent-cli-tools.yml`, rationale in its `docs/tooling-policy.md`)

| Tool | Website | Install | Use instead of |
|---|---|---|---|
| ripgrep `rg` | https://github.com/BurntSushi/ripgrep | `brew install ripgrep` | `grep` |
| fd | https://github.com/sharkdp/fd | `brew install fd` | `find` |
| bat | https://github.com/sharkdp/bat | `brew install bat` | `cat` |
| sd | https://github.com/chmln/sd | `brew install sd` | `sed` |
| eza | https://eza.rocks/ | `brew install eza` | `ls` |
| hck | https://github.com/sstadick/hck | `brew install hck` | `cut` / `awk` |
| delta | https://dandavison.github.io/delta/ | `brew install git-delta` | Raw `git diff` |
| jq | https://jqlang.org/ | `brew install jq` | Hand-parsing JSON |
| yq | https://mikefarah.gitbook.io/yq/ | `brew install yq` | Hand-parsing YAML |
| xh | https://github.com/ducaale/xh | `brew install xh` | `curl` for JSON APIs |
| ast-grep | https://ast-grep.github.io/ | `brew install ast-grep` | `rg` for code-shape queries |

These govern shell use. Claude Code's own `Read`/`Grep`/`Glob`/`Edit` tools
stay preferred over shelling out when an equivalent exists (site-djbclark
`docs/tooling-policy.md`).

Do not change global git config (e.g. making delta the pager) without asking.
If the user agrees, back up `~/.gitconfig` first (§15).

**Agent context graph**

| Tool | Website | Install | What it does |
|---|---|---|---|
| Graft | https://github.com/trailhq/Graft (npm package `@nanonets/graft`) | `npm install -g @nanonets/graft`, or `npx @nanonets/graft init` without a global install. **Re-read the upstream README's Quick start and use its exact command; do not invent a package name.** | Builds a local, regenerable code-context graph under `graft/` (tree-sitter only; no model or key needed) and exposes it as an MCP server plus CLI (`graft init/build/map/ask/skeleton/callers/grep`), so agents read far less source. `graft init` wires hooks and a statusline into `.claude/`; see §6 for the policy |

Graft facts to respect (from the upstream README, 2026-09): `graft build`
adds `graft/` to `.gitignore` itself; the graph is a local cache like
`node_modules`, and what gets committed is the wiring under `.claude/`.
`graft init` merges into `.claude/settings.json` without clobbering, is
idempotent, and has `--dry-run`, `--agents claude`, `--no-hooks` and
`--no-statusline`. `graft build --deep` (LLM summaries) needs an API key and
is not used. The hosted side (`graft trail ...`, `graft init --trail`, and the
Graft GitHub App) sends code to a third party and is **opt-in only** (§12).
`graft uninstall` (dry-run without `-y`) is the inverse of `init`.

**GitHub-side services** (accounts and app installs happen in the interactive phase)

| Service | Website | What it does |
|---|---|---|
| GitHub Actions | https://docs.github.com/actions | CI running the same `just` gates |
| CodeRabbit | https://www.coderabbit.ai/ | AI pull-request review, label-gated by `review-ready` |
| coderabbit-feeder (private; used via a generalized fork, §14) | https://github.com/djbclark/coderabbit-feeder | Queues and paces CodeRabbit reviews of an entire codebase. Kuriboh493 already has access |
| Semgrep AppSec Platform (optional) | https://semgrep.dev/ | Hosted Semgrep scanning. Only if the user opts in |

**Kotlin (deliberate exception).** Do not install Kotlin tooling until Kotlin
code appears. Then copy `stayturgid`'s Gradle-plugin setup (Spotless + ktfmt,
detekt with a baseline, Konsist, JUnit 5/Kotest, Kover). Those tools are pinned
inside Gradle and are not meaningful as global installs.

---

## 2. Coverage rule for unlisted languages and formats

Inventory every tracked file type (`git ls-files | sed 's/.*\.//' | sort | uniq -c`,
plus extensionless scripts identified by shebang). For **any language or format
not covered in §1**, have a `researcher` find tools in the same spirit and treat
them as if they had been on the original list. The spirit is:

- a deterministic formatter, a linter, a type/static checker where one exists,
  and a security check where relevant;
- free and open source; installable through Homebrew, `uv tool`, or a locked
  `bun`/`uv` dev dependency; offline-capable; pinnable;
- runnable from `just`, pre-commit and CI.

For each one, report the website, install command, purpose and why it was
chosen. Then install it and wire it in exactly like the other tools.

---

## 3. Phase order (strict)

1. **Inspect** the target and the reference repos (§4).
2. **Install** all tools (§1–§2).
   - 2a. **Backup system:** create the backup store and its restore `justfile`
     (§15) before the first change to any untracked file.
   - 2b. **Subagents:** create `.claude/agents/*.md` (§0.3).
   - 2c. **Skills and plugins:** install the "yes" set from §0.6.
   - 2d. **Fork and generalize:** fork any reference project you will *run*
     that contains djbclark-specific hardcoding (§14). Do this before using any
     of those projects.
3. **Baseline:** write characterization tests against the *unchanged* code, run
   them, and record the outputs (§5). Do not change product code before this.
4. **Configure** the tooling (§6).
5. **Backport:** apply the tools across the existing codebase, re-running the
   baseline after each step (§7).
6. **Documentation and agent integration:** `AGENTS.md` plus `CLAUDE.md`
   import, the skill, README, and license (§8–§10).
7. **CI** (§11).
8. **Interactive phase** (§12): accounts, GitHub-side installs, the plugin
   walkthrough, approvals for forks and pushes, and a CodeRabbit test.
9. **Last:** feed the entire codebase to CodeRabbit through coderabbit-feeder
   (§13), only after everything above is verified working.

Update `HANDOFF.md` at the end of every phase.

---

## 4. Inspect first

Fan this out to `scout` subagents in parallel (§0.4). Each returns a compact
summary of the specific facts requested, with file paths.

**Target repo:** record the branch, `git status`, the Python version implied by
syntax and dependencies, how each script is invoked, existing tests, the full
`.gitignore`, existing hooks (including `core.hooksPath`), any existing
`AGENTS.md`/`CLAUDE.md`/`.claude/`, `LICENSE` and CI. Preserve unrelated local
changes. Do not assume a `src/` layout or an existing `tests/` directory.

**Reference repos.** All are public except `coderabbit-feeder`. Read their
current default branches. Do not copy them blindly.

- `djbclark/stayturgid`: `docs/toolchain.md` (the canonical toolchain and the
  "N+1 pattern": every tool appears in `justfile`, `.pre-commit-config.yaml`,
  its config file and CI), `.pre-commit-config.yaml`, `pyproject.toml`,
  `justfile`, `just/tests.just`, `package.json`, `.shellcheckrc`,
  `.coderabbit.yaml`, `AGENTS.md`, `docs/hacking.md`
- `djbclark/aiuse`: `pyproject.toml`, `.pre-commit-config.yaml`, `justfile`,
  `.yamllint`, `.markdownlint.json`, `package.json`, `.github/workflows/test.yml`,
  `AGENTS.md`
- `djbclark/site-djbclark`: `docs/tooling-policy.md`,
  `brew/fragments/agent-cli-tools.yml`, `.coderabbit.yaml`, `AGENTS.md`
- `djbclark/ops-djbclark`: `AGENTS.md` (non-interactive command rules),
  `docs/ops-worktrees-layout.md` (cross-agent rules),
  `docs/headless-claude-worker.md` (permission policy for unattended runs)
- `djbclark/claude-orchestration-skills`: `README.md`, `plugins/`
  (orchestration discipline, session handoff)
- `djbclark/RevengeQuickSwitcher`: its `justfile`, which mirrors the stayturgid
  tooling in a TypeScript project
- `djbclark/coderabbit-feeder` (private): `README.md`, `pyproject.toml`, `src/`
- `frdminc/tendcf` (a focused schema linter, `bin/schema_lint.py`, run from
  CI and from a plain `.githooks/pre-commit` via `core.hooksPath`; not the
  pre-commit framework), `frdminc/Shizuku` (`review-ready` convention in
  `.coderabbit.yaml`), `frdminc/sudo-secretspec` (`CLAUDE.md`, CHANGELOG
  discipline)
- `trailhq/Graft`: `README.md` (Quick start, Claude Code integration, CLI,
  uninstall), `package.json`, `docs/`
- other relevant public repos under https://github.com/djbclark and https://github.com/frdminc

Distinguish active, historical, project-specific and **deliberately retired**
policy. Cite the repo and file for each notable choice. Do not claim the review
was exhaustive if it wasn't.

---

## 5. Baseline characterization tests (before any tooling change)

Delegate to `test-author` (Opus); Python and HTML/JS tests can be written in
parallel by two subagents with disjoint files.

1. Create `tests/` (pytest) and, for the HTML app, a Puppeteer smoke test.
2. Write tests that pin **current behavior**, not desired behavior:
   - Python: pure functions in `common/` and the analysis scripts. Use small
     synthetic inputs, never the 90 GB data. Use mathematical invariants where
     they apply (no-arbitrage bounds, non-negative prices, put–call parity,
     monotonicity, zero-volatility and zero-jump limits) plus golden values
     captured from the current code. Use explicit tolerances.
   - HTML pricer: load `perps/index.html` from `file://`; click each preset
     (BTC/ETH/US stock/Gold), each model (Merton/Bates) and European/everlasting;
     assert no console errors or uncaught exceptions; assert price/Greeks fields
     are finite; capture golden displayed values for the default preset. Also
     extract the pure `<script id="math">` functions (`Ncdf`, `black`,
     `fairPerp`, `euro`, `impliedVol`, …) in a Node test and assert invariants
     and golden values.
   - Scripts that need missing data: assert they import or parse arguments
     cleanly, or mark them `@pytest.mark.data` and skip by default.
3. The orchestrator runs everything (or has a `verifier` run it) and **records
   the outputs** in `tests/baseline/BASELINE.md`: the date, commit SHA,
   interpreter and tool versions, commands, full pass/fail output, and the
   golden values. Commit the golden data with the tests.
4. Rule: if a baseline test fails on the untouched code, it is a finding. Record
   it and do not "fix" the product code to make it pass.

---

## 6. Tooling configuration

Split distinct config files across parallel `config-writer`s. The orchestrator
writes the `justfile` and `.pre-commit-config.yaml` itself, because they tie
everything together.

Follow stayturgid's **N+1 pattern**: every tool appears consistently in the
`justfile`, `.pre-commit-config.yaml`, its config file, and CI.

- **`pyproject.toml` + `uv.lock`:** runtime deps (numpy, scipy, pandas, pyarrow)
  and a `dev` group (pytest, ruff, mypy, bandit, yamllint, pre-commit).
  Don't invent a license string before §10. Don't create a package/`src/`
  migration.
  - Ruff: `line-length = 120`, target matching Python, `select = ["E","F","I","W"]`,
    `ignore = ["E501","E402"]`, `line-ending = "lf"`. Evaluate `UP`, `B` and `SIM`
    (used in coderabbit-feeder).
  - mypy: `explicit_package_bases`, `ignore_missing_imports`,
    `warn_redundant_casts`, `warn_unused_ignores`, `warn_unreachable`,
    excluding `.venv/` and data.
  - pytest: `testpaths = ["tests"]` and a `data` marker excluded by default.
- **`package.json` + `bun.lock`:** all JS and web dev deps from §1, with
  `"trustedDependencies": ["vnu-jar"]` and `"private": true`.
- **Config files:** `.yamllint` (aiuse's: `extends: default`, line length 160,
  truthy values `["true", "false"]`, forbid implicit and explicit octal),
  `.markdownlint.json` (aiuse/stayturgid rule set: `default: true` with
  MD013, MD024, MD028, MD029, MD031, MD033, MD034, MD036, MD038, MD040, MD041,
  MD046 and MD056 off), `.html-validate.json`, `.stylelintrc.json`,
  `biome.json`, `.shellcheckrc`, `.typos.toml` (only for real domain words such
  as Kalshi, Polymarket, Deribit, Bates), and `.coderabbit.yaml` exactly as
  stayturgid and Shizuku have it:

  ```yaml
  reviews:
    auto_review:
      enabled: false
      labels:
        - "review-ready"
  ```

- **`justfile`** (`set shell := ["bash", "-uc"]`) with recipes for:
  `setup test baseline ruff mypy bandit yamllint markdownlint prettier typos
  html-validate vnu stylelint biome tsc pa11y puppeteer lighthouse lychee-docs
  shellcheck shfmt actionlint dotenv-linter pyinilint gitleaks semgrep-audit
  graft-build just-check check lint lint-offline format pre-commit ci`.
  - Every recipe works on `git ls-files` output or explicit paths, never the
    data directories.
  - A recipe for a format that is absent passes with "no files", so tools stay
    wired in for later.
  - Browser-dependent checks (Lighthouse) are skipped cleanly when Chrome is
    unavailable. `lint-offline` skips anything network-dependent.
  - `check` is the fast deterministic gate, `lint` is `check` plus security, and
    `ci` is exactly what GitHub Actions runs.
- **`.pre-commit-config.yaml`**, with
  `default_install_hook_types: [pre-commit, pre-push]`:
  - **pre-commit:** fast file-level checks: Ruff fix+format, typos,
    markdownlint, Prettier check, yamllint, html-validate, Stylelint, Biome,
    ShellCheck, shfmt, actionlint, dotenv-linter, pyinilint, `just --fmt --check`,
    Bandit, Gitleaks.
  - **pre-push:** pytest, mypy, the Node/Puppeteer tests and `vnu`.
  - Never recurse. Never silently `git add` generated output: copy stayturgid's
    pattern in `.pre-commit-config.yaml` that fails and names the unstaged
    files so the developer reviews and stages them.
- **Semgrep policy:** install it and add `just semgrep-audit` using a
  **curated** ruleset (for example `p/python`, `p/security-audit`) with
  `--metrics off`. Do **not** add `--config auto` as a blocking gate. stayturgid
  removed its semgrep pre-commit hook on 2026-08-23 (commits `0319f25` and
  `3cf92e3`) after an audit found it only produced unjustified suppressions and
  false positives. Promote a curated ruleset to a gate only if its findings on
  this repo are actionable, and every suppression must carry a written
  justification.
- **Graft:** back up `.claude/settings.json` and `~/.claude/settings.json`
  (§15), then run `graft init --dry-run` and show the file list in
  `HANDOFF.md`. If it is acceptable, run `graft init --agents claude` and
  `graft build`. Follow upstream: `graft/` stays git-ignored (it is a local
  cache), the `.claude/` wiring is committed, and `just graft-build` wraps
  `graft build`. Keep the hooks only if a trial session shows they are not
  noisy; otherwise re-run `graft init --no-hooks`. If `init` fails, needs
  credentials, or the graph adds noise, document that it was declined and
  run `graft uninstall` (dry-run first).
- **`.gitignore`:** add caches (`.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`,
  `node_modules/`, `.coverage`, `htmlcov/`, browser and lighthouse output,
  `graft/` if `graft build` did not add it) and keep the data/report
  exclusions.
- Install hooks (back up any existing untracked `.git/hooks/*` first, §15):
  `uv run pre-commit install --hook-type pre-commit --hook-type pre-push --install-hooks`.

---

## 7. Backport the tools into the existing codebase

**Sequential, one tool at a time.** Order: formatters (Ruff format, Prettier,
Biome, shfmt), then safe autofixes (Ruff `--fix`), then linters, types,
HTML/CSS, accessibility and security.

For each tool:

1. A `backport-worker` applies that one tool's changes to the paths it is
   assigned.
2. A `verifier` runs `just baseline` and compares against
   `tests/baseline/BASELINE.md`. Golden values must match within tolerance, and
   no test may regress.
3. If the diff touches numerical code or `perps/index.html`, a
   `numeric-reviewer` checks that nothing changed meaning: no reordering of
   floating-point operations, no altered constants, no changed defaults.
4. The orchestrator checks the diff itself, then makes one focused local commit
   per tool, e.g. `style: apply ruff format`.

Independent read-only checks of the result (e.g. running several linters) can
run in parallel. Edits cannot.

Rules:

- Fix real findings. Use **narrow, justified** suppressions only; a bare
  `# noqa`/`# nosemgrep` without a reason is not allowed.
- If fixing a finding would change results, stop and report it instead.
- For the HTML pricer, keep it single-file and dependency-free. If a reformat
  would produce a huge diff that is hard to review, prefer lint-only plus
  targeted fixes and record that decision.
- Finish with `just ci`, `just lint` and `just baseline` all green, and record a
  final run below the baseline in `BASELINE.md`.

---

## 8. Agent instructions file and skill

`docs-writer` drafts; the orchestrator reviews.

**Which file:** `AGENTS.md` is canonical (the cross-vendor convention). Claude
Code auto-loads only `CLAUDE.md`, so also create a `CLAUDE.md` whose entire
content is the import line `@AGENTS.md` (or a symlink, if the user prefers;
imports are the portable choice). If a `CLAUDE.md` with real content already
exists, move that content into `AGENTS.md` and leave the import behind. Never
maintain two divergent copies. Add these sections:

1. **Required skill.** "Before any code change, load and follow the
   `dev-tooling` skill at `.claude/skills/dev-tooling/SKILL.md`."
2. **Commands:** `just setup`, `just test`, `just check`, `just lint`,
   `just format`, `just ci`, `just baseline`.
3. **Subagents, skills and plugins:** list `.claude/agents/`, the installed
   plugins and skills from §0.6 with one line each, the model routing rule
   (Haiku mechanical, Sonnet standard, Opus for numerical correctness and
   risky judgment, never Fable unless the user asks), the §0.2 rules, and the
   parallelism rule (parallel reads, disjoint writes, one tool at a time for
   codebase-wide changes).
4. **Testing rules** (from stayturgid, aiuse and coderabbit-feeder):
   - Run the full test suite before **and** after every change.
   - Every bug fix gets a regression test. Every new feature gets tests.
   - Pin behavior with characterization or golden tests before refactoring.
   - For numerical code, test invariants with explicit tolerances.
   - Tests are offline and deterministic. Tests that need data are marked
     `data` and excluded from CI.
   - Never weaken or delete a test to make it pass.
5. **Coding and workflow guidelines** (from the reference repos; adjust as needed):
   - Make one coherent change at a time. Commit early and often.
   - Don't trust a clean exit code; verify real outputs and state (ops-djbclark).
   - Use non-interactive command forms (`cp -f`, `mv -f`, `rm -f`, `ssh -o
     BatchMode=yes`, `HOMEBREW_NO_AUTO_UPDATE=1`) (ops-djbclark).
   - Prefer `rg`, `fd`, `bat` and `sd` in shell; use `ast-grep`/`semgrep` for
     code-shape queries; use the Graft tools before broad source reading
     (site-djbclark, Graft).
   - Run `typos` before finalizing docs.
   - Keep the N+1 pattern in sync and bump tool versions in lockstep across
     `pyproject.toml`, `package.json`, `.pre-commit-config.yaml` and CI
     (stayturgid).
   - Suppressions need a written justification (stayturgid's Semgrep audit).
   - Never commit secrets. Gitleaks runs on every commit.
   - Hooks must not silently stage generated files.
   - Before merging, check provenance:
     `git log origin/main..HEAD` and `git diff origin/main...HEAD`. Green CI does
     not replace knowing what you are merging (ops-djbclark).
   - Never commit into a branch or worktree another agent created.
   - Back up untracked files before changing them.
   - No environment-specific hardcoding: use config, environment variables or
     derived values, with committed `*.example` files.
   - Keep a `CHANGELOG.md` "Unreleased" section for user-facing changes
     (sudo-secretspec).
   - Research results must not change silently. Any change to a model or number
     needs a test and a note.
6. **Review:** add the `review-ready` label to request a CodeRabbit review. Bulk
   or full-codebase reviews go through coderabbit-feeder; never create
   throwaway PRs by hand. Use `/code-review` and the `pr-review-toolkit`
   agents for the in-session pass first.

**Skill:** create `.claude/skills/dev-tooling/SKILL.md` using the
`skill-creator` plugin from §0.6, following the current skills docs
(https://code.claude.com/docs/en/skills; the vendor-neutral spec is
https://agentskills.io/specification if reachable), with YAML frontmatter:

```yaml
---
name: dev-tooling
description: Use this repository's quality toolchain (just, uv, pytest, ruff, mypy, pre-commit, HTML/CSS/JS checkers, security scanners, graft, CodeRabbit) and its subagents when writing, changing, testing, or reviewing code here.
---
```

The skill body should cover:

- a decision table: change type → which `just` recipes to run, and which
  subagent to use;
- the before/after-test rule and `just baseline`;
- how to add a test of each kind (pytest, Node math, Puppeteer);
- how to add a new language or format (§2 rule plus N+1 wiring);
- search-tool selection (Graft MCP / `graft ask` / `ast-grep` / `rg`);
- the token budget rules from §0.5, in short form;
- the suppression policy;
- how to request review (`review-ready` label; coderabbit-feeder for bulk).

Validate it with `skill-creator`'s evaluation, or with `skills-ref validate
.claude/skills/dev-tooling` if that validator is installed. Mirror the skill
at `.agents/skills/dev-tooling/SKILL.md` (or symlink it) so non-Claude agents
find it.

---

## 9. README

Keep the existing README content. Add a **Development** section covering macOS
bootstrap (the Homebrew one-liner from §1.2), `just setup`, the hook install,
daily commands, the testing rules, a pointer to `AGENTS.md` and the skill, the
plugin list, and the CI badge. Replace the manual `python -m venv` setup with
`uv`, but keep the "run scripts from their own folder" note.

---

## 10. License (interactive; only if no license exists)

If there is no `LICENSE`, ask the user **one question at a time**, waiting for
each answer:

1. Do you want others to be allowed to use, copy and modify this code at all?
   (If no: say no license file is needed, all rights stay reserved, and stop.)
2. Do you require anyone who distributes modified versions to publish their
   source under the same terms (copyleft)?
3. If yes: should that also apply when it is only offered over a network (AGPL),
   or only on distribution (GPL-3.0)? Is linking from proprietary code acceptable
   (LGPL/MPL-2.0)?
4. If no (permissive): do you want an explicit patent grant and
   patent-retaliation clause (Apache-2.0), or the simplest short license (MIT)?
5. Should the written research and documentation use a separate content
   license, e.g. CC BY 4.0?
6. Whose name and what year go in the copyright line?

Recommend one license with a one-sentence rationale. Point to
https://choosealicense.com/ for comparison. Once the user confirms, add the
canonical `LICENSE` text, set `license` in `pyproject.toml` and `package.json`
(`private: true` stays), and mention the license in the README.

---

## 11. CI

Add `.github/workflows/ci.yml`:

- runs on `pull_request` and `push` to `main`, with least-privilege
  `permissions: contents: read`;
- installs Python through `uv`, plus `just`, Bun, Java (for vnu) and Chrome
  (for Puppeteer);
- installs dependencies from the lockfiles (`uv sync --frozen`,
  `bun install --frozen-lockfile`);
- runs `just ci`, plus `actionlint` on the workflow itself;
- no secrets, no dataset downloads, no live market APIs;
- actions pinned to current stable majors. aiuse's workflow uses
  `actions/checkout`, `actions/setup-python`, `astral-sh/setup-uv`,
  `extractions/setup-just` and `oven-sh/setup-bun`; have a `researcher` check
  the current major of each rather than copying aiuse's pins.

Run `actionlint` locally before finishing.

---

## 12. Interactive phase: one step at a time

Only start after §5–§11 pass locally. For **each** step: say what it does, give
the exact command or URL, say what the user should see, then **wait for
confirmation** before giving the next step. Troubleshoot anything that doesn't
match. Skip steps that are already done (check first). No subagents here.

1. **Homebrew password:** only if §1.1 needed interactive authorization.
2. **Skills and plugins walkthrough** (§0.6): one item per turn, with what it
   is, how to invoke it, when to use it and how to remove it. Keep or drop
   each on the user's answer, then update `AGENTS.md`.
3. **GitHub CLI login:** `gh auth login` → GitHub.com → HTTPS → log in with a
   web browser. Then verify with `gh auth status` and
   `gh api /user --jq .login` (expected: `Kuriboh493`).
4. **Verify feeder access:** `gh repo view djbclark/coderabbit-feeder`. If it
   fails, the user checks https://github.com/notifications for a pending
   invitation and accepts it.
5. **Approve forks** (§14.2): for each repo that needs generalizing, confirm
   creating the fork and its visibility (private stays private).
6. **Notification preference** for forked tools such as coderabbit-feeder:
   none, log only, or the user's own command.
7. **Approve pushing each generalized fork branch** (§14.3).
8. **License questions** (§10), if no license exists yet.
9. **Review local commits:** show `git log --oneline origin/main..HEAD` and
   `git diff --stat origin/main...HEAD`, and get explicit approval.
10. **Authorize the push:** with the user's yes, run `git push origin main` (or
    push a branch and open a PR if the user prefers).
11. **GitHub Actions:** check
    https://github.com/Kuriboh493/perp-option-pricer/settings/actions allows
    Actions, then confirm the first run is green with `gh run list --limit 1`.
12. **CodeRabbit account:** go to https://www.coderabbit.ai/ → sign up with GitHub.
13. **CodeRabbit GitHub App:** install it on **only selected repositories** →
    `Kuriboh493/perp-option-pricer`. Review the permissions it requests.
14. **CodeRabbit plan:** note the plan and its review rate limit. The feeder's
    pacing assumes CodeRabbit's "Next review available in: N minutes" messages.
15. **Verify CodeRabbit:** open a tiny test PR, add the `review-ready` label,
    and confirm that a real CodeRabbit review appears. Close the PR afterwards
    without merging unless the user says otherwise.
16. **Optional branch ruleset:** require PRs and the CI check (use the real
    check name from step 11).
17. **Optional Semgrep platform:** explain that it sends code to a third party;
    proceed only if the user opts in (https://semgrep.dev/ → sign in with
    GitHub → select the repo).
18. **Optional Graft hosted (Trail) integration and GitHub App:** same opt-in
    rule. Local mode needs no account and is what §6 set up.
19. **Optional upstream suggestions** (§14.4): show each draft; open it only on
    approval.

---

## 13. Last step: feed the entire codebase to CodeRabbit with coderabbit-feeder

Do this only after the interactive phase is complete, CI is green, CodeRabbit
has produced a verified review, and the tooling commits are pushed. The
orchestrator does this directly, without subagents.

1. **Clone the generalized fork** (§14), not `djbclark/coderabbit-feeder`, into
   its own source checkout:

   ```bash
   gh repo clone Kuriboh493/coderabbit-feeder ~/src/coderabbit-feeder
   cd ~/src/coderabbit-feeder && git remote -v && uv sync --group dev && uv run pytest
   ```

   `git remote -v` must show `origin` pointing at the fork and `upstream` at
   `djbclark/coderabbit-feeder`.
2. **Read** its current `README.md`, `src/coderabbit_feeder/{cli,feeder}.py`,
   and `coderabbit-feeder --help` (subcommands as of 2026-08: `tick`, `build`,
   `list`, `add`, `add-crossfork`). Confirm the details below against the code
   before relying on them.
3. **Confirm the generalization from §14 is in place.** The known hardcoding
   that must already be fixed in the fork: `NOTIFY_TARGET` in `feeder.py`
   (djbclark's Telegram target), the unconditional `hermes send` call in
   `notify()` (it raises `FileNotFoundError` when `hermes` isn't installed,
   because `check=False` does not catch a missing executable), and every
   `/Users/djbclark`, `~/ops`, `com.djbclark.*` or `djbclark/...` default in
   code, docs, plists and examples. The user's chosen notification setting
   lives in local untracked config.
4. **Use an independent runtime directory.** Never use djbclark's queue or
   state. Back up any existing directory first (§15).

   ```bash
   mkdir -p ~/.config/coderabbit-feeder && cd ~/.config/coderabbit-feeder
   ```

   Always invoke it as:

   ```bash
   uv run --project ~/src/coderabbit-feeder coderabbit-feeder <cmd>
   ```

   Use **`--project`, never `--directory`.** `--directory` changes the working
   directory and writes the queue into the source checkout, where the
   scheduler never reads it (this is documented in the feeder's README).
5. **Configure `repos.toml`** in the runtime directory, following the format in
   the feeder's source. Point it at a dedicated, clean worktree of the target
   (for example `~/src/feeder-workspace/perp-option-pricer`), never the
   development checkout, with `gh_repo = "Kuriboh493/perp-option-pricer"`.
6. **Build the queue:** `coderabbit-feeder build`. It chunks the repo's tracked
   files into batches of at most 300 (CodeRabbit's review-slot limit). Then
   check `coderabbit-feeder list` and confirm the batches cover every tracked
   file and nothing from the data directories. Tell the user how many
   throwaway "audit" PRs this will open, and get confirmation.
7. **Smoke-test:** run `coderabbit-feeder tick` once by hand. Verify a real
   audit PR opened, it got the `review-ready` label and `@coderabbitai review`
   trigger, and `list` shows the queue advancing.
8. **Schedule it:** ask the user to choose between running `tick` manually or
   periodically, or installing a per-user LaunchAgent (`StartInterval` 300,
   `WorkingDirectory` = `~/.config/coderabbit-feeder`, `ProgramArguments` =
   `uv run --project ~/src/coderabbit-feeder coderabbit-feeder tick`, logs in
   that directory, a label in the user's own namespace, not `com.djbclark.*`).
   Install the LaunchAgent only if the user says yes, and record it in the
   backup manifest as "absent" so it can be removed (§15). Verify it with
   `launchctl list | grep coderabbit-feeder` and a log line showing a tick.
9. **Explain how to watch and act on results:** findings land in
   `~/.config/coderabbit-feeder/findings/`. Fix actionable findings with
   normal PRs under the AGENTS.md rules. The feeder never auto-commits fixes.

---

## 14. Fork and generalize anything with environment-specific hardcoding

Any reference project that you will **run, install from source or copy code
out of** (not merely read) must be checked for values specific to djbclark's
environment. If it has any, **fork it, generalize the fork, and use the fork**.
Never point the user's tools at djbclark's live infrastructure, accounts or
messaging.

### 14.1 Detect (`fork-auditor`, Opus)

In every candidate repo, search code, docs, configs, plists, workflows,
templates and tests:

```bash
rg -n -i --hidden -g '!.git' \
  -e 'djbclark' -e 'frdminc' -e '/Users/[A-Za-z0-9_-]+' -e '~/ops\b' -e 'site-(djbclark|private)' \
  -e 'telegram:' -e '\bhermes\b' -e 'com\.djbclark\.' -e '@(gmail|mit)\.(com|edu)' \
  -e 'greyhound|\.ts\.net' -e '100\.[0-9]+\.[0-9]+\.[0-9]+' -e 'ops-worktrees'
```

Then read each hit in context and classify it as one of:

- **environment-specific:** must be generalized (usernames, home paths,
  hostnames, Tailscale names or IPs, notification targets, email addresses,
  LaunchAgent labels, repo owners used as defaults, account names);
- **attribution or history:** leave it (copyright lines, changelog entries,
  upstream issue links, `authors` metadata);
- **intentional upstream reference:** leave it, but make it configurable if it
  is used as a default (e.g. `gh_repo` defaults).

Known case: `djbclark/coderabbit-feeder` (`NOTIFY_TARGET`, `hermes send`,
`/Users/djbclark/...` and `com.djbclark.coderabbit-feeder` in its README's
launchd instructions). Also check anything copied out of `stayturgid`,
`site-djbclark`, `aiuse` or `claude-orchestration-skills`, such as justfile
snippets that reference `~/ops/stayturgid`, `STAYTURGID_*` variables, `site-*`
discovery, or `~/src/ops-worktrees` paths (the `session-handoff` plugin's
default paths are its author's layout; adapt them). Templates and snippets
copied into the target repo get the same treatment, without forking.

Audits of different repos can run in parallel.

### 14.2 Fork (orchestrator, after user approval)

For each repo that needs changes:

```bash
gh repo fork <owner>/<repo> --clone=false --fork-name <repo>
#   creates Kuriboh493/<repo>. Keep a private source private; check with:
gh repo view Kuriboh493/<repo> --json visibility,parent
gh repo clone Kuriboh493/<repo> ~/src/<repo>
cd ~/src/<repo> && git remote add upstream https://github.com/<owner>/<repo>.git 2>/dev/null || true
git switch -c generalize-environment
```

If forking is blocked (for example, forking is disabled on the private repo),
stop and hand it to the interactive phase: the user asks djbclark to enable
forking or to push a generalized branch.

### 14.3 Generalize (`fork-generalizer`, one per repo, in parallel)

- Replace each hardcoded value with, in order of preference: a config file
  entry (with documented defaults), an environment variable, a CLI flag, or a
  value derived at runtime (`$HOME`, `gh api /user --jq .login`,
  `git remote get-url origin`).
- Defaults must be **safe and generic**. For notifications, the default is
  "log only". Optional notify commands run only when configured, and a missing
  executable is reported, never raised as an uncaught error.
- Where the user's own environment needs a specific value (their username,
  paths or notification choice), put it in a **local, untracked config file**
  plus a committed `*.example`. Do not hardcode the user's values in place of
  djbclark's.
- Update docs, README examples and plist templates to match.
- Add tests for each new configuration path, including "no notifier
  installed" for the feeder.
- Run the fork's own test suite before and after.
- Record each change in the fork's `CHANGELOG.md` "Unreleased" section.
- The orchestrator verifies the result, commits, and pushes to the **fork**
  only after user approval (§12). Never push to the upstream repo.

### 14.4 Use the fork, and offer it upstream

- All later steps (§13 especially) use the fork's clone.
- Draft an upstream issue or PR description explaining that the changes make
  the project portable (configurable values, safe defaults, no behavior change
  for djbclark when he sets his own config). Show it to the user; open it only
  if they approve.
- List every fork, its upstream, its branch and its changes in the final report.

---

## 15. Backups of untracked files, with a restore justfile

### 15.1 Store

Create one backup store for the whole session:

```bash
BACKUP_ROOT="$HOME/.local/state/perp-tooling-backups"
SESSION="$(date +%Y%m%dT%H%M%S)"
mkdir -p "$BACKUP_ROOT/$SESSION" && chmod 700 "$BACKUP_ROOT"
```

It lives outside every repo, so git operations can't delete it and it is never
committed.

### 15.2 Rule for each file

Before the first edit, overwrite, move or delete of any **untracked** path,
check `git ls-files --error-unmatch <path>` in its repo (or note that it is
outside any repo). If it is not tracked:

1. Copy it, keeping its metadata: `cp -p` for files, `cp -pR` for
   directories. For a symlink, record the link itself (`cp -P`) and its target.
2. If the path **does not exist yet** (you are about to create it), record an
   "absent" marker so restoring means removing what you created.
3. Back up each path only once per session. The first copy is the true
   original.
4. Append a line to `$BACKUP_ROOT/$SESSION/MANIFEST.tsv`:
   `id  original_path  kind(file|dir|symlink|absent)  sha256  reason`.
5. Never print the contents of files containing credentials. Note in the
   manifest that a backed-up file contains secrets.

Typical candidates: `~/.zshrc`, `~/.bash_profile`, `~/.gitconfig`,
`~/.claude/settings.json`, `~/.claude/plugins/*` (plugin installs edit it),
`.claude/settings.json` in the target (Graft and `/fewer-permission-prompts`
edit it), `.git/hooks/*`, `~/Library/LaunchAgents/*.plist`, `~/.config/*`, any
existing `~/.config/coderabbit-feeder/`, untracked or ignored files in the
target repo (e.g. a local `.venv`, local configs), and Homebrew-created shell
setup lines.

Subagents never write backups or the restore justfile. They tell the
orchestrator which untracked paths they need to change, and the orchestrator
backs them up first.

### 15.3 Restore justfile

Maintain `$BACKUP_ROOT/justfile` and update it as each backup is taken:

```just
set shell := ["bash", "-euo", "pipefail", "-c"]

backups := justfile_directory()

# List everything that can be restored (default).
default:
    @just --justfile "{{ backups }}/justfile" --list --unsorted
    @echo
    @echo "Manifest:"
    @column -t -s $'\t' "{{ backups }}"/*/MANIFEST.tsv

# Restore ~/.zshrc from session 20261001T120000 (backed up before adding PATH lines).
restore-zshrc-20261001T120000:
    #!/usr/bin/env bash
    set -euo pipefail
    src="{{ backups }}/20261001T120000/files/zshrc"
    dst="$HOME/.zshrc"
    if [[ -e "$dst" ]]; then cp -p "$dst" "$dst.pre-restore.$(date +%Y%m%dT%H%M%S)"; fi
    cp -p "$src" "$dst"
    echo "restored $dst"

# Remove ~/Library/LaunchAgents/<label>.plist (it did not exist before this session).
restore-launchagent-feeder-20261001T120000:
    #!/usr/bin/env bash
    set -euo pipefail
    dst="$HOME/Library/LaunchAgents/<label>.plist"
    launchctl bootout "gui/$(id -u)" "$dst" 2>/dev/null || true
    if [[ -e "$dst" ]]; then mv -f "$dst" "$dst.pre-restore.$(date +%Y%m%dT%H%M%S)"; fi
    echo "removed $dst (restored to absent)"

# Restore every backup from a session, in reverse order of capture.
restore-all-20261001T120000:
    @just --justfile "{{ backups }}/justfile" restore-launchagent-feeder-20261001T120000
    @just --justfile "{{ backups }}/justfile" restore-zshrc-20261001T120000
```

The recipes above are examples of the shape; generate the real ones. Rules for
the generated file:

- **One recipe per backed-up path**, named `restore-<short-name>-<session>`,
  with a comment line describing the path and why it was backed up. The
  comment is what `just --list` shows.
- `default` must be the **first** recipe, so plain `just` lists everything
  that can be restored.
- Every restore first saves the *current* file as `*.pre-restore.<timestamp>`,
  so a restore can itself be undone. "absent" entries remove the created path
  (unloading LaunchAgents first). Directory restores replace the directory
  wholesale, after moving the current one aside.
- Include `restore-all-<session>`, which restores in reverse order of capture.
- For things with their own uninstaller (Graft: `graft uninstall`; plugins:
  `/plugin uninstall`), the recipe comment names it, but the recipe still
  restores the backed-up file, because the uninstaller may not exist later.
- Verify with `just --justfile "$BACKUP_ROOT/justfile" --fmt --check` and
  `just --justfile "$BACKUP_ROOT/justfile" --list`. Then dry-run at least one
  restore against a temporary copy to prove it works, and record that in the
  final report.

### 15.4 Tell the user

At the end of the autonomous phase and in the final report, print:

```bash
just --justfile ~/.local/state/perp-tooling-backups/justfile          # list restorable items
just --justfile ~/.local/state/perp-tooling-backups/justfile restore-<name>-<session>
```

Do not delete the backups. Explain that the user can remove them once they
are satisfied.

---

## 16. Final report

Include:

- the orchestration used: Claude Code version, subagents created, which phases
  ran in parallel, and any deviation from §0 (e.g. different frontmatter
  fields);
- a rough token-use note per phase (`/cost`, `session-report`), and where
  cheaper routing was used;
- every tool installed, with its version, website and install method;
- "same spirit" tools added under §2, with rationale;
- tools declined and why;
- the skills and plugins installed, kept, dropped and offered (§0.6), and
  where they are recorded;
- the baseline commands and results, before and after the backport;
- files created or changed;
- `AGENTS.md`, the `CLAUDE.md` import, the skill path and the subagent files;
- the README changes and the chosen license;
- CI status and link;
- CodeRabbit verification;
- forks created (`Kuriboh493/<repo>` ← upstream), branches, generalized values,
  tests, and any upstream suggestion drafted or opened;
- feeder status: queue size, first PR link, schedule and notification choice;
- backup store path, manifest summary, the restore `justfile` recipe list, and
  the result of the restore dry-run;
- outstanding findings;
- the location of `HANDOFF.md`;
- `git status --short`.

Never report an external service as working until it has been verified with a
real authenticated interaction.
