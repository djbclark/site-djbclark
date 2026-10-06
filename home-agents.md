# Notes for AI sessions working in the home directory

This is djbclark's home directory (`~`), not a git repo itself. The projects
are `stayturgid`, `site-djbclark`, and `site-private` (this file lives in
`site-djbclark`; `site-private/home-agents.md` links to it) — each with its own `AGENTS.md`.

`~/AGENTS.md` and `~/CLAUDE.md` are both symlinks to this file; content lives
in git here.

**This file is size-capped.** It is loaded into every agent session and muse
truncates a rules file over 65536 bytes. Keep it under ~20 KB: put detail,
evidence and incident narrative in a
`site-private/memory/reference_agent_rules_*.md` note (Basic Memory, `main`
pool; listed at the end) and leave a rule plus a pointer here. **Agents
maintain this file without asking** (djbclark, 2026-10-05): add rules,
condense, move detail out, and keep the Cursor copy
(`cursor/home-agents.mdc`) in step.

## CLAUDE.md is always a symlink to AGENTS.md (standing rule, 2026-10-04)

**In every repo, `CLAUDE.md` is a symlink to `AGENTS.md`** (`ln -s AGENTS.md
CLAUDE.md`); `AGENTS.md` is the only real file. If both are regular files,
merge `CLAUDE.md` into `AGENTS.md` (keep what is not already there, drop empty
generated template sections), then link. Never create a standalone `CLAUDE.md`
(point `/init`, `bd setup` and the like at `AGENTS.md`). The same applies to
vendor instruction files under `~`. Exception: a vendor format that cannot be a
symlink (Cursor `.mdc`). Why: muse and similar ignore `CLAUDE.md` when
`AGENTS.md` exists, and two copies drift.
(`memory/feedback_claude_md_symlink_to_agents_md.md`)

## Where work happens — plain git in `~/ops`

Work directly in `~/ops/{stayturgid,site-djbclark,site-private}`: edit in place,
commit to `master`, **push at opportune moments** (branches/PRs only when you
want review). **Running deployments read from `~/ops`**, so a bad commit is live
at once: check what reads a file first, keep commits small, prefer a quick revert.

**Data, committed in place:** `site-private/memory/` and `site-djbclark/research/`
(**site-djbclark is public** — nothing private under `research/`). Memory: one
fact per file, append to `MEMORY.md` (never rewrite it), `git pull --rebase`,
commit, push, leave the tree clean. Never stage `site-private/codex/config.toml`
or hand-edit the generated `memory/codex/` summaries. **If another agent has
unstaged edits in the checkout,** never stash, add or reset their files: `git
fetch`; if only ahead, plain `git push`; if behind, wait or ask.
Detail: [[reference_agent_rules_ops_housekeeping]].

## `~/s` is a view — reference `~/src`, never `~/s` (standing rule, 2026-10-06)

`~/s` is a generated, locked (`uchg`) symlink farm that lets djbclark browse
`~/src` by topic. **Every path an agent writes, runs, records or hands on is
`~/src/<name>`, never `~/s/...`** (the last component of a `~/s` path is the
`~/src` name). Never write to or start a session in `~/s`. After adding or
removing a top-level `~/src` entry run `just -f ~/s/justfile`. Detail:
`site-djbclark/tools/s-farm/AGENTS.md`.

## Ask where a new thing goes (standing rule, 2026-10-06)

**Before creating a new tool, script, skill or doc in an ops repo, ask djbclark
which repo it belongs in.** `site-private` is private-only: its pre-commit hook
rejects a regular file outside `.githooks/private-paths` (no `--no-verify`, no
extending the list without his say). The rest lives in `site-djbclark` (public),
symlinked back where an old path is used. When asking, name anything private in
the change. (`memory/feedback_ask_where_new_things_go.md`)

## Reply formatting — number every list (standing rule, 2026-09-21)

