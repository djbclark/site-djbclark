# Handoff — 2026-07-26 Herdr workstation + ops 1.0.2

**For the next agent:** read this fully before continuing. Site deploy is
`~/ops` at **ops-v1.0.2**. Code only in `~/src/ops-worktrees/` (never edit
`~/ops` for development).

## Outcome of this session

### Shipped / live

| Item | State |
|------|--------|
| Coordinated suite | **ops-v1.0.2** tagged, released, deployed on all three `~/ops` checkouts |
| Herdr brew service | `homebrew.mxcl.herdr` **running** (`herdr server`, KeepAlive/RunAtLoad) |
| On-box Herdr config | `~/.config/herdr/config.toml` multi-vendor baseline (not in git) |
| OliveTin | Live config has **5** `user_herdr_*` actions; source `olivetin/user-actions.yaml` in site-djbclark |
| Release serialization | `bin/ops_release_lock.py` + flock in `deploy_ops_release.py` (merged via PR #10, in 1.0.1/1.0.2) |
| Open GitHub PRs (three repos) | **none** |
| Ops release claim | **none** (clear after 1.0.2) |

### Merged site-djbclark PRs (this workstream)

| PR | Title |
|----|--------|
| [#10](https://github.com/djbclark/site-djbclark/pull/10) | release: serialize multi-agent ops cut/deploy (lock + claim) |
| [#7](https://github.com/djbclark/site-djbclark/pull/7) | docs: Herdr multi-vendor workstation reference |
| [#8](https://github.com/djbclark/site-djbclark/pull/8) | ops: herdr brew service, registry, OliveTin dashboard |
| [#11](https://github.com/djbclark/site-djbclark/pull/11) | release: advance ops suite to 1.0.2 |

(1.0.1 Codex/local-config suite was a **parallel** agent: site #9, site-private #6, stayturgid #70 — completed and deployed before 1.0.2.)

### Docs in repo (ops-v1.0.2)

- [`docs/reference/herdr-workstation.md`](../../reference/herdr-workstation.md) — keys, mouse, launchers, sidebar, manifests
- [`docs/reference/herdr-brew-service.md`](../../reference/herdr-brew-service.md) — brew service, registry UDS note, OliveTin
- [`docs/OPS-RELEASES.md`](../../OPS-RELEASES.md) — claim + flock workflow
- Registry: `paths.yml` (`~/.config/herdr/**`, `homebrew.mxcl.herdr`); `ports.yml` UDS-only note for herdr

### On-box Herdr config highlights (`~/.config/herdr/config.toml`)

- `prefix = "ctrl+a"` (double `ctrl+a` for literal beginning-of-line)
- `mouse_capture = true`
- `manifest_check = true`, `version_check = true`
- `agent_panel_sort = "priority"`
- Rich sidebar rows + `rows_by_agent` for common vendors
- Launchers: grok, agy, claude, codex, cursor-agent, opencode, hermes, copilot
- Agent jump: `prefix+[` / `]`, `prefix+alt+1..9`
- Dual `ctrl+alt` pane/tab chords
- `[worktrees] directory = "~/.herdr/worktrees"`
- Still **off** (freeze investigation): `reveal_hidden_cursor_for_cjk_ime`, `redraw_on_focus_gained`

Shell: `h` / `hs` / `hreload` / `hstop` in `~/.bashrc`; `~/.local/bin/hreload` on PATH.

## Open issue (next work)

**[site-djbclark#12](https://github.com/djbclark/site-djbclark/issues/12)** — *Herdr: first-class detection for Goose, Aider, and local-LLM backends*

Research snapshot (full detail + localllm addendum in the issue):

- **goose 1.44.0**, **aider 0.86.2** on PATH; site Goose via `roles/goose` + LiteLLM
- **No** Herdr official integration / remote manifests for goose or aider
- Local `agent-detection/<agent>.toml` cannot invent new agent ids without upstream process detection
- Aider: screen-manifest first; resume likely out of scope v1
- Goose: session resume may be feasible; lifecycle hooks need research
- **Local LLM (“localllm”):** no `localllm` binary — site stack is **omlx** (running :8000), **Ollama** (:11434), **LM Studio** app, **LiteLLM** (:4000). These are inference/providers, not Herdr agents; document + optional interactive clients. Do not confuse with WordPress **Local.app**.
- Upstream Herdr contribution preferred over permanent site fork

## Loose ends (non-blocking)

1. **Task worktrees** still on disk under `~/src/ops-worktrees/`:
   `herdr-brew-service`, `herdr-workstation-docs`, `ops-release-lock` (+ this handoff branch). Safe to remove after PR merge.
2. **`just site-sync` from `~/ops/site-djbclark`** can fail on generated-fragment drift (`OPS_ROOT` path rewriting). Do **not** force-write generated into the deploy checkout (dirtifies a release tag). Live OliveTin already has `user_herdr_*`.
3. **`~/Desktop/herdr-setup.md`** is older than live config + repo docs — archive/refresh optional.
4. CJK cursor reveal / redraw-on-focus still disabled pending Ghostty stability confidence.

## How to continue

### If working Goose/Aider (#12)

1. Attach Herdr (`h`), run `goose` / `aider` in panes; capture with `herdr pane read` + `herdr agent explain --json`.
2. File or link upstream issue on `ogulcancelik/herdr` for process detection + manifests.
3. Prototype only after process ids exist, or use temporary `herdr pane report-agent` wrappers.
4. Keep launchers/docs in site-djbclark; do not invent fake TCP ports for herdr (UDS only).

### If cutting next ops release

```bash
cd ~/ops/site-djbclark   # or main worktree for tooling
just ops-release-claim-status
just ops-release-claim-begin X.Y.Z cut --holder <you>
# … version bumps on three repos, merge, tag ops-vX.Y.Z, gh release create ×3 …
just ops-release-check X.Y.Z
just ops-release-deploy X.Y.Z
just ops-release-claim-end --version X.Y.Z
just ops-release-status
```

Never retag; never develop in `~/ops`.

### Verify Herdr quickly

```bash
brew services info herdr
herdr status
hs
# OliveTin: https://mac.greyhound-sidemirror.ts.net/olivetin/  or http://127.0.0.1:1337
```

## Do not redo

- Re-cutting 1.0.1 / 1.0.2
- Disabling `manifest_check` / `mouse_capture` without a new freeze investigation
- Installing Herdr integrations for CLIs not on PATH
- Nesting tmux inside Herdr panes
