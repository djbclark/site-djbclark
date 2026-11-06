---
name: teach
description: >-
  Walk djbclark through today's one or two Claude Code things to install or
  start using (mods, skills, built-ins, already-installed plugins) from the
  rollout checklist, one item at a time: a few paragraphs about the item, then
  its own AskUserQuestion picklist, doing each item before the next and
  ticking it off. Use for /teach, "/teach N" for a
  specific day, "/teach list", "what's today's mod", "teach me the next one",
  and when the 04:14 Hermes "run /teach" ping arrives.
---

# teach — today's install-or-use items, one prompt at a time

Canonical copy: `~/src/djbclark-ade/skills/teach/` (git: `~/src/djbclark-ade`,
github.com/djbclark/djbclark-ade); linked everywhere by `skill-everywhere teach`.
Claude Code slash command: `~/.claude/commands/teach.md` → `claude/commands/teach.md` here.

Checklist: `~/ops/site-private/memory/project_claude_code_mods_rollout.md`
(djbclark, 2026-10-17: "install and introduce me to one or two each day", widened
the same day to skills, built-ins and plugins already installed but unused). The
04:14 launchd job `com.djbclark.mods-reminder` runs `scripts/next_item.py --ping`:
the day `/teach` will give plus the last completed day's names, via Hermes.

**Pacing (djbclark, 2026-10-17):** one day number per calendar day, advanced only by
running `/teach`. A day ticked today comes back again on a second run the same day;
missed calendar days never skip a number (four idle days, then the next day number).
`next_item.py` applies this; never pick the day yourself from the checklist.

djbclark is choosing and learning, not reading a report. Same pacing as the `steps`
skill: **one AskUserQuestion per call**, recommended option first, act on the
answer before asking the next. Never dump the whole day as prose options. One
item at a time: a few paragraphs about that item, then its picklist (step 3).

## Procedure

1. **Find the day.** `python3 scripts/next_item.py` prints JSON: `mode` (`new` =
   first unticked day, `repeat` = a day already ticked today, `done`), `day`,
   `install`, `use`, `names`, `also` (other days ticked today), and `last` (the
   most recent day completed before today: `days`, `date`, `names`). `--day N`
   picks one; `--list` shows all. `/teach list` → print the table of days with
   ticks and stop.
2. **Recap first, names only.** If `last` is set, open with one line:
   "Last time (Day 1+1b, 2026-10-17): agent-radar, /radar, …". No descriptions;
   djbclark asks if one needs explaining.
   **`mode: repeat`**: say Day N (plus `also`) was already done today and the next
   day number comes on the next calendar day's run. One AskUserQuestion:
   `Revisit one of today's items (Recommended)` / `Show today's names again` /
   `Done for today`. Revisiting re-demos or re-explains; it never re-ticks.
   `/teach N` still opens any named day on request.
3. **`mode: new`: present the day's items one at a time** (djbclark, 2026-10-28; the
   combined "do both now" question is gone). Name the day and its items in one line,
   then take the install item, then the use item, each through the **item
   introduction** below. Each item gets its own picklist; skipping one never skips
   the other. If djbclark answers a picklist with a question, answer it from the
   README or source (not from memory), then ask the same picklist again. A day
   where every item was skipped ticks nothing; ask once whether to show the next
   day's items instead.

   **Item introduction (before every item's first AskUserQuestion):** write a few
   short paragraphs (three or four, no bullets), not a summary line:
   (a) what it is and what it does, concretely;
   (b) how it behaves in this setup: which sessions, tools or agents it covers and
   which it cannot see (most delegation here goes through `acp-dispatch`, not
   Agent-tool subagents), what it costs (context, a hook timeout, a refresh
   poll), and how it overlaps or conflicts with what is already installed;
   (c) the command or keystroke that starts it and where it draws.
   Read the README and, for an install, the hook source first; never state scope,
   limits or a command name from the checklist alone. Run or `rg` the docs for a
   slash command before naming it (2026-10-28: the checklist said `/fullscreen`,
   the command is `/tui fullscreen`, and fullscreen was already the default); fix
   a wrong checklist entry when ticking the day. Then one picklist, recommended
   option first, whose options are the four or three listed in step 4b or 5.
4. **Install item** (a mod or plugin), in this order, each step narrated in one
   line (do 4a before writing the introduction, so it reports what the code does):
   a. `gh repo view` the source (stars, last push); `claude plugin marketplace add`
      if the marketplace is new; `find` the plugin's files; `rg` its hooks for
      `child_process|execSync|spawn\(|fetch\(|writeFile|process\.env` and read
      anything that hits; `claude plugin validate <dir>`. Mods run unsandboxed as
      djbclark: a hit that is not obviously benign is a question, not a shrug.
   b. The introduction (above), then one AskUserQuestion: `Install (Recommended)` /
      `Skip this one` / `Show me the hook source first` (add `Install with <option>
      changed` when the mod has a setting that matters, e.g. a timeout).
   c. `claude plugin install <name>@<marketplace>`; then
      `~/src/djbclark-ade/bin/self-slash "/reload-plugins"` (fires when the
      session goes idle, so say that) and name the slash command and where
      the mod draws (band above the prompt, side pane, status line). Panes dock
      on their own only at ≥110–144 columns; name the command that opens one.
   d. If it can be demonstrated cheaply, do it: a Haiku `Explore` subagent for
      anything that watches subagents; a two-line edit for an edit watcher.
5. **Use item** (something already present): the introduction (above; cost is the
   context bar before/after for a plugin, nothing for a built-in), after checking
   whether it is already on (`/tui fullscreen` answered "Already using the
   fullscreen renderer"). Then one AskUserQuestion:
   `Try it now (Recommended)` / `Keep it, no demo` / `Disable or uninstall it` /
   `Later`. A plugin that was disabled for context cost (mattpocock-skills, adhd)
   is enabled only for the trial: `claude plugin enable`, `/reload-plugins`,
   measure, and the closing question offers `Disable again`.
6. **Close the day:** one AskUserQuestion per installed thing: `Keeper, add to
   apply-toolchain-prompt.md (Recommended)` / `Keep but don't document` / `Uninstall`.
   Keepers get a row in `~/src/djbclark-ade/docs/apply-toolchain-prompt.md` §0.6
   "Claude Code mods" table (one line, what it gives the user, install note).
7. **Tick and commit.** Change `- [ ] **Day N**` to `- [x] **Day N, YYYY-MM-DD**`
   (today's date; the repeat and recap logic reads it)
   and append one short "result:" clause (kept / uninstalled / disabled again).
   `git -C ~/ops/site-private add memory/project_claude_code_mods_rollout.md &&
   git commit && git push`; same for djbclark-ade if the prompt doc changed.
   Then `~/.local/bin/hermes-ping "teach: Day N done — <one line>"`.

## Rules carried over

- Pinned installs, never `npx ... @latest` in a status-line or hook command;
  pick a release at least two weeks old.
- Two marketplaces both named `claude-code-mods` (hamzafer's is registered;
  Ray Amjad's `ray-amjad/awesome-claude-code-function-hooks` clashes): add Ray's
  by git URL or copy the one plugin into the local marketplace
  (`~/ops/site-djbclark/claude/local-marketplace`), never replace hamzafer's.
- `aiuse watch --all-providers`, omp, and anything that spends credits stay out
  of demos ([[feedback_never_use_credits_without_asking]]).
- All days ticked: say so, offer `/plugin discover` for a fresh batch, and
  mention that the 04:14 job boots itself out on the next run.
