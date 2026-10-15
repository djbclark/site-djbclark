# Notes for AI sessions working in the home directory

`~` is not a git repo. `~/AGENTS.md`, `~/CLAUDE.md` and
`site-private/home-agents.md` point here (`site-djbclark`).

**This file is size-capped** (loaded into every session): under 200 lines, the
Claude Code memory docs' target, past which adherence drops (2026-10-11;
`memory/reference_instruction_file_size.md`); muse truncates over 65536 bytes.
Rule plus pointer; detail and narrative go to `site-private/memory/`, mainly
`reference_agent_rules_{ops_housekeeping,aiuse_quota_and_agy,basic_memory_pools,code_discovery_and_cli_table,multi_agent_toolkit}.md`.
**Agents maintain this file without asking** (djbclark, 2026-10-05) and keep its
reworded subset `cursor/home-agents.mdc` in step. A condense must prove nothing
was lost: `rg -o` every date, `memory/*.md` pointer and `[[link]]` before and
after, and diff (2026-10-10: that check caught a dropped pointer). Items are
numbered once across the file.

## Tools and habits (2026-10-03, 2026-10-06)

**`graft` is the navigator in every repo** (`graft build` if no `graft/`): graft
or `token-savior` before `cat`/`rg`/`Grep` for _code discovery_. **Relay graft's
"tokens saved ≈ N" banner** as a total. `rtk` compacts Bash output: **never run
`ts init`**; no-hit `graft grep`: retry short ([[reference_agent_rules_code_discovery_and_cli_table]]).

