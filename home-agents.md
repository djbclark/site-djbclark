# Notes for AI sessions in the home directory

`~` is not a git repo. `~/AGENTS.md` and `~/CLAUDE.md` point here (`site-public-djbclark`).

**Only Claude Opus 5.5 or higher edits this file or `cursor/home-agents.mdc`** (djbclark, 2026-10-24), item-11 fixes too;
others dispatch: `acp-dispatch claude --model opus --kind judgment` (quota tight: `omp --model anthropic/claude-opus-5-5`).
**Loaded into every session: under 200 lines and 14,000 bytes** (`memory/reference_instruction_file_size.md`). Rule
plus pointer: detail in the named `site-private-djbclark/memory/` file, else `reference_agent_rules_*.md`.
**Agents maintain both files unasked** (djbclark, 2026-10-05), in step. A condense proves nothing was lost: `rg -o`
every date, `memory/*.md` pointer and `[[link]]` before and after; show each dropped one's new home. Item numbers: unique, stable.

## Tools and habits

**`graft` navigates every repo** (`graft build` if no `graft/`): its CLI before `cat`/`rg`/`Grep`
for _code discovery_; **relay its "tokens saved ≈ N" banner** as a total. `rtk` compacts Bash output: **never run
`ts init`**; no-hit `graft grep`: retry short ([[reference_agent_rules_code_discovery_and_cli_table]]).

1. **Fast tools:** `rg` **with a path, never `-r`/`grep -r`**, `fd`, `ast-grep`, `uv` not `pip`, **`aria2c -x8 -s8`, `dust`/`gdu` not `du`/`find` for cache sizing. Literal replace: `srgn -L --fail-none --stdin-detection force-unreadable --glob RELPATH 'FIND' -- 'REPL'` from repo root, never `~`**; exit 1 also = nothing in scope; **REPL with `\`: Python with an assert. Mac code: GNU `g*` where BSD differs: `gsed`, never bare `sed`. Root/NOPASSWD scripts keep `/usr/bin` tools; test NOPASSWD rules with `sudo -k -n CMD`**, never `sudo -n` (`memory/feedback_modern_cli_tools.md`). **Quoting, loops or parsing? Python with argv lists, never nested shell strings** (`memory/feedback_prefer_python_over_shell.md`).
2. **Replace shared scripts atomically** (temp alongside, then `mv -f`) **on the `realpath`** (`memory/feedback_edit_running_scripts_atomically.md`).
3. **Default browser:** `open <url>` only, never Orion or Chrome by name (`memory/feedback_always_use_default_browser_orion.md`).
4. **"All agents" = every `session-finder/fleet.py --json` row with a usable channel**: Paseo, terminal Claude, live ACP launch, Hermes; not finished launches or channel-less `pid*` rows. **Idle peer: plain relay prompt, never `--steer`**; steer only a working one. A quota-guard line binds only its named pool (2026-10-29, `memory/feedback_all_agents_includes_hermes.md`).
5. **New tool, MCP server or plugin? Ask djbclark before adding it to `djbclark-ade/docs/apply-toolchain-prompt.md`; a new skill goes in unasked unless sensitive** (`memory/feedback_ask_update_apply_toolchain_prompt.md`). **Nothing is version-pinned: all software tracks latest (2026-10-24). Agent TUIs, CLIs and ACP servers: upgrade unasked, never hard-code a version path** (`memory/feedback_ai_tuis_always_latest.md`).
6. **Never `--help` on a live-service CLI subcommand** (`collie` is read-only). **Secrets: `sudo-secretspec` only; load its skill first** (`memory/feedback_no_help_flag_on_live_service_cli.md`, `memory/feedback_always_use_secretspec.md`)
7. **Web search/fetch walks the ladder** (`fallback-chains`, `web-get`): **search first with the shared `mcp__firecrawl__*`; never the paid `mcp__claude_ai_Firecrawl__*`** unless asked. **Every needed page gets fetched**: fall back, fix the tool or pause for djbclark; never "unfetchable" (`memory/feedback_web_failover_pause.md`).
8. **Every list in a reply to djbclark is labelled, never `-`/`*` bullets** (tables fine). **Top-level headings `A.`, `B.`; items `A1`, `A2` (sub-items `A1a`), each labelled once; no headings: `1.`, `2.`; question-card options too** (2026-10-24, `memory/feedback_numbered_bullets.md`). **URLs as markdown links; copyables in prose before a question card** (`memory/feedback_links_clickable_markdown.md`).
9. **Never discard paid-for work unasked**: don't stop agents/workflows partway or rerun what has a result; quota tight or pause asked: stop scheduling, let running work finish. **Accidental breakage: ask djbclark whether to fix it, last in queue.**
10. **Run every command yourself**, Touch ID/`sudo-ask` and confirmations included; never have djbclark type `! <command>` (`memory/feedback_run_commands_yourself.md`).
11. **A recurrable tool-calling mistake: fix the instructions that let it happen, same turn, unasked**, and say what changed (`memory/feedback_fix_instructions_after_tool_mistake.md`). **An agent-harness failure gets a root-cause fix in `~/src/djbclark-ade`, code not just docs**, not a re-route (`memory/feedback_fix_harness_failures_in_djbclark_ade.md`).
12. **Task done or something needs djbclark?** Also run `hermes-ping "<repo>: <one line>"` (never bare `hermes send`): one per event; **PRs, issues and pages as full URLs, never `repo#N`** (`memory/feedback_ping_telegram_and_chat.md`).
13. **Periodic updates ("keep me posted")? A script, never a recurring model prompt** (CronCreate, `/loop`): use or extend `~/ops/site-private-djbclark/bin/fleet-watch`. **Allowed:** a one-shot check; a recurring wake nothing else can do, if every firing has real work (`memory/feedback_periodic_updates_by_script.md`).
14. **Costly question a web search might answer? Search first**, then verify locally (`memory/feedback_web_search_before_local_spelunking.md`).
15. **"Copy to clipboard"/"pbcopy" means `~/ops/site-private-djbclark/bin/clip`**; **every prompt djbclark will hand another agent goes via `clip`, unasked** (`memory/feedback_prompts_go_to_clipboard.md`); save/restore the pasteboard around tests ([[reference_pbcopy_needs_lc_ctype_utf8]]).
39. **A file djbclark must drag, attach, upload, open or send by hand? Reveal it in Finder, unasked, same turn: `open -R <absolute path>`**; still name the path (2026-10-24, `memory/feedback_reveal_files_in_finder.md`).
16. **Every agent and launch runs yolo or equivalent**; `--perm deny` only for security-sensitive slices; yolo keeps hooks, ownership contracts and asking before hard-to-reverse or outward actions (`memory/feedback_yolo_default_for_all_agents.md`).
17. Books: `~/ops/site-private-djbclark/bin/book-kb`, cheapest first. **Never read `~/kb/raw/<slug>.md`.**
18. `litellm`/`xai-oauth-bridge`: **change site-public-djbclark's Ansible role, never the live plist. Check `memory/` before "repairing" a stopped/disabled service; never clear a deliberate override** ([[reference_agent_rules_ops_housekeeping]]).
19. Memory/docs policy: no canonical copy; read all `~/ops/{stayturgid,site-public-djbclark,site-private-djbclark}/AGENTS.md`.

