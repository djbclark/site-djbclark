# roles/basic_memory_mcp

One shared `basic-memory` MCP server per machine over streamable HTTP on
loopback (`http://127.0.0.1:18796/mcp`), replacing one stdio copy per agent
session. Measured 2026-09-26: 13 stdio copies ≈ 2.6 GB phys footprint on a
16 GB laptop. See `defaults/main.yml` for the rationale and the rollback.

- Apply: `just basic-memory-mcp-apply` · check: `…-check` · status: `…-status`
- Clients: `~/.claude.json` `mcpServers.basic-memory` → `{"type":"http","url":…}`.
- Log: `~/Library/Logs/basic-memory-mcp/basic-memory-mcp.log` (5 MB × 2 via logpipe).

## What it serves (since 2026-09-30)

The `main` project is `~/ops/site-private/memory`; this server is the memory
search service for agent memory. The project path and two settings live in
`~/.basic-memory/config.json`, which this role does not render:
`ensure_frontmatter_on_sync: false` (otherwise indexing adds `title`/`type` to
every note without frontmatter) and `auto_update: false` (the nightly
`brew-fast-upgrade` upgrades the uv tool with `uv tool upgrade --all`; nothing
pins it). **Permalinks are mandatory since Basic Memory 0.24** (upstream
[#1395](https://github.com/basicmachines-co/basic-memory/issues/1395),
[PR #1477](https://github.com/basicmachines-co/basic-memory/pull/1477)): the
old `disable_permalinks: true` is gone (0.24.1 deleted it from the config on
2026-10-23), and sync writes a `permalink:` into every note's frontmatter,
re-dumping that YAML. That one-time rewrite of the memory tree was committed as
site-private `f29f752` (2026-10-24); after it, a note is only rewritten when its
permalink differs. A new note gets its `permalink:` on first sync: commit it.
After an upgrade or config change, check `git -C ~/ops/site-private status
--short` for anything beyond that.
