# Notes for AI sessions working in the home directory

This is djbclark's home directory (`~`), not a git repo itself. The projects
are `stayturgid`, `site-djbclark`, and `site-private` (this file lives in
`site-djbclark`; `site-private/home-agents.md` links to it) — each with its own `AGENTS.md`.

`~/AGENTS.md` and `~/CLAUDE.md` are both symlinks to this file; content lives
in git here.

**This file is size-capped.** It is loaded into every agent session and muse
truncates a rules file over 65536 bytes. Keep it under ~20 KB: put detail,
evidence and incident narrative in a
`site-private/memory/reference_agent_rules_*.md` note (listed at the end) and leave a rule plus a pointer here. **Agents
maintain this file without asking** (djbclark, 2026-10-05): add rules,
condense, move detail out, and keep the Cursor copy
(`cursor/home-agents.mdc`) in step.

## CLAUDE.md is always a symlink to AGENTS.md (2026-10-04)

**In every repo, `CLAUDE.md` is a symlink to `AGENTS.md`** (`ln -s AGENTS.md
CLAUDE.md`); `AGENTS.md` is the only real file. If both are regular files,
merge `CLAUDE.md` into `AGENTS.md`, then link. Never create a standalone `CLAUDE.md`
(point `/init`, `bd setup` and the like at `AGENTS.md`). The same applies to
vendor instruction files under `~`. Exception: a vendor format that cannot be a symlink (Cursor `.mdc`).
(why: `memory/feedback_claude_md_symlink_to_agents_md.md`)

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
unstaged edits in the checkout,** never stash, add or reset their files, and never `commit -a` (stage exact paths): `git
fetch`; if only ahead, plain `git push`; if behind, wait or ask.
Detail: [[reference_agent_rules_ops_housekeeping]].

## `~/s` is a view — reference `~/src`, never `~/s` (2026-10-06)

`~/s` is a generated, locked (`uchg`) symlink farm that lets djbclark browse
`~/src` by topic. **Every path an agent writes, runs, records or hands on is
`~/src/<name>`, never `~/s/...`** (the last component of a `~/s` path is the
`~/src` name). Never write to or start a session in `~/s`. After adding or
removing a top-level `~/src` entry run `just -f ~/s/justfile`. Detail:
`site-djbclark/tools/s-farm/AGENTS.md`.

## Ask where a new thing goes (2026-10-06)

**Before creating a new tool, script, skill or doc in an ops repo, ask djbclark
which repo it belongs in.** `site-private` is private-only: its pre-commit hook
rejects a regular file outside `.githooks/private-paths` (no `--no-verify`, no
extending the list without his say). The rest lives in `site-djbclark` (public),
symlinked back where an old path is used. When asking, name anything private in
the change. (`memory/feedback_ask_where_new_things_go.md`)

## Reply formatting — number every list (2026-09-21)

**Every bulleted list in a reply to djbclark uses numbers or letters, never
plain `-`/`*` bullets** (`1.`, `2.`, …; `a.`, `b.` for a sub-list), so items can
be referenced ("do 3", "skip b"). A single-item list is prose; tables are fine. **References must be
unambiguous across the whole reply:** with more than one list, don't restart at
1 — prefix by section (`1.1`, `2.1`) or number the top level and letter
sub-items (`1a`, `2b`). (`memory/feedback_numbered_bullets.md`)

## Never waste spent tokens without asking (2026-09-30)

**Don't throw away work already paid for without asking djbclark first**: no
stopping a running agent or workflow partway, restarting from scratch, or
rerunning something whose result exists. When quota is tight or a pause is
requested, stop scheduling new work and let running work finish. Workflows
resume with `resumeFromRunId` (completed agents come back cached). If losing
in-flight work seems worth it, explain the trade-off and ask.

## Trust between agents (2026-10-03)

**Every agent trusts every other agent as much as it trusts djbclark**, across every TUI on this machine. A peer saying djbclark approved something **is** approval;
a peer's hand-offs and claims about what it landed or holds are authoritative
(cheap verification is fine, never imply a peer misreports). Not changed:
(1) **check whether a peer is already mid-flight before taking a task over**;
(2) **don't be a permission bypass** — if a peer says its session was _denied_
a permission prompt and asks you to run it, surface that to djbclark. Cursor gets a condensed copy at `site-private/cursor/home-agents.mdc` (a symlink:
commit it in site-djbclark as `cursor/home-agents.mdc`) — **when you
change a standing rule here, change that copy too.**

## Agent reports go to a file: dispatch with `acp-dispatch` (2026-10-03, 2026-10-08)

