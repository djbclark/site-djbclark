# Herdr workstation guide (site)

Operator reference for the multi-vendor Herdr setup on the site Mac
(Ghostty + Homebrew `herdr`). Config lives on the machine at
`~/.config/herdr/config.toml` (not in this repo). Shell helpers:
`h` / `herdr`, `hs` / `herdr status`, `hreload` / `herdr server reload-config`,
`hstop` / `herdr server stop`.

Canonical upstream docs: [herdr.dev/docs](https://herdr.dev/docs/).
Ecosystem index: [awesome-herdr](https://github.com/yigitkonur/awesome-herdr).

## Mental model

| Concept       | Role                                                               |
| ------------- | ------------------------------------------------------------------ |
| **Session**   | Background server; `herdr` attaches. Detach with prefix+`q`.       |
| **Workspace** | Project container; sidebar rolls up agent state per workspace.     |
| **Tab**       | Layout inside a workspace.                                         |
| **Pane**      | Real terminal (agents run here).                                   |
| **Agent**     | Detected process: `working`, `blocked`, `done`, `idle`, `unknown`. |

Never nest **tmux** inside a Herdr pane — detection will see `tmux`, not the
agent. Run agents as the pane’s foreground process.

## Prefix and keyboard

**Prefix is `ctrl+a`** (not tmux’s default `ctrl+b`).

1. Press `ctrl+a`, release.
2. Press the action key.

| Action                                      | Keys                                           |
| ------------------------------------------- | ---------------------------------------------- |
| Help (live bindings)                        | `ctrl+a` then `?`                              |
| Settings                                    | `ctrl+a` then `s`                              |
| Detach (leave server running)               | `ctrl+a` then `q`                              |
| Reload config                               | `ctrl+a` then `Shift+r`, or `hreload`          |
| New tab                                     | `ctrl+a` then `c`                              |
| Next / previous tab                         | `ctrl+a` then `n` / `p`                        |
| Split right / down                          | `ctrl+a` then `v` / `-`                        |
| Focus pane h/j/k/l                          | `ctrl+a` then h/j/k/l                          |
| Last focused pane                           | `ctrl+a` then `;`                              |
| Zoom pane                                   | `ctrl+a` then `z`                              |
| Workspace picker                            | `ctrl+a` then `w`                              |
| New workspace                               | `ctrl+a` then `Shift+n`                        |
| Previous / next workspace                   | `ctrl+a` then `Shift+Left` / `Shift+Right`     |
| Focus workspace 1–9                         | `ctrl+a` then `Shift+1`…`Shift+9`              |
| New / open / remove git worktree            | `ctrl+a`, then `Shift+g` / `Shift+o` / `alt+d` |
| Toggle sidebar                              | `ctrl+a` then `b`                              |
| **Previous / next agent** (attention queue) | `ctrl+a` then `Shift+a` / `a`                  |
| **Focus agent 1–9**                         | `ctrl+a` then `alt+1`…`alt+9`                  |

Send a literal `ctrl+a` into a pane (readline beginning-of-line, etc.): press
**`ctrl+a` twice**.

All assigned built-in actions use Herdr 0.7.5 defaults. Only the `ctrl+a`
prefix and actions that Herdr leaves unset by default are customized. The
optional choices above follow the most common patterns found in a sample of
public Herdr configurations while avoiding default and launcher conflicts.

## Mouse (Ghostty)

`mouse_capture = true`. Outer Ghostty should keep `mouse-reporting = true`
(default).

| Gesture                          | Effect                                               |
| -------------------------------- | ---------------------------------------------------- |
| Click pane / tab / sidebar agent | Focus                                                |
| Drag split border                | Resize                                               |
| Right-click                      | Context menus                                        |
| Drag-select                      | Copy (clipboard toast enabled)                       |
| Shift+drag                       | Usually terminal selection (Shift reserved by hosts) |

## Agent launchers (prefix + alt)

Opens a temporary pane with the agent CLI. Prefer a normal shell pane + typing
the command for long-lived sessions, or
`herdr agent start <name> -- <cmd>` for labeled persistent agents.

| Keys after `ctrl+a` | Command                                                     |
| ------------------- | ----------------------------------------------------------- |
| `alt+g`             | `grok`                                                      |
| `alt+a`             | `agy` (gemini / antigravity alias)                          |
| `alt+c`             | `claude`                                                    |
| `alt+x`             | `codex`                                                     |
| `alt+u`             | `cursor-agent`                                              |
| `alt+o`             | `opencode`                                                  |
| `alt+e`             | `hermes`                                                    |
| `alt+y`             | `copilot`                                                   |
| `alt+s`             | `herdr-goose` (Goose, sidebar/border reporting — see below) |
| `alt+i`             | `herdr-aider` (Aider, sidebar/border reporting — see below) |

`config.toml` is machine-local (not in this repo); add these two blocks by
hand next to the existing launchers, then `hreload`:

```toml
[[keys.command]]
key = "prefix+alt+s"
type = "pane"
command = "herdr-goose"
description = "start Goose with Herdr agent-state reporting"

[[keys.command]]
key = "prefix+alt+i"
type = "pane"
command = "herdr-aider"
description = "start Aider with Herdr agent-state reporting"
```

## Pane-moving plugins

Two installed plugins preserve live processes while reorganizing the layout:

| Keys after `ctrl+a` | Action                                                  |
| ------------------- | ------------------------------------------------------- |
| `Shift+c`           | Break a pane into a new tab in the current workspace    |
| `Shift+m`           | Move a complete tab to another or new workspace (drovr) |
| `m`                 | Move a pane to a tab or new workspace (drovr)           |

These are standard `[[keys.command]]` entries with `type = "plugin_action"`
and a `description`. Herdr 0.7.5 automatically renders such entries in the
**custom** group of the live `ctrl+a` then `?` help screen; no Herdr patch or
upstream PR is needed.

## Sidebar and attention queue

- **`agent_panel_sort = "priority"`** — blocked / needs-attention agents rise
  across all workspaces (not grouped only by space).
- Rows show: state icon + agent + state text, then stripped terminal title,
  then workspace · tab. Per-agent overrides match the common vendors.
- Pane borders show agent labels when set
  (`show_agent_labels_on_pane_borders = true`).

Use `ctrl+a` `Shift+a` / `a` to jump the queue; click an agent row to focus
its pane.

## Notifications and sound

- Toasts: **macOS system notifications** (`delivery = "system"`), 1s delay.
- Sounds: **on** for background agent state changes (done / needs input).
- Active tab is suppressed so you are not spammed for what you already see.

## Worktrees (parallel agents on one repo)

```toml
[worktrees]
directory = "~/.herdr/worktrees"
```

Checkouts land under `~/.herdr/worktrees/<repo>/<branch-slug>/`.

From the sidebar (or `ctrl+a` `Shift+g`): create a worktree, open it as a
Herdr workspace, run a different vendor agent per tree so they do not fight
over the same working copy. Delete worktree checkout is explicit in the UI
(does not delete the git branch by default).

## Updates and detection quality

```toml
[update]
version_check = true
manifest_check = true
```

- **version_check** — notices new Herdr releases (this install is Homebrew;
  upgrade with `brew upgrade herdr`, not `herdr update`).
- **manifest_check** — pulls remote **screen-detection** rules so Claude,
  Codex, Cursor, Grok, agy, etc. keep accurate `working` / `blocked` labels.

Force a manifest refresh:

```bash
herdr server update-agent-manifests
```

## Session restore and history

| Setting                           | Behavior                                                                                                                                                        |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `resume_agents_on_restore = true` | After **server** restart, re-launch supported agents with their native session IDs (needs current integrations).                                                |
| `pane_history = true`             | Replays recent screen contents for panes that cannot resume. Stored under `~/.config/herdr/session-history.json` — treat like shell history (secrets possible). |

**Detach** (`ctrl+a` `q`) keeps processes alive; that is stronger than restore.

Integrations installed on this machine (hooks/plugins): pi, claude, codex,
copilot, cursor, opencode, hermes. Grok and agy use screen manifests (no
lifecycle integration). Check with `herdr integration status`. **Goose and
Aider are neither** — see the next section.

## Goose and Aider (site-side prototype, site-djbclark#12)

Herdr 0.7.5 has no built-in agent "kind" for `goose` or `aider`
(`herdr agent start --kind` does not list either), and no remote manifest
exists for them. A local `~/.config/herdr/agent-detection/<agent>.toml`
override can only re-tune screen-detection _rules_ for an agent Herdr already
recognizes by process name — it cannot invent a new agent id. Upstream
contribution is the correct long-term fix (file/track on
[herdr.dev](https://herdr.dev/docs/agents/)); until then this repo ships a
site-side prototype per the issue's own suggested path.

### Mechanism

`bin/herdr_agent_wrapper.py` (+ thin shims `bin/herdr-goose`, `bin/herdr-aider`)
wraps the real binary and self-reports pane lifecycle over the documented
`herdr pane report-agent` / `release-agent` socket API — the same API the
official `claude`/`codex`/`cursor`/… hook scripts use
(`~/.claude/hooks/herdr-agent-state.sh` etc.), just invoked from a standalone
wrapper instead of a per-tool hook. The real `goose`/`aider` binaries on
`PATH` are untouched; only the `herdr-goose`/`herdr-aider` launcher names go
through the wrapper.

State classification (`working` / `idle` / `blocked`) is a generic
content-quiescence poll (every 2s by default, `HERDR_AGENT_POLL_INTERVAL`):
pane output changing → `working`; unchanged for two consecutive polls →
`idle`; a confirm/permission-prompt pattern (best-effort regexes tuned
against real prompts observed live from both tools, see
`bin/herdr_agent_wrapper.py`) → `blocked`. This is coarser than Herdr's own
per-agent manifest rules (`~/.local/state/herdr/agent-detection/remote/*.toml`)
but needs no agent-specific screen regions to hit the issue's "at least
working vs idle" bar.

Aider additionally has a real upstream hook Goose lacks —
`--notifications-command` fires when Aider is ready for input — so
`herdr-aider` layers that on top (`--notify-idle` mode of the same wrapper
script) for a more precise idle transition, unless the invocation already
passes its own `--notifications-command` / `--no-notifications`.

### Install

```bash
just herdr-agents-install   # symlinks into ~/.local/bin; re-run after each release
```

Then add the `[[keys.command]]` blocks above to `~/.config/herdr/config.toml`
and `hreload`. Run `just herdr-agents-install` from the **released**
`~/ops/site-djbclark` checkout, not a task worktree — the symlinks it creates
are absolute and must not point at a worktree that gets deleted later (the
same landmine class site-djbclark#100 fixed for generated fragments).

### Empirical gotchas (confirmed live, 2026-07-29 — don't re-derive)

- **`herdr pane report-agent`/`release-agent` need `<PANE_ID>` as the first
  argument**, before any `--flags`. Passing it last, as the `--help` usage
  line shows, fails with `unknown option: <value>` on herdr 0.7.5.
- **`release-agent` needs an explicit, fresh `--seq`.** Without one, a
  release that lands after a report-agent call carrying a `--seq` (the
  wrapper's poller always sets one) is silently ignored — last-write-by-seq
  wins — leaving a stale sidebar label on a pane whose agent already exited.
  Both wrapper calls always pass `--seq $(time.time_ns())`.
- **A reported `--state idle` displays as `agent_status: "done"`** in
  `herdr agent list`/the sidebar, not `"idle"` — Herdr's own display-state
  mapping, not a wrapper bug.
- **Aider's real OS process name is `Python`**, not `aider` — its Homebrew
  install runs under a framework Python whose `argv0` gets rewritten for the
  macOS Dock, confirmed via `herdr pane process-info`. Any future
  process-name-based detection (upstream or local override) cannot key off
  the process name for Aider; it would need to match `cmdline` containing
  `aider`, or Aider would need its own hook. Goose's process name (`goose`)
  is clean by contrast.

### Not done (honest scope call, not silently dropped)

**Session resume (issue goal #4) is not implemented.**
`resume_agents_on_restore` re-launches agents through Herdr's own
integration/kind system on server restart — it has no hook into a
report-agent-only pane, so nothing here can wire it without the same
upstream "kind" support layer #12 identifies as the real gap for detection
in general. Goose's `session --resume --session-id` and Aider's
`--restore-chat-history` both exist and could back a resume flow once that
upstream layer exists; wiring them now would be a facade with no actual
restart-survives-it behavior. The issue's own text already calls Aider
restore "likely out of scope v1"; the same call now extends to Goose for the
same underlying reason.

## Shell aliases and PATH helpers

| Command       | Effect                                                     |
| ------------- | ---------------------------------------------------------- |
| `h` / `herdr` | Attach                                                     |
| `hs`          | `herdr status`                                             |
| `hreload`     | `herdr server reload-config` (also `~/.local/bin/hreload`) |
| `hstop`       | `herdr server stop`                                        |

After editing `config.toml`, run `hreload` (or prefix reload). Most UI
settings apply without recreating panes; keybindings apply on reload.

## Official agent skill

Global skill **herdr** is installed via the skills CLI
(`~/.agents/skills/herdr`, linked into Claude Code / Codex / Cursor / Grok).
Agents inside Herdr (`HERDR_ENV=1`) can list panes, spawn helpers, send keys,
and wait on status when you ask them to use Herdr. Do not expect them to
drive Herdr unless you invoke that skill / ask explicitly.

## Debugging wrong agent state

```bash
herdr agent list
herdr agent explain <target> --json
herdr pane read <id> --source recent --lines 50
```

Logs: `~/.config/herdr/herdr.log`, `herdr-client.log`, `herdr-server.log`.

Sandboxed wrappers that hide the real binary: set on the **host-visible**
command, e.g. `HERDR_AGENT=claude nono run -- …`.

## Intentionally left alone

These stay as preference / already-good defaults (not part of the multi-vendor
hardening pass):

- Theme (`catppuccin`)
- Toast/sound delivery already on
- `resume_agents_on_restore` already on
- Integrations for agents **not** installed on PATH
- `reveal_hidden_cursor_for_cjk_ime` / `redraw_on_focus_gained` left off after
  earlier Ghostty freeze investigation — re-enable only if freezes stay gone

## Quick daily loop

1. Open Ghostty → `h`.
2. One **workspace** per project (or worktree per parallel agent).
3. Launch agents (launcher keys or type in pane).
4. Watch sidebar priority queue; jump with `ctrl+a` `Shift+a` / `a` or mouse.
5. Detach with `ctrl+a` `q`; reattach later with `h`.
6. Full stop only when intended: `hstop`.
