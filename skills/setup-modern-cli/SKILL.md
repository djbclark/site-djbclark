---
name: setup-modern-cli
description: >-
  Install and prefer modern, faster replacements for the old Unix tools — rg for
  grep, fd for find, bat for cat, srgn for sed, eza for ls, hck for cut/awk,
  delta, jq/yq, xh, ast-grep, dust/gdu, and rtk for compacting noisy output —
  with the exact command patterns to use and the footguns to avoid. Use when a
  repo or an agent still shells out to find|grep|sed|cat|ls|awk, when setting up
  a machine or repo toolchain, or when asked for "modern CLI tools", "faster
  grep/find", or a "find | grep" pipeline replacement.
---

# Modern CLI tools: install once, prefer everywhere

One place that says which classic Unix tool to replace, with which modern tool,
using which flags — and the traps. It is the skill form of the install table in
`djbclark-ade/docs/apply-toolchain-prompt.md` (§1.2 install, §1.3 "what each
tool is … Use instead of"). That file stays the canonical installer for a new
repo; this skill is the standing instruction to prefer the modern tools.

Canonical source: `skills/setup-modern-cli/SKILL.md` in `~/src/djbclark-ade`.
Every other TUI reaches it through the skill-everywhere symlink chain, so there
is nothing to keep in sync.

## Install (Homebrew)

```bash
HOMEBREW_NO_AUTO_UPDATE=1 brew install \
  ripgrep fd bat srgn eza hck git-delta jq yq xh ast-grep dust gdu
```

That is the agent-facing core. `docs/apply-toolchain-prompt.md` §1.2 has the
full quality toolchain (ruff, pre-commit, gitleaks, shellcheck, semgrep, …);
Python CLIs go through `uv tool install`, repo JS through `bun`/`bunx`.

## The replacement table

| Instead of | Use | Command pattern |
|---|---|---|
| `grep -r` | ripgrep `rg` | `rg -n '<pat>' <path>` — **always pass a path** |
| `grep -r` + `--include` | `rg` glob/type | `rg -n -g '*.py' '<pat>' <path>`, `rg -t py '<pat>' <path>` |
| `find . -name '*.py'` | `fd` | `fd -e py`, `fd -g '*.ts'`, `fd -e py --changed-within 1d` |
| `find … \| xargs grep …` | `rg` (one command) | `rg -n -g '*.py' '<pat>' <path>`; files only: `rg -l '<pat>' <path>`; counts: `rg -c` |
| `cat` | `bat` | `bat -n FILE`, slice: `bat -n --line-range 40:80 FILE` |
| `sed -i s/a/b/` | `srgn` | `srgn -L --fail-none --stdin-detection force-unreadable --glob RELPATH 'FIND' -- 'REPL'` |
| `ls` / `tree` | `eza` | `eza -la --git`, `eza --tree --level=2 --icons` |
| `cut` / `awk` (columns) | `hck` | `hck -d, -f2-4` |
| `diff` / raw `git diff` | `delta` | set as git pager once, or pipe through `delta` |
| hand-parsing JSON | `jq` | `jq -r '.accounts[].provider'` |
| hand-parsing YAML/TOML | `yq` | `yq '.services[].image'` |
| `curl` for JSON APIs | `xh` | `xh POST url k:=v` |
| text search for code shape | `ast-grep` (`sg`) | `sg -p '<pattern>' -l <lang>`, `sg -p '$X.unwrap()'` |
| `du` / `find` over caches | `dust`, `gdu` | `dust -d 2 ~/.cache` (never `du`/`find` over `~/.cache` — it times out) |
| noisy command output | `rtk` | `rtk git status`, `rtk test`, `rtk grep '<pat>'`, `rtk read FILE` |

`rtk` is normally applied automatically: its Claude Code / OpenCode hook rewrites
Bash calls to the `rtk` equivalent. Its subcommands are the manual form.

## Footguns

1. **`rg` with no path** searches more than intended. Always name the path
   (home-agents rule, 2026-10-09).
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

## How an agent should use this

1. Before running a shell search, pick the table row instead of `grep`/`find`/
   `sed`/`cat`/`ls`/`awk`.
2. For "which files contain X under glob Y", use the one-command `rg -g`/`rg -t`
   form — never a `find … | xargs grep …` pipeline.
3. For a repo with no toolchain yet, point at
   `djbclark-ade/docs/apply-toolchain-prompt.md` (full, versioned installer).
4. Report which tool ran when a search is slow, so a missing install is visible
   (`command -v rg fd ast-grep`).

## Experimental: indexed one-command find+grep (measured 2026-10-11)

A crop of indexed, agent-oriented search tools claims large speedups over `rg`
by building a trigram/n-gram index and answering repeat queries in
milliseconds. Measured 2026-10-11 on a 3.3k-file Rust/JS tree (a copy of
`~/src/herdr`), pattern `serde`, file-list mode (`-l`), indexes built, one
`hyperfine` pass at low machine load (8 runs; the ratios move with load, so
compare within a run, not across):

| Tool | Mean | vs `find … \| xargs grep -l` | Files found (rg = 176) |
|---|---:|---:|---:|
| `find … \| xargs grep -l` | 147.6 ms | — | 176 |
| `rg -l` | 54.9 ms | 2.7x | 176 |
| `xg -l` (xgrep) | 27.2 ms | 5.4x | 177 |
| `ig search -l` (instant-grep) | 11.1 ms | 13.3x | 170 |
| `ayg search -l` (aygrep) | 10.1 ms | 14.6x | 148 |
| `sift -g … --files` | 131.5 ms | 1.1x (2.4x *slower* than `rg`) | 176 |
| `ag -l` (Silver Searcher) | ~72 ms | ~2.0x | 149 |

Verdict: **`rg` stays the default**; these are opt-in, and only `ig` is worth
considering because its index lives outside the repo.

1. **`ag` is slower than `rg`** — the "ag" in `find|grep` folklore is the 2012
   Silver Searcher. `sift`'s command is *also* `ag`, so `cargo install
   sift-search` shadows the Silver Searcher on `PATH`; rename its binary
   (`mv ~/.cargo/bin/ag ~/.cargo/bin/sift`).
2. **`sift` adds nothing but composition.** Its default build links the `rg`
   backend only (`lex`/`sem` are feature-gated and print "skipped"), so it
   returns byte-identical results to `rg` and is slower. Use it for `(pipe …)`
   multi-stage queries, never for speed.
3. **`ayg` (aygrep) indexes only git-tracked files.** File discovery is
   `git ls-files`, so (a) a file ignored by `.gitignore` but intended greppable
   via a `.ignore` exception is invisible, and (b) an **untracked** file stays
   invisible **even after `ayg build`** — verified: a new untracked file was
   not found after a rebuild, and only appeared once `git add`ed. It also
   writes `ayg_index/` **inside the repo** (54.7 MB for 3.3k files; 131 MB
   `lookup.bin` + 668 MB `postings.bin` + 2.3 GB `content.bin` on a large
   monorepo). There is no watch/incremental mode and no flag for extra file
   types; upstream is 3 stars / 13 commits / 0 forks / no issues, so **no fork
   fixes this**.
4. **`ig` (instant-grep) is the better indexed option** — index in
   `~/.cache/ig` (not the repo), 16 s and 189 MB for this corpus, and a file
   added after the build **is** picked up by `ig index` even when untracked
   (unlike `ayg`). It still needs a rebuild after edits, and it missed 6
   `vendor/` files `rg` returns, so verify recall. `ig` is really a whole
   token-optimization suite (`ls`, `read`, `symbols`, `git`, `test`, `run`,
   agent hooks, `import-rtk`) that overlaps `rtk`.
5. **`xg` (xgrep)** indexes into `~/Library/Caches/xgrep/`, needs re-index, and
   returned one file `rg` ignores; `ffs` (`quangdang46/fast_file_search`) does
   **not build here** — its `zlob` dependency needs Zig — so it is unverified.
6. **No `rg` flag magic.** On the same corpus `rg -F` was +4%, `rg -j8` ±0%,
   `rg --no-mmap` **+15% slower**, and `rg --sort path` **396% slower** (sorting
   serialises the search). Performance advice that matters is process, not
   flags: pass an explicit path, use `-l`/`-c` to cut output, keep the tree
   inside one filesystem, and do not add `--sort`.


