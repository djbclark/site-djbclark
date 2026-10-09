# Orca vs herdr after ACP — does Orca still earn its place?

2026-10-08. Question: `djbclark-ade` now drives agents over the Agent Client
Protocol (`acp-run`) inside herdr panes. The move to Orca was made because herdr
had trouble with subagents, and ACP has fixed that. Apart from (arguably) the
UI, does Orca still have advantages over herdr, or can it go?

**Verdict: nothing in the repo's code needs Orca any more, and the operational
reason for adopting it is gone.** What Orca still has over herdr plus ACP is a
short list, mostly UI or features never exercised here. Dropping it is
defensible. The one item that is not "arguably UI" is the worktree registry
plus agent roster, which is where the fleet actually lives today, and it needs
a replacement before Orca is removed.

## Method

- Read `docs/orca-integration.md`, `docs/queue.md`, `docs/agent-sleep.md` and
  the 2026-10-08 handoff in `djbclark-ade`.
- Live probes: `orca status --json` (1.4.219), `orca worktree ps`, `orca repo
  list`, `herdr status` (0.9.1 preview, 2026-09-21), `herdr --help` and the
  `worktree`, `agent`, `machine`, `integration` subcommands, `herdr api
  snapshot`.
- A read-only sweep of every Orca reference in `djbclark-ade` code
  (`skills/session-finder/{fleet,where,launch}.py`, `skills/helm/helm.py`,
  `bin/cow-pasture`, `bin/route_agent.py`, `bin/orca-reorg-watch`,
  `bin/herdr-sleeper`, `tools/acp-run`, `skills/bigteam`, tests), asking for
  each: what does it use Orca for, and does a herdr/ACP path already exist
  beside it?

## Live state at the time of writing

| Host | What it held |
|---|---|
| Orca | 6 agents (4 claude, 2 grok) across 27 worktrees in 13 registered repos. All four running Claude Code sessions, including the one writing this, sat in Orca worktrees under `~/orca/workspaces`. |
| herdr | Default session: 2 panes, 0 agents. Earlier the same day helm ran in a herdr pane, so herdr may have been restarted since. |

The day-to-day fleet is in Orca, not herdr. That is the migration cost, not an
argument for Orca.

## 1. What Orca still has that herdr + ACP do not

