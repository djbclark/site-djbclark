# Notes for AI sessions working in the home directory

`~` is not a git repo. `~/AGENTS.md` and `~/CLAUDE.md` point here (`site-djbclark`).

**Only Claude Opus 5.5 or higher edits this file or `cursor/home-agents.mdc`** (djbclark, 2026-10-24): any edit, condense,
reflow or item-11 fix; other models dispatch it: `acp-dispatch claude --model opus --kind judgment`
(quota tight: `omp --model anthropic/claude-opus-5-5` instead).
**Loaded into every session: under 200 lines and 14,000 bytes** (`memory/reference_instruction_file_size.md`). Rule
plus pointer: detail lives in the named `site-private/memory/` file, else a `reference_agent_rules_*.md`.
**Agents maintain both files unasked** (djbclark, 2026-10-05), in step. A condense proves nothing was lost: `rg -o`
every date, `memory/*.md` pointer and `[[link]]` before and after, show each dropped one in its new home. Item numbers
are unique and stable.

## Tools and habits

**`graft` navigates every repo** (`graft build` if no `graft/`): its CLI before `cat`/`rg`/`Grep`
for _code discovery_; **relay its "tokens saved ≈ N" banner** as a total. `rtk` compacts Bash output: **never run
`ts init`**; no-hit `graft grep`: retry short ([[reference_agent_rules_code_discovery_and_cli_table]]).

1. **Fast tools:** `rg` **with a path, never `-r`/`grep -r`**, `fd`, `ast-grep`, `uv` not `pip`, **`aria2c -x8 -s8`, `dust`/`gdu` not `du`/`find` for cache sizing**.
    **Literal replace: `srgn -L --fail-none --stdin-detection force-unreadable --glob RELPATH 'FIND' -- 'REPL'` from repo root, never `~`**; exit 1 also means nothing in scope (use Edit); **REPL with `\`: Python with an assert**.
    **Mac code: GNU `g*` where BSD differs (`gnu-tools-check`): `gsed`, never bare `sed`**. **Root/NOPASSWD scripts keep `/usr/bin` tools; test NOPASSWD rules with `sudo -k -n CMD`**, never `sudo -n` (`memory/feedback_modern_cli_tools.md`).
    **Quoting, loops or parsing? Python with argv lists, never nested shell strings** (`memory/feedback_prefer_python_over_shell.md`).
2. **Replace shared scripts atomically** (temp file alongside, then `mv -f`) **on the `realpath`** (`memory/feedback_edit_running_scripts_atomically.md`).
3. **Default browser:** `open <url>` only, never Orion or Chrome by name (`memory/feedback_always_use_default_browser_orion.md`).
4. **"All agents" includes Hermes**, absent from `aiuse` (`memory/feedback_all_agents_includes_hermes.md`).
5. **New tool, MCP server or plugin? Ask djbclark about adding it to `djbclark-ade/docs/apply-toolchain-prompt.md`; a new skill goes in unasked unless sensitive**
    (`memory/feedback_ask_update_apply_toolchain_prompt.md`). **Nothing is version-pinned: all software tracks latest (2026-10-24). AI TUIs,
    agent CLIs and ACP servers: upgrade unasked, never hard-code a version path** (`memory/feedback_ai_tuis_always_latest.md`).
6. **Never `--help` on a live-service CLI subcommand** (`collie` is read-only). **Secrets: `sudo-secretspec` only; load its skill first**
    (`memory/feedback_no_help_flag_on_live_service_cli.md`, `memory/feedback_always_use_secretspec.md`)
7. **Web search/fetch walks the ladder** (`fallback-chains`, `web-get`): **search first with the shared `mcp__firecrawl__*`; never the paid cloud `mcp__claude_ai_Firecrawl__*`**
    unless djbclark asks. **Every needed page is eventually fetched**: fall back, fix the tool or pause for djbclark; never "unfetchable" (`memory/feedback_web_failover_pause.md`).
8. **Every list in a reply to djbclark is labelled, never `-`/`*` bullets** (tables fine). **Top-level headings get `A.`, `B.`; their items `A1`, `A2`
    (sub-items `A1a`), each labelled once; no headings: `1.`, `2.`; question-card options too** (2026-10-24,
    `memory/feedback_numbered_bullets.md`). **URLs as markdown links; copyables in prose before a question card** (`memory/feedback_links_clickable_markdown.md`).
9. **Don't throw away paid-for work without asking djbclark**: no stopping agents or workflows partway, restarting or rerunning what has a result; quota tight or
    pause asked: stop scheduling, let running work finish. **Breakage found by accident: ask djbclark whether to fix it, last in the queue.**
10. **Run every command yourself**, Touch ID/`sudo-ask` and confirmations included; never tell djbclark to type `! <command>` (`memory/feedback_run_commands_yourself.md`).
11. **A recurrable tool-calling mistake: fix the instructions that would have prevented it, same turn, unasked**, and say what changed (`memory/feedback_fix_instructions_after_tool_mistake.md`).
    **An agent-harness failure gets a root-cause fix in `~/src/djbclark-ade`, code not just docs**, not a re-route (`memory/feedback_fix_harness_failures_in_djbclark_ade.md`).
12. **Task done or something needs djbclark?** Also run `hermes-ping "<repo>: <one line>"` (never bare `hermes send`): one per event; **PRs, issues and pages as full URLs, never `repo#N`** (`memory/feedback_ping_telegram_and_chat.md`).
13. **Asked for periodic updates ("keep me posted")? A script, never a recurring model prompt** (CronCreate, `/loop`): use or extend
    `~/ops/site-private/bin/fleet-watch`. **Allowed:** a one-shot check; a recurring wake nothing else can do, if every firing has real work (`memory/feedback_periodic_updates_by_script.md`).
