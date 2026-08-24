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