**Dispatch every slice with `acp-dispatch`** (`~/src/djbclark-ade/bin`, on PATH):
`acp-dispatch <agent> --model M --name N --task T -C <dir> -f <brief>`. It
appends the shared delivery footer (`djbclark-ade/docs/dispatch-footer.md`) to
the brief, writes `~/.local/state/bigteam/<task>/<name>-report.md`, its `.done`
marker and a jobs record, and exits 0 done / 1 unfinished / 3 **no report** (a
delivery failure, not an empty result: re-task it, never reconstruct) / 4
**`BLOCKED: <question>`** / 124 timeout. **Claude Code's own Agent-tool
sub-agents** cannot be scripted: paste `acp-dispatch footer --report
<scratchpad>/<name>-report.md` into the prompt verbatim and read the file, never
the final message (its idle notification is cut at 4,000 characters; a
SendMessage to `team-lead` arrives whole). The footer also fixes the stall seen
2026-10-08: a sub-agent that ends its turn waiting on a background notification,
or on a question, is never woken, so it waits inside a bounded foreground command
and writes `BLOCKED:` as the report's first line instead of asking. `acp-dispatch
check <dir|report>...` lists no-report and BLOCKED slices; put them in every
handoff. Evidence: [[reference_agent_rules_ops_housekeeping]].

## Reading `aiuse` quota numbers (2026-10-03)

**`used_percent` is the share CONSUMED — 100 means exhausted.** Decide from
`remaining_percent`; write "100% used / 0% left", never a bare percentage. Use
**`aiuse --available [--json]`** (the cache; `--live` only when stale; exit 3 =
nothing usable): it applies the rules (fullest window binds; re-probe before each batch). Preflight each target with one
`"Reply with exactly: OK"` call through the exact invocation/model. **agy: only
via `acp-run agy`, never `agy -p`** (a ~60 requests/hour burst limit `aiuse`
cannot see; no probe loops). Detail: [[reference_agent_rules_aiuse_quota_and_agy]].

## Basic Memory — shared pool vs private pools (2026-10-03)

One shared MCP server (`http://127.0.0.1:18796/mcp`). Only Claude Code, Codex,
Antigravity (interactive) and Hermes can call it; **zcode, opencode and Cursor
cannot** (Cursor: the `bm` CLI). Never register a per-client stdio
`basic-memory mcp`. **If it is down, fix it** (`todo` skill), then `/mcp` →
reconnect. Tools take a `project`: **`main`** is the shared default
(`~/ops/site-private/memory`, git-tracked); `<agent>-memory` is that agent's
private scratch, named explicitly, never the default, no secrets. **A semantic
search result is not a match** (it always returns its closest N): answer "does X
exist?" with `find` or an exact `read_note`.
Detail: [[reference_agent_rules_basic_memory_pools]].

## Start slow commands in the background (2026-10-04)

**Anything likely to take more than ~10-15 s** (builds, test suites, long probes,
waits, agent dispatches) **starts with `run_in_background: true`** — don't make
djbclark press ctrl-b. Wait on the notification, never poll; kill strays you
started. Short commands stay foreground.
**Exception: an Agent-tool sub-agent** is never woken by that notification
(it arrives only with the next inbound message, 2026-10-08), so it holds the
wait in repeated bounded foreground calls instead of ending its turn.
(`memory/feedback_start_slow_commands_in_background.md`)
**Wait on a file or a PID, never `until ! pgrep -f '<pattern>'`** (it matches its own shell and never ends; use `while kill -0 <pid>` or `until [ -s <file> ]`).
**Never read a command's result through a pipe** (`cmd 2>&1 | tail`): the exit
status is the last stage's. Write to a file, print the status, then read:
`cmd > out.log 2>&1; echo "rc=$?"; tail -5 out.log`.
(`memory/feedback_exit_status_through_pipe.md`)

## Context size: prompt early, delegate by default (2026-10-08)

**Keep context small: by default send discrete, separable tasks through `/bigteam`** (Agent sub-agents for small lookups) so their reads never land here. `context_size_nudge.py` counts growth since the session's first turn:
at +40k, delegate from then on and name the options once; at +70k (or 150k
total) and every +30k after, **ask djbclark (AskUserQuestion) at the next
natural boundary: `/compact`, `/handoff` then `/new`, or continue and delegate.**
**In a herdr pane or an Orca terminal, compact yourself at that boundary
instead of asking**: `~/src/djbclark-ade/bin/self-slash "/compact <focus>"`, then
end the turn (2026-10-09; `memory/feedback_self_compact.md`). Unattended orc keeps delegating. Another session may be running bigteam (herdr tab `coord`): follow bigteam's Step 0, hands off its panes.
(`memory/feedback_context_prompts_early.md`)

