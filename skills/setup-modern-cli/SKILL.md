---
name: setup-modern-cli
description: >-
  Install and prefer modern replacements for the classic Unix tools — rg for
  grep, fd for find, bat for cat, srgn for sed, eza for ls, hck cut, mlr for
  awk/sort/join, jq/yq, xh, ast-grep, dust/gdu, and rtk for compacting noisy
  output — with the search policy (rg by default, opt-in indexed ig), the
  command patterns, the BSD-vs-GNU portability answer, and the footguns to
  avoid. Use when a repo or an agent still shells out to find|grep|sed|awk|cut|
  cat|ls, when setting up a machine or repo toolchain, or when asked for "modern
  CLI tools", "faster grep/find", or a "find | grep" pipeline replacement.
---

# Modern CLI tools: install once, prefer everywhere

The standing instruction to prefer the modern tools, plus the traps. The full
classic→modern tables live in the reference files below; this file is the part
to read first.

Canonical source: `skills/setup-modern-cli/SKILL.md` in `~/src/djbclark-ade`.
Every other TUI reaches it through the skill-everywhere symlink chain, so there
is nothing to keep in sync. `djbclark-ade/docs/apply-toolchain-prompt.md` §1.2
is the full, versioned installer for a new machine or repo.

## Search policy: `rg` by default, `ig` as an opt-in first line

1. **Default to `rg`.** It is exhaustive and always correct, and it already does
   the `find … | grep …` pipeline in one command (`rg -n -g '*.py' PAT PATH`;
   `-l` for files, `-c` for counts). Always pass a path.
2. **First line, when justified: `ig`** (instant-grep, `~/.cargo/bin/ig`, index
   in `~/.cache/ig`). Use it for one thing you already know — an exact literal
   symbol or string you expect in a handful of files — in a repo whose index is
   current. Measured ~13x faster than `rg`.
3. **Fall back to `rg`** the moment any of these holds: the search must be
   exhaustive; the pattern is a regex, multiline or PCRE2; you need filters
   beyond `ig -g`/`ig -t`; `ig` returns nothing (it missed 6 of `rg`'s files in
   the same test, `vendor/` among them); or the tree changed since the last
   index — `ig` returns nothing *silently* until `ig index` is re-run, which is
   the normal case mid-edit.
4. **Almost never bare `grep`.** A recursive `grep` or `ggrep` (`-r`, `-R`, `--recursive`)
   is denied by `bash_habits_gate` (2026-10-22: `grep -rl` over `~/src` and `~/ops`
   ran 38 minutes at one core). Content search is `rg` with a path. One file that
   needs a GNU flag is `ggrep`. A filename, when the nightly index is fresh enough,
   is `plocate` (step 2 below). `rtk grep` is BSD grep, not ripgrep.
5. **Never `ayg`** (aygrep): it indexes only git-tracked files, so untracked
   work is invisible even after a rebuild, and it writes `ayg_index/` inside the
   repo. `xg`, `sift` and `ag` earn no place ahead of `rg`; numbers in
   `references/indexed-search-benchmarks.md`.

## Search ladder: try these in order

Adapted from the public agent skills for ripgrep and ast-grep
(`ast-grep/agent-skill`, 866★; `oimiragieo/agent-studio`'s `ripgrep` skill,
which carries the same "ranked-first, raw-sweep-second" split). The point is to
pick the *cheapest tool that can actually answer*, not to always reach for `rg`.

1. **You already know the file** → Read it (or `bat -n --line-range`). Do not
   search to re-find something you have the path for.
2. **A filename, and today's index is enough** → `plocate -i NAME`. The db is
   `/opt/homebrew/var/lib/plocate/plocate.db`, rebuilt nightly at 03:30 by
   `com.djbclark.plocate-updatedb`. It does not search file contents. If the
   path may have appeared since that rebuild, use `fd` in a scoped directory.