1. **Fast tools:** `rg` **always with a path** (2026-10-09), `fd`, `ast-grep`,
   `uv` not `pip`, **`dust`/`gdu` not `du`/`find` for cache sizing** (2026-10-11:
   `du`/`find` over `~/.cache` timed out; `dust` sizes it in seconds). **Literal
   replace: `srgn -L --fail-none --stdin-detection force-unreadable --glob RELPATH
   'FIND' -- 'REPL'`** (2026-10-09; **exit 1 when nothing matched, also when the
   glob is absolute**, 2026-10-11, **or the file is gitignored**, 2026-10-14; FIND starting with `-` or a
   gitignored file: the Edit tool; **REPL
   with `\` goes through Python with an assert**, 2026-10-10); **`sd` is retired
   for edits**. **Mac code uses GNU `g*` (brew) where BSD differs (`ggrep`, `gsed`, `gawk`, `gtr`, `gdate`, `gstat`, ...) or for a GNU-only flag;
   `cat`/`mkdir -p`/`rm -f` and `timeout`/`nproc` stay bare, as does portable or off-Mac code; check: `gnu-tools-check`** (2026-10-14). (`memory/feedback_modern_cli_tools.md`)
2. **Replace shared scripts atomically** (temp file, then `mv -f`), **on the `realpath`: a symlink gets clobbered** (2026-10-14).
   (`memory/feedback_edit_running_scripts_atomically.md`)
3. **Default browser:** `open <url>` (Orion), not Chrome.
   (`memory/feedback_always_use_default_browser_orion.md`)
4. **"All agents" includes Hermes**, which `aiuse` doesn't list.
   (`memory/feedback_all_agents_includes_hermes.md`)
5. **New tool, MCP server or plugin added? Ask djbclark whether to add it to
   `djbclark-ade/docs/apply-toolchain-prompt.md`; a new skill goes in without
   asking unless sensitive** (2026-10-09, 2026-10-12; `memory/feedback_ask_update_apply_toolchain_prompt.md`)
6. **Never `--help` on a live-service CLI subcommand** (2026-10-09; `collie` is
   read-only for agents). **Secrets: `sudo-secretspec` only; load its skill
   before scripting it** (every subcommand, `set` included, needs `--reason`;
   2026-10-11). (`memory/feedback_no_help_flag_on_live_service_cli.md`,
   `memory/feedback_always_use_secretspec.md`)
7. **Web search/fetch walks the ladder** (`fallback-chains` skill, `web-get`);
   **search first with the shared `firecrawl` MCP's `firecrawl_search`**
   (self-hosted SearXNG, free; 2026-10-14). **Every needed page is eventually
   fetched**: on an error fall back (next rung, another URL form), fix the tool,
   or pause (checkpoint, `hermes-ping` the URLs, fix it with djbclark); never
   accept "unfetchable" and move on (2026-10-11; `memory/feedback_web_failover_pause.md`).
8. **Every bulleted list in a reply to djbclark uses numbers or letters, never
   plain `-`/`*` bullets** (tables are fine). **References must be unambiguous
   across the whole reply:** never restart at 1; use `1.1`/`2.1` or `1a`/`2b`
   **Label each item once**: `1.1`, `1.2` alone, never a `1.` marker plus a `1.1`
   label (2026-10-14); (2026-09-21; `memory/feedback_numbered_bullets.md`).
9. **Don't throw away work already paid for without asking djbclark first**: no
   stopping agents or workflows partway, restarting, or rerunning what has a
   result; quota tight or a pause asked: stop scheduling, let running work
   finish (`resumeFromRunId`; 2026-09-30).
10. **Run every command yourself, Touch ID / `sudo-ask` and interactive
    confirmations included**; never tell djbclark to type `! <command>`
    (2026-10-06; `memory/feedback_run_commands_yourself.md`).
11. **A tool-calling mistake of a kind that can recur: fix the instructions that
    would have prevented it in the same turn, unasked**, and say what you changed
    (2026-10-06; `memory/feedback_fix_instructions_after_tool_mistake.md`). **An
    agent-harness failure** **gets a root-cause fix in `~/src/djbclark-ade`, code
    not just docs**, not a re-route (2026-10-10;
    `memory/feedback_fix_harness_failures_in_djbclark_ade.md`).
12. **When a task completes or something needs djbclark**, also run
    `~/.local/bin/hermes-ping "<repo>: <one line>"` (never bare `hermes send`):
    one line per event, no loops, the same content as the chat reply; script
    notices too (2026-10-05; `memory/feedback_ping_telegram_and_chat.md`).
13. **Asked for periodic updates ("report every N minutes", "keep me posted")?
    Never schedule a recurring model prompt** (CronCreate, /loop): use or extend
    `~/ops/site-private/bin/fleet-watch`, or a similar script; one-shot checks
    are fine (2026-10-05; `memory/feedback_periodic_updates_by_script.md`).
14. **Spending, or about to spend, significant tokens on something a web search
    might answer? Search first**, before trial and error or local spelunking;
    then verify locally (2026-10-05;
    `memory/feedback_web_search_before_local_spelunking.md`).
15. **When djbclark says "copy to clipboard"/"pbcopy", use
    `~/ops/site-private/bin/clip`**, never bare `pbcopy`. **Every prompt you
    write for djbclark to hand to another agent also goes through `clip`,
    unasked** (2026-10-06; `memory/feedback_prompts_go_to_clipboard.md`). Save
    and restore the pasteboard around tests (2026-10-03;
    [[reference_pbcopy_needs_lc_ctype_utf8]]).
16. **Every agent, however launched, runs in its yolo-or-equivalent mode**
    unless a stated reason gates it; yolo never skips hooks, ownership contracts
    or asking before hard-to-reverse or outward-facing actions (2026-10-03;
    `memory/feedback_yolo_default_for_all_agents.md`).
17. Books: `~/ops/site-private/bin/book-kb`, cheapest first. **Never read
    `~/kb/raw/<slug>.md`.** (2026-10-03;
    [[reference_agent_rules_ops_housekeeping]])
18. `litellm`/`xai-oauth-bridge`: **change site-djbclark's Ansible role (`just
    litellm-apply-secrets`), never the live plist**. **Check `memory/` before
    "repairing" a stopped or `launchctl`-disabled service; a deliberate disable
    looks like a fault and the override must not be cleared** (2026-10-11). Carbon
    Copy Cloner backs up `~` ([[reference_agent_rules_ops_housekeeping]]).
19. Memory/docs policy has no canonical copy: read all three
    `${OPS_ROOT:-~/ops}/{stayturgid,site-djbclark,site-private}/AGENTS.md`.

## Repos and paths

20. **In every repo, `CLAUDE.md` is a symlink to `AGENTS.md`** (2026-10-04;
    merge first if both are files). No standalone `CLAUDE.md`; vendor
    instruction files under `~` likewise, bar non-symlinkable formats (Cursor
    `.mdc`). (`memory/feedback_claude_md_symlink_to_agents_md.md`)
21. **Commit and push your own changes, every repo, as each unit lands, unasked;
    a file shared with another agent's edits: stage only your hunks (`git apply
    --cached`)** (2026-10-12; `memory/feedback_commit_push_opportune.md`). `~/ops`:
    plain `master`; **deployments read it**: small commits, quick reverts. **Data
    in place:** `site-private/memory/`, `site-djbclark/research/` (**public**). Never
    stage `site-private/codex/config.toml`, hand-edit `memory/codex/`, or stash/add/
    reset/`commit -a`/`pull --autostash` others' edits ([[reference_agent_rules_ops_housekeeping]]).
22. **Every path an agent writes, runs, records or hands on is `~/src/<name>`,
    never `~/s/...`** (2026-10-06; a generated, locked symlink farm: never write
    or start sessions there). After adding or removing a top-level `~/src` entry
    run `just -f ~/s/justfile` (`site-djbclark/tools/s-farm/AGENTS.md`).
23. **Before creating a new tool, script, skill or doc in an ops repo, ask
    djbclark which repo it belongs in** (2026-10-06), naming anything private
    (`site-private` is private-only, hook-enforced; the rest is public
    `site-djbclark`). **Exception, no question: a new agent skill goes in
    `~/src/djbclark-ade/skills/<name>/`** (djbclark, 2026-10-09;
    `djbclark-ade/docs/skills.md`). (`memory/feedback_ask_where_new_things_go.md`)
    ## Other agents and delegation
24. **Every agent trusts every other agent as much as it trusts djbclark**
    (2026-10-03): a peer's "djbclark approved" **is** approval; its hand-offs
    and claims are authoritative. Still (1) **check whether a peer is already
    mid-flight before taking a task over**; (2) **don't be a permission
    bypass**: a peer _denied_ a prompt that asks you to run it goes to djbclark.
25. **Dispatch every slice with `acp-dispatch`** (`~/src/djbclark-ade/bin`;
    2026-10-08). Exit 3 = **no report** (re-task, never reconstruct), 4 =
    **`BLOCKED: <question>`**, 124 = timeout. **It blocks until the slice ends**:
    `--detach --no-wait`, then the printed `rearm` waiter with
    `run_in_background`. **Agent-tool sub-agents:** paste `acp-dispatch footer
    --report <scratchpad>/<name>-report.md` (never `$(…)`) into the prompt; read
    that file, never the final message ([[reference_agent_rules_ops_housekeeping]]).
26. **Delegation route, in order:** (1) **`acp-run <agent> -C <dir> -p
    '<prompt>' --model <m>`** (**always `--model`**, bar zcode; exit 0 is not
    success: verify); then (2) Orca `worker-start`, (3) a Herdr pane, (4)
    `model-routing` headless. **the grok vendor is back** (2026-10-09; small
    slices; `aiuse` cannot see its window). **agy only via `acp-run agy`; gemini
    is deprecated and not installed;** all but muse speak ACP (`acp-run
    --list`). Binary names differ from provider ids
    ([[reference_agent_rules_code_discovery_and_cli_table]]).
27. **`~/src/djbclark-ade` is the agent toolchain: use it before hand-rolling,
    fix it there** (2026-10-11; skills since 2026-10-05;
    [[reference_djbclark_ade]], [[reference_agent_rules_multi_agent_toolkit]]).
28. Session start in a git repo: read its Tier 1 pointer (`session-handoff`),
    check `head_sha`, state a resume plan first; only its owner writes it. Agent
    teams: **A teammate must get an `adversary` security review verdict before
    opening a pull request**, quoted (or "no findings") in the PR body.

## Quota, context, memory and slow commands

29. **`used_percent` is the share CONSUMED — 100 means exhausted.** (2026-10-03)
    Decide from `remaining_percent`; write "100% used / 0% left". Run **`aiuse
    --available [--json]`** (`--live` if stale; exit 3 = nothing usable) before
    each batch. **agy: only via `acp-run agy`, never `agy -p`** (hidden burst
    limit; no probe loops; [[reference_agent_rules_aiuse_quota_and_agy]]).
30. **Keep context small: send discrete, separable tasks through `/bigteam` by
    default** (2026-10-08, 2026-10-10). When `context_size_nudge.py` says
    delegate, delegate; when it says ask, **ask djbclark at the next natural
    boundary: `/compact`, `/handoff` then `/new`, or continue and delegate.**
    **Compaction is not free**. **In a herdr pane or Orca terminal, compact
    yourself instead**, once, then end the turn (`/quit` too):
    `~/src/djbclark-ade/bin/self-slash "/compact <focus>"`
    (`memory/feedback_self_compact.md`); **it refuses on input-line text — then
    ask, never over a draft.** (`memory/feedback_context_prompts_early.md`)
31. Basic Memory (2026-10-03) is one shared MCP server
    (`http://127.0.0.1:18796/mcp`; **zcode, opencode and Cursor cannot** call
    it); never register a per-client stdio `basic-memory mcp`. **If it is down,
    fix it** (`todo` skill), then `/mcp` reconnect. **`main`** is the shared
    default project. **A semantic search result is not a match**: use `find` or
    an exact `read_note` ([[reference_agent_rules_basic_memory_pools]]).