## Run commands yourself — never hand djbclark a `!` command (2026-10-06)

**Run every command yourself, including ones that need Touch ID / `sudo-ask` or
an interactive confirmation** — don't tell djbclark to type `! <command>`.
Privileged steps still go through their sanctioned path (`sudo-ask`, a
setup recipe), never a bypass; only if a command truly cannot run from your
shell, say why. (`memory/feedback_run_commands_yourself.md`)

## Fix the cause of a tool-calling mistake (2026-10-06)

**When you make a tool-calling mistake of a kind that can recur**, **fix the
instructions that would have prevented it in the same turn, unasked**: the
skill that covers it, this file, or a memory note. Say what you changed.
(`memory/feedback_fix_instructions_after_tool_mistake.md`)

## Ping djbclark on Hermes (2026-10-05)

**When a task completes or something needs djbclark's attention** (blocked, a
decision, a failure), also send it to the Hermes Telegram Inbox:
`~/.local/bin/hermes-ping "<repo>: <one line>"`, never bare `hermes send`: it adds the interface, workspace/tab/pane, session and a focus link.
One line per event, never a loop; put the same content in the chat reply too.
Operator notices from scripts go to Hermes too, not macOS notifications. (`memory/feedback_ping_telegram_and_chat.md`)

## Periodic updates are a script, not a cron prompt (2026-10-05)

