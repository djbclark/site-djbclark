# Claude config: only `local-marketplace` remains here (2026-10-14)

`local-marketplace/` is the Claude Code plugin marketplace source for
`local-lsp` (registered in `~/.claude/settings.json` at this path; bump
`version` in `marketplace.json` after edits, Claude Code caches plugins).

Everything else that used to live in this directory moved to the agent
toolchain repo and is linked **directly** into `~/.claude/` — no chains:

- `claude/agents/{adversary,backend,fable-deep,ux}.md`,
  `claude/commands/*.md` (helm-all, herdr-tidy, orca-tidy, resume,
  session-finder-all, skillopt-sleep, steps), `claude/hooks/*.py|sh` and
  `claude/hooks/handoff-tools/` → `~/src/djbclark-ade/claude/…`
- skills → `~/src/djbclark-ade/skills/<name>` (private: `1password` stays
  in `~/ops/site-private/skills/`)

The old hook-registration stanzas documented here previously now live in
`~/src/djbclark-ade/docs/` (see `docs/skills.md`,
`docs/skill-everywhere.md`); the graft hooks are checked by
`~/.hermes/scripts/check-graft-wiring-invariants.sh`, which compares
`~/.claude/hooks/` against the canonical copies in djbclark-ade.
