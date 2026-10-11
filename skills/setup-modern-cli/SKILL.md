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
4. **Never `ayg`** (aygrep): it indexes only git-tracked files, so untracked
   work is invisible even after a rebuild, and it writes `ayg_index/` inside the
   repo. `xg`, `sift` and `ag` earn no place ahead of `rg`; measurements below.

## Search ladder: try these in order

Adapted from the public agent skills for ripgrep and ast-grep (`ast-grep/agent-skill`,
866★; `oimiragieo/agent-studio`'s `ripgrep` skill, which carries the same
"ranked-first, raw-sweep-second" split). The point is to pick the *cheapest tool
that can actually answer*, not to always reach for `rg`.

1. **You already know the file** → Read it (or `bat -n --line-range`). Do not
   search to re-find something you have the path for.
2. **The repo has a code graph** (a `graft/` directory, or the harness's own
   index) → ask it first; `graft ask` / `graft grep` return ranked `file:line`
   spans without a filesystem sweep.
3. **Exact literal, few expected hits, index current** → `ig search -l '<lit>' .`
   (see the policy above).
4. **Default: `rg`.** One command for the whole `find | grep` shape, exhaustive:
   `rg -n -g '*.py' '<pat>' <path>`. Add `-F` when the literal contains regex
   metacharacters (`.is_file()`, `a[0]`), `-w` for whole words, `-C3` for
   context, `-t py` instead of `-g '*.py'` for known languages.
5. **A shape question, not a text question** ("every call site of X with two
   args", "async fns with no await") → `ast-grep`, not `rg`. Text search will
   either miss it or drown you. See below.
6. **Not in the working tree** → history, not a bigger sweep:
   `git log -S'<literal>' --oneline` (who introduced/removed it),
   `git grep '<pat>' <rev>`, `git log -L` for one symbol's history.
7. **Broaden only deliberately.** `rg` skips hidden, ignored and binary files by
   design; `-u` removes ignore rules, `-uu` adds hidden, `-uuu` adds binary. If
   a search "found nothing" and you expected a hit, run it again with `--debug`
   (it prints the ignore rule that excluded the file) before reaching for `-uuu`.

## Token discipline (agents read the output too)

1. **Locate, then read.** `rg -l '<pat>' <path>` gives file names; read only
   those. Dumping every matching line of a thousand hits is the common way an
   agent burns its context.
2. **Cap the output** at the command, not after: `--max-count N` (per file),
   `--max-columns 200` (truncate long lines), `-c` for counts, `--stats` for a
   summary, `-l` for names.
3. **`rg` exit code 1 means "no matches"** — it is not an error, and not a
   reason to re-run with different flags. Exit 2 is a real error. `ig` behaves
   the same way.
4. **Never search the whole machine** (`rg … ~` or `rg … /`) for a code
   question, and never search `.git/` — use `git grep` / `git log` for objects
   and history. `--max-filesize 10M` keeps generated files and logs out of a
   legitimately broad sweep.

## Structural search with ast-grep

When the question is about code *shape*, `sg` (ast-grep) is the right tool, and
its official agent skill is worth loading rather than reinventing:
`https://github.com/ast-grep/agent-skill` (marketplace:
`/plugin marketplace add ast-grep/agent-skill`). Its three-step workflow, which
this skill endorses:

1. Write a small snippet of the pattern you want to match (a temp file is fine).
2. Turn it into a rule or `-p '<pattern>'`, starting simple; for relational
   rules (`inside`, `has`) **always set `stopBy: end`**, or the search stops
   early and returns wrong results.
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

That is the agent-facing core. `docs/apply-toolchain-prompt.md` §1.2 has the
full quality toolchain (ruff, pre-commit, gitleaks, shellcheck, semgrep, …);
Python CLIs go through `uv tool install`, repo JS through `bun`/`bunx`.

## The replacement table — every classic, not just `grep`/`find`

The web's "modern unix" lists (`ibraheemdev/modern-unix`,
`thegdsks/awesome-modern-cli`, `johnalanwoods/maintained-modern-unix`,
`onmyway133/awesome-cli`) mix two kinds of tool. Splitting them is the useful
part: **only group A can be called from an agent's Bash loop.** Group B needs a
TTY, a daemon or a fuzzy prompt, so an agent call either hangs or returns
nothing.

