# Handoff — 2026-07-29 Herdr Goose/Aider prototype (site-djbclark#12, layer A)

**For the next agent/reader:** this closes the layer-A ("coding-agent TUIs")
slice of [site-djbclark#12](https://github.com/djbclark/site-djbclark/issues/12).
Layers B (LiteLLM) and C (omlx/Ollama/llama.cpp/mlx/LM Studio) were already
done or made moot before this unit started — LiteLLM already has
`user_litellm_*` OliveTin actions and registry/docs coverage, and omlx/Ollama
were uninstalled entirely on 2026-07-29. This unit did not touch either.

Worktree: `~/src/ops-worktrees/herdr-workstation-12/site-djbclark`
(branch `feature/herdr-workstation-12`).

## What shipped

- `bin/herdr_agent_wrapper.py` — the actual mechanism: wraps a real agent
  binary, self-reports pane lifecycle over `herdr pane report-agent` /
  `release-agent` (the same socket API the official `claude`/`codex`/…
  hooks use), classifies `working`/`idle`/`blocked` via a generic
  content-quiescence poll + best-effort confirm-prompt regexes.
- `bin/herdr-goose`, `bin/herdr-aider` — thin launcher shims. The real
  `goose`/`aider` on `PATH` are untouched; only these new launcher names go
  through the wrapper. Aider's shim also wires its real
  `--notifications-command` hook (Goose has no equivalent) for a more
  precise idle signal on top of the same poller.
- `tests/test_herdr_agent_wrapper.py` — 9 unit tests on the two pure pieces
  (`_looks_blocked`, `classify_next_state`), using real prompt text captured
  live from both tools, not invented strings.
- `justfile`: `herdr-agents-install` recipe (symlink pattern copied from
  `install-caut`).
- `docs/reference/herdr-workstation.md`: new "Goose and Aider" section
  (mechanism, install, empirical gotchas, explicit non-goal call on session
  resume) + two new launcher-table rows (`alt+s` goose, `alt+i` aider) + the
  `[[keys.command]]` TOML block to hand-add to the machine-local
  `~/.config/herdr/config.toml` (not tracked in this repo).
- `.gitignore`: added `.aider*` (aider's local session-state files; using
  `herdr-aider` from this repo root now leaves droppings without it).

## Confirmed scope narrowing (from the launching prompt, verified, not re-derived)

Layer A only. Session resume (issue goal #4) investigated and **not
implemented** for either tool — see the doc's "Not done" subsection for why
(no upstream Herdr "kind"/integration layer to hook a restart-resume flow
into; the issue itself already called Aider resume out of scope, the same
reasoning now covers Goose too).

## Empirical findings (live-tested, 2026-07-29 — see doc for the durable version)

All of this was verified against real `goose session` / `aider` panes in a
live Herdr session on this Mac, not inferred from `--help` text:

1. **`herdr agent list`/`explain` confirm goose/aider are undetected today**
   — `herdr agent explain <pane>` returns `agent_not_found` for a bare
   `goose session` pane; `herdr pane process-info` shows aider's actual OS
   process name is **`Python`** (framework-Python `argv0` rewrite), not
   `aider` — so no future process-name-keyed detection (upstream or local
   override) can key off aider's process name at all; it would need to match
   `cmdline` content or use aider's own hook.
2. **`report-agent`/`release-agent` CLI quirk**: `<PANE_ID>` must be the
   _first_ argument, before `--flags` — the `--help` usage line order
   (`[OPTIONS] ... <PANE_ID>`) does not work on herdr 0.7.5, fails with
   `unknown option: <value>`.
3. **Real bug found and fixed during testing**: `release-agent` without an
   explicit fresh `--seq` was silently ignored whenever a prior
   `report-agent` call had a `--seq` — last-write-by-seq-wins left a stale
   `goose: idle` sidebar entry on a pane whose process had already fully
   exited (confirmed via `herdr pane process-info` showing a bare shell).
   Fixed by always passing `--seq $(time.time_ns())` on both calls; verified
   fixed with a second live goose run through the wrapper end-to-end.
4. **`--state idle` displays as `agent_status: "done"`** in `herdr agent
list`, not `"idle"` — a Herdr display-mapping detail, not a wrapper bug.
5. End-to-end verified live: goose `working`→`idle` round trip on a real
   prompt (~2s LLM turn, correctly tracked); aider `working`→`idle` round
   trip via both the notification hook and the poller; both wrappers'
   `release-agent` cleanly removes the sidebar entry on process exit.

## Not re-litigated / already true before this unit

- LiteLLM `user_litellm_*` OliveTin actions, port/docs coverage — pre-existing.
- omlx/Ollama uninstalled 2026-07-29 — see `registry/ports.yml` /
  `registry/paths.yml` removal comments. Not touched, not reinstalled.

## Loose ends / honest gaps

- **Blocked-state detection is best-effort**, tuned against the specific
  prompts observed live (aider's `(Y)es/(N)o` format, goose's clack-style
  `● Yes / ○ No` toggle). A confirm prompt phrased differently won't be
  caught — the pane just stays `working` a beat longer, never falsely stuck.
- **No sidebar icon/color customization** for the synthetic `goose`/`aider`
  agent labels — Herdr's per-agent row styling
  (`rows_by_agent` in `config.toml`) targets known agent ids; whether it
  picks up arbitrary report-agent labels the same way wasn't tested this
  unit (cosmetic, not a functional gap).
- `just herdr-agents-install` was **not** run for real during this session —
  it was smoke-tested then its resulting `~/.local/bin` symlinks were
  immediately removed, because running it from this task worktree would
  point live machine config at a path that disappears once this worktree is
  cleaned up (the exact landmine class site-djbclark#100 fixed for generated
  fragments). Run it for real from the **released** `~/ops/site-djbclark`
  checkout after this PR ships in a coordinated release.
- The `[[keys.command]]` config.toml blocks and `alt+s`/`alt+i` keybindings
  are **documented only** — not applied to the live
  `~/.config/herdr/config.toml` (machine-local, not this repo's to write).
  Operator step: copy the blocks from the doc, `hreload`.

## PR

`feature/herdr-workstation-12` → site-djbclark. Not merged by this agent —
per this unit's brief, pushed and opened only; orchestrator verifies and
merges.