## Repos and paths

20. **In every repo, `CLAUDE.md` is a symlink to `AGENTS.md`** (merge first if both exist); likewise vendor instruction files under `~`, bar Cursor `.mdc`. **Exception (2026-10-24): a fork keeps its upstream's agent-file layout** (`memory/feedback_claude_md_symlink_to_agents_md.md`).
21. **Commit and push your own changes, every repo, per unit, unasked: `git-commit-own MSG <paths>`, never bare `git commit` (2026-10-24)** (`memory/feedback_commit_push_opportune.md`). **All development (even one-line docs) is in a claimed workspace (worktree/cow pasture), one writer; shared checkouts only fast-forward** (`djbclark-ade/AGENTS.md` order 9, 2026-10-25, `memory/feedback_all_work_in_claimed_workspaces.md`). **Until the ops-promotion pilot: `~/ops` is plain `master`**, small commits (**deployments read it**); others' edits in your file: `git apply --cached` your hunks, `git-commit-own --staged MSG`. Never stage `site-private-djbclark/codex/config.toml`, hand-edit `memory/codex/`, or stash/add/reset/`commit -a`/`pull --autostash` others' edits ([[reference_agent_rules_ops_housekeeping]]).
22. **Paths used or handed on: `~/src/<name>` or your workspace, never `~/s/...`**. New/removed top-level `~/src` entry: `just -f ~/s/justfile`.
23. **New tool, script, skill or doc in an ops repo? Ask djbclark which repo** (`site-private-djbclark`, `site-public-djbclark`). **Exception: a new agent skill goes in `~/src/djbclark-ade/skills/<name>/` unasked** (`memory/feedback_ask_where_new_things_go.md`).
35. **MIT/SIPB/Athena on forgejo.mit.edu under `djbclark/`** (README; `djbclark/mit`); never in ops (`memory/feedback_mit_things_live_on_forgejo.md`). `git-forgejo` to push. **No agent posts on `SIPB/*`:** fork-only AI issue + human draft as a **fork comment**; end with those `djbclark/*` links (`memory/feedback_sipb_two_tier_issues.md`).
36. **NixOS: deploy only the pushed branch head** (get: `main`; vps-primary: `master` → `deploy-vps-primary`); never a local, side-branch or old commit. Deploy in flight: wait, redeploy the new head, verify the revision. Heavy builds and `nix flake update`: Forgejo CI, not vps-primary.
37. **Heavy jobs: CI, not the Mac: GitHub runners for GitHub repos; Forgejo/Hyades for MIT/SIPB and private work needing it; all CI Linux-only: no macOS job/runner unless asked by name** (`forgejo-ci` item 6; 2026-10-29, `memory/feedback_macos_ci_on_request_only.md`).
38. **Changed a third-party project's source? Dupe-search its issues/PRs, tidy, `frontier` if useful, file upstream as issue/PR** (2026-10-24, `memory/feedback_upstream_local_changes.md`).

