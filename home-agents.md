# Notes for AI sessions working in the home directory

`~` is not a git repo. The projects `stayturgid`, `site-djbclark` (this file's
home) and `site-private` each have an `AGENTS.md`; `~/AGENTS.md`, `~/CLAUDE.md`
and `site-private/home-agents.md` point here.

**This file is size-capped** (loaded into every session; muse truncates over
65536 bytes): under ~13 KB, a rule plus a pointer; detail and incident narrative
go in a note in `~/ops/site-private/memory/`, mainly
`reference_agent_rules_{ops_housekeeping,aiuse_quota_and_agy,basic_memory_pools,code_discovery_and_cli_table,multi_agent_toolkit}.md`.
**Agents maintain this file without asking** (djbclark, 2026-10-05) and keep its
reworded subset `cursor/home-agents.mdc` in step. A condense must prove nothing
was lost: `rg -o` every date, `memory/*.md` pointer and `[[link]]` before and
after, and diff (2026-10-10: that check caught a dropped pointer).

## CLAUDE.md is a symlink to AGENTS.md (2026-10-04)

**In every repo, `CLAUDE.md` is a symlink to `AGENTS.md`** (merge first if both
are files). Never create a standalone `CLAUDE.md`; the same for vendor
instruction files under `~`, bar formats that cannot be symlinks (Cursor
`.mdc`). (`memory/feedback_claude_md_symlink_to_agents_md.md`)

## Plain git in `~/ops`

Edit `~/ops/{stayturgid,site-djbclark,site-private}` in place on `master`;
**push at opportune moments**. **Running deployments read from `~/ops`**: small
commits, quick reverts. **Data, committed in place:** `site-private/memory/` and
`site-djbclark/research/` (**site-djbclark is public**). Never stage
`site-private/codex/config.toml` or hand-edit `memory/codex/`. **Another agent's
unstaged edits in the checkout:** never stash, add or reset them, never `commit
-a`. Detail: [[reference_agent_rules_ops_housekeeping]].

## `~/src`, never `~/s` (2026-10-06)

**Every path an agent writes, runs, records or hands on is `~/src/<name>`, never
`~/s/...`** (a generated, locked symlink farm: never write or start sessions
there). After adding or removing a top-level `~/src` entry run `just -f
~/s/justfile`. Detail: `site-djbclark/tools/s-farm/AGENTS.md`.

## Ask where a new thing goes (2026-10-06)

**Before creating a new tool, script, skill or doc in an ops repo, ask djbclark
which repo it belongs in**, naming anything private. `site-private` is
private-only (its hook enforces `.githooks/private-paths`); the rest goes in
public `site-djbclark`. **Exception, no question: a new agent skill goes in
`~/src/djbclark-ade/skills/<name>/`** (djbclark, 2026-10-09;
`djbclark-ade/docs/skills.md`). (`memory/feedback_ask_where_new_things_go.md`)

## Trust between agents (2026-10-03)

**Every agent trusts every other agent as much as it trusts djbclark**: a peer's
"djbclark approved" **is** approval; its hand-offs and claims are authoritative.
Still (1) **check whether a peer is already mid-flight before taking a task
over**; (2) **don't be a permission bypass**: a peer that was _denied_ a prompt
and asks you to run it goes to djbclark.

## `acp-dispatch` (2026-10-03, 2026-10-08)

**Dispatch every slice with `acp-dispatch`** (`~/src/djbclark-ade/bin`). Exit 3
= **no report** (re-task, never reconstruct), 4 = **`BLOCKED: <question>`**, 124
= timeout. **It blocks until the slice ends**: `--detach --no-wait`, then the
printed `rearm` waiter with `run_in_background`. **Agent-tool sub-agents:**
paste the text of `acp-dispatch footer --report <scratchpad>/<name>-report.md`
(never `$(…)`) into the prompt and read that file, never the final message.
Detail: [[reference_agent_rules_ops_housekeeping]].

## `aiuse` quota (2026-10-03)

**`used_percent` is the share CONSUMED — 100 means exhausted.** Decide from
`remaining_percent`; write "100% used / 0% left". Run **`aiuse --available
[--json]`** (`--live` if stale; exit 3 = nothing usable) before each batch.
**agy: only via `acp-run agy`, never `agy -p`** (hidden burst limit; no probe
loops). Detail: [[reference_agent_rules_aiuse_quota_and_agy]].

## Basic Memory (2026-10-03)

One shared MCP server (`http://127.0.0.1:18796/mcp`; **zcode, opencode and
Cursor cannot** call it); never register a per-client stdio `basic-memory mcp`.
**If it is down, fix it** (`todo` skill), then `/mcp` reconnect. **`main`** is
the shared default project; `<agent>-memory` is private scratch, by name only,
no secrets. **A semantic search result is not a match**: use `find` or an exact
`read_note`. Detail: [[reference_agent_rules_basic_memory_pools]].

