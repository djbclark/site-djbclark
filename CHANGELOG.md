# Changelog

## Unreleased

- Added the skills, tools and tests moved here with their history from djbclark-ade's slim-down (E1, 2026-11-06): 14 skills under `skills/` (aws-rules, barnowl, bottom-config, coderabbit-feeder, diskfree, firecrawl, gmail-search, greptile, ovhcloud-api, report, setup-modern-cli, teach, terminus-kira, todo), `bench/`, `bin/app-tamer-ab`, `bin/heavy-shim`, `bin/codium-ai`, `bin/change-hermes`, `bin/change-hermes-ssh-gate`, `claude/commands/teach.md` and four test files; `skills/` is a `skill-everywhere` root again (`skills/README.md`). (branch slim-intake/2026-11)
- Added scheduled relay acknowledgement sweeps and one operator ping per overdue expectation: pages only open overdue rows from `--pending --json` (nothing when that list is unavailable), sanitized and clipped, under one 90 s deadline and a non-blocking lock; a ping killed by its timeout is not retried; a reused ID pages again after its earlier expectation closed. (#236)