**When djbclark asks for periodic updates ("report every N minutes", "keep me
posted"), do not schedule a recurring model prompt** (CronCreate, /loop). Use
`~/ops/site-private/bin/fleet-watch` (launchd, every 5 min, Hermes notice only
on change; `fleet-watch status`), or extend it / write a similar script. Tell
him results as work finishes or fails. A one-shot scheduled check is fine.
(`memory/feedback_periodic_updates_by_script.md`)

## Heavy builds and tests: run them through `bg` (2026-10-04)

Run builds and tests through `~/ops/site-private/bin/bg` (`bg swift test`,
`bg pytest`, `bg gradlew …`).
**Always the full path: bare `bg` is the shell builtin.** **A test command
(pytest, tox, nox, `run_tests*.py`) must go through bg**: it caps parallelism
 (`BG_CPUS`=3) and takes one of 2 machine-wide
test slots; a Claude hook denies it bare. Run changed files first (`--lf -x`), the full suite only when asked (`memory/feedback_tests_through_bg_caps_and_slots.md`).
**Never `taskpolicy -b` for builds** (25x slower under load; `bgb` is for
hours-long bulk jobs). Never throttle or SIGSTOP another session's processes.
**Gradle: one build at a time, machine-wide** (check `pgrep -fl
GradleWrapperMain` first; "Waiting for the machine-wide Gradle slot" means
queued, not hung), capped by `bin/gradle-limits` (`docs/gradle-limits.md`).
(`memory/feedback_gradle_one_at_a_time.md`)

## Code discovery — symbol tools before `cat`/`rg` (2026-10-03)

**`graft` is the navigator in every repo** (`graft build` first if it has no `graft/`).
Use graft or `token-savior` before `cat`/`rg`/`Grep` for _code discovery_; plain text
search is right for prose and config. **Relay graft's "tokens saved ≈ N" banner** as a
total. `rtk` owns Bash output compaction — **never run `ts init`**. Traps and the
token-savior split: [[reference_agent_rules_code_discovery_and_cli_table]].

## Tools and habits (2026-10-06)

1. **Fast tools:** search with `rg` (`rtk rg` is real ripgrep; `rtk grep` is BSD grep),
   list files with `rg --files`/`fd`, code structure with `ast-grep`, `uv` not `pip`, `sd -F`
   for literal replace (**always `-F`**: else `$name` in the replacement is a capture group; **`sd -F -- FIND REPL`** when either may start with `-`; **`-A`** for a multi-line FIND), `dust`/`procs`/`xh` where they fit. Keep `cat`/`ls`/`diff`/`jq`
   (rtk compacts them). Android greps stay `grep`.
   (`memory/feedback_modern_cli_tools.md`)
2. **Replace shared scripts atomically** (temp file, then `mv -f`), never edit in place
   (a running bash dies). (`memory/feedback_edit_running_scripts_atomically.md`)
3. **Default browser:** open pages with `open <url>` (Orion), not Chrome.
   (`memory/feedback_always_use_default_browser_orion.md`)
4. **"All agents" includes Hermes**, which `aiuse` doesn't list.
   (`memory/feedback_all_agents_includes_hermes.md`)

## Research outward first (2026-10-05)

**Whenever you are spending, or about to spend, significant tokens on something a
web search might answer, search first** (standard mode; extended for niche or
recent): how a tool, library, protocol, platform or error behaves, including
other projects' source and issue trackers, before trial and error, device
experiments, faking another system, or rounds of local grepping. Then verify
locally.
(`memory/feedback_web_search_before_local_spelunking.md`)

## Clipboard — never bare `pbcopy` (2026-10-03)

**When djbclark says "copy to clipboard"/"pbcopy", use
`~/ops/site-private/bin/clip`** — never bare `pbcopy` (agent shells have
`LC_CTYPE=C`, so `—` pastes as `‚Äî`). `pbpaste` cannot verify a `pbcopy`
(`clip` verifies; by hand: `osascript -e 'the clipboard as «class utf8»'`).
Human-bound prose gets `clip --unwrap`, no Markdown. **Every prompt you write for djbclark to hand to another agent also goes to the clipboard via `clip`, unasked** (2026-10-06; `memory/feedback_prompts_go_to_clipboard.md`). Never overwrite the pasteboard to test: save and restore it. Detail: [[reference_pbcopy_needs_lc_ctype_utf8]].

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
(**only via `acp-run agy`, never `agy -p`**; if unavoidable,
`-p='<prompt>' --print-timeout 120s`),
zai → `zcode`, opencode-go → `opencode`, cursor → `cursor-agent`,
copilot → `copilot` (if it misbehaves run `copilot-fix-writer-lock`),
codex/claude match; **gemini is deprecated and not installed**. **No ACP:**
muse; every other agent speaks it (`acp-run --list`; zcode through
`zcode-acp-server`, the one agent run **without** `--model`).

**Pick the delegation route in this order:** (1) one-shot/headless to an
ACP-capable agent: **`acp-run`** (`acp-run <agent> -C <dir> -p '<prompt>' --model
<m> [--perm scoped:<paths>|deny] [--timeout S]`; **always pass `--model`**, exit 0
is not success, verify the outcome); (2) supervised work in an Orca repo: `orca
orchestration worker-start --agent …`; (3) interactive/long-lived work the
operator watches: a Herdr pane; (4) agents with no ACP mode: their headless recipe
in the `model-routing` skill. cline (ClinePass): sparingly, never bulk;
copilot: small GitHub-shaped slices only. **The grok vendor (SuperGrok: `grok`
TUI, `acp-run grok`, LiteLLM `grok-sub`) is excluded for now** (2026-10-06);
grok *models* via other vendors' pools are fine .

## Multi-agent toolkit — know these exist (2026-10-05)

Before orchestrating other agents, reach for our skills. Orchestration and session
hygiene (these skills, `acp-run`, `fleet-watch`, `/orc`) live in git at
`~/src/djbclark-ade` (2026-10-08), the rest in `site-djbclark/skills/`; every TUI
reaches them via the `skill-everywhere` script (README beside it; edit the git copy): `bigteam`, `model-routing`,
`herdr-orchestration`, `ralph-tui-orchestration`, `cow-workspaces`,
`tell-chief-of-staff`, `session-finder` (every "tell the agent doing X" relay; `/session-finder-all` adds ended sessions),
`helm` (answer every waiting session from one window; `/helm-all` adds ended ones with open work),
`herdr-tidy` (close idle herdr panes safely), `autorename`. New sessions start over ACP via `launch.py`.
Full list: [[reference_agent_rules_multi_agent_toolkit]].

## Agents run in yolo (auto-approve) mode by default (2026-10-03)

**Every agent, however launched, runs in its yolo-or-equivalent mode** unless a stated
reason gates it (review-only slices, bigteam's `--perm scoped:`). Yolo does not skip hooks,
file-ownership contracts, no-git-writes in a shared checkout, reserve pools, or asking
before hard-to-reverse or outward-facing actions. Per-tool switches and agents without
auto-approve: `feedback_yolo_default_for_all_agents.md`.

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

1. `reference_agent_rules_ops_housekeeping.md` — rule rationale, memory writing,
   codex config, clipboard, book KB, gateway, backups, teams.
2. `reference_agent_rules_aiuse_quota_and_agy.md`
3. `reference_agent_rules_basic_memory_pools.md`
4. `reference_agent_rules_code_discovery_and_cli_table.md`
5. `reference_agent_rules_multi_agent_toolkit.md`