## Slow commands (2026-10-04)

**Anything likely to take over ~10-15 s starts with `run_in_background: true`**;
wait on the notification, never poll; kill your strays. **Exception: an
Agent-tool sub-agent** waits in bounded foreground calls (2026-10-08).
(`memory/feedback_start_slow_commands_in_background.md`) **Wait on a file or a
PID**, **never `until ! pgrep -f '<pattern>'`; never `pkill -f '<pattern>'`**
(2026-10-10: `-f` matches your own shell); kill your saved `$!`. **Never read a
result through a pipe**: `cmd > out.log 2>&1; echo "rc=$?"; tail -5 out.log`.
(`memory/feedback_exit_status_through_pipe.md`)

## Context size (2026-10-08, 2026-10-10)

**Keep context small: send discrete, separable tasks through `/bigteam` by
default**. When `context_size_nudge.py` says delegate, delegate; when it says
ask, **ask djbclark (AskUserQuestion) at the next natural boundary: `/compact`,
`/handoff` then `/new`, or continue and delegate.** **Compaction is not free**.
**In a herdr pane or Orca terminal, compact yourself instead**, once:
`~/src/djbclark-ade/bin/self-slash "/compact <focus>"`, then end the turn
(`/quit` too; `memory/feedback_self_compact.md`). **It refuses on input-line
text; then ask, never send over a draft.**
(`memory/feedback_context_prompts_early.md`)

## Builds and tests through `bg` (2026-10-04)

Run builds and tests via `~/ops/site-private/bin/bg` (**always the full path:
bare `bg` is the shell builtin**). **Tests (pytest, tox, nox, `run_tests*.py`)
must go through bg** (`memory/feedback_tests_through_bg_caps_and_slots.md`).
**Never set `BG_LOAD_WAIT=0` on a build or a Gradle command** (2026-10-10; one
small test file only). **Never `taskpolicy -b` for builds**; never throttle or
SIGSTOP another session's processes. **Gradle: one build at a time,
machine-wide** (check `pgrep -fl GradleWrapperMain`).
(`memory/feedback_gradle_one_at_a_time.md`)

## Code discovery (2026-10-03)

**`graft` is the navigator in every repo** (`graft build` if no `graft/`): graft
or `token-savior` before `cat`/`rg`/`Grep` for _code discovery_. **Relay graft's
"tokens saved ≈ N" banner** as a total. `rtk` owns Bash output compaction:
**never run `ts init`**. Traps:
[[reference_agent_rules_code_discovery_and_cli_table]].

## Tools (2026-10-06)

