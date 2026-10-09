---
name: terminus-kira
description: Delegate a real coding/shell task to TerminusKira, a sandboxed coding agent running in a native Apple Container VM with a real host directory bind-mounted in. Use when a task is better handed to an isolated agent than run directly in this session -- exploratory/risky work you want contained to one directory and reviewable before trusting it, or a long task you'd rather delegate and check back on than block this turn on. Also covers running it against a terminal-bench dataset for benchmark evaluation instead of ad-hoc work.
---

# terminus-kira — sandboxed task delegation

Built 2026-08-21 getting KIRA's `terminus-kira` (krafton-ai/KIRA, harbor's
Terminus2 agent extended with native tool calling) running locally on Apple
Silicon with no Docker/Colima and no Rosetta emulation. This skill is the
"I (Claude) can choose to pass real work to this" entry point — distinct
from `bigteam` (fan-out to peer agent sessions) and
`ralph-tui-orchestration` (multi-repo controller loops). TerminusKira is a
single sandboxed sub-agent you dispatch one task to, not a peer session.

## When to reach for this

- A task is exploratory or has some risk to it, and you want the blast
  radius contained to one bind-mounted directory you can review before
  trusting the result, rather than running commands directly against the
  real host.
- A task is long enough that you'd rather delegate it and check back than
  block the current turn on it (run in background, per usual tool
  conventions).
- You specifically want a *different* model's take (currently wired to
  `github_copilot/gemini-3.1-pro-preview`) on a coding task, as a second
  opinion or to burn a quota pool that isn't Anthropic's.

Don't reach for this for anything that's just "run this shell command" or
"edit this file" — that's what your own Bash/Edit tools are for. This is
for handing off a chunk of real agentic work to an isolated process.

## Usage

```bash
terminus-kira-task "<instruction>" [--dir HOST_DIR] [--image IMAGE] [harbor run options...]
```

- `HOST_DIR` (default: cwd) is bind-mounted at `/workspace` inside the
  sandbox — the agent's changes land back on the real host directory when
  it's done, no separate export step.
- `IMAGE` (default: `ubuntu:24.04`) is the base image; the generated
  Dockerfile installs git/curl/build-essential/python3/ripgrep on top.
- No pass/fail verification — this isn't a benchmark run, it just does the
  work. Read the transcript (`jobs/<timestamp>/*/agent/trajectory.json` and
  `*.pane` under `~/src/KIRA/`) or just inspect the mounted directory
  afterward to see what happened.
- Model/effort: `TERMINUS_KIRA_MODEL` / `TERMINUS_KIRA_REASONING_EFFORT`
  env vars override the `github_copilot/gemini-3.1-pro-preview` +
  `high` defaults.
- Auth is via `sudo-secretspec run` internally — never touches this
  session's shell/transcript with a key.

For a full terminal-bench dataset benchmark run instead of one ad-hoc task,
use `~/.local/bin/terminus-kira` (same fixes, no bind mount, defaults to
`-d`/`--path` you supply) rather than `terminus-kira-task`.

## Load-bearing facts (don't relitigate these — verify against current code
if something looks broken, per the memory-verification convention)

- **harbor must stay pinned to exactly 0.2.0**, not "latest." KIRA's
  `terminus_kira.py` (last committed 2026-03-18) overrides
  `Terminus2._setup_episode_logging`, which a later harbor refactor
  removed — upgrading harbor breaks TerminusKira outright with an
  `AttributeError`. 0.2.0 (2026-03-25) is the earliest release with the
  `apple-container` environment backend and still has that method.
- **harbor's CLI flags shifted around 0.2.0**: `--agent` became a closed
  enum of built-in names — a custom agent class only loads via
  `--agent-import-path` (never combine the two). `-i`/task-id filtering
  became `-t`/`--task-name` (glob-based).
- **Apple Silicon native, no Rosetta** needs three things harbor doesn't do
  on its own: `container system kernel set --recommended`,
  `container builder start`, and `--force-build` on `harbor run` (else it
  pulls the task's pinned amd64-only prebuilt image instead of building the
  Dockerfile locally — the Dockerfiles use standard multi-arch base images,
  so a local build produces a native arm64 image).
- **harbor's `AppleContainerEnvironment` has no bind-mount support** — only
  `--mounts-json` (Docker-only) exists at the CLI level. Apple's own
  `container` CLI supports `-v host:target` mounts fine; harbor's wrapper
  just never passes one through. Fixed via a small subclass at
  `~/src/KIRA/terminus_kira/mounted_apple_container.py`
  (`MountedAppleContainerEnvironment`), wired in via harbor's
  `--environment-import-path` + `--ek mount=host:target` extension points
  — the same mechanism `--agent-import-path` uses for custom agents. Full
  rationale in that file's docstring and in
  `~/src/KIRA/docs/apple-container-terminus-kira-setup.md`.
- **Model auth**: direct `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` (both in
  sudo-secretspec) hit real walls in practice — Anthropic key had
  insufficient credit balance, Gemini key is free-tier and hit a
  per-day/per-minute quota within a couple of calls. `github_copilot/*`
  models (via litellm's built-in `github_copilot` provider) work instead,
  billing against the GitHub Copilot Individual Pro *monthly* quota
  instead of a per-token key — genuinely idle capacity per `aiuse --json`
  at the time this was set up. First use requires a one-time interactive
  device-code OAuth (`https://github.com/login/device` + a code printed to
  stderr) — this is litellm's own token cache at
  `~/.config/litellm/github_copilot/`, separate from `gh auth` or any IDE
  Copilot login. If that cache is ever cleared, the next run will need
  that step redone once.
- litellm's bundled model-pricing catalog can be stale — it only listed
  `gemini-3-pro-preview` under `github_copilot/`, but querying
  `https://api.githubcopilot.com/models` directly showed the real
  `gemini-3.1-pro-preview` is actually available through Copilot. Don't
  trust the catalog as an availability check; query the live endpoint (or
  just try the model) if a "not mapped yet" warning shows up — it's often
  harmless (falls back to a generic context-window estimate), but "model
  not supported" from the backend itself means the id is genuinely wrong.

## Fork and docs

KIRA is `krafton-ai/KIRA` upstream; our changes (the mounted-environment
subclass, this setup) live on a fork — check
`~/src/KIRA/docs/apple-container-terminus-kira-setup.md` for the full
narrative writeup and `git remote -v` in `~/src/KIRA` for the current fork
remote.