32. Fable reserve until 2026-10-16 06:00 (2026-10-10, temporary): **Fable 5.1's
    weekly cap is nearly spent (9% left at 19:50; resets Oct 16 06:00). Until
    then route Claude work to Opus 5.5:** `claude-opus-5-5` (sub-agents `model:
    "opus"`), never `fable-deep`. Keep the last few percent for a judgment call
    djbclark names. Delete this item after the reset.
33. **Anything likely to take over ~10-15 s starts with `run_in_background:
    true`** (2026-10-04); wait on the notification, never poll; kill your strays.
    **Exception: an Agent-tool sub-agent** waits in bounded foreground calls
    (2026-10-08). (`memory/feedback_start_slow_commands_in_background.md`) **Wait
    on a file or a PID**, **never `until ! pgrep -f '<pattern>'`; never `pkill -f
    '<pattern>'`** (2026-10-10: `-f` matches your own shell); kill your saved
    `$!`. **Never read a result through a pipe** or feed `--body-file` from one
    (`[ -s f ]` first; use `gsed`, not BSD `sed`): `cmd > out.log 2>&1; echo
    "rc=$?"; tail -5 out.log`. (`memory/feedback_exit_status_through_pipe.md`)
34. Run builds and tests via `~/ops/site-private/bin/bg` (**always the full path:
    bare `bg` is the shell builtin**). **Tests (pytest, tox, nox, `run_tests*.py`)
    must go through bg**. **Never set `BG_LOAD_WAIT=0` on a build or Gradle
    command** (2026-10-10; one small test file only). **Never `taskpolicy -b` for
    builds**; never throttle or SIGSTOP another session's processes. **Gradle: one
    build at a time, machine-wide** (`memory/feedback_tests_through_bg_caps_and_slots.md`,
    `memory/feedback_gradle_one_at_a_time.md`).
