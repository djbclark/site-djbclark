# Classic tool → modern tool: the full tables

Reference for the `setup-modern-cli` skill (`../SKILL.md`).

The web's "modern unix" lists (`ibraheemdev/modern-unix`,
`thegdsks/awesome-modern-cli`, `johnalanwoods/maintained-modern-unix`,
`onmyway133/awesome-cli`) mix kinds of tool. Splitting them is the useful part:
**only groups A and A2 can be called from an agent's Bash loop.** Group B needs
a TTY, a daemon or a fuzzy prompt, so an agent call either hangs or returns
nothing. Group A3 is about portability, not replacement.

The "Here" column is what is installed on djbclark's machine, 2026-10-11
(`✅` installed, `—` not installed). Use it to see what a `brew install` would
add; it is not a policy.

## A. Agent-safe: non-interactive, deterministic — what Bash calls should use

| Instead of | Use | Command pattern | Here |
|---|---|---|---|
| `grep -r` | ripgrep `rg` | `rg -n '<pat>' <path>` — **always pass a path** | ✅ |
| `grep -r --include` | `rg` glob/type | `rg -n -g '*.py' '<pat>' <path>`, `rg -t py '<pat>' <path>` | ✅ |
| `find . -name '*.py'` | `fd` | `fd -e py`, `fd -g '*.ts'`, `fd -e py --changed-within 1d` | ✅ |
| `find … \| xargs grep …` | `rg` (one command) | `rg -n -g '*.py' '<pat>' <path>`; `rg -l` files, `rg -c` counts | ✅ |
| `grep` inside PDFs/Office/zips | `rga` (ripgrep-all) | `rga -n '<pat>' <path>` | ✅ |
| `cat` | `bat` | `bat -n FILE`, slice `bat -n --line-range 40:80 FILE` | ✅ |
| `less` / `more` (non-interactive) | `bat` | `bat --paging=never -n FILE` (interactive pager `ov` if you want one) | ✅ |
| `xxd` / `hexdump` | `hexyl` | `hexyl FILE` | ✅ |
| `sed -i s/a/b/` | `srgn` | `srgn -L --fail-none --stdin-detection force-unreadable --glob RELPATH 'FIND' -- 'REPL'` | ✅ |
| `cut` / `awk` (columns) | `hck` (or `choose`) | `hck -d, -f2-4` | ✅ |
| `xargs` + `awk` | `rargs` / GNU `parallel` | `rargs '…{}…'` | ✅ |
| `sort -u` on unsorted input | `runiq` | `runiq` | ✅ |
| `du` (and `find` over caches) | `dust`, `gdu` (`dua`) | `dust -d 2 ~/.cache` — never `du`/`find` over `~/.cache`, it times out | ✅ |
| `df` | `duf` | `duf` | ✅ |
| `ps` (scripted) | `procs` | `procs --json` | ✅ |
| `diff` | `delta`, or `difft` for structural | `delta < a.diff`, `difft a.py b.py` | ✅ |
| raw `git diff` / `git log -p` | `delta` as the pager | set once in git config (ask first) | ✅ |
| `time cmd` for real numbers | `hyperfine` | `hyperfine --warmup 3 'cmd'` | ✅ |
| `man` (to recall flags) | `tldr` | `tldr rg` | ✅ |
| hand-parsing JSON | `jq` (`jaq` is a faster clone; `gron` flattens for grep) | `jq -r '.accounts[].provider'` | ✅ |
| hand-parsing YAML/TOML/XML | `yq`; `dasel` for a format zoo | `yq '.services[].image'`; `dasel query -i json 'x.y' < f.json` (`dasel` 3 takes the query plus `-i`/`-o`, and reads stdin — there is no file argument) | ✅ |
| `cat x.csv` + eyeballing | `qsv` / `csvlens` | `qsv stats x.csv` | ✅ |
| `tail -f` a log while working | `rtk log`, `tailspin`, `lnav` | `rtk log < file` | ✅ |
| `curl` for JSON APIs | `xh` | `xh POST url k:=v` | ✅ |
| `wget` | `rtk wget`, `aria2c` | `rtk wget <url>` | ✅ |
| `dig` | `doggo` | `doggo example.com MX` | ✅ |
| `tar`/`unzip`/`7z` | `ouch` | `ouch decompress x.tar.gz`, `ouch compress dir out.zip` | ✅ |
| `tree` | `eza --tree` | `eza --tree --level=2 --icons` | ✅ |
| `grep` for code **shape** | ast-grep (`sg`) | `sg -p '<pattern>' -l <lang>` | ✅ |
| noisy command output | `rtk` | `rtk git status`, `rtk test`, `rtk grep '<pat>'`, `rtk read FILE` | ✅ |
| markdown to read | `glow` / `mdcat` | `glow README.md` | ✅ glow |

