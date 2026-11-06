# Indexed one-command find+grep: measurements and verdict

Reference for the `setup-modern-cli` skill (`../SKILL.md`). Supersedes the
"Experimental" section that used to live in the skill body.

Measured 2026-10-11 on a 3.3k-file Rust/JS tree (a copy of `~/src/herdr`),
pattern `serde`, file-list mode (`-l`), indexes built, one `hyperfine` pass at
low machine load (8 runs; the ratios move with load, so compare within a run,
not across):

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
   invisible **even after `ayg build`** — verified: a new untracked file was not
   found after a rebuild, and only appeared once `git add`ed. It also writes
   `ayg_index/` **inside the repo** (54.7 MB for 3.3k files; 131 MB `lookup.bin`
   + 668 MB `postings.bin` + 2.3 GB `content.bin` on a large monorepo). There is
   no watch/incremental mode and no flag for extra file types; upstream is 3
   stars / 13 commits / 0 forks / no issues, so **no fork fixes this**.
4. **`ig` (instant-grep) is the better indexed option** — index in `~/.cache/ig`
   (not the repo), 16 s and 189 MB for this corpus, and a file added after the
   build **is** picked up by `ig index` even when untracked (unlike `ayg`). It
   still needs a rebuild after edits, and it missed 6 `vendor/` files `rg`
   returns, so verify recall. `ig` is really a whole token-optimization suite
   (`ls`, `read`, `symbols`, `git`, `test`, `run`, agent hooks, `import-rtk`)
   that overlaps `rtk`.
5. **`xg` (xgrep)** indexes into `~/Library/Caches/xgrep/`, needs re-index, and
   returned one file `rg` ignores; `ffs` (`quangdang46/fast_file_search`) does
   **not build here** — its `zlob` dependency needs Zig — so it is unverified.
6. **No `rg` flag magic.** On the same corpus `rg -F` was +4%, `rg -j8` ±0%,
   `rg --no-mmap` **+15% slower**, and `rg --sort path` **396% slower** (sorting
   serialises the search). Performance advice that matters is process, not flags:
   pass an explicit path, use `-l`/`-c` to cut output, keep the tree inside one
   filesystem, and do not add `--sort`.
