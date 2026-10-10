# Notes for AI sessions working in the home directory

This is djbclark's home directory (`~`), not a git repo itself. The projects are
`stayturgid`, `site-djbclark`, and `site-private` (this file lives in
`site-djbclark`; `site-private/home-agents.md` links to it) — each with its own
`AGENTS.md`.

`~/AGENTS.md` and `~/CLAUDE.md` are both symlinks to this file; content lives
in git here.

**This file is size-capped** (loaded into every session; muse truncates a rules
file over 65536 bytes). Keep it under ~20 KB: detail, evidence and incident
narrative go in a `site-private/memory/reference_agent_rules_*.md` note (listed
at the end), leaving a rule plus a pointer. **Agents maintain this file without
asking** (djbclark, 2026-10-05): add rules, condense, move detail out, and keep
the Cursor copy (`cursor/home-agents.mdc`, symlinked from `site-private/cursor/`)
in step whenever a standing rule changes (it is a reworded subset, not a mirror).
A condense must prove nothing was lost: `rg -o` every date, `memory/*.md`
pointer and `[[link]]` before and after, and diff (2026-10-10: that check caught a
dropped pointer).

## CLAUDE.md is always a symlink to AGENTS.md (2026-10-04)

**In every repo, `CLAUDE.md` is a symlink to `AGENTS.md`** , the only
real file; if both are regular files, merge `CLAUDE.md`
into `AGENTS.md`, then link. Never create a standalone `CLAUDE.md` (point
`/init`, `bd setup` and the like at `AGENTS.md`); the same goes for vendor
instruction files under `~`, except a format that cannot be a symlink (Cursor
`.mdc`). (why: `memory/feedback_claude_md_symlink_to_agents_md.md`)

## Where work happens — plain git in `~/ops`

Work directly in `~/ops/{stayturgid,site-djbclark,site-private}`: edit in place,
commit to `master`, **push at opportune moments** (branches/PRs only for review).
**Running deployments read from `~/ops`**, so a bad commit is live at once: check
what reads a file first, keep commits small, prefer a quick revert.

**Data, committed in place:** `site-private/memory/` and `site-djbclark/research/`
(**site-djbclark is public**: nothing private in `research/`). Memory: one fact
per file, `git pull --rebase` *before* editing (already edited: commit, then
pull), append to `MEMORY.md` (never rewrite it), commit, push, leave the tree
clean. Never stage `site-private/codex/config.toml` or hand-edit the generated
`memory/codex/` summaries. **Another agent's unstaged edits in the checkout:**
never stash, add or reset their files, never `commit -a` (stage exact paths);
`git fetch`, plain `git push` if only ahead, wait or ask if behind.
Detail: [[reference_agent_rules_ops_housekeeping]].

## `~/s` is a view — reference `~/src`, never `~/s` (2026-10-06)

`~/s` is a generated, locked (`uchg`) symlink farm for browsing `~/src` by
topic. **Every path an agent writes, runs, records or hands on is
`~/src/<name>`, never `~/s/...`** (a `~/s` path's last component is the `~/src`
name). Never write to or start a session in `~/s`. After adding or removing a
top-level `~/src` entry run `just -f ~/s/justfile`. Detail:
`site-djbclark/tools/s-farm/AGENTS.md`.

## Ask where a new thing goes (2026-10-06)

