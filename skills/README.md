# Local Claude skills (tracked here, symlinked from `~/.claude/skills/`)

These are the operator's **local, hand-maintained** Claude skills. Content lives
in git here (site-private is private — the correct home for them), and each is
symlinked back into `~/.claude/skills/<name>` so Claude Code still resolves it.
Same pattern as `~/CLAUDE.md`: content-in-git + symlink.

Only hand-maintained local skills belong here. **Tool-managed skills stay where
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

1. Create it under this directory: `skills/<name>/SKILL.md` (plus any support
   files).
2. Link it into every agent TUI (Claude Code, Codex, Copilot, Hermes, …):
   `~/ops/site-private/bin/skill-everywhere <name>`. Never copy a skill folder
   into another TUI's dir: copies go stale (11 had, until 2026-10-03). The
   `skill-everywhere` skill says which TUIs this covers and how to verify.
3. Commit + push (direct to `master`, `git pull --rebase` first — see
   `../AGENTS.md`).

## Move an existing local skill under version control

```sh
name=<skill>
cp -a ~/.claude/skills/$name ~/ops/site-private/skills/$name
diff -r ~/.claude/skills/$name ~/ops/site-private/skills/$name   # must be clean
rm -rf ~/.claude/skills/$name
ln -s ~/ops/site-private/skills/$name ~/.claude/skills/$name
```

Never move a symlinked or tool-managed skill; when unsure, leave it in place.
