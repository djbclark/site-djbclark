# Skills: retired hub layer (2026-10-14)

This directory is no longer part of the skill path. Every skill now lives in
exactly one place and every agent TUI links it **directly** — no hub, no
chained symlinks:

- **Public skills** (the default): `~/src/djbclark-ade/skills/<name>/`
  (git: github.com/djbclark/djbclark-ade). Create, edit and commit them there.
- **Private skills**: `~/ops/site-private/skills/<name>/` (real directory,
  listed in `.githooks/private-paths` there). Only `1password` today.

`~/src/djbclark-ade/bin/skill-everywhere <name>` links a skill into every
TUI (Claude Code, Codex, Copilot, opencode, zcode, Qwen, Grok, agy, Devin,
Cline, Muse, Antigravity, Hermes, omp); its README is
`~/src/djbclark-ade/docs/skill-everywhere.md`. Never copy a skill into a
TUI's dir — copies drift.

History: until 2026-10-14 the TUIs linked through this repo
(`site-private/skills/<name>` → `site-djbclark/skills/<name>` →
djbclark-ade), so git churn here could break skill loading machine-wide;
that chain was collapsed to direct links. The symlinks under this path were
removed; nothing should link here any more.
