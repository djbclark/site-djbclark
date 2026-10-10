# Local agent skills (tracked here, reached through `site-private/skills/`)

These are the operator's **local, hand-maintained** skills. Since 2026-10-06
the content lives in git here, in `site-djbclark/skills/<name>/` (public).
`site-private/skills/<name>` is a symlink to it, and every agent TUI links to
that `site-private` path (`~/.claude/skills/<name>` and the rest), so one root
serves public and private skills alike. Same pattern as `~/CLAUDE.md`:
content-in-git + symlink.

**Orchestration and session-hygiene skills live in djbclark-ade (2026-10-08).**
`bigteam`, `model-routing`, `effort-routing`, `helm`, `session-finder`,
`ralph-tui-orchestration`, `cow-workspaces`, `handoff`,
`baton`, `session-handoff`, `steps` and `loose`, plus `autorename` and
`herdr-tidy` (moved or added there later on 2026-10-08), are absolute symlinks here into `~/src/djbclark-ade/skills/<name>/`
(github.com/djbclark/djbclark-ade, whose README describes them as one
project). On 2026-10-08 `resume` was folded into `baton`, `helm-all` into
`helm`, `session-finder-all` into `session-finder` (their old names survive
as command wrappers), and `skill-everywhere` became
[`../bin/skill-everywhere.md`](../bin/skill-everywhere.md). Edit and commit them there; the chain `site-private/skills/<name>`
→ here → djbclark-ade is unchanged for every TUI. A new skill of that kind goes
in djbclark-ade too, with the same symlink here.

Two skills are private and are real directories in `site-private/skills/`:
`1password` and `tell-chief-of-staff`. This repo is public: no credentials,
tokens, vault or item identifiers in a skill here.

**Since 2026-10-09 every skill here is a symlink into `~/src/djbclark-ade/skills/`, and a new skill goes there, not here** (see `djbclark-ade/docs/skills.md`). Only hand-maintained local skills belong in that chain. **Tool-managed skills stay where
their tool put them** and are NOT tracked here:

- Symlinks in `~/.claude/skills/` pointing into `~/.agents/skills/`,
  `~/.bailian/skills/`, `/opt/homebrew/...` (bailian-*, composio-cli,
  computer-use, herdr, orca-*, orchestration, sudo-secretspec, ...).
- Anything listed in `~/.agents/.skill-lock.json` (e.g. `ralph-tui-create-*`,
  `ralph-tui-prd`).
- Anything carrying an installer/marketplace marker: a `.origin`,
  `marketplace.json`, `.claude-plugin/`, `.superset-managed`, a `PROVENANCE.md`
  that says "installed ... unmodified" from a named source (e.g. `ln-11-*`,
  `ln-21-*`), or a synced-bucket dir (`synced/`).

## Add a new local skill

1. Ask djbclark whether it is public or private (standing rule, 2026-10-06).
2. **Public** (the default): create `~/ops/site-djbclark/skills/<name>/SKILL.md`
   (plus any support files), then add the link that puts it under the one root:
   `ln -s ../../site-djbclark/skills/<name> ~/ops/site-private/skills/<name>`.
   **Private**: create it as a real directory in
   `~/ops/site-private/skills/<name>/` and add `skills/<name>/` to
   `~/ops/site-private/.githooks/private-paths`; the pre-commit hook there
   rejects it otherwise.
3. Link it into every agent TUI (Claude Code, Codex, Copilot, Hermes, …):
   `~/ops/site-private/bin/skill-everywhere <name>`. Never copy a skill folder
   into another TUI's dir: copies go stale (11 had, until 2026-10-03). The
   script's README, [`../bin/skill-everywhere.md`](../bin/skill-everywhere.md),
   says which TUIs this covers and how to verify.
4. Commit + push both repos (direct to `master`, `git pull --rebase` first —
   see `../AGENTS.md`): the skill here, the symlink in `site-private`.

## Move an existing local skill under version control

```sh
name=<skill>
cp -a ~/.claude/skills/$name ~/ops/site-djbclark/skills/$name
diff -r ~/.claude/skills/$name ~/ops/site-djbclark/skills/$name   # must be clean
ln -s ../../site-djbclark/skills/$name ~/ops/site-private/skills/$name
rm -rf ~/.claude/skills/$name
ln -s ~/ops/site-private/skills/$name ~/.claude/skills/$name
```

That is the public case. For a private skill copy it to
`~/ops/site-private/skills/$name` instead, skip the first `ln -s`, and add it
to `.githooks/private-paths` there.

Never move a symlinked or tool-managed skill; when unsure, leave it in place.