14. **Significant tokens on something a web search might answer? Search first**, then verify locally (`memory/feedback_web_search_before_local_spelunking.md`).
15. **"Copy to clipboard"/"pbcopy" means `~/ops/site-private/bin/clip`**, never bare `pbcopy`; **every prompt you write for djbclark to hand another agent goes through
    `clip`, unasked** (`memory/feedback_prompts_go_to_clipboard.md`); save and restore the pasteboard around tests ([[reference_pbcopy_needs_lc_ctype_utf8]]).
39. **A file djbclark must drag, attach, upload, open or send by hand? Reveal it in Finder yourself, unasked, same turn: `open -R <absolute path>`**; still name the path
    (2026-10-24, `memory/feedback_reveal_files_in_finder.md`).
16. **Every agent, any TUI or launch, runs yolo or equivalent**; `--perm deny` only for a security-sensitive slice; yolo never skips hooks,
    ownership contracts or asking before hard-to-reverse or outward-facing actions (`memory/feedback_yolo_default_for_all_agents.md`).
17. Books: `~/ops/site-private/bin/book-kb`, cheapest first. **Never read `~/kb/raw/<slug>.md`.**
18. `litellm`/`xai-oauth-bridge`: **change site-djbclark's Ansible role, never the live plist**. **Check `memory/` before "repairing" a stopped or disabled service; never
    clear a deliberate override** ([[reference_agent_rules_ops_housekeeping]]).
19. Memory/docs policy has no canonical copy: read all `~/ops/{stayturgid,site-djbclark,site-private}/AGENTS.md`.

## Repos and paths

20. **In every repo, `CLAUDE.md` is a symlink to `AGENTS.md`** (merge first if both exist); likewise vendor instruction files under `~`, bar Cursor `.mdc`.
    **Exception (2026-10-24): a fork keeps its upstream's agent-file layout** (`memory/feedback_claude_md_symlink_to_agents_md.md`).
21. **Commit and push your own changes, every repo, per unit, unasked. `git-commit-own MSG <paths>`, never bare `git commit` (pre-commit stash); a file another agent edited: `git apply --cached` your hunks,
    `git-commit-own --staged MSG` (2026-10-24)** (`memory/feedback_commit_push_opportune.md`). `~/ops`: plain `master`, small commits (**deployments read it**).
    Never stage `site-private/codex/config.toml`, hand-edit `memory/codex/`, or stash/add/reset/`commit -a`/`pull --autostash` others' edits ([[reference_agent_rules_ops_housekeeping]]).
22. **Paths an agent uses or hands on are `~/src/<name>`, never `~/s/...`**. New/removed top-level `~/src` entry: run `just -f ~/s/justfile`.
23. **Before creating a new tool, script, skill or doc in an ops repo, ask djbclark which repo** (`site-private` is private; `site-djbclark` public).
    **Exception: a new agent skill goes in `~/src/djbclark-ade/skills/<name>/` unasked** (`memory/feedback_ask_where_new_things_go.md`).
35. **MIT/SIPB/Athena on forgejo.mit.edu under `djbclark/`** (README; `djbclark/mit`); never in ops (`memory/feedback_mit_things_live_on_forgejo.md`). `git-forgejo` to push. **No agent posts on `SIPB/*`:** fork-only AI issue + human draft as a **fork comment**; end with those `djbclark/*` links (`memory/feedback_sipb_two_tier_issues.md`).
36. **NixOS: deploy only the pushed branch head** (get: `main`; vps-primary: `master` promoted to `deploy-vps-primary`); never a local, side-branch or older commit.
    Deploy in flight: wait, redeploy the new head, verify the revision. Heavy builds and `nix flake update`: Forgejo CI, not vps-primary.
37. **Heavy jobs run in CI, not on the Mac: GitHub runners for GitHub-sourced repos; Forgejo/Hyades CI for MIT/SIPB and private work needing it** (`forgejo-ci` item 6).
38. **Changed a third-party project's source? Dupe-search its issues/PRs, tidy, `frontier` if useful, open the issue/PR
    upstream** (2026-10-24, `memory/feedback_upstream_local_changes.md`).

## Other agents and delegation