1.1. **Task DAG orchestration.** Runs, tasks with `--deps`, decision gates,
supervised workers (stop/abandon/release/retain, `--retry-of`), a cross-agent
mailbox (`ask`/`reply`/inbox), federation to other machines (`--on
<environment>`). herdr has no equivalent. But no code in the repo calls it; the
last live run was 2026-08-23. `bigteam` dispatches through `acp-run` and
coordinates with CLAIM files and a herdr `coord` tab. The integration doc
records the sharp edges: `agent_prompt_stalled` false deaths on cold CLI boot,
`task-create` returning a UUID that `worker-start` rejects, no Claude
folder-trust preset, cow pastures not resolving as worktrees (stablyai/orca
#16226, #20560).

1.2. **Worktree registry and agent roster.** Orca owns the worktrees (27) and
repos (13), and preconfigures ~25 agents with launch flags and trust presets,
plus Claude/Codex account switchers (`orca account`). herdr has `herdr worktree
create/list/open/remove` but no registry or roster. `acp-run` has its own
agent table of 11. Orca's enabled roster names 28, but the difference is
smaller than it looks (corrected 2026-10-08, see 5.1): most of the extra names
are Orca's stock TUI list and are not installed here, three are aliases of
agents `acp-run` already has, and the installed extras (aider, muse, zcode,
and crush, since uninstalled 2026-10-08) have no ACP mode, so `acp-run` could
not drive them anyway.
`bin/route_agent.py` builds its discovery list from Orca's `orca-data.json`.

1.3. **Hibernation.** Orca sleeps idle agents of every TUI (codex, gemini,
antigravity, pi, droid, grok, devin, …), sleeps a worktree's panes as a unit,
and checks for live subagents and in-flight dispatches first. `herdr-sleeper`
gives herdr panes the same policy but only for claude and opencode.

1.4. **Remote, mobile, integrations.** Mobile app with push notifications
(`serve --mobile-pairing`), remote workers by pairing code, scheduled
`automations`, built-in browser and iOS emulator tools, Linear/Jira/GitHub
work-item context on worktrees, cross-TUI session search (`orca search`, ~1,600
session files with a `resumeCommand` per hit). herdr has `--remote <ssh>` and
`machine`, nothing else on this list. None of it is used by repo code.

1.5. **Structured agent view.** Orca reads the agent transcript (status feed,
question answers, conversation outline, rewind). herdr is terminal-only.
`helm.py` already reads transcripts itself, so for the fleet tooling this is
UI, not a dependency.

## 2. What goes away with Orca

2.1. **A second host in every fleet tool.** `fleet.py` handle resolution (Orca
reissues terminal handles on runtime restart; 17 tests exist for it), helm's
Orca channel ("written but not yet exercised"), `launch.py --host orca`,
`cow-pasture --orca` (`orca repo add` so `worker-start --worktree path:`
resolves), `orca-reorg-watch`, the `reorg-orca` skill, `orca_upstream_watch.py`
in site-djbclark. The orca-tidy slice (djbclark-ade issue #1, a `--host` mode
for `herdr-tidy`) becomes unnecessary.

2.2. **Known hazards.** Closing a terminal skips Claude Code SessionEnd hooks
(#23865); closing an agent terminal can kill a shared Codex managed daemon
(#23833); app-bundle rewrites flood FSEvents (#23302); `terminal wait --for
tui-idle` can report satisfied while the agent runs (#14561); the global
`orca-status` hook breaks agy tool calls (`acp-run` carries a shadow
`GEMINI_HOME` workaround); the intentional open listener on TCP 6768.

## 3. Reasons not to, or not yet

3.1. **1.2 needs a replacement first.** A worktree home (`herdr worktree` or
plain git; the 27 worktrees are ordinary git worktrees, so git does not care
who created them) and an agent roster (extend `acp-run`'s table, point
`route_agent.py` at it).

3.2. **Sleep for non-claude/opencode agents.** `herdr-sleeper` has to grow, or
the RAM cost is accepted.

3.3. **Cross-machine DAG and mobile app have no herdr path.** With zero use
since August, "rebuild if the need appears" is the sensible stance.

## 4. Operator decisions

4.1. Proceed with, or park, the orca-tidy slice in the sibling worktree
(`herdr-tidy-orca-host-mode-orca-tidy`).

4.2. Is 1.4 (mobile monitoring, Linear/Jira context) actually used? If yes,
Orca stays as a GUI to look at while herdr and ACP do the work, which is what
the repo already is today.

## 5. Migration, if the answer is go

1. Give `route_agent.py` a discovery source that does not depend on Orca:
   `acp-run`'s table plus the non-ACP headless recipes in the `model-routing`
   skill (muse, zcode). There is no set of ACP-capable agents to "add"
   to `acp-run`: of Orca's 28 enabled roster names, only 3 extra are installed
   (4 before crush was uninstalled 2026-10-08) and none of them speak ACP. Worth doing even if Orca stays, so routing lists
   what can actually be dispatched rather than what Orca knows about.
2. Move or symlink the `~/orca/projects` and `~/orca/workspaces` checkouts.
3. Retire the Orca branches in `fleet.py`, `where.py`, `launch.py`, `helm.py`,
   `cow-pasture`; delete `orca-reorg-watch` and the `reorg-orca` skill; stop
   `orca_upstream_watch.py`.
4. Close djbclark-ade issue #1 as won't-do.
5. Rewrite the "two altitudes" framing in `djbclark-ade` README and AGENTS.md,
   and `docs/orca-integration.md`, `docs/agent-sleep.md`, `docs/model-routing.md`
   ("Orca is the fleet registry"), `docs/coding-factory.md`.

## Sources

- `~/src/djbclark-ade`: `docs/orca-integration.md`, `docs/queue.md`,
  `docs/agent-sleep.md`, `docs/upstream-issues.md`,
  `docs/handoffs/HANDOFF_standalone-5a60_helm-relay-sleeper-herdr-ai_2026-10-08_dccb.md`.
- orca-tidy feasibility report (Sonnet sub-agent, 2026-10-08), local state only.
- Orca fork: github.com/djbclark/orca (upstream stablyai/orca). herdr: herdr.dev.