`rtk` is normally applied automatically — its Claude Code / OpenCode hook
rewrites Bash calls to the `rtk` equivalent; that is why it appears as a
"replacement" for several rows. Its subcommands are the manual form.

## A2. Structured and stream data: `awk`, `sed`, `sort`, `join`, `tr`, `wc`

The classics an earlier version of this skill did not cover. Prior art worth
knowing: **Miller** (`mlr`, `johnkerl/miller`) bills itself as "like awk, sed,
cut, join and sort for name-indexed data", which is exactly the gap — no curated
list offers an `awk` answer at all. And `chmln/sd#297` is the best write-up of
why a literal-replace tool cannot do scripted `sed` ranges/loops/case transforms,
so for real stream programs the answer is a different tool, not a fancier `sd`.

| Instead of | Use | Command pattern | Here |
|---|---|---|---|
| `awk '{print $2}'` | `hck` / `choose` | `hck -d, -f2`, `choose 1` | ✅ |
| `awk`/`sed`/`cut`/`join`/`sort` over CSV, TSV, JSON | `mlr` (Miller) | `mlr --csv sort -f county f.csv`; `mlr --csv put '$d=$a-$b' then cut -f d f.csv`; `mlr join -j id -f a.csv b.csv` | ✅ |
| `sort`, `sort -h`, `sort -k` | GNU `gsort`, or `mlr sort` | `gsort -h`, `gsort -k2,2` | ✅ |
| `join` on a key | `mlr join`, `qsv join` | see above | ✅ |
| `tr` | GNU `gtr` | `gtr -d '\n'`, `gtr 'a-z' 'A-Z'` | ✅ |
| `wc` | GNU `gwc`, or `rtk wc` for agent-sized output | `gwc -l` | ✅ |
| `split` / `csplit` | GNU `gsplit` | `gsplit -l 1000 -d big.txt part-` | ✅ |
| `head -c` / `tail -c` (GNU semantics) | `ghead` / `gtail` | `ghead -c 200` | ✅ |
| `sed` doing ranges/loops/multi-line scripts | `srgn` for edits, `mlr` for records, `perl -pe`/`-ne` when it is genuinely a stream program, GNU `gsed` for GNU sed syntax | `perl -pe 's/x/y/g'`, `gsed -E '2,4d'` | ✅ |
| `uniq` on unsorted input | `runiq` | `runiq` | ✅ |
| `xargs -I{}` + `awk` | `rargs` | `rargs 'mv {} {}.bak'` | — |
| `date -d '2 days ago'` | GNU `gdate` | `gdate -d '2 days ago' +%F` | ✅ |
| `base64`, checksums | `b3sum` (fast), `sha256sum` (macOS ships it now) | `b3sum FILE`, `sha256sum FILE` | ✅ |
| `locate` | `plocate` | `plocate '*.pdf'` | ✅ |
| `watch cmd` | `watchexec`, `entr` | `watchexec -e py 'pytest -q'` | ✅ |
| `awk` over logs (aggregate/slice) | `angle-grinder` (`agrind`) | `agrind '* \| where status >= 500 \| count by path'` | — |
| `csvlook` / CSV eyeballing | `qsv`, `csvlens` | `qsv stats f.csv` | ✅ |
| `find`/`xargs`/`locate` (uutils) | `uu-find`, `uu-locate`, `uu-xargs` | `uu-find . -name '*.rs'` | ✅ |

