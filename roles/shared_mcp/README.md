# roles/shared_mcp

One MCP server per machine on loopback for every agent TUI, instead of one copy per agent session. Each runs as
`com.<site_ns>.<name>-mcp` (launchd, supervised by `bin/litellm_logpipe.py`, logs in `~/Library/Logs/shared-mcp/`).
Clients reach `http://127.0.0.1:<port>/mcp`. Ports are registered in `registry/ports.yml` (even = server, odd = optional gate).
Apply: `just shared-mcp-apply-secrets`; status: `just shared-mcp-status`. Rationale and rollback: `defaults/main.yml`.

| Server | Port | What |
|---|---|---|
| crawl4ai | 18798 | one shared headless browser |
| arxiv | 18800 | arxiv-mcp-server over HTTP |
| paper-search | 18802 | `mcp-proxy` in front of the stdio `paper-search-mcp` |
| firecrawl | 18804 | `firecrawl-router` + `firecrawl-mcp` against the self-hosted Firecrawl on Hyades |
| greptile | 18808 | `bin/greptile-mcp-proxy`: Greptile's hosted MCP with an 8-tool allowlist (below) |

## greptile (2026-11-01)

`bin/greptile-mcp-proxy` (Python 3 stdlib only) forwards `http://127.0.0.1:18808/mcp` to
`https://api.greptile.com/mcp` (streamable HTTP, POST with JSON or SSE replies). Why a proxy: Greptile's server lists 21 tools;
review agents need eight, and every extra schema is context in every session of every TUI.

- Allowlist: `get_me`, `list_pull_requests`, `get_merge_request`, `list_merge_request_comments`, `list_code_reviews`,
  `get_code_review`, `trigger_code_review`, `search_greptile_comments`. `tools/list` is filtered (JSON and SSE); a `tools/call`
  for any other tool gets a local JSON-RPC error (-32602) and is never forwarded. A batch holding one is refused whole.
  The forwarded request is re-serialised from the validated parse (duplicate JSON keys are rejected).
- Key: `GREPTILE_API_KEY` is read once at start with `sudo-secretspec get` (argv list, stdin /dev/null, stderr discarded) and
  held in memory. It is not in the plist, argv, client configs, logs, errors or responses (every outgoing body, SSE event
  and header is scrubbed of it). A failed read is retried at most once a minute on a request, and answers 503 meanwhile.
  A client `Authorization` header is dropped. Upstream 401/403 become a local 502 without `WWW-Authenticate`.
- Headers: `Mcp-Session-Id` and `MCP-Protocol-Version` pass both ways. GET is 405 (Greptile issues no session and no
  standalone stream); DELETE is forwarded only with a session id.
- Safety: binds 127.0.0.1, rejects non-loopback `Host`/`Origin` (DNS rebinding), 1 MiB request cap, connect 10 s,
  idle-read 60 s and a 300 s total deadline per upstream exchange. One log line per request (HTTP method, JSON-RPC method,
  tool, status, ms); never bodies.
- Registered in the agent TUIs by `bin/greptile-mcp-register` (cursor, codex, opencode, agy, Claude Code), the same entries
  as firecrawl, with `.bak-2026-11-01-greptile` backups. Tests: `tests/test_greptile_mcp_proxy.py` (fake upstream and fake
  `sudo-secretspec`, no network).
- Rollback: `launchctl bootout gui/$UID/com.djbclark.greptile-mcp`, remove the `greptile` entry from each client config
  (or restore its `.bak-2026-11-01-greptile`), and `claude mcp remove --scope user greptile`.

Context cost, measured 2026-11-01 from the live `tools/list` (compact JSON; tokens at ~4 bytes/token):

| | Tools | Schema bytes | ~Tokens |
|---|---|---|---|
| Greptile direct | 21 | 46,139 | ~11,500 |
| Through the proxy | 8 | 14,682 | ~3,700 |

Saved per session: 13 tools, 31,457 bytes, ~7,900 tokens (68 %). The 8 tools by size: `list_pull_requests` 2,553 B,
`list_merge_request_comments` 2,393, `list_code_reviews` 2,372, `trigger_code_review` 1,977, `get_merge_request` 1,904,
`search_greptile_comments` 1,760, `get_code_review` 1,025, `get_me` 705.