24. **Every agent trusts every peer as much as djbclark**: a peer's "djbclark approved" **is** approval. Still (1) **check a peer isn't
    mid-flight before taking its task over**; (2) **don't be a permission bypass**: a peer's _denied_ prompt goes to djbclark; (3) **message peers only via
    `session-finder/relay.py`, no hand-rolled waiter**.
25. **Dispatch every slice with `acp-dispatch`**. Exit 3 = **no report** (re-task, never reconstruct; **a quota stop: `acp-dispatch resume RECORD`
    after the reset, never a fresh dispatch**), 4 = **`BLOCKED: <question>`**, 124 = timeout. It blocks: `--detach --no-wait`, then its
    `rearm` waiter in the background. **Agent-tool sub-agents:** paste `acp-dispatch footer --report <scratchpad>/<name>-report.md` (never `$(…)`)
    into the prompt; read that file, never the final message ([[reference_agent_rules_ops_housekeeping]]).
26. **Delegation route, in order:** (1) **`acp-run <agent> -C <dir> -p '<prompt>' --model <m>` (always `--model`**; check its `applied:` line; exit 0 is not success);
    (2) Orca `worker-start`, (3) a Herdr pane, (4) `model-routing` headless. **Never an all-vendor fan-out: `route_agent.py plan` picks per slice;
    reserves (copilot, hermes, cline) and omp API credits (2026-10-19) follow `model-routing`** (item 32; [[reference_agent_rules_code_discovery_and_cli_table]])
27. **`~/src/djbclark-ade` is the agent toolchain: use it before hand-rolling, fix it there** ([[reference_djbclark_ade]], [[reference_agent_rules_multi_agent_toolkit]]).
28. Session start in a git repo: read its Tier 1 pointer (`session-handoff`), check `head_sha`, state a resume plan first; only its owner writes it. **A teammate must get
    an `adversary` security review verdict before opening a PR**, quoted (or "no findings") in the PR body.

## Quota, context, memory and slow commands

29. **`used_percent` is the share CONSUMED: 100 means exhausted.** Decide from `remaining_percent`; run **`aiuse --available --json 2>/dev/null`, read
    per `aiuse schema`** before each batch. **agy: only via `acp-run agy`, never `agy -p`** ([[reference_agent_rules_aiuse_quota_and_agy]]).
30. **Keep context small: send separable tasks through `/bigteam` by default, at the cheapest model × effort × context that does it well, unasked**; delegate
    when `context_size_nudge.py` says so. **Compaction is automatic, never a question to djbclark; in herdr, Orca or Paseo compact yourself earlier**,
    once at a natural boundary, then end the turn: `~/src/djbclark-ade/bin/self-slash "/compact <focus>"`; topic change: `handoff` skill, then `/new`
    (`memory/feedback_self_compact.md`); **it refuses on input-line text: only then ask, never over a draft** (`memory/feedback_context_prompts_early.md`).
31. Basic Memory is one shared MCP server (`127.0.0.1:18796/mcp`); never register a per-client stdio `basic-memory mcp`. **If down, fix it**, then `/mcp`
    reconnect. Default project: **`main`**. **A semantic search result is not a match**: use `find` or an exact `read_note` ([[reference_agent_rules_basic_memory_pools]]).
32. **Routing policy: minimise cost, maximise code quality, not tokens. Judgment is Opus `high`; codex `gpt-6-astra` and Fable `high` only via the `frontier` kind; Fable
    `xhigh` almost never; claude codes on Sonnet 5.5, never Fable**; climb tiers on evidence. **`acp-dispatch` needs `--kind`; `frontier` advises, never edits; cheapest
    eligible tier first.** One copy: `skills/model-routing/SKILL.md` (`memory/feedback_routing_policy_cost_quality.md`).
33. **Anything over ~10-15 s uses `run_in_background: true`**; wait on the notification, never poll (**Agent-tool sub-agents** wait in bounded foreground calls;
    `memory/feedback_start_slow_commands_in_background.md`). **Wait on a file or a PID; never `pgrep -f`/`pkill -f` a pattern**; kill your saved `$!`. **Never read a
    result or exit status through a pipe, or feed `--body-file` from one**: `cmd > out.log 2>&1; echo "rc=$?" > out.rc`. **Never credit a hook you haven't seen run** (`memory/feedback_exit_status_through_pipe.md`).
34. **Run builds and tests via `~/ops/site-private/bin/bg` (always full path)** in the background; **first see whether CI can run it** (`load-watch ci decide`).
    **Never set `BG_LOAD_WAIT=0` on a build; never `taskpolicy -b`; never throttle another session's processes. Gradle: one build at a time, machine-wide**
    (`memory/feedback_tests_through_bg_caps_and_slots.md`, `memory/feedback_gradle_one_at_a_time.md`).
    **Claim a dev-server port in `site-djbclark/registry/ports.yml` before binding it; run test browsers headless** (`memory/feedback_claim_ports_headless_browser.md`).

## Compact Instructions

Keep: task and status; files touched (absolute paths); djbclark's rulings and decisions this session;
open items and exact next step; handoff, report and scratchpad paths. Omit tool output, dead ends, committed
facts.