3. **The repo has a code graph** (a `graft/` directory, or the harness's own
   index) → ask it first; `graft ask` / `graft grep` return ranked `file:line`
   spans without a filesystem sweep.
4. **Exact literal, few expected hits, index current** → `ig search -l '<lit>' .`.
5. **Default: `rg`.** One command for the whole `find | grep` shape, exhaustive:
   `rg -n -g '*.py' '<pat>' <path>`. Add `-F` when the literal contains regex
   metacharacters (`.is_file()`, `a[0]`), `-w` for whole words, `-C3` for
   context, `-t py` instead of `-g '*.py'` for known languages.
6. **A shape question, not a text question** ("every call site of X with two
   args", "async fns with no await") → `ast-grep`, not `rg`. See below.
7. **Not in the working tree** → history, not a bigger sweep:
   `git log -S'<literal>' --oneline` (who introduced/removed it),
   `git grep '<pat>' <rev>`, `git log -L` for one symbol's history.
8. **Broaden only deliberately.** `rg` skips hidden, ignored and binary files by
   design; `-u` removes ignore rules, `-uu` adds hidden, `-uuu` adds binary. If
   a search "found nothing" and you expected a hit, run it again with `--debug`
   (it prints the ignore rule that excluded the file) before reaching for `-uuu`.

## Token discipline (agents read the output too)

1. **Locate, then read.** `rg -l '<pat>' <path>` gives file names; read only
   those. Dumping every matching line of a thousand hits is the common way an
   agent burns its context.
2. **Cap the output** at the command, not after: `--max-count N` (per file),
   `--max-columns 200`, `-c` for counts, `--stats` for a summary, `-l` for names.
3. **`rg` exit code 1 means "no matches"** — it is not an error, and not a reason
   to re-run with different flags. Exit 2 is a real error. `ig` behaves the same.
4. **Never search the whole machine** (`rg … ~` or `rg … /`) for a code question,
   and never search `.git/` — use `git grep` / `git log` for objects and history.
   `--max-filesize 10M` keeps generated files and logs out of a broad sweep.

## Structural search with ast-grep

When the question is about code *shape*, `sg` is the right tool, and its official
skill is worth loading rather than reinventing:
`https://github.com/ast-grep/agent-skill` (`/plugin marketplace add
ast-grep/agent-skill`). Its three-step workflow, which this skill endorses:

1. Write a small snippet of the pattern you want to match (a temp file is fine).
2. Turn it into a rule or `-p '<pattern>'`, starting simple; for relational rules
   (`inside`, `has`) **always set `stopBy: end`**, or the search stops early and
   returns wrong results.
3. Test the rule against the snippet before trusting it on the repo.

Use `sg -p '<pattern>' -l <lang>` for a one-liner over a single language, and a
rule file (`sg scan -r rule.yml`) when the query needs several sub-rules
(`all`/`any`/`not`). Reach for `rg` again once you know the literal text you are
after — `sg` is slower and only worth it for shape.

## Install (Homebrew)

```bash
HOMEBREW_NO_AUTO_UPDATE=1 brew install \
  ripgrep fd bat srgn eza hck git-delta jq yq xh ast-grep dust gdu
```

That is the agent-facing core; `references/replacements.md` has an optional
second line covering the `awk`/`sed`/`sort`/`join`, GNU-vs-BSD and
structured-data gaps. `docs/apply-toolchain-prompt.md` §1.2 has the full quality
toolchain (ruff, pre-commit, gitleaks, shellcheck, semgrep, …); Python CLIs go
through `uv tool install`, repo JS through `bun`/`bunx`.

The `HOMEBREW_NO_AUTO_UPDATE=1` there is a **performance knob, not an update
switch**: it skips the `brew update` that brew otherwise runs first (minutes, and
it can fail on a flaky connection) and does not stop anything updating — brew
updates still work, `site-djbclark/shell/bashrc` exports it machine-wide, and the
scheduled `brew-fast-upgrade` job owns updating.

## Footguns

1. **`rg` with no path** searches more than intended. Always name the path
   (home-agents rule, 2026-10-09). **A named path can still over-search:**
   `~/src` holds vendored/generated trees (`node_modules`, `litellm`,
   `*.lock`, test fixtures, tokenizer JSON) that bury a config-literal sweep
   in megabytes of noise. For "find every live reference to X", scope to live
   dirs first (`~/.hermes/{bin,scripts,skills}`, `~/ops/<repo>`), or exclude
   with `--glob '!**/node_modules/**' --glob '!**/*.lock' --glob '!**/fixtures/**'`.
   Worktree checkouts under `~/src/*-worktrees` are separate branches, not live
   config — report them, and never assume they are what runs.
2. **`rg -r` is `--replace`, not a flag cluster.** `rg -rln PAT .` silently
   replaces every match in the *output* with `ln`, so ordinary files look
   corrupted (2026-10-11). Use `rg -l` and `rg -n` as separate flags.
3. **`fd`/`rg` skip hidden and ignored files** by default. For a full sweep add
   `--hidden` and `-u`/`--no-ignore` deliberately — do not make it the default.
4. **Do not alias `grep`/`find` globally.** Shell aliases break scripts and other
   tools' expectations; instruct agents and use hooks (rtk) instead.
5. **`sd` is retired for edits** (2026-10-09): without `-A` it matches line by
   line and exits 0 when nothing matched. Use `srgn` with `--fail-none`.
6. **Prefer the host's own tools** when they exist (Claude Code Read/Grep/Glob/
   Edit; this list is for *shell* work). The two rules from site-djbclark
   `docs/tooling-policy.md` still apply.