## A3. The whole toolset, portably: GNU (g-prefixed) or uutils

On macOS the real problem is **BSD vs GNU flags**, not old vs new: `sort -h`,
`sed -i` (takes an argument on BSD), `date -d`, `readlink -f`, `grep -P`,
`xargs -r`, `stat -c` vs `-f`. Two prior-art answers, both installable:

1. **GNU tools with a `g` prefix** — `brew install coreutils gnu-sed gawk` gives
   `gsort`, `gtr`, `ghead`, `gdate`, `gsed`, `gawk` (coreutils is separate from
   `gnu-sed`/`gawk`, which are their own formulae). Call them by the prefixed
   name in scripts so a macOS update cannot change what the script means.
   Prepending brew's `gnubin` to `PATH` makes bare names GNU instead, but then
   everything in the shell changes behaviour, not just the one script.
2. **uutils** (`brew install uutils-coreutils`) — `uu-sort`, `uu-cut`, `uu-wc`,
   `uu-comm`, `uu-stat`, `uu-base64`, six checksum tools, `uu-tac`, `uu-split`,
   `uu-shuf`, … (put its `uubin` on `PATH` for bare names). It is a Rust drop-in
   for GNU coreutils, 24k★, now shipping by default in **Ubuntu 25.10**, and the
   org also has `findutils`/`diffutils`/`grep` (beta) and `sed`/`awk`/`procps`
   **in progress** — so it does not yet cover `sed`/`awk`.

Rule: prefer the single-purpose tool (`rg`, `fd`, `bat`, `srgn`, `mlr`, `jq`) for
the job in front of you; reach for `g`-prefixed GNU or `uu-` when a script needs
portability or a flag BSD lacks. Never write a GNU-only flag without the prefix,
and never assume the BSD form either — check `command -v gsort` first.

## B. Human-interactive: install for yourself, never call from an agent

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

## Optional installs covering the gaps above

All of these were installed and smoke-tested on 2026-10-11:

```bash
HOMEBREW_NO_AUTO_UPDATE=1 brew install hexyl ouch glow doggo ripgrep-all rargs entr csvlens \
  miller gnu-sed gawk uutils-coreutils dasel qsv watchexec b3sum
cargo install runiq                  # `runiq` is NOT in Homebrew (crates-only)
```

The second row covers the A2/A3 gaps (`mlr` for awk/sed/sort/join; `gsed`/`gawk`
and `uu-*` for GNU/portable semantics; plus the structured-data and watch tools).
Smoke tests: `mlr` 6.22, `gsed` 4.10, `qsv` 24.0, `dasel` 3, `b3sum`,
`watchexec` 2.8, `uu-sort`/`uu-wc`/`uu-comm`, `hexyl`, `ouch`, `glow`, `doggo`,
`rga`, `rargs`, `entr`, `csvlens` and `runiq` all answered.

Still uninstalled alternates — install only if a need appears: `gron` and `jaq`
(the JSON companions to `jq`), `mdcat`, `angle-grinder` (`agrind`, awk over
logs), `tailspin`, `lnav`, `fclones`, `f2`, `atuin`, `lazygit`, `aria2c`, `ov`.

One idiom to keep right: `dasel` 3 replaced its old CLI. It is
`dasel query -i json 'x.y' < f.json` — the query subcommand plus `-i`/`-o`, and
it reads **stdin**, so there is no file argument (`dasel -i json 'x.y' f.json`
fails with "unexpected argument").

**About `HOMEBREW_NO_AUTO_UPDATE=1`: it is a performance knob, not an update
switch.** It suppresses the `brew update` that brew otherwise runs in front of
`install`/`upgrade` — minutes of network work that can fail on a flaky
connection — so a multi-package install stays fast and deterministic. It does
**not** stop anything updating: `brew update` and `brew upgrade` still work, and
on this machine `site-djbclark/shell/bashrc` exports the variable machine-wide
while the scheduled `brew-fast-upgrade` Jobber job (daily 03:10) updates brew and
npm globals. Keep it on automated install lines; there is nothing wrong with it.
