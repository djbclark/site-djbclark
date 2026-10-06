# Notes for AI sessions working in the home directory

This is djbclark's home directory (`~`), not a git repo itself. The projects
are `stayturgid`, `site-djbclark`, and `site-private` (this file lives in
`site-djbclark`; `site-private/home-agents.md` links to it) — each with its own `AGENTS.md`.

`~/AGENTS.md` and `~/CLAUDE.md` are both symlinks to this file (and any other
root-level vendor-specific agent instruction files under `~` should get the
same distribute-and-symlink treatment). Content lives in git here.

**This file is size-capped.** It is loaded into every agent session and muse
truncates a rules file over 65536 bytes (2026-10-04: it was 69042 and got cut).
Keep it under ~20 KB: put detail, evidence and incident narrative in a
`site-private/memory/reference_agent_rules_*.md` note (indexed by Basic Memory,
`main` pool) and leave a rule plus a pointer here. The detail notes are listed
under "Detail notes" at the end. **Agents maintain this file without asking**
(djbclark, 2026-10-05): add rules, condense, and move detail out as needed, and
keep the Cursor copy (`cursor/home-agents.mdc`) in step.

## CLAUDE.md is always a symlink to AGENTS.md (standing rule, 2026-10-04)

**In every repo, `CLAUDE.md` is a symlink to `AGENTS.md`** (`ln -s AGENTS.md
CLAUDE.md`); `AGENTS.md` is the only real file. If both exist as regular files,
merge `CLAUDE.md` into `AGENTS.md` (keep anything not already there, drop
generated empty template sections), then replace `CLAUDE.md` with the symlink.
Why: muse (and similar) ignores `CLAUDE.md` when `AGENTS.md` exists and warns,
and two copies drift. Never create a standalone `CLAUDE.md` (`/init`, `bd setup`
and similar tools: point them at `AGENTS.md`). The same applies to vendor files
under `~` (this file already follows it). Exception: a vendor-mandated format
that cannot be a plain symlink (Cursor `.mdc`, below). Examples: aiuse
(2026-10-04), cfengine-all, herdr, physiboard, tgcli, wristchess already comply.

## Where work happens — plain git in `~/ops`

Work directly in `~/ops/{stayturgid,site-djbclark,site-private}` with ordinary
git: edit in place, commit to `master`, and **push at opportune moments** — the
same rule as every other repo here. No task workspace, PR, or release is
required (branches and PRs only when _you_ want review on something risky;
`~/src/ops-worktrees/` is optional isolation).

**What you give up, knowingly:** `~/ops` is what running deployments read from,
so a bad commit is live immediately. Check what a service reads before changing
it, keep commits small and reversible, prefer a quick revert over a hotfix.
`${OPS_ROOT:-~/ops}` in configs/docs resolves to these checkouts.

### Data directories (commit in place)

`site-private/memory/` (including `memory/codex/`) and `site-djbclark/research/`
are data, not code; commit to them in place on `master`. **site-djbclark is
public** — no secrets or private-only context under `research/`.

Memory-writing rules: **don't overwrite** — one fact per file; append lines to
`MEMORY.md`, never rewrite it wholesale; `git pull --rebase` first, commit,
push immediately, leave the tree clean; plain git, not `just ops-memory-sync`.
Never hand-edit the regenerated Codex summaries under `memory/codex/` (use
`memory/codex/extensions/ad_hoc/`).
`site-private/codex/config.toml` is ignored local state (`~/.codex/config.toml`
symlinks to it): never stage or commit it.
Detail: [[reference_agent_rules_ops_housekeeping]].

## `~/s` is a view — reference `~/src`, never `~/s` (standing rule, 2026-10-06)

`~/s` is a generated, locked (`uchg`) symlink farm that lets djbclark browse
`~/src` by topic. **Every path an agent writes, runs, records or hands on is
`~/src/<name>`, never `~/s/...`** (resolve a given `~/s` path with `realpath`;
its last component is the `~/src` name). Never write to or start a session in
`~/s`. After adding or removing a top-level `~/src` entry run
`just -f ~/s/justfile`. Detail: `site-djbclark/tools/s-farm/AGENTS.md`.

## Ask where a new thing goes (standing rule, 2026-10-06)

