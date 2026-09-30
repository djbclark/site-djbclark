# roles/basic_memory_mcp

One shared `basic-memory` MCP server per machine over streamable HTTP on
loopback (`http://127.0.0.1:18796/mcp`), replacing one stdio copy per agent
session. Measured 2026-09-26: 13 stdio copies ≈ 2.6 GB phys footprint on a
16 GB laptop. See `defaults/main.yml` for the rationale and the rollback.

- Apply: `just basic-memory-mcp-apply` · check: `…-check` · status: `…-status`
- Clients: `~/.claude.json` `mcpServers.basic-memory` → `{"type":"http","url":…}`;
  `~/.config/crush/crushrc` `mcp add basic-memory --type http --url …`.
- Log: `~/Library/Logs/basic-memory-mcp/basic-memory-mcp.log` (5 MB × 2 via logpipe).

## What it serves (since 2026-09-30)

The `main` project is `~/ops/site-private/memory`; this server is the memory
search service that replaced Hindsight. The project path and three safety
settings live in `~/.basic-memory/config.json`, which this role does not
render: `ensure_frontmatter_on_sync: false`, `disable_permalinks: true` and
`auto_update: false`. With either of the first two at its default, indexing
rewrites tracked memory files. After any Basic Memory upgrade or config
change, check `git -C ~/ops/site-private status --short` shows no modified
files.