The "Here" column is what is installed on djbclark's machine, 2026-10-11
(`✅` installed, `—` not installed). Use it to see what a `brew install` would
add; it is not a policy.

### A. Agent-safe: non-interactive, deterministic — what Bash calls should use

| Instead of | Use | Command pattern | Here |
|---|---|---|---|
| `grep -r` | ripgrep `rg` | `rg -n '<pat>' <path>` — **always pass a path** | ✅ |
| `grep -r --include` | `rg` glob/type | `rg -n -g '*.py' '<pat>' <path>`, `rg -t py '<pat>' <path>` | ✅ |
| `find . -name '*.py'` | `fd` | `fd -e py`, `fd -g '*.ts'`, `fd -e py --changed-within 1d` | ✅ |
| `find … \| xargs grep …` | `rg` (one command) | `rg -n -g '*.py' '<pat>' <path>`; `rg -l` files, `rg -c` counts | ✅ |
| `grep` inside PDFs/Office/zips | `rga` (ripgrep-all) | `rga -n '<pat>' <path>` | — |
| `cat` | `bat` | `bat -n FILE`, slice `bat -n --line-range 40:80 FILE` | ✅ |
| `less` / `more` (non-interactive) | `bat` | `bat --paging=never -n FILE` (interactive pager `ov` if you want one) | ✅ |
| `xxd` / `hexdump` | `hexyl` | `hexyl FILE` | — |
| `sed -i s/a/b/` | `srgn` | `srgn -L --fail-none --stdin-detection force-unreadable --glob RELPATH 'FIND' -- 'REPL'` | ✅ |
| `cut` / `awk` (columns) | `hck` (or `choose`) | `hck -d, -f2-4` | ✅ |
| `xargs` + `awk` | `rargs` / GNU `parallel` | `rargs '…{}…'` | — |
| `sort -u` on unsorted input | `runiq` | `runiq` | — |
| `du` (and `find` over caches) | `dust`, `gdu` (`dua`) | `dust -d 2 ~/.cache` — never `du`/`find` over `~/.cache`, it times out | ✅ |
| `df` | `duf` | `duf` | ✅ |
| `ps` (scripted) | `procs` | `procs --json` | ✅ |
| `diff` | `delta`, or `difft` for structural | `delta < a.diff`, `difft a.py b.py` | ✅ |
| raw `git diff` / `git log -p` | `delta` as the pager | set once in git config (ask first) | ✅ |
| `time cmd` for real numbers | `hyperfine` | `hyperfine --warmup 3 'cmd'` | ✅ |
| `man` (to recall flags) | `tldr` | `tldr rg` | ✅ |
| hand-parsing JSON | `jq` (`jaq` is a faster clone; `gron` flattens for grep) | `jq -r '.accounts[].provider'` | ✅ |
| hand-parsing YAML/TOML/XML | `yq` (`dasel` does all formats) | `yq '.services[].image'` | ✅ |
| `cat x.csv` + eyeballing | `qsv` / `csvlens` | `qsv stats x.csv` | — |
| `tail -f` a log while working | `rtk log`, `tailspin`, `lnav` | `rtk log < file` | ✅ |
| `curl` for JSON APIs | `xh` | `xh POST url k:=v` | ✅ |
| `wget` | `rtk wget`, `aria2c` | `rtk wget <url>` | ✅ |
| `dig` | `doggo` | `doggo example.com MX` | — |
| `tar`/`unzip`/`7z` | `ouch` | `ouch decompress x.tar.gz`, `ouch compress dir out.zip` | — |
| `tree` | `eza --tree` | `eza --tree --level=2 --icons` | ✅ |
| `grep` for code **shape** | ast-grep (`sg`) | `sg -p '<pattern>' -l <lang>` | ✅ |
| noisy command output | `rtk` | `rtk git status`, `rtk test`, `rtk grep '<pat>'`, `rtk read FILE` | ✅ |
| markdown to read | `glow` / `mdcat` | `glow README.md` | — |

