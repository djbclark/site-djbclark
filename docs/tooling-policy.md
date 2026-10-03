# Tooling policy — modern CLI tools and structural search

Moved out of `AGENTS.md` on 2026-08-24. This is reference material an
agent consults when choosing a tool; `AGENTS.md` loads into context every
session, so keeping 78 lines of it there taxed every message.

## Modern CLI tool policy (any vendor AI, any of the three repos)

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

## Structural/semantic code search — `ast-grep` and `semgrep`

> **Not the same thing as the retired semgrep gate.** Automated semgrep
> scanning in hooks/CI was turned off 2026-08-23 (too many findings that were
> not defects). The `semgrep` *command* below is still installed and still the
> right tool for an ad-hoc structural query — nothing here asks you to
> re-enable a gate.

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


## Symbol-level navigation — `graft` and `token-savior` (added 2026-10-03)

One layer above structural search: both of these index a repo by *symbol*
(function, class, import, call edge) and answer with a `file:line` span plus the
few lines that matter, instead of a file you then have to read. A `find_symbol`
that returns 187 characters replaces a `cat` that returns thousands.

They are not redundant here, because their coverage does not overlap:

- **`graft`** is the navigator in the three ops repos — `stayturgid`,
  `site-djbclark`, `site-private` each carry a committed `graft/` graph, and a
  `PreToolUse` hook reminds every Bash call to prefer it. Nothing in `~/src` has
  a graft graph, so outside those three the graft tools have nothing to answer
  from.
- **`token-savior`** (PyPI `token-savior-recall`, MCP server `token-savior`)
  indexes lazily from whatever repo the session is running in, so it is the only
  symbol-level option in the ~80 repos under `~/src`. It also owns a few things
  graft has no equivalent of: `get_function_source`, `find_dead_code`,
  `detect_breaking_changes`, `analyze_config`, `find_semantic_duplicates`, and
  index-aware structural edits (`replace_symbol_source`, `add_field_to_model`).

So: **graft first in the three ops repos, token-savior first everywhere else,
either one before `cat`/`rg`/`Grep` for code discovery.** Reach across that line
whenever the other tool is the one that answers the question.

### How it is wired (Claude Code, user scope)

```bash
uv tool install "token-savior-recall[mcp]"            # ~/.local/bin/{token-savior,ts}
claude mcp add token-savior --scope user -- /Users/djbclark/.local/bin/token-savior-mcp
```

`token-savior-mcp` is a launcher in
[`site-private/bin/`](https://github.com/djbclark/site-private/blob/master/bin/token-savior-mcp),
symlinked into `~/.local/bin/`. It exists because neither way of configuring the
roots works on this machine:

- unset `WORKSPACE_ROOTS` auto-discovers from the server's cwd plus one level
  under `~/src`, `~/dev`, … and caps at 40 — which fills up alphabetically
  inside `~/src` and never reaches the `~/ops` repos;
- a static `WORKSPACE_ROOTS` list makes a session in any unlisted repo resolve
  symbol lookups against whichever pinned project is active, i.e. answer
  confidently from the wrong codebase.

An MCP stdio server inherits the session's working directory, so the launcher
computes the roots at startup instead: the current repo first (promoted to active
via `CLAUDE_PROJECT_ROOT`, which is token-savior's own override and set by no
host), then the three ops checkouts so they stay reachable by name from anywhere.
Any other path registers on demand when passed as `project=`.

It also pins `TOKEN_SAVIOR_PROFILE=optimized` (15 tools, ~9 KB manifest — the
alternatives are 1, 6, 51 or 68 tools) and `TS_CAPTURE_DISABLED=1`. Everything is
`${VAR:-default}`, so the MCP config's `env` or the shell can override any of it
without editing the script.

### Two things to know

1. **It writes `.token-savior-cache.json` into the repo root** — 13.6 MB for
   stayturgid — and has no environment variable to relocate it. Both that name
   and the legacy `.codebase-index-cache.json` are in `~/.config/git/ignore`, so
   it does not dirty a tree; it does land in the daily CCC snapshots.
2. **`rtk` owns the Bash layer, not token-savior.** token-savior ships its own
   Bash compactors and a `PreToolUse` rewriter, and `~/.claude/settings.json`
   already runs `rtk hook claude` on `PreToolUse: Bash`. Upstream's guidance for
   exactly this overlap is "pick one". The launcher pins `TS_BASH_COMPACT=0` and
   `TS_BASH_REWRITE=0`; **do not run `ts init`**, which would write a second,
   competing hook.

Vector search for `ts_search` is intentionally not installed (the
`[memory-vector]` extra pulls fastembed/ONNX and downloads embedding models); it
falls back to SQLite FTS5, and the server logs one line per start saying so.
