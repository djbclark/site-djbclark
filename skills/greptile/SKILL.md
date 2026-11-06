---
name: greptile
description: "Greptile (app.greptile.com) on this machine: the free Starter plan's credit budget and how reviews are spent, triggering and reading PR reviews, the API key held in sudo-secretspec, and which official Greptile skill fits a PR comment loop. Use when the user mentions Greptile, greptile.com, a Greptile review or score, @greptileai, or wants a second AI code review of a PR."
---

# Greptile

Greptile is an AI code-review service (repository graph, PR comments, a 0-5 confidence score). Organization `frdminc`
("Freedom Included") holds all 123 djbclark and frdminc repositories (2026-11-01).

## The budget comes first: free Starter plan

**50 credits a month** (100 the first month), for one active developer; a Base review costs 1 credit, Plus 3, Apex 10, a TREX
run 3 more. When credits run out, reviews pause until next month. Starter does **not** include CLI reviews, learning and
custom context, the Knowledge Base, cross-repo context or analytics (those are Pro, $1 a credit). So (djbclark, 2026-11-01):

1. Automatic reviews are **off** organization-wide (dashboard: Settings → Code Review → Automatic reviews: Never; drafts off).
   PR Summaries → "Update pull request description" is **off** too (2026-11-01): when on, Greptile appends ~4 KB of summary to the
   PR body, which holds our `adversary-verdict:v1` marker; a quoted marker there could stall the lander or block a merge. Its
   summary goes in a comment instead.