`rtk` is normally applied automatically — its Claude Code / OpenCode hook
rewrites Bash calls to the `rtk` equivalent; that is why it appears as a
"replacement" for several rows. Its subcommands are the manual form.

### A2. Structured and stream data: `awk`, `sed`, `sort`, `join`, `tr`, `wc`

These are the classics our earlier version of this file did not cover. Prior art
worth knowing: **Miller** (`mlr`) bills itself as "like awk, sed, cut, join and
sort for name-indexed data", which is exactly the gap; the `sd` issue tracker
(`chmln/sd#297`) is the best write-up of why a literal-replace tool cannot do
scripted `sed` ranges/loops — so for real stream programs the answer is a
different tool, not a fancier `sd`.

| Instead of | Use | Command pattern | Here |
|---|---|---|---|
| `awk '{print $2}'` | `hck` / `choose` | `hck -d, -f2`, `choose 1` | ✅ |
| `awk`/`sed`/`cut`/`join`/`sort` over CSV, TSV, JSON | `mlr` (Miller) | `mlr --csv sort -f county f.csv`; `mlr --csv put '$d=$a-$b' then cut -f d f.csv`; `mlr join -j id -f a.csv b.csv` | — |
| `sort`, `sort -h`, `sort -k` | GNU `gsort`, or `mlr sort` | `gsort -h`, `gsort -k2,2` | ✅ |
| `join` on a key | `mlr join`, `qsv join` | see above | — |
| `tr` | GNU `gtr` | `gtr -d '\n'`, `gtr 'a-z' 'A-Z'` | ✅ |
| `wc` | GNU `gwc`, or `rtk wc` for agent-sized output | `gwc -l` | ✅ |
| `split` / `csplit` | GNU `gsplit` | `gsplit -l 1000 -d big.txt part-` | ✅ |
| `head -c` / `tail -c` (GNU semantics) | `ghead` / `gtail` | `ghead -c 200` | ✅ |
| `sed` doing ranges/loops/multi-line scripts | `srgn` for edits, `mlr` for records, `perl -pe`/`-ne` when it is genuinely a stream program, GNU `gsed` for GNU sed syntax | `perl -pe 's/x/y/g'`, `gsed -E '2,4d'` | ✅/— |
| `uniq` on unsorted input | `runiq` | `runiq` | — |
| `xargs -I{}` + `awk` | `rargs` | `rargs 'mv {} {}.bak'` | — |
| `date -d '2 days ago'` | GNU `gdate` | `gdate -d '2 days ago' +%F` | ✅ |
| `base64`, checksums | `b3sum` (fast), `sha256sum` (macOS ships it now) | `b3sum FILE`, `sha256sum FILE` | —/✅ |
| `locate` | `plocate` | `plocate '*.pdf'` | ✅ |
| `watch cmd` | `watchexec`, `entr` | `watchexec -e py 'pytest -q'` | — |
| `awk` over logs (aggregate/slice) | `angle-grinder` (`agrind`) | `agrind '* | where status >= 500 | count by path'` | — |
| `csvlook` / CSV eyeballing | `qsv`, `csvlens` | `qsv stats f.csv` | — |

### A3. The whole toolset, portably: GNU (g-prefixed) or uutils

On macOS the real problem is **BSD vs GNU flags**, not old vs new: `sort -h`,
`sed -i` (takes an argument on BSD), `date -d`, `readlink -f`, `grep -P`,
`xargs -r`, `stat -c` vs `-f`. Two prior-art answers, both installable:

1. **GNU tools with a `g` prefix** — `brew install coreutils gnu-sed gawk`
   gives `gsort`, `gtr`, `ghead`, `gdate`, `gsed`, `gawk` (coreutils is already
   installed here; `gsed`/`gawk` are separate formulae). Call them by the
   prefixed name in scripts so a macOS update cannot change what the script
   means. Prepending brew's `gnubin` to `PATH` makes bare names GNU, but then
   everything in the shell changes behaviour, not just the script.
2. **uutils** — `brew install uutils-coreutils` installs `uu-sort`, `uu-cut`, …
   (put its `uubin` on `PATH` for bare names). It is a Rust drop-in for GNU
   coreutils, 24k★, now shipping by default in Ubuntu 25.10, and it has sibling
   `findutils`/`diffutils`/`grep` (beta) and `sed`/`awk`/`procps` **in
   progress** — so it does not yet cover `sed`/`awk`.

