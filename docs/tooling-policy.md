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
  indexes lazily from whatever repo the session is running in, so it needs no
  per-repo setup at all. It also owns things graft has no equivalent of:
  `find_dead_code`, `detect_breaking_changes`, `analyze_config`,
  `find_semantic_duplicates`, `get_entry_points`, and index-aware structural
  edits (`replace_symbol_source`, `add_field_to_model`).

**Correction, 2026-10-03:** an earlier version of this section said nothing under
`~/src` had a graft graph. That was wrong — it checked for a hidden `.graft/`.
**36 of the 77 repos under `~/src` already carry a committed `graft/`**, including
`aiuse`, `herdr`'s siblings, `orca`, `litellm`, `Shizuku` and the libntech set.
graft's coverage here is already broad, not confined to `~/ops`.

So: **graft first in the three ops repos, token-savior first everywhere else,
either one before `cat`/`rg`/`Grep` for code discovery.** Reach across that line
whenever the other tool is the one that answers the question.

### Why that order, measured 2026-10-03

The split above was assumed from coverage. These are the numbers that confirm it,
taken on `stayturgid` where both tools work:

| | graft | token-savior |
|---|---|---|
| symbols extracted | 2 898 functions+methods, 140 classes | 2 411 functions, 68 classes |
| index build | 3.6 s, free, 15 MB | 5.3 s, 13.6 MB in the repo root |
| languages | go, java, **kotlin**, php, python, r, **swift**, ts/js (+`--lsp` for rust/c) | **c, c#, rust**, go, java, php, python, ruby, ts |
| "who calls X" | `graft_trace_calls` — 14 callers, one call | no advertised tool (see below) |
| scope per call | all three ops repos at once | one active project |
| uncommitted edits | refreshes the graph before answering | incremental cache update |

**graft is the better navigator wherever its graph exists.** Same 14 callers for
`run_command_with_timeout`, denser output, and it reports its own token saving per
call. It also extracts ~20% more symbols from the same tree, and it has Kotlin and
Swift, which this machine's Android and macOS repos need.

**"Who calls X" is awkward on token-savior and natural on graft.** `get_call_chain`
is a path-finder between two named symbols and rejects a single `symbol=` —
`{"from_name":"X","to_name":""}` answers `no path`. Two tools do answer it:
`get_full_context` (advertised, returns a `dependents` list) and `get_dependents`
(hidden by the profile but still callable, since the server accepts unadvertised
names — note validation is skipped for those, so a wrong argument name costs a
silent round trip; it is `name=`, not `symbol=`). graft answers the same question
from the tool whose name says so, about 5x denser once its banner is discounted.

**Operator's call, 2026-10-03: graft's footprint is not a factor.** It edits the
tracked `.gitignore`, writes `.ignore` and creates `graft/` in whatever repo you
build in — including forks and upstreams — and that is explicitly fine. With that
off the table nothing argues for token-savior as the *navigator* anywhere, so the
order collapses to one rule:

> **graft is the navigator in every repo.** If a repo has no `graft/` yet, run
> `graft build` (free, no API key, ~0.4 s on a 10-file repo and ~3.6 s on
> stayturgid's 282) and then use it. token-savior is what you reach for in a repo
> nobody has built yet, and for the four things graft does not do at all.

Those four, and the only reasons token-savior stays installed:

1. `find_dead_code` — project-wide unreferenced symbols.
2. `detect_breaking_changes` — removed/changed signatures against a git ref.
3. `analyze_config` and `find_semantic_duplicates`.
4. Index-aware structural edits: `replace_symbol_source`, `add_field_to_model`.

`get_function_source` is a fifth, but `graft_find_code --full` covers the same
ground — and given defect 1 below, graft is the safer way to read a function.

### Measured defects — read before trusting either tool (2026-10-03)

Both tools returned at least one confidently wrong answer under test. These are
the ones that change how you call them:

1. **`get_function_source` returns no function body by default. Always pass
   `force_full: true`.** Asked for `lan_ipv4`, it returned 82 characters — the
   signature and docstring summary, none of the eight body lines that gate on
   CGNAT, loopback and link-local. On a second symbol the same call returned a
   551-char stub with type annotations stripped and the body simply absent, then
   the correct 980 chars when repeated with identical arguments. The escalation
   level is persisted in `.token-savior-cache.json` and survives across
   processes, so the answer depends on invisible accumulated history: 980, then
   385, then 551, then 980 for one symbol in one session. `force_full: true`
   returned correct complete source on the first call, verified byte-for-byte.
   An agent that edited on the strength of the default reply would destroy logic
   it never saw.
2. **`find_symbol` silently collapses ambiguity.** `~/src/herdr` has seven
   `fn main` definitions; `find_symbol {"name":"main"}` returned exactly one —
   and not `src/main.rs`, the real entry point — with nothing in the response
   indicating six others exist. `level:2` did not help. Use `get_entry_points`
   or `search_codebase` when more than one definition is plausible;
   `get_entry_points` listed them all correctly.
3. **`find_dead_code` is a lead list, never authority — ~43% false positives in
   a 7-finding spot-check.** Among the false positives: `dispatch` on a
   `BaseHTTPMiddleware` subclass in `control/bin/firerpa_mcp.py`, which *is* the
   bearer-token authentication check Starlette calls on every request. Also an
   `HTMLParser.handle_starttag` override, an `HTTPRedirectHandler.redirect_request`
   override, and an `@property` referenced five times from tests. Root cause: it
   labels methods as functions and counts only bare-name references, so anything
   framework-dispatched, inherited or reached by attribute access reads as dead.
   Verify every finding against source before deleting anything.
4. **`detect_breaking_changes` was accurate** on a dirty tree (5 issues, all
   correctly classified) but analyses Python only — it silently ignored two
   changed Ansible YAML files in the same diff.
5. **`graft_file_api` fails unless the server's cwd is the repo root.** From a
   session rooted at `~/ops` it returns `no wiring graph — run graft build
   first` for a file whose graph plainly exists; every other graft tool works
   from that same cwd. Run it from inside the repo, or use `graft ask`.
6. **Scope workspace-wide graft queries.** From `~/ops`, `graft_find_code
   "extract_devlog_lines definition"` ranked an unrelated `_extract_turns` in a
   different repo above the exact-name match. `in: "stayturgid/"` fixes the
   ranking; so does running from the repo.
7. **Neither tool resolves alias-qualified callers, so blast radius is
   under-reported by both.** For `extract_devlog_lines` (4 real call sites) graft
   and token-savior each returned the same 2, omitting both
   `tests/python/test_fleet_health.py` calls made as `fh.extract_devlog_lines(…)`
   through a module alias. Tests are exactly what breaks when you change a
   function, so back a blast-radius answer with a grep for the bare name before
   relying on it. token-savior additionally emitted malformed `null` entries in
   its `dependents`/`dependencies` lists here.
8. **First token-savior use on a fresh machine hits the network.** The cold path
   downloaded an embedding model from the HuggingFace Hub (~8 s of a 15.8 s cold
   call) and warned about unauthenticated Hub requests. Already warmed here; it
   matters for offline work.

They also do not index the same corpus: for stayturgid, token-savior indexed
1504 files including the vendored `.ansible/collections/` tree, graft 282 code
files. That alone explains much of the divergence in their result sets.

### How it is wired — 11 agent CLIs, one identical command

```bash
uv tool install "token-savior-recall[mcp,memory-vector]"   # ~/.local/bin/{token-savior,ts}
claude        mcp add token-savior --scope user -- /Users/djbclark/.local/bin/token-savior-mcp
codex         mcp add token-savior              -- /Users/djbclark/.local/bin/token-savior-mcp
opencode      mcp add --global token-savior     -- /Users/djbclark/.local/bin/token-savior-mcp
grok          mcp add token-savior                 /Users/djbclark/.local/bin/token-savior-mcp
agy           mcp add token-savior                 /Users/djbclark/.local/bin/token-savior-mcp
```

Hand-edited, because they have no add subcommand or it is broken:
`cursor-agent` (`~/.cursor/mcp.json`, then `cursor-agent mcp enable token-savior`),
`zcode` (`~/.zcode/cli/setting.json`, under `mcp.servers`),
`crush` (`~/.config/crush/crushrc`, an `mcp add …` DSL line),
`goose` (`~/.config/goose/config.yaml`, under `extensions`, `cmd:` not `command:`),
`qwen` (`~/.qwen/settings.json`, `mcpServers` — the key did not exist before),
`copilot` (`~/.copilot/mcp-config.json`, `"type": "local"` — its own
`mcp add` *and* `mcp list` both fail with "The shared writer lock or its directory
changed", which is pre-existing and not caused by the edit).

Not possible: `gemini` and `openclaw` are not installed (`~/.gemini` belongs to
`agy`, which reads `~/.gemini/config/mcp_config.json`; upstream Gemini CLI would
read `~/.gemini/settings.json`, a different file); `aider` has no MCP support;
`orca` is an orchestration host, not an MCP client. `hermes` *is* an MCP client
with a working `hermes mcp add`, but it is deliberately left out — `basic-memory`
is disabled there too, and `~/.hermes/` is not ours to hand-edit.

Verification per client, where one exists: `codex mcp get`, `cursor-agent mcp list`
(→ `ready`), `agy mcp list` (→ `enabled`), `grok mcp list`, and
`opencode debug config` — **not** `opencode mcp list`, which prints "No MCP servers
configured" even when servers are loaded. An end-to-end tool call from a non-Claude
host is still unproven: the codex attempt hit its usage limit before the call.

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
alternatives are 1, 6, 51 or 68 tools), `TS_CAPTURE_DISABLED=1` and
`TS_MEMORY_DISABLE=1`. Everything is `${VAR:-default}`, so the MCP config's `env`
or the shell can override any of it without editing the script.

Two bits of hardening, both there so one identical registration is safe on every
host rather than needing per-client `env`/`env_vars` bookkeeping:

- **`HOME` and `PATH` are rebuilt if absent.** Codex whitelist-filters the
  environment it hands an MCP server, and its filter also strips any variable
  whose name contains `KEY`/`SECRET`/`TOKEN` — which would silently eat
  `TOKEN_SAVIOR_BIN`. Verified by running the launcher under `env -i`.
- **The repo root is resolved without trusting `PATH`.** A host that passes a
  filtered `PATH` with no `git` on it would make `git rev-parse` fail silently and
  fall back to the standing `~/ops` list — answering confidently from the wrong
  codebase, the exact thing the launcher exists to prevent. It now tries git from
  an explicit candidate list and, failing that, walks up for a project marker in
  pure bash. Verified from `~/src/herdr` with `PATH=/usr/bin:/bin` and with
  `PATH=/nonexistent`; both still resolve `herdr` as the active project.

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

**Memory stays with Basic Memory.** `TS_MEMORY_DISABLE=1` drops
`memory_*`/`reasoning_*`/`corpus_*` from the manifest *and* from what `ts_search`
can route to, so nothing reaches for token-savior's own SQLite store
(`~/.local/share/token-savior/memory.db`) — a second durable store no other agent
on this machine can read is state divergence, not redundancy. It is also what
upstream's benchmarked configuration uses: `optimized` is an alias for the
tiny_plus manifest only, and the documented Pareto config is that manifest *plus*
`TS_THIN_SCHEMAS=1 + TS_CAPTURE_DISABLED=1 + TS_MEMORY_DISABLE=1`.

**The `[memory-vector]` extra is installed**, and it earns its 132 MB (tool venv
40 MB → 172 MB; the Nomic model was already in the shared `~/.cache/huggingface`).
It is what makes `ts_search` — the router to the ~51 tools the profile hides —
actually work: the same query went from `method: "substring"`, top hits
`find_dead_code`/`find_symbol` at score 0.25, to `method: "embedding"`, top hit
`detect_breaking_changes` at 0.692. The 1.1 MB tool-embedding cache persists
across server respawns, so only the first call pays the model load.