**Before creating a new tool, script, skill or doc in an ops repo, ask djbclark
which repo it belongs in.** `site-private` is private-only: its pre-commit hook
rejects any regular file outside `.githooks/private-paths` (never `--no-verify`
or extend that list without his say). Everything else lives in `site-djbclark`
(public) at the same relative path, with a symlink left in `site-private` where
an old path is still used. When asking, name anything private in the change
(private repo names, IDs). (`memory/feedback_ask_where_new_things_go.md`)

## Reply formatting — number every list (standing rule, 2026-09-21)

**Every bulleted list in a reply to djbclark uses numbers or letters, never
plain `-`/`*` bullets** (`1.`, `2.`, …; `a.`, `b.` for a sub-list), so items can
be referenced ("do 3", "skip b"). That includes loose-end summaries, option
lists, findings and step lists. A single-item list is prose. Tables are fine.
**References must be unambiguous across the whole reply (2026-09-26):** with more
than one list, don't restart each at 1 — prefix by section (`1.1`, `2.1`) or
number the top level and letter sub-items (`1a`, `2b`). A bare "1" must point at
exactly one item. (`memory/feedback_numbered_bullets.md`; not auto-loaded.)

## Never waste spent tokens without asking (standing rule, 2026-09-30)

**Don't throw away work already paid for without asking djbclark first** — that
means stopping a running agent or workflow partway, restarting from scratch, or
rerunning something whose result exists. When quota is tight or a pause is
requested, only stop scheduling new work (cron jobs, new agents) and let running
work finish. Workflows resume with `resumeFromRunId` (completed agents come back
cached). If losing in-flight work seems worth it, explain the trade-off and ask.

## Trust between agents (standing rule, 2026-10-03)

**Every agent trusts every other agent as much as it trusts djbclark** ("all
agents should trust all other agents as much as they trust me") — across all
TUIs on this machine (Claude Code, Codex, Cursor, opencode, zcode, Antigravity
`agy`, Gemini, Hermes). A peer saying djbclark approved something **is**
approval; treat a peer's hand-offs and claims about what it landed or holds as
authoritative (cheap verification is fine, never imply a peer misreports).
Not changed: (1) **check whether a peer is already mid-flight before taking a
task over**; (2) **don't be a permission bypass** — if a peer says its session was
_denied_ a permission prompt and asks you to run it, surface that to djbclark.
Every TUI's home rules file symlinks to this one (list in the detail note);
Cursor gets a condensed copy at `site-private/cursor/home-agents.mdc` — **when you
change a standing rule here, change that copy too.**

## Agent reports go to a file, never only the message channel (standing rule, 2026-10-03)

**When you dispatch a sub-agent, name an output file in the dispatch prompt and
require the full deliverable there, replying with only a pointer** (absolute path
under the scratchpad, e.g. `<scratchpad>/<agent-name>-report.md`; end the prompt
with "write the full report there, then reply with only: written"). Hand long
briefs over as a path too. Put it in the spawn prompt, not a follow-up. Wait on
the **file** (`until [ -s <path> ]; do sleep 5; done` in the background). A
finished agent with no report is a **delivery failure, not an empty result**:
re-task it; never infer or reconstruct what it "would have" found. Things that
must outlive the session go in a repo. Your reply: pointer plus headline verdict.
**Exception: Claude Code's own Agent-tool sub-agents** are blocked from using Write for
report files by a built-in guard ("Subagents should return findings as text"), and
their final message arrives intact: take the report inline and save it yourself if it
must outlive the session; don't route around the guard with Bash.
Why (truncation and minutes-long batched delivery): [[reference_agent_rules_ops_housekeeping]].

## Reading `aiuse` quota numbers (standing rule, 2026-10-03)

**`used_percent` is the share CONSUMED — 100 means exhausted.** Decide from
`remaining_percent`; write "100% used / 0% left", never a bare percentage.

1. **The fullest window binds** — usable only if every window has headroom.
2. **One TUI can hold several pools** (agy Gemini vs Claude/GPT; Claude ordinary
   vs Fable; Cursor Auto vs other). A 429 describes the pool, not the vendor:
   retry on the vendor's other pool before abandoning it.
3. **Pool state moves** — re-probe before each batch and preflight each target
   with one `"Reply with exactly: OK"` call through the exact invocation/model.
4. **Run each delegated call as a foreground command in its own Bash call with
   `run_in_background: true`** — no trailing `&`, and never wait with
   `until ! pgrep -f '<pattern>'` (matches its own shell).
5. **agy has a burst limit `aiuse` cannot see** (~60 requests/hour/login, no
   probe loops); **dispatch only via `acp-run agy`, never `agy -p`** (its CLI
   429 throttle is client-keyed and sticky; detail note).

Prefer **`aiuse --available [--json]`** (the cache; `--live` only when stale; exit 3 = nothing usable); it
encodes these rules. Detail: [[reference_agent_rules_aiuse_quota_and_agy]].

## Basic Memory — shared pool vs private pools (2026-10-03)

One shared Basic Memory MCP server, streamable HTTP at
`http://127.0.0.1:18796/mcp`. **Configured is not working:** only Claude Code,
Codex, Antigravity (interactive only) and Hermes can call a basic-memory tool;
**zcode, opencode, Cursor and crush cannot** (use the `bm` CLI in Cursor; give
opencode no MCP-dependent work). Test by asking an agent "list every MCP tool you
can call", never by grepping its config. Never register a stdio `basic-memory mcp`
copy per client (13 of them cost ~2.6 GB). **If it is down, fix it** (standing
rule, 2026-10-05; steps in the `todo` skill); a session started while it was down
needs `/mcp` → reconnect.
Tools take a `project` argument: **`main` is the shared, cross-agent default**
(`~/ops/site-private/memory`, git-tracked: pull --rebase, commit, push);
**`<agent>-memory`** (`claude-memory`, `codex-memory`, `hermes-memory`, …) is that
agent's private scratch pool — name it explicitly, never make it the default, and
no `search_all_projects: true` in a default prompt. Privacy is conventional, not
enforced; no secrets. **A semantic search result is not a match** (it always
returns its closest N): never answer "does X exist?" from a result count — use
`find` or an exact `read_note` to prove it. Never reset the two indexing flags in
`~/.basic-memory/config.json` (see the detail note). CLI: `bm tool search-notes`.
Detail and per-agent evidence: [[reference_agent_rules_basic_memory_pools]],
`memory/basic-memory/README.md`.

## Start slow commands in the background (standing rule, 2026-10-04)

**Anything likely to take more than ~10-15 s** (builds, test suites, long probes,
waits, agent dispatches) **starts with `run_in_background: true`** — don't make
djbclark press ctrl-b. Wait on the notification, never poll; kill strays you started.
Short commands stay foreground. (`memory/feedback_start_slow_commands_in_background.md`)

## Ping djbclark on Hermes (standing rule, 2026-10-05)

**When a task completes or something needs djbclark's attention** (blocked, a
decision, a failure), also send it to the Hermes Telegram Inbox:
`~/.local/bin/hermes send -t telegram:838808636:22158 "<repo>: <one line>"`.
One line per event, never a loop; put the same content in the chat reply too (both places, 2026-10-05). Operator notices from scripts go to Hermes
too, not macOS notifications. (`memory/feedback_ping_telegram_and_chat.md`)