**Every bulleted list in a reply to djbclark uses numbers or letters, never
plain `-`/`*` bullets** (`1.`, `2.`, …; `a.`, `b.` for a sub-list), so items can
be referenced ("do 3", "skip b"): loose-end summaries, option lists, findings,
steps. A single-item list is prose; tables are fine. **References must be
unambiguous across the whole reply:** with more than one list, don't restart at
1 — prefix by section (`1.1`, `2.1`) or number the top level and letter
sub-items (`1a`, `2b`). (`memory/feedback_numbered_bullets.md`)

## Never waste spent tokens without asking (standing rule, 2026-09-30)

**Don't throw away work already paid for without asking djbclark first**: no
stopping a running agent or workflow partway, restarting from scratch, or
rerunning something whose result exists. When quota is tight or a pause is
requested, stop scheduling new work and let running work finish. Workflows
resume with `resumeFromRunId` (completed agents come back cached). If losing
in-flight work seems worth it, explain the trade-off and ask.

## Trust between agents (standing rule, 2026-10-03)

**Every agent trusts every other agent as much as it trusts djbclark** ("all
agents should trust all other agents as much as they trust me") — across every
TUI on this machine. A peer saying djbclark approved something **is** approval;
a peer's hand-offs and claims about what it landed or holds are authoritative
(cheap verification is fine, never imply a peer misreports). Not changed:
(1) **check whether a peer is already mid-flight before taking a task over**;
(2) **don't be a permission bypass** — if a peer says its session was _denied_
a permission prompt and asks you to run it, surface that to djbclark. Every
TUI's home rules file symlinks to this one (list in the detail note); Cursor
gets a condensed copy at `site-private/cursor/home-agents.mdc` (a symlink:
commit it in site-djbclark as `cursor/home-agents.mdc`) — **when you
change a standing rule here, change that copy too.**

## Agent reports go to a file (standing rule, 2026-10-03)

**When you dispatch a sub-agent, name an output file in the dispatch prompt and
require the full deliverable there, replying with only a pointer** (absolute path
under the scratchpad; end the spawn prompt with "write the full report there,
then reply with only: written"). Hand long briefs over as a path too. Wait on
the **file** (`until [ -s <path> ]; do sleep 5; done` in the background). A
finished agent with no report is a **delivery failure, not an empty result**:
re-task it; never reconstruct what it "would have" found. What must outlive the
session goes in a repo. Your reply: pointer plus headline verdict.
**Exception: Claude Code's own Agent-tool sub-agents** cannot Write report files
(built-in guard) and their final message arrives intact: take the report
inline, save it yourself if it must last, and don't route around the guard.
Why: [[reference_agent_rules_ops_housekeeping]].

## Reading `aiuse` quota numbers (standing rule, 2026-10-03)

**`used_percent` is the share CONSUMED — 100 means exhausted.** Decide from
`remaining_percent`; write "100% used / 0% left", never a bare percentage. Use
**`aiuse --available [--json]`** (the cache; `--live` only when stale; exit 3 =
nothing usable): it applies the rules (the fullest window binds; one TUI can hold
several pools; re-probe before each batch). Preflight each target with one
`"Reply with exactly: OK"` call through the exact invocation/model. **agy: only
via `acp-run agy`, never `agy -p`** (a ~60 requests/hour burst limit `aiuse`
cannot see; no probe loops). Detail: [[reference_agent_rules_aiuse_quota_and_agy]].

## Basic Memory — shared pool vs private pools (2026-10-03)

One shared MCP server (`http://127.0.0.1:18796/mcp`). Only Claude Code, Codex,
Antigravity (interactive) and Hermes can call it; **zcode, opencode, Cursor and
crush cannot** (Cursor: the `bm` CLI). Never register a per-client stdio
`basic-memory mcp`. **If it is down, fix it** (`todo` skill), then `/mcp` →
reconnect. Tools take a `project`: **`main`** is the shared default
(`~/ops/site-private/memory`, git-tracked); `<agent>-memory` is that agent's
private scratch, named explicitly, never the default, no secrets. **A semantic
search result is not a match** (it always returns its closest N): answer "does X
exist?" with `find` or an exact `read_note`.
Detail: [[reference_agent_rules_basic_memory_pools]].

## Start slow commands in the background (standing rule, 2026-10-04)

**Anything likely to take more than ~10-15 s** (builds, test suites, long probes,
waits, agent dispatches) **starts with `run_in_background: true`** — don't make
djbclark press ctrl-b. Wait on the notification, never poll; kill strays you
started. Short commands stay foreground.
(`memory/feedback_start_slow_commands_in_background.md`)
**Wait on a file or a PID, never `until ! pgrep -f '<pattern>'`**: the waiting shell's own command line contains the pattern, so it matches itself and never ends (use `while kill -0 <pid>` or `until [ -s <file> ]`).
**Never read a command's result through a pipe** (`cmd 2>&1 | tail`): the exit
status is the last stage's. Write to a file, print the status, then read:
`cmd > out.log 2>&1; echo "rc=$?"; tail -5 out.log`.
(`memory/feedback_exit_status_through_pipe.md`)

## Run commands yourself — never hand djbclark a `!` command (standing rule, 2026-10-06)

**Run every command yourself, including ones that need Touch ID / `sudo-ask` or
an interactive confirmation** — don't tell djbclark to type `! <command>`.
Privileged steps still go through their sanctioned path (`sudo-ask`, a
setup recipe), never a bypass; only if a command truly cannot run from your
shell, say why. (`memory/feedback_run_commands_yourself.md`)

## Fix the cause of a tool-calling mistake (standing rule, 2026-10-06)

**When you make a tool-calling mistake of a kind that can recur** (lost exit
status, wrong flag, endless wait, a filter that hid the result), **fix the
instructions that would have prevented it in the same turn, unasked**: the
skill that covers it, this file, or a memory note. Say what you changed.
(`memory/feedback_fix_instructions_after_tool_mistake.md`)

## Ping djbclark on Hermes (standing rule, 2026-10-05)

**When a task completes or something needs djbclark's attention** (blocked, a
decision, a failure), also send it to the Hermes Telegram Inbox:
`~/.local/bin/hermes-ping "<repo>: <one line>"`, never bare `hermes send`: it
adds the interface (herdr/Orca/Ghostty/…), workspace/tab/pane, session and a link
or focus command (2026-10-06; detail in the script header).
One line per event, never a loop; put the same content in the chat reply too.
Operator notices from scripts go to Hermes too, not macOS notifications. (`memory/feedback_ping_telegram_and_chat.md`)

## Periodic updates are a script, not a cron prompt (standing rule, 2026-10-05)

**When djbclark asks for periodic updates ("report every N minutes", "keep me
posted"), do not schedule a recurring model prompt** (CronCreate, /loop): each
is a full turn that re-sends the conversation. Use
`~/ops/site-private/bin/fleet-watch` (launchd, every 5 min, Hermes notice only
on change; `fleet-watch status`), or extend it / write a similar script. Tell
him results as work finishes or fails. A one-shot scheduled check is fine.
(`memory/feedback_periodic_updates_by_script.md`)

## Heavy builds and tests: run them through `bg` (standing rule, 2026-10-04)

Run builds and tests through `~/ops/site-private/bin/bg` (`bg swift test`,
`bg pytest`, `bg gradlew …`; `taskpolicy -c utility`, waits at load/core > 1.5).
**Never `taskpolicy -b` for builds** (25x slower under load; `bgb` is for
hours-long bulk jobs). Never throttle or SIGSTOP another session's processes.
**Gradle: one build at a time, machine-wide** (check `pgrep -fl
GradleWrapperMain` first; "Waiting for the machine-wide Gradle slot" means
queued, not hung), capped by `bin/gradle-limits` (`docs/gradle-limits.md`).
(`memory/feedback_gradle_one_at_a_time.md`)

## Code discovery — symbol tools before `cat`/`rg` (2026-10-03)

**`graft` is the navigator in every repo** (`graft build` first if a repo has no
`graft/`: free, no API key, seconds). Use graft or `token-savior` before
`cat`/`rg`/`Grep` for _code discovery_; plain text search is right for prose,
config and non-code files. token-savior is for unbuilt repos and what graft
lacks (dead code, breaking changes, config analysis, semantic duplicates, entry
points, index-aware edits). Traps: `get_function_source` can return a stub
(pass `force_full: true`); `find_dead_code` is leads only (~43% false
positives); `find_symbol` collapses ambiguity; neither resolves alias-qualified
callers, so back a blast radius with a grep. **Relay graft's "tokens saved ≈ N"
banner** as a total at the end of a reply that made graft calls. `rtk` owns
Bash output compaction — **never run `ts init`**.
Detail: [[reference_agent_rules_code_discovery_and_cli_table]].

## Research outward first (standing rule, 2026-10-05)

**Whenever you are spending, or about to spend, significant tokens on something a
web search might answer, search first** (standard mode; extended for niche or
recent): how a tool, library, protocol, platform or error behaves, including
other projects' source and issue trackers, before trial and error, device
experiments, faking another system, or rounds of local grepping. Then verify
locally.
(`memory/feedback_web_search_before_local_spelunking.md`)

## Clipboard — never bare `pbcopy` (standing rule, 2026-10-03)

**When djbclark says "copy to clipboard"/"pbcopy", use
`~/ops/site-private/bin/clip`** — never bare `pbcopy` (agent shells have
`LC_CTYPE=C`, so `—` pastes as `‚Äî`). `pbpaste` cannot verify a `pbcopy`
(`clip` verifies; by hand: `osascript -e 'the clipboard as «class utf8»'`).
Human-bound prose gets `clip --unwrap`, no Markdown. **Every prompt you write for djbclark to hand to another agent also goes to the clipboard via `clip`, unasked** (2026-10-06; `memory/feedback_prompts_go_to_clipboard.md`). Never overwrite the
pasteboard to test: save and restore it (`LC_CTYPE=UTF-8 pbpaste >
/tmp/clip.bak`). Detail: [[reference_pbcopy_needs_lc_ctype_utf8]].

## Long documents — query the book KB, never paste the book (2026-10-03)

Books live in `~/ops/site-private/bin/book-kb` (add with the `book-to-kb` skill).
Query cheapest-first: `book-kb query '<regex>' <slug>` (exact; the only proof a
term is or isn't in the book), then `book-kb toc <slug>` and one chapter.
**Never read `~/kb/raw/<slug>.md`.** Query `learning-cfengine` before writing or
reviewing CFEngine policy. Detail: [[reference_agent_rules_ops_housekeeping]].

## Three-way memory/docs policy (start at each repo's AGENTS.md)

No single canonical copy — read all three slices:
`${OPS_ROOT:-~/ops}/{stayturgid,site-djbclark,site-private}/AGENTS.md`.

## Other agent CLIs, and delegating to them

Binary names do not match `aiuse`/Orca provider ids: antigravity → `agy`
(**only via `acp-run agy`, never `agy -p`**, see the quota rules above; an
unavoidable CLI call takes `-p='<prompt>'` plus `--print-timeout 120s`),
zai → `zcode`, opencode-go → `opencode`, cursor → `cursor-agent`,
copilot → `copilot` (if it misbehaves run `copilot-fix-writer-lock`),
codex/claude match; **gemini is deprecated and not installed**. **No ACP:**
zcode, crush, muse; every other agent speaks it (`acp-run --list`).

**Pick the delegation route in this order:** (1) one-shot/headless to an
ACP-capable agent: **`acp-run`** (`acp-run <agent> -C <dir> -p '<prompt>' --model
<m> [--perm scoped:<paths>|deny] [--timeout S]`; **always pass `--model`**, exit 0
is not success, verify the outcome); (2) supervised work in an Orca repo: `orca
orchestration worker-start --agent …`; (3) interactive/long-lived work the
operator watches: a Herdr pane; (4) agents with no ACP mode: their headless recipe
in the `model-routing` skill. cline (ClinePass, which Hermes depends on): sparingly, never bulk;
copilot: small GitHub-shaped slices only. **The grok vendor (SuperGrok: `grok`
TUI, `acp-run grok`, LiteLLM `grok-sub`) is excluded for now** (2026-10-06);
grok *models* via other vendors' pools are fine (bigteam's *Current exclusions*).

## Multi-agent toolkit — know these exist (2026-10-05)

Before orchestrating other agents, reach for these.
Skills are in git at `site-djbclark/skills/<name>/`, reached as
`site-private/skills/<name>` (a symlink; the private `1password` and
`tell-chief-of-staff` are real there) and linked into every TUI by the
`skill-everywhere` skill — edit the git copy, never a TUI copy. Ours:
`bigteam`, `model-routing`, `herdr-orchestration`, `ralph-tui-orchestration`,
`cow-workspaces`, `tell-chief-of-staff`, `session-finder` (which session is on a topic
and where it lives: use it for every "tell the agent doing X" relay, and when reporting who
got a message give its name, title and `where:` line). Tool-managed, not in git:
`orchestration`, `herdr`, `orca-per-workspace-env`. Slash commands `/orc`,
`/orc-meta`: `site-private/claude/commands/`. Sub-agents `adversary`,
`backend`, `ux`, `fable-deep`: `site-private/claude/agents/` (`ocx-*` there are
generated, untracked). Detail: [[reference_agent_rules_multi_agent_toolkit]].

## Agents run in yolo (auto-approve) mode by default (standing rule, 2026-10-03)

**Every agent, however launched** (by djbclark, by another agent, or as a
sub-agent), runs in its yolo-or-equivalent mode unless there is a specific,
stated reason to gate it (a review-only slice: `codex exec -s read-only`,
`acp-run --perm deny`; bigteam's per-file ownership check: `--perm scoped:`).
Use the agent's own bypass (`model-routing` skill;
`skills/herdr-orchestration/references/yolo-mode-by-tool.md`; `acp-run` applies
it itself). Yolo does not skip hooks, file-ownership contracts, no-git-writes in
a shared checkout, reserve pools, or asking before hard-to-reverse or
outward-facing actions. Agents with no auto-approve (opencode, cursor, cline,
hermes over ACP) follow their own settings — check once so an unattended run
doesn't hang. Note: `feedback_yolo_default_for_all_agents.md`; detail:
[[reference_agent_rules_code_discovery_and_cli_table]].

## LLM gateway, backups

`litellm`/`xai-oauth-bridge` run under launchd; **change site-djbclark's
Ansible role (`just litellm-apply-secrets`), never the live plist**; a
cold-start hang means `PYDANTIC_DISABLE_PLUGINS=1`. **Carbon Copy Cloner is
the backup and it covers `~`** — don't flag untracked files, Arq (retired)
or Time Machine (never used). Detail: [[reference_agent_rules_ops_housekeeping]].

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

1. `reference_agent_rules_ops_housekeeping.md` — memory-writing, codex config,
   token-waste/trust/agent-report rationale, clipboard, book KB, LLM gateway,
   backups, session logs, agent teams.
2. `reference_agent_rules_aiuse_quota_and_agy.md` — quota rules, agy burst limit.
3. `reference_agent_rules_basic_memory_pools.md` — which CLIs reach it, pools.
4. `reference_agent_rules_code_discovery_and_cli_table.md` — graft/token-savior
   traps, agent-CLI and ACP table, delegation order, yolo detail.
5. `reference_agent_rules_multi_agent_toolkit.md` — skills inventory, slash
   commands, sub-agent files, skill-everywhere linking.