2. The djbclark-ade lander requests a Base review for its riskiest PRs only, after the adversary approves: at most 1 a day and
   30 a month (`scripts/greptile-gate.py`; the lander keeps its count in `greptile-budget.json` in the lead's state dir). The rest of the month's credits are manual.
3. Manual review of one PR: comment `@greptileai` on it. Use it for a PR that deserves a second opinion, not by habit.
4. Base tier only; never `--plus`/`--apex` or TREX without djbclark asking.
5. Greptile's free open-source program needs **50 or more GitHub stars** before you can apply (djbclark, 2026-11-01); none of
   djbclark's repositories qualify, so do not send him to the form. Every review comes out of the free-plan budget above.

| Task | Use |
|---|---|
| Fix the Greptile comments on an open PR, check its status checks and description | the official skill `check-pr` |
| Loop: trigger a review, fix, re-review until 5/5 and zero comments | the official skill `greploop` (spends a credit per round: count them) |
| Read a PR's latest Greptile review status and score | `greptile-gate.py status PR` under `sudo-secretspec run` (below) |
| Review a local branch with the CLI | not on the free plan; the CLI section below applies only on a paid (Pro) plan |
| Greptile MCP tools | the shared proxy (8 review tools), once installed; see MCP below |

The official skills come from [greptileai/skills](https://github.com/greptileai/skills) (MIT), installed unmodified with
`npx skills add greptileai/skills -g` into `~/.agents/skills` (2026-11-01). Update them with `npx skills update`; never edit them
in place.

Read a PR's review without the CLI (any repository; prints status, review id and the `Confidence Score` when completed):

```bash
sudo-secretspec run --reason "greptile status" -- python3 -I ~/src/djbclark-ade/skills/greptile/scripts/greptile-gate.py status 229
# a third and fourth argument select another repository and its default branch: ... status 12 frdminc/nix2cf main
```

## Authentication: the key stays in sudo-secretspec

The API key is `GREPTILE_API_KEY` in `sudo-secretspec` (stored 2026-11-01). The CLI reads that exact environment variable,
so run every CLI command under `sudo-secretspec run`:

```bash
GREPTILE_NO_UPDATE_CHECK=1 sudo-secretspec run --reason "greptile review" -- greptile whoami
# Signed in as djbclark@gmail.com (via GREPTILE_API_KEY)   organization: Freedom Included
```

1. **Never** `greptile login --api-key`: it writes a second copy of the key to `~/.greptile/`, outside the audited store.
   Never pass the key as an argument (Greptile's docs say the same).
2. `greptile login` (browser OAuth) is for a human's interactive use; agents use the key under `run`.
3. If `whoami` fails under `run`, check the key's presence with the sudo-secretspec skill's length check; never print it.
4. `GREPTILE_NO_UPDATE_CHECK=1` keeps the CLI from checking for updates on every run. The CLI is installed with
   `brew install greptileai/tap/greptile` and tracks latest (`brew upgrade greptile`).

## Review a local branch (CLI: Pro plan only, not the free plan)

Run from the repository root of a branch with committed changes (uncommitted changes are ignored; the base is the default branch):

```bash
GREPTILE_NO_UPDATE_CHECK=1 sudo-secretspec run --reason "greptile review" -- greptile review --agent
```

| Flag | Effect |
|---|---|
| `--agent` (= `--text`) | plain-text findings for an agent; also the default when piped |
| `--json` | machine-readable findings |
| `-b, --branch BASE` | base branch other than the default |
| `--instructions "TEXT"` | like an `@greptile TEXT` comment: focus the review |
| `--resume` | continue the latest unfinished review |
| `--plus` / `--apex` | higher review tier: **3 / 10 credits** instead of Base (prepaid credits). Use only when the user asks |
| `--include PATHS` | send files the CLI held back as possibly sensitive; only after checking they hold no secret |

A review takes minutes. Run it in the background with a time limit, and register the limit with `bin/deadline` once that
tool is installed (`deadline run --budget 20m -- ...`).

Check a commit's review in a hook or script; read the exit code, not the text:

```bash
sudo-secretspec run --reason "greptile status" -- greptile review status [--commit SHA] [--json]
```

| Exit | Meaning |
|---|---|
| 0 | completed review exists |
| 1 | no review, signed out, or no `origin` |
| 2 | invalid command, not a git repo, or unresolvable commit |
| 3 | review still running |
| 4 | latest review failed |
| 5 | latest review cancelled |

Other commands: `greptile review show [ID]` (reopen; lists recent reviews when piped), `greptile config [PATH]` (the
effective review config: `.greptile/` folders, dashboard settings, org rules).

## How Greptile relates to this repo's gates

A Greptile review is an extra signal. It does not replace djbclark-ade's merge gates (adversary verdict marker, clean
`bin/local-review`, `pr-wait` merge_ready; AGENTS.md "Code review"). Treat its findings like any reviewer's: fix real ones,
say why for rejected ones.

## MCP

The Greptile MCP server is `https://api.greptile.com/mcp` (streamable HTTP, 21 tools). Greptile's docs describe OAuth only
(`claude mcp login greptile`), and say a static `Authorization` header can block that sign-in; but the API key also works
as a bearer token (probed 2026-11-01 under `sudo-secretspec run`: `tools/call get_me` 200 with the key, 401 without). Its
tool definitions are about 47.7 KB, roughly 12,000 tokens of context in every session that registers it. It is not
registered on this machine: adding it to a client, or fronting it with a shared local proxy that injects the key, is a
toolchain change: ask djbclark first (`~/AGENTS.md` item 5).

## Docs

Index of every page (append `.md` to any page URL for raw Markdown): https://www.greptile.com/docs/llms.txt. Most useful:
[CLI](https://www.greptile.com/docs/code-review/greptile-cli.md),
[review tiers](https://www.greptile.com/docs/code-review/review-tiers.md),
[.greptile/ config](https://www.greptile.com/docs/code-review/greptile-config.md),
[MCP tools](https://www.greptile.com/docs/mcp/tools.md),
[billing](https://www.greptile.com/docs/account/billing-seats.md).
The older REST API reference (`docs.greptile.com/api-reference/...`: index, query and search repositories) now redirects to
the overview (checked 2026-11-01): do not build new tooling on it; use the CLI or MCP.