Rule: prefer the single-purpose tool (`rg`, `fd`, `bat`, `srgn`, `mlr`, `jq`)
for the job in front of you; reach for `g`-prefixed GNU or `uu-` when a script
needs portability or a flag BSD lacks. Never write a GNU-only flag without the
prefix, and never assume the BSD form either — check `command -v gsort` first.

### B. Human-interactive: install for yourself, never call from an agent

These need a TTY or a background daemon. An agent's Bash call to one of them
either hangs waiting on stdin or returns nothing useful.

1. **Files and navigation:** `broot` (navigate + fuzzy), `yazi`/`lf`/`nnn`/
   `joshuto`/`superfile` (file managers), `zoxide` ✅ (smart `cd`), `tere`.
2. **History, prompt, shell:** `atuin`/`mcfly` (history), `starship` (prompt),
   `nushell`/`fish` (structured shells), `fzf` ✅/`skim`/`television` (fuzzy
   finders — the human's Ctrl-R/T, not a search primitive).
3. **Monitoring and processes:** `btop` ✅/`bottom`/`glances`/`macmon` (system),
   `procs` ✅ (scripted `ps` is group A), `pik`, `pueue`, `mprocs`.
4. **Disk, in a TUI:** `ncdu`/`dua`/`diskonaut` (`dust` ✅/`gdu` ✅ are group A
   because they print and exit).
5. **Git:** `lazygit`/`gitui`/`tig`/`serie` (TUIs), `gita` (many repos),
   `git-cliff` (changelogs), `jj`/`sapling` (alternate VCS).
6. **Logs, APIs, markdown:** `lnav` (log TUI), `posting`/`ATAC` (API clients),
   `blog`/`ov` (pagers).
7. **Network and transfer:** `trippy`/`gping`/`bandwhich`/`sniffnet`/`termshark`
   (diagnostics), `croc`/`portal`/`rclone`/`termscp` (transfers), `miniserve`
   (`caddy` is already installed for this).
8. **Editing and bulk file work:** `helix`/`micro`/`fresh` (editors), `f2`/
   `nomino` (batch rename), `fclones` (duplicates), `kondo` (build artifacts).

Optional installs from group A, A2 and B worth adding here:

```bash
HOMEBREW_NO_AUTO_UPDATE=1 brew install hexyl ouch glow doggo gron jaq ripgrep-all fclones f2 atuin lazygit lnav \
  miller gnu-sed gawk uutils-coreutils dasel qsv watchexec b3sum
```

(The last line covers the A2/A3 gaps: `mlr` for awk/sed/sort/join, `gsed`/`gawk`
and `uu-*` for GNU/portable semantics, plus the structured-data and watch tools.)

**About `HOMEBREW_NO_AUTO_UPDATE=1`: it is a performance knob, not an update
switch.** It suppresses the `brew update` that brew otherwise runs in front of
`install`/`upgrade` — minutes of network work that can fail on a flaky
connection — so a multi-package install stays fast and deterministic. It does
**not** stop anything updating: `brew update` and `brew upgrade` still work, and
on this machine `site-djbclark/shell/bashrc` exports the variable machine-wide
while the scheduled `brew-fast-upgrade` Jobber job (daily 03:10) updates brew and
npm globals. Keep it on automated install lines; there is nothing wrong with it.

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
7. **BSD vs GNU flags are the trap, not age.** `sort -h`, `sed -i`, `date -d`,
   `readlink -f`, `grep -P`, `xargs -r` and `stat -c` differ or do not exist in
   macOS's BSD userland. Use the `g`-prefixed GNU tool (`gsort`, `gsed`,
   `gdate`) or `uu-*`, and check it exists before relying on it — a script that
   works locally with GNU flags breaks on stock macOS, and vice versa.
8. **Do not reach for `sed`/`awk` to transform structured data.** Named-field
   work (CSV/TSV/JSON) is `mlr`, `jq`, `yq`/`dasel` or `qsv`; positional
   `awk`-style slicing is how off-by-one field bugs get written.

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