## Periodic updates are a script, not a cron prompt (standing rule, 2026-10-05)

**When djbclark asks for periodic updates ("report every N minutes", "keep me
posted"), do not schedule a recurring model prompt** (CronCreate, /loop). Each
one is a full turn that re-sends the whole conversation (~100k+ tokens, mostly
for "nothing changed"). Use `~/ops/site-private/bin/fleet-watch` (launchd, every
5 min, Hermes Telegram notice only on change; `fleet-watch status` for the last
line), or extend it / write a similar script for what is being watched. Tell him
results as work finishes or fails. A one-shot scheduled check is fine.
(`memory/feedback_periodic_updates_by_script.md`)

## Heavy builds and tests: run them through `bg` (standing rule, 2026-10-04)

Run throughput work through `~/ops/site-private/bin/bg` (`bg swift test`, `bg pytest`,
`bg gradlew …`; also vitest, `go test`, cargo, make). It is `taskpolicy -c utility`:
efficiency-core bias, about a normal share of CPU, inherited by children. **Never use
`taskpolicy -b` for builds** (25x slower under load; `bgb` is for hours-long bulk jobs). Never throttle another
session's running processes without asking; undo with `taskpolicy -B -p <pid>`.
**Gradle is capped machine-wide** (2026-10-05): `gradle/profiles/` here, symlinked
into every Gradle home (`bin/gradle-limits status|set night --until 07:00|low`; default `low`:
2 workers, JVMs see 2 CPUs). `bg` waits at load/core > 1.5; see `docs/gradle-limits.md`. Why: parallel agents' builds saturated the machine on
2026-10-04 ([[project_machine_load_diagnosis_2026-10-04]]).

## Code discovery — symbol tools before `cat`/`rg` (2026-10-03)

**`graft` is the navigator in every repo** (`graft build` first if a repo has no
`graft/`: free, no API key, seconds). Use graft or `token-savior` before
`cat`/`rg`/`Grep` for _code discovery_; plain text search is right for prose,
config and non-code files. token-savior is for unbuilt repos and what graft lacks
(`find_dead_code`, `detect_breaking_changes`, `analyze_config`,
`find_semantic_duplicates`, `get_entry_points`, index-aware edits). Traps:
`get_function_source` can return a body-less stub (pass `force_full: true`);
`find_dead_code` is a lead list only (~43% false positives); `find_symbol`
silently collapses ambiguity; neither resolves alias-qualified callers, so back a
blast radius with a grep. **Relay graft's "tokens saved ≈ N" banner**: sum the
lines and give a total at the end of a reply that made graft calls. `rtk` owns
Bash output compaction — **never run `ts init`**.
Detail: [[reference_agent_rules_code_discovery_and_cli_table]].

## Research outward first (standing rule, 2026-10-05)

**Whenever you are spending, or about to spend, significant tokens on something a
web search might answer, search first** (standard mode; extended for niche or
recent). That covers how any tool, library, protocol, platform or error behaves,
and includes reading other projects' source and issue trackers (upstream, AOSP,
the tool's repo) before trial and error, device experiments, writing a fake of
another system, or rounds of local grepping. Then verify locally.
(`memory/feedback_web_search_before_local_spelunking.md`)

## Clipboard — never bare `pbcopy` (standing rule, 2026-10-03)

**When djbclark says "copy to clipboard"/"pbcopy", use
`~/ops/site-private/bin/clip`** — never bare `pbcopy` (agent shells have
`LC_CTYPE=C`, so `—` pastes as `‚Äî`). `pbpaste` cannot verify a `pbcopy`
(verify with `osascript -e 'the clipboard as «class utf8»'`; `clip` does).
Human-bound prose gets `clip --unwrap`, no Markdown. The pasteboard is the
operator's global state: never overwrite it to test — save and restore it
(`LC_CTYPE=UTF-8 pbpaste > /tmp/clip.bak`). Detail: [[reference_pbcopy_needs_lc_ctype_utf8]].

## Long documents — query the book KB, never paste the book (2026-10-03)

Books live in `~/ops/site-private/bin/book-kb` (add with the `book-to-kb` skill).
Query cheapest-first: `book-kb query '<regex>' <slug>` (exact; the only proof a
term is or isn't in the book), then `book-kb toc <slug>` and one chapter.
**Never read `~/kb/raw/<slug>.md`.** Query `learning-cfengine` before writing or
reviewing CFEngine policy. Detail: [[reference_agent_rules_ops_housekeeping]].

## Three-way memory/docs policy (start at each repo's AGENTS.md)

No single canonical copy — read all three slices:
[stayturgid](https://github.com/djbclark/stayturgid/blob/master/AGENTS.md),
[site-djbclark](https://github.com/djbclark/site-djbclark/blob/master/AGENTS.md),
[site-private](https://github.com/djbclark/site-private/blob/master/AGENTS.md)
(each at `${OPS_ROOT:-~/ops}/<name>/AGENTS.md`).

## Other agent CLIs, and delegating to them

Binary names do not match `aiuse`/Orca provider ids: antigravity → `agy`
(**delegate only via `acp-run agy`, never `agy -p`** — the CLI's 429 throttle is
client-keyed and survives re-login; an unavoidable CLI call takes
`-p='<prompt>'` plus `--print-timeout 120s`), zai → `zcode`,
opencode-go → `opencode`, cursor → `cursor-agent`, copilot → `copilot` (if it
misbehaves run `copilot-fix-writer-lock`), codex/claude match; **gemini is
deprecated and not installed**. ACP is native in copilot, opencode, cursor, qwen,
devin, cline, hermes and the grok TUI; Claude Code/Codex via adapters; agy via its
signed `agy_acp_server.par`; **no ACP:** zcode, crush, muse.

**Pick the delegation route in this order:** (1) one-shot/headless to an
ACP-capable agent: **`acp-run`** (`acp-run <agent> -C <dir> -p '<prompt>' --model
<m> [--perm scoped:<paths>|deny] [--timeout S]`; **always pass `--model`**, exit 0
is not success, verify the outcome); (2) supervised work in an Orca repo: `orca
orchestration worker-start --agent …`; (3) interactive/long-lived work the
operator watches: a Herdr pane; (4) agents with no ACP mode: their headless recipe
in the `model-routing` skill. cline (ClinePass, which Hermes depends on) and the
grok TUI (GrokBot's pool): sparingly, never bulk; copilot: small GitHub-shaped
slices only.

## Multi-agent toolkit — know these exist (2026-10-05)

From any start dir, before orchestrating other agents, reach for these.
Editable copies are in git at `site-djbclark/skills/<name>/` (reached as
`site-private/skills/<name>`, a symlink; `1password` and `tell-chief-of-staff`
are private and real there), symlinked into
every TUI by the `skill-everywhere` skill — edit the git copy, never a TUI
copy. Ours: `bigteam` (fan work out across vendors by quota pool),
`model-routing` (vendor/model/effort per task), `herdr-orchestration`
(drive handoff chains through Herdr), `ralph-tui-orchestration` (Ralph TUI
and Beads controllers), `cow-workspaces` (copy-on-write isolation per
agent), `tell-chief-of-staff`. Tool-managed, not in git: `orchestration`,
`herdr`, `orca-per-workspace-env`. Slash commands `/orc`, `/orc-meta` live
in `site-private/claude/commands/`. Sub-agent definitions `adversary`,
`backend`, `ux`, `fable-deep` in `site-private/claude/agents/` (the `ocx-*`
files there are generated, untracked). Detail:
[[reference_agent_rules_multi_agent_toolkit]].

## Agents run in yolo (auto-approve) mode by default (standing rule, 2026-10-03)

**Every agent, however launched** (by djbclark, by another agent via `acp-run`/
Orca/Herdr/raw `-p`/`exec`/`run`, or as a sub-agent), runs in its yolo-or-
equivalent mode unless there is a specific, stated reason to gate it (a review-only
slice: `codex exec -s read-only`, `acp-run --perm deny`; or bigteam's per-file
ownership check: `--perm scoped:`). Use the agent's own bypass (`model-routing`
skill; `skills/herdr-orchestration/references/yolo-mode-by-tool.md`; `acp-run`
applies it itself). Yolo does not skip hooks, file-ownership contracts,
no-git-writes in a shared checkout, reserve pools, or "ask before hard-to-reverse
or outward-facing actions". Agents with no auto-approve (opencode, cursor, cline,
hermes over ACP) follow their own settings — check once so an unattended run
doesn't hang on an approval. Note: `feedback_yolo_default_for_all_agents.md`.
Detail: [[reference_agent_rules_code_discovery_and_cli_table]].

## LLM gateway, backups

`litellm`/`xai-oauth-bridge` run under launchd; **change site-djbclark's
Ansible role (`just litellm-apply-secrets`), never the live plist**; a
cold-start hang means `PYDANTIC_DISABLE_PLUGINS=1`. **Carbon Copy Cloner is
the backup and it covers `~`** — don't flag untracked files, Arq (retired)
or Time Machine (never used). Detail (Gemini/xAI fallback ids):
[[reference_agent_rules_ops_housekeeping]].

## Session logs and agent teams

At the start of a session in any git repo, read its Tier 1 pointer with the
`session-handoff` skill (under `~/.local/state/handoffs/`), compare `head_sha` to
`HEAD`, and state a resume plan before acting. Only the workspace-owning session
writes it; a missing pointer is a fresh start.

Agent teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`): teammates are
`~/ops/site-private/claude/agents/{ux,backend,adversary}.md`. **A teammate must
request an `adversary` security review and receive its verdict before opening a
pull request**; put the verdict (or an explicit "no findings") in the PR body.

## Detail notes (all in `~/ops/site-private/memory/`)

1. `reference_agent_rules_ops_housekeeping.md` — memory-writing, codex config
   drift, token-waste/trust/agent-report rationale, clipboard, book KB, LLM
   gateway, backups, session logs, agent teams.
2. `reference_agent_rules_aiuse_quota_and_agy.md` — quota-reading rules in full,
   agy burst limit.
3. `reference_agent_rules_basic_memory_pools.md` — which CLIs reach Basic Memory,
   pools, semantic-search caveat.
4. `reference_agent_rules_code_discovery_and_cli_table.md` — graft/token-savior
   traps, agent-CLI table, delegation order, yolo detail.
5. `reference_agent_rules_multi_agent_toolkit.md` — multi-agent skills
   inventory, slash commands, sub-agent files, skill-everywhere linking.
