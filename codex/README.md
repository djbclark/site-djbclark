# Codex home mapping

This directory holds durable, non-secret Codex policy/support files and a
bootstrap configuration example (moved here from site-private 2026-10-06). The
live `CODEX_HOME` remains `~/.codex`; most top-level entries there are symlinks
into site-private (`codex/`, `memory/codex/`) or its ignored `.codex-runtime/`
directory, but some (for example `agents/`, `hooks/`, `packages/`,
`.codex-global-state.json`) are real files and directories.

`config.toml` is intentionally ignored machine-local state because Codex
updates model choices, trusted projects, plugins, marketplaces, and desktop
preferences. On a new machine, copy `config.toml.example` to `config.toml`;
then let Codex and the operator maintain the live file in place. Never commit
the live file.

Repository ownership follows the three-way policy:

- durable stayturgid product facts and session handoffs live in
  `${OPS_ROOT:-~/ops}/stayturgid/docs/`;
- non-sensitive site practice lives in `${OPS_ROOT:-~/ops}/site-djbclark/docs/`;
- generic/private cross-project notes and Codex memory live in site-private
  (`memory/codex/`);
- authentication, databases, logs, caches, plugins, attachments, and session
  state are never committed and live under site-private's ignored `.codex-runtime/`;
- mutable live preferences remain in site-private's ignored `codex/config.toml`.
