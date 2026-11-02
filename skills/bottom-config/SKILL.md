---
name: bottom-config
description: >-
  Edit, validate and preview the config of bottom (the `btm` process monitor)
  and its fork build `btm-mt` with the split Command column
  (`processes.split_command`). Use when changing ~/.config/bottom/bottom.toml,
  tuning columns, layout, colors or process options, or when btm-mt needs a rebuild.
---

# bottom-config

djbclark runs two binaries from the same config, `~/.config/bottom/bottom.toml`:

1. `btm`: Homebrew's stock bottom (`/opt/homebrew/bin/btm`).
2. `btm-mt`: the fork `djbclark/bottom`, branch `middle-truncate-command` (the name is
   historical), checkout `~/src/bottom`. It adds `[processes] split_command = true`: a full
   command is drawn as `name ┊ cwd ┊ options` (interpreters as `python3.15 script.py`;
   cwd cut in the middle with `…`, last directory kept; options keep at least 10 cells,
   cut at the end), and grouped mode (`Tab`) groups by that name with expandable groups
   (`Space`/`+`/`-`, `Right`/`Left`). Stock `btm` ignores that key.

## The trap: typos are silent

bottom ignores unknown config keys in release builds (checked 2026-11-01: a config with
`truncate_cmd_midle` and `process_comand` started normally, showing names). The published
schema does not forbid them either. So after EVERY edit run the strict validator:

```sh
~/src/djbclark-ade/skills/bottom-config/scripts/validate.py            # the live config
~/src/djbclark-ade/skills/bottom-config/scripts/validate.py FILE       # another file
```

It adds `additionalProperties: false` to the fork's `schema/nightly/bottom.json`, names the
unknown key with a "did you mean", and reports wrong types by path. Exit 0 = valid, 1 =
problems, 2 = unreadable input. It needs `uv` (it carries its own `jsonschema` dependency).

## Workflow

1. Find the option: `~/src/bottom/docs/content/configuration/config-file/*.md` (one page
   per area: `processes`, `flags`, `layout`, `styling`, the graphs and tables) and the
   commented sample `~/src/bottom/sample_configs/default_config.toml`. Read those; do not
   guess key names or values.
2. Edit `~/.config/bottom/bottom.toml` (keep the comments; they say which binary knows a key).
3. Validate (above).
4. See it, without touching the user's terminal:
   ```sh
   scripts/preview.py                           # live config, 140x30, process widget
   scripts/preview.py --config "$draft" --width 100 --keys t   # a draft; `t` = tree
   ```
   It runs `btm-mt` in its own private tmux server (the user's tmux is never touched) and
   prints the screen. It refuses a `--config` that does not exist or is not valid TOML,
   because bottom writes a default config to any `-C` path it cannot read. Make the draft
   with `d=$(mktemp -d) && draft=$d/draft.toml`; copy it over the live config only when it
   looks right, and run the validator on it first. Keys in the process table: `P`
   name/command, `t` or `F5` tree, `e` expand widget; more in
   `~/src/bottom/docs/content/usage/widgets/process.md`.
5. Config that only `btm-mt` understands goes under a comment saying so; stock `btm` must
   still start with the file (it does: unknown keys are ignored).

## Rebuilding btm-mt (never build locally)

Builds go to CI (standing rule, `memory/feedback_macos_ci_on_request_only.md`). Work in a
worktree on a feature branch from `origin/middle-truncate-command` (`~/src/bottom` is the
shared checkout; it only fast-forwards). Format with `cargo +stable fmt --all` before each
push: the machine's default toolchain is pinned to 1.92, whose rustfmt disagrees with CI's
latest stable (2026-11-01, a CI fmt failure). Check the branch with
`gh workflow run fork-build.yml --repo djbclark/bottom --ref <branch>` (its artifact can be
previewed with `preview.py --bin`), then publish by fast-forward:
`git push origin <branch>:middle-truncate-command`, and `git merge --ff-only` `~/src/bottom`
(the validator reads its schema). `.github/workflows/fork-build.yml` runs on push and manual
dispatch only (no `pull_request` trigger: a PR run uses the PR's copy of the workflow, so an
outsider could replace the artifact), runs fmt, clippy and tests, and builds the macOS arm64
binary as artifact `btm-macos-arm64`. After the push run on `middle-truncate-command` passes:

```sh
scripts/install_btm_mt.py
```

It takes the fork branch's head commit, requires a successful *push* run for exactly that
commit (it refuses and installs nothing otherwise), downloads that artifact into a private
temp dir, checks the binary runs, and replaces `~/.local/bin/btm-mt` atomically. Do not
replace it by hand with "the newest run": `gh run list --branch` also lists other people's
PR runs.

To follow upstream: `git fetch upstream && git rebase upstream/main` in `~/src/bottom`
(the conflict hot spot is `src/widgets/process_table/process_data.rs`), push with
`--force-with-lease`, wait for CI, reinstall. Do not file anything upstream: its
`AI_POLICY.md` requires human-written issue and PR text.

## Where the change lives

`SplitCommand` (`src/collection/processes/split_command.rs`) is built at collection time
when the key is on (it also turns on per-process cwd reads); `split_widths`/`split_line`
in `src/widgets/process_table/process_data.rs` draw it (the separator uses the theme's
`selected_border_colour`); grouping and expansion are in `get_normal_data`
(`src/widgets/process_table.rs`). Sorting uses the joined text; search still matches the
full command. Docs: `docs/content/configuration/config-file/processes.md`, "Split Command".