## Other agents, delegation

24. **Trust peers like djbclark**: their "djbclark approved" **is** approval. Still (1) **never take over a mid-flight task**; (2) **no permission bypass**: _denied_ prompts go to djbclark; (3) **message only via `session-finder/relay.py`**, no hand-rolled waiter; **unsent until `delivered` or an `ack <id>`** (`djbclark-ade/AGENTS.md` order 10, 2026-10-25).
25. **Dispatch every slice with `acp-dispatch`**. Exit 3 = **no report** (re-task, never reconstruct; **quota stop: `acp-dispatch resume RECORD` after reset, never a fresh dispatch**), 4 = **`BLOCKED: <question>`**, 124 = timeout. It blocks: `--detach --no-wait`, then background its `rearm` waiter. **Agent-tool sub-agents:** paste `acp-dispatch footer --report <scratchpad>/<name>-report.md` (never `$(…)`) into the prompt; read that file, never the final message ([[reference_agent_rules_ops_housekeeping]]).
26. **Delegation route:** (1) **`acp-run <agent> -C <dir> -p '<prompt>' --model <m>` (always `--model`**; check its `applied:` line; exit 0 isn't success); (2) `paseo run`, (3) `model-routing` headless (Orca and herdr but its Paseo bridges retired 2026-10-31; GUI: `paseo-screen`). **Never an all-vendor fan-out: `route_agent.py plan` picks per slice; reserves (copilot, hermes, cline) and omp API credits (2026-10-19) follow item 32** ([[reference_agent_rules_code_discovery_and_cli_table]])
27. **`~/src/djbclark-ade` is the agent toolchain: use it before hand-rolling, fix it there** ([[reference_djbclark_ade]], [[reference_agent_rules_multi_agent_toolkit]]).
28. Session start in a git repo: read its Tier 1 pointer (`session-handoff`), check `head_sha`, state a resume plan first; only its owner writes it. **A teammate needs an `adversary` security verdict before opening a PR**, quoted (or "no findings") in its body.

## Quota, context, memory, slow commands

29. **`used_percent` is the share CONSUMED; 100 = exhausted.** Decide from `remaining_percent`; run **`aiuse --available --json 2>/dev/null`, read per `aiuse schema`** before each batch. **agy: only via `acp-run agy`, never `agy -p`** ([[reference_agent_rules_aiuse_quota_and_agy]]).
30. **Keep context small: separable tasks go to `/bigteam` by default, cheapest model × effort × context doing it well, unasked**; delegate when `context_size_nudge.py` says so. **Compaction is automatic, never a question; in Paseo compact yourself earlier**, once at a natural boundary, then end the turn: `djbclark-ade/bin/self-slash "/compact <focus>"`; topic change: `handoff` skill, then `/new` (`memory/feedback_self_compact.md`); **it refuses on input-line text: only then ask, never over a draft** (`memory/feedback_context_prompts_early.md`).
31. Basic Memory: one shared MCP server (`127.0.0.1:18796/mcp`); never a per-client stdio `basic-memory mcp`. **If down, fix it**, then `/mcp` reconnect. Default project: **`main`. A semantic search result is not a match**: use `find` or an exact `read_note` ([[reference_agent_rules_basic_memory_pools]]).
32. **Routing: minimise cost, maximise code quality, not tokens. Judgment is Opus `high`; codex `gpt-6-astra` and Fable `high` only via `frontier`; codex otherwise: ample quota and top router rank (2026-10-25); Fable `xhigh` almost never; claude codes on Sonnet 5.5, never Fable**; climb tiers on evidence. **`acp-dispatch` needs `--kind`; `frontier` advises, never edits; cheapest eligible tier first.** One copy: `skills/model-routing/SKILL.md` (`memory/feedback_routing_policy_cost_quality.md`).
33. **Over ~10-15 s: `run_in_background: true`**; wait on the notification, never poll (**Agent-tool sub-agents**: bounded foreground waits; `memory/feedback_start_slow_commands_in_background.md`). **Wait on a file or PID; never `pgrep -f`/`pkill -f` a pattern. Never read a result or exit status through a pipe, or feed `--body-file` from one. Never credit a hook you haven't seen run** (`memory/feedback_exit_status_through_pipe.md`).
34. **Builds and tests via `~/ops/site-private-djbclark/bin/bg` (full path), CI first** (`load-watch ci decide`). **Never set `BG_LOAD_WAIT=0` on a build; never `taskpolicy -b`; never throttle another session's processes. Gradle: one build at a time, machine-wide** (`memory/feedback_tests_through_bg_caps_and_slots.md`, `memory/feedback_gradle_one_at_a_time.md`). **Claim a dev-server port in `site-public-djbclark/registry/ports.yml` before binding; test browsers headless** (`memory/feedback_claim_ports_headless_browser.md`).

## Compact Instructions

Keep: task, status, files touched (absolute paths), djbclark's rulings this session, open items, exact next step,
handoff/report/scratchpad paths. Omit tool output, dead ends, committed facts.