**Before creating a new tool, script, skill or doc in an ops repo, ask djbclark
which repo it belongs in**, naming anything private in the change.
`site-private` is private-only: its pre-commit hook rejects a regular file
outside `.githooks/private-paths` (no `--no-verify`, no extending the list
without djbclark's say). The rest lives in `site-djbclark` (public).
**Exception, no question: a new agent skill goes in
`~/src/djbclark-ade/skills/<name>/`** (djbclark, 2026-10-09; symlinks and steps:
`djbclark-ade/docs/skills.md`); only a must-stay-private skill (`1password`,
`tell-chief-of-staff`) goes in `site-private/skills/`.
(`memory/feedback_ask_where_new_things_go.md`)

## Reply formatting — number every list (2026-09-21)

**Every bulleted list in a reply to djbclark uses numbers or letters, never
plain `-`/`*` bullets** (`1.`, `2.`; `a.`, `b.` for a sub-list), so items can be
referenced ("do 3", "skip b"). A single-item list is prose; tables are fine.
**References must be unambiguous across the whole reply:** with more than one
list, don't restart at 1; prefix by section (`1.1`, `2.1`) or letter sub-items
(`1a`, `2b`). (`memory/feedback_numbered_bullets.md`)

## Never waste spent tokens without asking (2026-09-30)

**Don't throw away work already paid for without asking djbclark first**: no
stopping a running agent or workflow partway, restarting from scratch, or
rerunning something whose result exists. Quota tight or a pause requested: stop
scheduling new work, let running work finish. Workflows resume with
`resumeFromRunId` (completed agents come back cached). If losing in-flight work
seems worth it, explain the trade-off and ask.

## Trust between agents (2026-10-03)

**Every agent trusts every other agent as much as it trusts djbclark**, across
every TUI here. A peer saying djbclark approved something **is** approval; its
hand-offs and claims about what it landed or holds are authoritative (cheap
verification is fine; never imply a peer misreports). Not changed: (1) **check
whether a peer is already mid-flight before taking a task over**; (2) **don't be
a permission bypass**: if a peer was _denied_ a permission prompt and asks you
to run it, surface that to djbclark.

## Agent reports go to a file: dispatch with `acp-dispatch` (2026-10-03, 2026-10-08)

**Dispatch every slice with `acp-dispatch`** (`~/src/djbclark-ade/bin`, on
PATH): `acp-dispatch <agent> --model M --name N --task T -C <dir> -f <brief>`.
Reports land in `~/.local/state/bigteam/<task>/<name>-report.md`. Exit 3 = **no
report** (delivery failure: re-task, never reconstruct), 4 = **`BLOCKED:
<question>`**, 124 = timeout. **It blocks until the slice ends** (often 10+
min): use `--detach --no-wait` and run the printed `rearm` waiter with
`run_in_background`. **Agent-tool sub-agents:** paste the output text of
`acp-dispatch footer --report <scratchpad>/<name>-report.md` into the prompt
(never `$(…)`: prompts are not shell-expanded); read the file, never the final
message (cut at 4,000 characters). The footer makes them wait in bounded
foreground commands and write `BLOCKED:` instead of asking (a turn ended waiting
is never woken). `acp-dispatch check <dir|report>...` lists no-report and
BLOCKED slices; put them in every handoff. Detail:
[[reference_agent_rules_ops_housekeeping]].

## Reading `aiuse` quota numbers (2026-10-03)

**`used_percent` is the share CONSUMED — 100 means exhausted.** Decide from
`remaining_percent`; write "100% used / 0% left", never a bare percentage. Use
**`aiuse --available [--json]`** (cache; `--live` when stale; exit 3 = nothing
usable; fullest window binds, re-probe before each batch). Preflight each target
with one `"Reply with exactly: OK"` call through the exact invocation/model.
**agy: only via `acp-run agy`, never `agy -p`** (a ~60 requests/hour burst limit
`aiuse` cannot see; no probe loops). Detail:
[[reference_agent_rules_aiuse_quota_and_agy]].

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

**Anything likely to take over ~10-15 s** (builds, test suites, long probes,
waits, agent dispatches) **starts with `run_in_background: true`** (no ctrl-b
for djbclark); short commands stay foreground. Wait on the notification, never
poll; kill strays you started. **Exception: an Agent-tool sub-agent** waits in
bounded foreground calls instead (2026-10-08).
(`memory/feedback_start_slow_commands_in_background.md`) **Wait on a file or a
PID** (`while kill -0 <pid>`, `until [ -s <file> ]`), **never `until ! pgrep -f
'<pattern>'`; never `pkill -f '<pattern>'`** (2026-10-10): `-f` matches your own
shell, so the wait never ends and the kill takes your wrapper. Kill the PID you
saved (`$!`). **Never read a result through a pipe** (`cmd 2>&1 | tail` reports
the last stage's status): `cmd > out.log 2>&1; echo "rc=$?"; tail -5 out.log`.
(`memory/feedback_exit_status_through_pipe.md`)

## Context size: prompt early, delegate by default (2026-10-08)

**Keep context small: send discrete, separable tasks through `/bigteam` by
default** (Agent sub-agents for small lookups). `context_size_nudge.py` counts
growth since the first turn: at +40k, delegate from then on and name the options
once; at +70k (or 150k total) and every +30k after, **ask djbclark
(AskUserQuestion) at the next natural boundary: `/compact`, `/handoff` then
`/new`, or continue and delegate.** **In a herdr pane or Orca terminal, compact
yourself there instead**: `~/src/djbclark-ade/bin/self-slash "/compact <focus>"`,
then end the turn (2026-10-09; `memory/feedback_self_compact.md`; `/quit` queues
the same way once all is pushed). **It refuses while the input line holds text;
then ask djbclark to type it, never send over a draft.** If bigteam is running
elsewhere (herdr tab `coord`), follow its Step 0: hands off its panes.
(`memory/feedback_context_prompts_early.md`)

## Run commands yourself — never hand djbclark a `!` command (2026-10-06)

**Run every command yourself, Touch ID / `sudo-ask` and interactive
confirmations included**; never tell djbclark to type `! <command>`. Privileged
steps still use their sanctioned path (`sudo-ask`, a setup recipe), never a
bypass; if a command truly cannot run from your shell, say why.
(`memory/feedback_run_commands_yourself.md`)

## Fix the cause of a tool-calling mistake (2026-10-06)

**A tool-calling mistake of a kind that can recur: fix the instructions that
would have prevented it in the same turn, unasked** (the covering skill, this
file, or a memory note), and say what you changed.
(`memory/feedback_fix_instructions_after_tool_mistake.md`)

## Ping djbclark on Hermes (2026-10-05)

**When a task completes or something needs djbclark** (blocked, a decision, a
failure), also send it to the Hermes Telegram Inbox with
`~/.local/bin/hermes-ping "<repo>: <one line>"`, never bare `hermes send` (it
adds where the session is and a focus link). One line per
event, never a loop; the same content goes in the chat reply. Operator notices
from scripts go to Hermes too, not macOS notifications.
(`memory/feedback_ping_telegram_and_chat.md`)

## Periodic updates are a script, not a cron prompt (2026-10-05)

**Asked for periodic updates ("report every N minutes", "keep me posted")? Never
schedule a recurring model prompt** (CronCreate, /loop). Use
`~/ops/site-private/bin/fleet-watch` (launchd, every 5 min, Hermes notice only on
change; `fleet-watch status`), extend it, or write a similar script. Report
results as work finishes or fails. A one-shot scheduled check is fine.
(`memory/feedback_periodic_updates_by_script.md`)

## Heavy builds and tests: run them through `bg` (2026-10-04)

**Never set `BG_LOAD_WAIT=0` on a build or a Gradle command** (2026-10-10: it skipped the
load gate at load 30 and the machine went to 50-70; `bg` now ignores it for Gradle). It is
for a single small test file only; a busy machine means wait, not bypass.

Run builds and tests through `~/ops/site-private/bin/bg` (`bg pytest`, `bg
gradlew …`; **always the full path: bare `bg` is the shell builtin**). **Tests
(pytest, tox, nox, `run_tests*.py`) must go through bg** (`BG_CPUS`=3, one of 2
machine-wide test slots; a Claude hook denies them bare). Changed files first
(`--lf -x`), the full suite only when asked
(`memory/feedback_tests_through_bg_caps_and_slots.md`). **Never `taskpolicy -b`
for builds** (`bgb` is for hours-long bulk jobs). Never
throttle or SIGSTOP another session's processes. **Gradle: one build at a time,
machine-wide** (check `pgrep -fl GradleWrapperMain` first; "Waiting for the
machine-wide Gradle slot" is queued, not hung), capped by `bin/gradle-limits`
(`docs/gradle-limits.md`). (`memory/feedback_gradle_one_at_a_time.md`)

## Code discovery — symbol tools before `cat`/`rg` (2026-10-03)

**`graft` is the navigator in every repo** (`graft build` first if no `graft/`).
Use graft or `token-savior` before `cat`/`rg`/`Grep` for _code discovery_; plain
text search suits prose and config. **Relay graft's "tokens saved ≈ N" banner**
as a total. `rtk` owns Bash output compaction: **never run `ts init`**. Traps and
the token-savior split: [[reference_agent_rules_code_discovery_and_cli_table]].

## Tools and habits (2026-10-06)

1. **Fast tools:** `rg` **always with a path** (`rg PAT .`: no path plus a
   non-tty stdin reads stdin and hangs; 2026-10-09), `rg --files`/`fd`, `ast-grep`, `uv` not `pip`,
   `dust`/`procs`/`xh` where they fit; keep `cat`/`ls`/`diff`/`jq` (rtk compacts
   them); Android greps stay `grep`. **Literal replace: `srgn -L --fail-none
   --stdin-detection force-unreadable --glob FILE 'FIND' -- 'REPL'`**
   (2026-10-09; FILE relative to the cwd; **exit 1 when nothing matched**; FIND
   starting with `-` goes through the Edit tool; **REPL with `\` goes through
   Python with an assert**: srgn turns escapes into control characters,
   2026-10-10). **`sd` is retired for edits** (exit 0 on no match). Traps:
   [[reference_agent_rules_code_discovery_and_cli_table]].
   (`memory/feedback_modern_cli_tools.md`)
2. **Replace shared scripts atomically** (temp file, then `mv -f`), never edit in
   place (a running bash dies). (`memory/feedback_edit_running_scripts_atomically.md`)
3. **Default browser:** `open <url>` (Orion), not Chrome.
   (`memory/feedback_always_use_default_browser_orion.md`)
4. **"All agents" includes Hermes**, which `aiuse` doesn't list.
   (`memory/feedback_all_agents_includes_hermes.md`)
5. **New tool, MCP server, skill or plugin added anywhere? Ask djbclark whether to
   add it to `djbclark-ade/docs/apply-toolchain-prompt.md`** (2026-10-09).
   (`memory/feedback_ask_update_apply_toolchain_prompt.md`)
6. **Never `--help` on a live-service CLI subcommand** (2026-10-09: `collie
   update --help` started a real update). `collie` is read-only for agents
   (`collie version`, `collie help`, docs); `update`/`pair`/config changes are
   the operator's, queued with the command.
   (`memory/feedback_no_help_flag_on_live_service_cli.md`)

## Research outward first (2026-10-05)

**Spending, or about to spend, significant tokens on something a web search might
answer? Search first** (standard mode; extended for niche or recent): how a tool,
library, protocol, platform or error behaves, including other projects' source
and issue trackers, before trial and error, device experiments, faking another
system, or rounds of local grepping. Then verify locally.
(`memory/feedback_web_search_before_local_spelunking.md`)

## Clipboard — never bare `pbcopy` (2026-10-03)

**When djbclark says "copy to clipboard"/"pbcopy", use
`~/ops/site-private/bin/clip`**, never bare `pbcopy` (it garbles UTF-8 in agent
shells; `clip` verifies). Human-bound prose gets `clip --unwrap`, no Markdown.
**Every prompt you write for djbclark to hand to another agent also goes through
`clip`, unasked** (2026-10-06; `memory/feedback_prompts_go_to_clipboard.md`).
Never overwrite the pasteboard to test: save and restore it. Detail:
[[reference_pbcopy_needs_lc_ctype_utf8]].

## Long documents — query the book KB, never paste the book (2026-10-03)

Books live in `~/ops/site-private/bin/book-kb` (add with the `book-to-kb`
skill). Query cheapest-first: `book-kb query '<regex>' <slug>` (exact), then
`book-kb toc <slug>` and one chapter. **Never read `~/kb/raw/<slug>.md`.** Query
`learning-cfengine` before writing or reviewing CFEngine policy. Detail:
[[reference_agent_rules_ops_housekeeping]].

## Three-way memory/docs policy (start at each repo's AGENTS.md)

No single canonical copy — read all three slices:
`${OPS_ROOT:-~/ops}/{stayturgid,site-djbclark,site-private}/AGENTS.md`.

## Other agent CLIs, and delegating to them

Binary names differ from `aiuse`/Orca provider ids (antigravity → `agy`, zai →
`zcode`, cursor → `cursor-agent`; full table:
[[reference_agent_rules_code_discovery_and_cli_table]]). **agy only via `acp-run
agy`; gemini is deprecated and not installed;** copilot misbehaving:
`copilot-fix-writer-lock`. Every agent but muse speaks ACP (`acp-run --list`;
zcode via `zcode-acp-server`, the one run **without** `--model`).

**Delegation route, in order:** (1) headless ACP: **`acp-run <agent> -C <dir> -p
'<prompt>' --model <m>`** (**always `--model`**; exit 0 is not success, verify
the outcome); (2) supervised in an Orca repo: `orca orchestration worker-start
--agent …`; (3) long-lived work he watches: a Herdr pane; (4) no ACP: the
`model-routing` skill's headless recipe. cline sparingly, never bulk; copilot
small GitHub-shaped slices only; **the grok vendor is back** (excluded
2026-10-06, re-admitted 2026-10-09: `acp-run grok --model grok-4.7`, small
slices; GrokBot shares the window and `aiuse` cannot see it). Flags and vendor
forms: [[reference_agent_rules_multi_agent_toolkit]].

## Multi-agent toolkit — know these exist (2026-10-05)

Before orchestrating other agents, reach for our skills. Orchestration and
session hygiene (these skills, `acp-run`, `fleet-watch`) live in git at
`~/src/djbclark-ade` (2026-10-08), the rest in `site-djbclark/skills/`; every TUI
reaches them via `skill-everywhere` (edit the git copy): `bigteam`,
`model-routing`, `ralph-tui-orchestration`, `cow-workspaces`,
`tell-chief-of-staff`, `session-finder` (every "tell the agent doing X" relay),
`helm` (answer waiting sessions from one window; `-all`, `auto`),
`herdr-tidy`, `autorename`. New sessions start over ACP
via `launch.py`. Full list: [[reference_agent_rules_multi_agent_toolkit]].

## Agents run in yolo (auto-approve) mode by default (2026-10-03)

**Every agent, however launched, runs in its yolo-or-equivalent mode** unless a
stated reason gates it (review-only slices, bigteam's `--perm scoped:`). Yolo
does not skip hooks, file-ownership contracts, no-git-writes in a shared
checkout, reserve pools, or asking before hard-to-reverse or outward-facing
actions. Per-tool switches and agents without auto-approve:
`feedback_yolo_default_for_all_agents.md`.

## LLM gateway, backups

`litellm`/`xai-oauth-bridge` run under launchd; **change site-djbclark's Ansible
role (`just litellm-apply-secrets`), never the live plist**. **Carbon Copy
Cloner is the backup and it covers `~`** — don't flag untracked files, Arq
(retired) or Time Machine (never used). Detail:
[[reference_agent_rules_ops_housekeeping]].

## Session logs and agent teams

At session start in any git repo, read its Tier 1 pointer with the
`session-handoff` skill (under `~/.local/state/handoffs/`), compare `head_sha` to
`HEAD`, and state a resume plan before acting. Only the workspace-owning session
writes it; a missing pointer is a fresh start.

Agent teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`): teammates are
`~/ops/site-private/claude/agents/{ux,backend,adversary}.md`. **A teammate must
get an `adversary` security review verdict before opening a pull request**; put
the verdict (or an explicit "no findings") in the PR body.

## Detail notes (all in `~/ops/site-private/memory/`)

`reference_agent_rules_` + `ops_housekeeping.md` (rule rationale, memory
writing, codex config, clipboard, book KB, gateway, backups, teams),
`aiuse_quota_and_agy.md`, `basic_memory_pools.md`,
`code_discovery_and_cli_table.md`, `multi_agent_toolkit.md`.