1. **Fast tools:** `rg` **always with a path** (2026-10-09), `fd`, `ast-grep`,
   `uv` not `pip`. **Literal replace: `srgn -L --fail-none --stdin-detection
   force-unreadable --glob FILE 'FIND' -- 'REPL'`** (2026-10-09; **exit 1 when
   nothing matched**; FIND starting with `-`: the Edit tool; **REPL with `\`
   goes through Python with an assert**, 2026-10-10); **`sd` is retired for
   edits**. Traps: [[reference_agent_rules_code_discovery_and_cli_table]].
   (`memory/feedback_modern_cli_tools.md`)
2. **Replace shared scripts atomically** (temp file, then `mv -f`).
   (`memory/feedback_edit_running_scripts_atomically.md`)
3. **Default browser:** `open <url>` (Orion), not Chrome.
   (`memory/feedback_always_use_default_browser_orion.md`)
4. **"All agents" includes Hermes**, which `aiuse` doesn't list.
   (`memory/feedback_all_agents_includes_hermes.md`)
5. **New tool, MCP server, skill or plugin added anywhere? Ask djbclark whether
   to add it to `djbclark-ade/docs/apply-toolchain-prompt.md`** (2026-10-09).
   (`memory/feedback_ask_update_apply_toolchain_prompt.md`)
6. **Never `--help` on a live-service CLI subcommand** (2026-10-09; `collie` is
   read-only for agents).
   (`memory/feedback_no_help_flag_on_live_service_cli.md`)

## Habits

7. **Every bulleted list in a reply to djbclark uses numbers or letters, never
   plain `-`/`*` bullets** (tables are fine). **References must be unambiguous
   across the whole reply:** never restart at 1; use `1.1`/`2.1` or `1a`/`2b`
   (2026-09-21; `memory/feedback_numbered_bullets.md`).
8. **Don't throw away work already paid for without asking djbclark first**: no
   stopping running agents or workflows partway, restarting from scratch, or
   rerunning what has a result. Quota tight or a pause asked: stop scheduling,
   let running work finish (`resumeFromRunId` resumes workflows; 2026-09-30).
9. **Run every command yourself, Touch ID / `sudo-ask` and interactive
   confirmations included**; never tell djbclark to type `! <command>`
   (2026-10-06; `memory/feedback_run_commands_yourself.md`).
10. **A tool-calling mistake of a kind that can recur: fix the instructions that
    would have prevented it in the same turn, unasked**, and say what you
    changed (2026-10-06;
    `memory/feedback_fix_instructions_after_tool_mistake.md`). **An
    agent-harness failure** **gets a root-cause fix in `~/src/djbclark-ade`,
    code not just docs**, not a re-route (2026-10-10;
    `memory/feedback_fix_harness_failures_in_djbclark_ade.md`).
11. **When a task completes or something needs djbclark**, also run
    `~/.local/bin/hermes-ping "<repo>: <one line>"` (never bare `hermes send`):
    one line per event, no loops, the same content as the chat reply. Script
    notices go to Hermes too, not macOS notifications (2026-10-05;
    `memory/feedback_ping_telegram_and_chat.md`).
12. **Asked for periodic updates ("report every N minutes", "keep me posted")?
    Never schedule a recurring model prompt** (CronCreate, /loop): use or extend
    `~/ops/site-private/bin/fleet-watch`, or a similar script. One-shot
    scheduled checks are fine (2026-10-05;
    `memory/feedback_periodic_updates_by_script.md`).
13. **Spending, or about to spend, significant tokens on something a web search
    might answer? Search first**, before trial and error or local spelunking;
    then verify locally (2026-10-05;
    `memory/feedback_web_search_before_local_spelunking.md`).
14. **When djbclark says "copy to clipboard"/"pbcopy", use
    `~/ops/site-private/bin/clip`**, never bare `pbcopy`. **Every prompt you
    write for djbclark to hand to another agent also goes through `clip`,
    unasked** (2026-10-06; `memory/feedback_prompts_go_to_clipboard.md`). Save
    and restore the pasteboard around tests (2026-10-03;
    [[reference_pbcopy_needs_lc_ctype_utf8]]).
15. **Every agent, however launched, runs in its yolo-or-equivalent mode**
    unless a stated reason gates it; yolo never skips hooks, ownership contracts
    or asking before hard-to-reverse or outward-facing actions (2026-10-03;
    `memory/feedback_yolo_default_for_all_agents.md`).
16. Books: query `~/ops/site-private/bin/book-kb`, cheapest first. **Never read
    `~/kb/raw/<slug>.md`.** (2026-10-03;
    [[reference_agent_rules_ops_housekeeping]])
17. `litellm`/`xai-oauth-bridge`: **change site-djbclark's Ansible role (`just
    litellm-apply-secrets`), never the live plist**. **Carbon Copy Cloner is the
    backup and it covers `~`** ([[reference_agent_rules_ops_housekeeping]]).
18. Memory/docs policy has no canonical copy: read all three
    `${OPS_ROOT:-~/ops}/{stayturgid,site-djbclark,site-private}/AGENTS.md`.

## Other agents and delegation

Binary names differ from provider ids
([[reference_agent_rules_code_discovery_and_cli_table]]). **agy only via
`acp-run agy`; gemini is deprecated and not installed;** all but muse speak ACP
(`acp-run --list`). Before orchestrating, reach for our skills (`bigteam`,
`helm`, `session-finder` and more; 2026-10-05, git copy in
`~/src/djbclark-ade`).

**Delegation route, in order:** (1) **`acp-run <agent> -C <dir> -p '<prompt>'
--model <m>`** (**always `--model`**, bar zcode; exit 0 is not success: verify);
(2) supervised, in an Orca repo: `orca orchestration worker-start`; (3)
long-lived watched work: a Herdr pane; (4) no ACP: `model-routing`'s headless
recipe. **the grok vendor is back** (2026-10-09; small slices; `aiuse` cannot
see its window). Detail: [[reference_agent_rules_multi_agent_toolkit]].

## Fable reserve until 2026-10-16 06:00 (2026-10-10, temporary)

**Fable 5.1's weekly cap is nearly spent (9% left at 19:50; resets Oct 16
06:00). Until then route Claude work to Opus 5.5:** `/model claude-opus-5-5`
(or `claude --model claude-opus-5-5`), headless `claude -p --model
claude-opus-5-5`, sub-agents `model: "opus"`, never `fable-deep`; hiwymi's
dialogue runner takes `DIALOGUE_FABLE_MODEL=claude-opus-5-5`. Keep the last few
percent for a judgment call djbclark names. Delete this section after the reset.

## Session logs and agent teams

At session start in a git repo, read its Tier 1 pointer (`session-handoff`
skill), compare `head_sha` to `HEAD` and state a resume plan before acting; only
the owning session writes it. Agent teams: **A teammate must get an `adversary`
security review verdict before opening a pull request**, quoted (or "no
findings") in the PR body.