7. **BSD vs GNU flags are the trap, not age.** `sort -h`, `sed -i`, `date -d`,
   `readlink -f`, `grep -P`, `xargs -r` and `stat -c` differ or do not exist in
   macOS's BSD userland. Use the `g`-prefixed GNU tool (`gsort`, `gsed`,
   `gdate`, `ggrep`) or a newer search tool (`rg`). Bare `grep` is BSD and
   only when a BSD flag is required. Check the binary exists before relying on it.
   On this Mac always run `gsed`, never bare `sed`, unless BSD sed is
   specifically required (2026-10-15: a BSD `sed -i` broke an edit).
8. **Do not reach for `sed`/`awk` to transform structured data.** Named-field
   work (CSV/TSV/JSON) is `mlr`, `jq`, `yq`/`dasel` or `qsv`, and *aggregation*
   (group-by, join, count, window) over files is `duckdb` — it reads CSV, JSON
   and Parquet by path with no import step. Positional `awk`-style slicing is how
   off-by-one field bugs get written.

## How an agent should use this

1. Before running a shell command, pick the matching row in
   `references/replacements.md` instead of `grep`/`find`/`sed`/`awk`/`cat`/`ls`.
2. For "which files contain X under glob Y", use the one-command `rg -g`/`rg -t`
   form — never a `find … | xargs grep …` pipeline.
3. For a repo with no toolchain yet, point at
   `djbclark-ade/docs/apply-toolchain-prompt.md` (full, versioned installer).
4. Report which tool ran when a search is slow, so a missing install is visible
   (`command -v rg fd ast-grep mlr duckdb`).

## Reference files

1. `references/replacements.md` — the full tables: agent-safe tools (group A),
   structured/stream data covering `awk`/`sed`/`sort`/`join`/`tr`/`wc` (A2), the
   GNU-vs-BSD portability answer (A3), human-interactive-only tools (B), and the
   optional install line with a per-tool "installed here" column.
2. `references/indexed-search-benchmarks.md` — the measured indexed find+grep
   numbers (`ig`, `ayg`, `xg`, `sift`, `ag` vs `rg`) and the `rg`-flag results.
