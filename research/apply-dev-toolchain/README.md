# apply-dev-toolchain — a drop-in prompt that applies the djbclark toolchain to a repo

One file, [`CLAUDE_APPLY_DJBCLARK_TOOLING.md`](CLAUDE_APPLY_DJBCLARK_TOOLING.md):
a human preamble (how to use it, how to cut it down to a budget, what changed
since the previous version) followed by the full prompt for a Claude Code
orchestrator session. The prompt installs the stayturgid/aiuse/site-djbclark
quality toolchain, Graft, project subagents, a curated set of Claude Code
skills and plugins, characterization tests, pre-commit, CI, CodeRabbit and
coderabbit-feeder into a target repo, with backups and restore recipes for
everything it touches outside git.

Current target: `Kuriboh493/perp-option-pricer`. Only §P0 and §12 of the
prompt are specific to that repo; everything else is reusable.

History: Version 4 (2026-09, outside this repo) → Version 5 (2026-10-01, this
file; re-researched against the live reference repos and the current Claude
Code docs).

This repository is public: the prompt names private repos only by URL and
contains no credentials.
