# Skills: the third `skill-everywhere` root (since 2026-11-06)

This directory is a skill root again. It holds the skills that moved here from
`djbclark-ade` in its slim-down (slice E1, 2026-11-06), because they are
about this site, its machines or the operator's own services rather than
about running agents:

`aws-rules`, `barnowl`, `bottom-config`, `coderabbit-feeder`,
`diskfree`, `firecrawl`, `gmail-search`, `greptile`, `ovhcloud-api`,
`report`, `setup-modern-cli`, `teach`, `terminus-kira`, `todo`.

They came with their history (`git filter-repo`, same paths) together with
`bench/`, `bin/app-tamer-ab`, `bin/heavy-shim`, `bin/codium-ai`,
`bin/change-hermes`, `bin/change-hermes-ssh-gate`, `claude/commands/teach.md`
and their tests (`tests/test_barnowl_skill.py` with `tests/fixtures/barnowl-*`,
`tests/test_bigteam_prune.py`, `tests/test_change_hermes_*.py`). PR numbers
in the imported commit messages refer to djbclark/djbclark-ade.

The three roots, each skill in exactly one of them:

- **Agent skills**: `~/src/djbclark-ade/skills/<name>/`
  (github.com/djbclark/djbclark-ade).
- **Site skills** (this directory): `~/ops/site-public-djbclark/skills/<name>/`.
- **Private skills**: `~/ops/site-private/skills/<name>/` (real directory,
  listed in `.githooks/private-paths` there).

`~/src/djbclark-ade/bin/skill-everywhere` reads all three roots (this one via
`SKILL_EVERYWHERE_SITE`, default `${OPS_ROOT:-~/ops}/site-public-djbclark/skills`)
and links each skill **directly** into every agent's skills directory; its
README is `~/src/djbclark-ade/docs/skill-everywhere.md`. Run
`skill-everywhere <name>` (or `--all`) after adding a skill here. Never copy a
skill into an agent's directory: copies drift.

**`book-to-kb` (2026-11-06):** the copy moved from djbclark-ade was deleted on the operator's choice ("keep the better one"); the skill is `tools/book-to-kb/skills/book-to-kb/`, the packaged tool's own, linked by its `install.sh`. `skill-everywhere` does not link a `book-to-kb` from this root.

History: until 2026-10-14 the agents linked through this directory as a hub
(`site-private/skills/<name>` -> `site-djbclark/skills/<name>` ->
djbclark-ade), and git churn here could break skill loading machine-wide.
That chain stays retired: nothing links *through* this directory. A link
points straight at the skill that lives here.
