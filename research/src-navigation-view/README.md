# A navigable view of ~/src: prior art and the virtual-filesystem question

Research behind `tools/s-farm` (the locked symlink farm at `~/s`), 2026-10-06.
Two web surveys were run by Claude Haiku sub-agents; a Claude Fable session
checked what it could and wrote this up. Items marked *unverified* come from
the sub-agent reports and were not confirmed.

## Question 1: does a tool already build a categorised symlink farm?

No. A custom script is justified.

| Tool | What it does | Why it does not fit |
| --- | --- | --- |
| ghq, projj, git-workspace | Lay clones out as `host/owner/repo` | They restructure the real directories; no user-chosen topics |
| GNU Stow, XStow, lndir | Mirror one tree into another with links | One source tree to one target; no categories |
| TMSU, tagsistant | Tag files, browse by tag | Need a FUSE mount; tag per file, not per project |
| myrepos, gita, mani | Run commands across many repos | No view of the filesystem at all |
| zoxide, fzf | Jump by frecency or fuzzy match | Complementary: they find a directory, they do not give a browsable tree |
| Rinkle, Pilgo | Declarative link-farm managers | *Unverified*: named by the survey, not checked |

Ideas taken from them: placement rules in one declarative file, a dry run
(`plan`), idempotent regeneration that prunes stale links, and no state file
(a link is recognised as the tool's own by where it points).

## Question 2: would a userspace virtual filesystem be better?

No. For this use it is worse than regenerated symlinks.

1. **A daemon to keep alive.** macFUSE (kernel extension, or its FSKit backend
   on macOS 15.4+), FUSE-T (NFS loopback) and `rclone nfsmount` all leave a hung
   or empty mount point when their process dies. Agents and builds that `cd`
   through the view would stall. A symlink has no failure mode beyond dangling.
2. **Overhead on git and builds.** Every file operation crosses the userspace
   boundary; the survey reported macFUSE's FSKit backend as markedly slower than
   its kernel extension (*unverified numbers*).
3. **Nothing ready-made.** No maintained tool presents "these real directories,
   rearranged into this tree" on macOS. mergerfs is Linux/BSD only. bindfs was
   reported as Linux-only, which is wrong as far as we know (it builds against
   macFUSE), but it re-exports one directory rather than composing a tree.
4. **Native options do not fit.** `/etc/synthetic.conf` and firmlinks are for
   root-level entries and are static; autofs is for network mounts; File Provider
   extensions are built for cloud sync.
5. **File watching and real paths.** Symlinks resolve to the real `~/src` path,
   so FSEvents, git and editors behave exactly as they do without the view.

The one weakness of the farm, going stale, costs a sub-second `just` run.

## Fuzzy matching for the `just NAME` jump

fzf's matcher needs the query's letters in order, so it handles partials and
abbreviations but not typos (a swapped or wrong letter matches nothing). skim
recently gained a typo-resistant matcher (*unverified*; not installed here).
The jump therefore uses rapidfuzz for edit distance (Damerau-Levenshtein, so a
swap counts as one edit) and fzf for abbreviations and the selection list.

## Side findings

1. Interactive bash here runs with `failglob`, so an unquoted `just physi*`
   is rejected by the shell before `just` starts. The jump works around it with
   an alias that disables globbing for that one command line, active only inside
   the farm.
2. graft writes a per-session cache to `<cwd>/graft/.cache/session/<id>.json`
   on each prompt. In the locked farm that write cannot succeed, one more reason
   agent sessions should start in `~/src/<name>` and not in `~/s`.
3. `chflags uchg` on a directory blocks creating, deleting and renaming its
   entries and renaming or deleting the directory itself, for the owner too,
   without root. It is a file flag, not an extended attribute.
