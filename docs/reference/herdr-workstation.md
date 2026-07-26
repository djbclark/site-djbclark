# Herdr workstation guide (site)

Operator reference for the multi-vendor Herdr setup on the site Mac
(Ghostty + Homebrew `herdr`). Config lives on the machine at
`~/.config/herdr/config.toml` (not in this repo). Shell helpers:
`h` / `herdr`, `hs` / `herdr status`, `hreload` / `herdr server reload-config`,
`hstop` / `herdr server stop`.

Canonical upstream docs: [herdr.dev/docs](https://herdr.dev/docs/).
Ecosystem index: [awesome-herdr](https://github.com/yigitkonur/awesome-herdr).

## Mental model

| Concept | Role |
| -------- | ---- |
| **Session** | Background server; `herdr` attaches. Detach with prefix+`q`. |
| **Workspace** | Project container; sidebar rolls up agent state per workspace. |
| **Tab** | Layout inside a workspace. |
| **Pane** | Real terminal (agents run here). |
| **Agent** | Detected process: `working`, `blocked`, `done`, `idle`, `unknown`. |

Never nest **tmux** inside a Herdr pane — detection will see `tmux`, not the
agent. Run agents as the pane’s foreground process.

## Prefix and keyboard

**Prefix is `ctrl+a`** (not tmux’s default `ctrl+b`).

1. Press `ctrl+a`, release.
2. Press the action key.

| Action | Keys |
| ------ | ---- |
| Help (live bindings) | `ctrl+a` then `?` |
| Settings | `ctrl+a` then `s` |
| Detach (leave server running) | `ctrl+a` then `q` |
| Reload config | `ctrl+a` then `Shift+r`, or shell `hreload` |
| New tab | `ctrl+a` then `c`, or **`ctrl+alt+c`** |
| Next / previous tab | `ctrl+a` `n` / `p`, or **`ctrl+alt+]`** / **`ctrl+alt+[`** |
| Split right / down | `ctrl+a` `v` / `-`, or **`ctrl+alt+d`** / **`ctrl+alt+Shift+d`** |
| Focus pane h/j/k/l | `ctrl+a` h/j/k/l, or **`ctrl+alt+`h/j/k/l** |
| Zoom pane | `ctrl+a` `z`, or **`ctrl+alt+z`** |
| Workspace picker | `ctrl+a` then `w` |
| New workspace | `ctrl+a` then `Shift+n` |
| New git worktree workspace | `ctrl+a` then `Shift+g` |
| Toggle sidebar | `ctrl+a` then `b` |
| **Previous / next agent** (attention queue) | `ctrl+a` then `[` / `]` |
| **Focus agent 1–9** | `ctrl+a` then `alt+1`…`alt+9` |

Send a literal `ctrl+a` into a pane (readline beginning-of-line, etc.): press
**`ctrl+a` twice**.

`ctrl+alt+…` chords are dual-bound so they work without the prefix (safe
across Ghostty/macOS). If a chord does nothing, Ghostty or macOS may own it —
free it in terminal/OS settings or rebind in Herdr.

## Mouse (Ghostty)

`mouse_capture = true`. Outer Ghostty should keep `mouse-reporting = true`
(default).

| Gesture | Effect |
| ------- | ------ |
| Click pane / tab / sidebar agent | Focus |
| Drag split border | Resize |
| Right-click | Context menus |
| Drag-select | Copy (clipboard toast enabled) |
| Shift+drag | Usually terminal selection (Shift reserved by hosts) |

## Agent launchers (prefix + alt)

Opens a temporary pane with the agent CLI. Prefer a normal shell pane + typing
the command for long-lived sessions, or
`herdr agent start <name> -- <cmd>` for labeled persistent agents.

| Keys after `ctrl+a` | Command |
| ------------------- | ------- |
| `alt+g` | `grok` |
| `alt+a` | `agy` (gemini / antigravity alias) |
| `alt+c` | `claude` |
| `alt+x` | `codex` |
| `alt+u` | `cursor-agent` |
| `alt+o` | `opencode` |
| `alt+e` | `hermes` |
| `alt+y` | `copilot` |

## Sidebar and attention queue

- **`agent_panel_sort = "priority"`** — blocked / needs-attention agents rise
  across all workspaces (not grouped only by space).
- Rows show: state icon + agent + state text, then stripped terminal title,
  then workspace · tab. Per-agent overrides match the common vendors.
- Pane borders show agent labels when set
  (`show_agent_labels_on_pane_borders = true`).

Use `ctrl+a` `[` / `]` to jump the queue; click an agent row to focus its pane.

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

| Setting | Behavior |
| ------- | -------- |
| `resume_agents_on_restore = true` | After **server** restart, re-launch supported agents with their native session IDs (needs current integrations). |
| `pane_history = true` | Replays recent screen contents for panes that cannot resume. Stored under `~/.config/herdr/session-history.json` — treat like shell history (secrets possible). |

**Detach** (`ctrl+a` `q`) keeps processes alive; that is stronger than restore.

Integrations installed on this machine (hooks/plugins): pi, claude, codex,
copilot, cursor, opencode, hermes. Grok and agy use screen manifests (no
lifecycle integration). Check with `herdr integration status`.

## Shell aliases and PATH helpers

| Command | Effect |
| ------- | ------ |
| `h` / `herdr` | Attach |
| `hs` | `herdr status` |
| `hreload` | `herdr server reload-config` (also `~/.local/bin/hreload`) |
| `hstop` | `herdr server stop` |

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
4. Watch sidebar priority queue; jump with `ctrl+a` `[` / `]` or mouse.
5. Detach with `ctrl+a` `q`; reattach later with `h`.
6. Full stop only when intended: `hstop`.
