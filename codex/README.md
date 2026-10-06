# Codex home mapping

This directory holds durable, non-secret Codex policy/support files and a
bootstrap configuration example. The live `CODEX_HOME` remains `~/.codex`;
each entry there is a symlink into this repository or its ignored
`.codex-runtime/` directory.

`config.toml` is intentionally ignored machine-local state because Codex
updates model choices, trusted projects, plugins, marketplaces, and desktop
preferences. On a new machine, copy `config.toml.example` to `config.toml`;
then let Codex and the operator maintain the live file in place. Never commit
the live file.

Repository ownership follows the three-way policy:

- durable stayturgid product facts and session handoffs live in
  `${OPS_ROOT:-~/ops}/stayturgid/docs/`;
- non-sensitive site practice lives in `${OPS_ROOT:-~/ops}/site-djbclark/docs/`;
- generic/private cross-project notes and Codex memory live in this repository;
- authentication, databases, logs, caches, plugins, attachments, and session
  state are never committed and live under `.codex-runtime/`;
- mutable live preferences remain in the ignored `codex/config.toml`.
