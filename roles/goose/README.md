# Goose role

This role installs Goose Desktop (`block-goose` cask) and Goose CLI
(`block-goose-cli` formula) when absent, then configures a declarative custom
OpenAI-compatible provider pointing at the site-owned loopback LiteLLM proxy
and templates researched MCP extension entries (Phase E3).

Goose **1.43.x** (verified 2026-07-20) uses:

- `~/.config/goose/config.yaml` with structured `active_provider` /
  `providers:` keys and an `extensions:` map (legacy flat `goose_provider`
  alone is not enough for CLI sessions)
- `~/.config/goose/custom_providers/*.json` for OpenAI-compatible endpoints

Managed files:

- `~/.config/goose/config.yaml` (provider + site-managed extensions)
- `~/.config/goose/custom_providers/litellm-local.json`

Both are mode `0600`; parent directories are `0700`. Each managed file carries
a site marker or fixed ownership path so apply refuses to overwrite unrelated
user configuration.

## Apply and inspect

```bash
just goose-apply
just goose-check
just goose-status
```

## Provider and E4 boundary

The managed provider targets `http://127.0.0.1:4000/v1` with model
`smart-router`. Authentication is disabled at the Goose layer
(`requires_auth: false`) because E1 binds LiteLLM to loopback without a master
key.

Until E4 configures SecretSpec and LiteLLM provider credentials:

- `curl http://127.0.0.1:4000/v1/models` works
- `goose info -v` shows `litellm-local` / `smart-router`
- `goose run --no-session -t "…"` starts but hangs or fails once LiteLLM tries
  upstream provider completion — expected missing-credential behavior

Do not invent API keys in this role or configure SecretSpec here.

## E3 MCP research findings (2026-07-20)

Step0 guessed package names (`@shortwave/mcp-server`, `@saner-ai/mcp-server`,
`fieldy_mcp`) were **wrong**. Verified status:

| Target | Goose-facing MCP? | Transport / install | Auth | Templated? |
| --- | --- | --- | --- | --- |
| **filesystem** | **Yes** — official | stdio: `npx -y @modelcontextprotocol/server-filesystem <dirs…>` | None (local paths) | Yes, `enabled: true` by default |
| **Fieldy** | **Yes** — vendor remote | streamable HTTP URI `https://api.fieldy.ai/mcp` | Browser OAuth (Fieldy account email) on first use | Yes, `enabled: false` until OAuth (E4) |
| **Shortwave** | **No** | Shortwave is an MCP **client** only (connects *to* other MCP servers from Shortwave UI) | n/a | Comment stub only |
| **Saner.ai** | **No** | No official MCP docs or published package found | n/a | Comment stub only |

### Sources (do not substitute lookalikes)

**Filesystem**

- <https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem>
- npm: `@modelcontextprotocol/server-filesystem` (verified present; e.g. 2026.7.10)
- Goose 1.43 config shape: `type: stdio`, `cmd`, `args` — see
  [Configuration Files](https://goose-docs.ai/docs/guides/config-files)

**Fieldy**

- <https://intercom.help/Fieldy/en/articles/15019124-connecting-fieldy-to-claude-chatgpt-and-your-own-apps>
- MCP endpoint: <https://api.fieldy.ai/mcp>
- Related: <https://fieldyai.github.io/docs/#/mcp>

**Shortwave (client only — not a Goose MCP server)**

- <https://www.shortwave.com/docs/how-tos/using-mcp/>
- <https://www.shortwave.com/blog/integrate-ai-with-all-your-apps-mcp/>
- npm `@shortwave/mcp-server` → **404** (not published)

**Saner.ai (no MCP found)**

- Product: <https://www.saner.ai/>
- npm `@saner-ai/mcp-server` / `saner-mcp` → **404**; no PyPI `fieldy-mcp` /
  Saner MCP package verified

### Defaults and variables

| Variable | Default | Notes |
| --- | --- | --- |
| `goose_ext_filesystem_enabled` | `true` | Needs Node/npx (Homebrew `node` on this host) |
| `goose_ext_filesystem_package` | `@modelcontextprotocol/server-filesystem` | Official only |
| `goose_ext_filesystem_allowed_dirs` | `~/ops`, `~/Documents` | Narrower than full `$HOME`; override in group_vars if needed |
| `goose_ext_fieldy_enabled` | `false` | Flip to `true` after E4 OAuth first-run |
| `goose_ext_fieldy_uri` | `https://api.fieldy.ai/mcp` | Vendor endpoint |

First filesystem tool use downloads the npm package via `npx -y` (network).
This role does **not** pre-install MCP packages at apply time.

### What remains human / E4

1. SecretSpec + LiteLLM provider API keys (E4) so completions work.
2. Fieldy: set `goose_ext_fieldy_enabled: true` (or re-apply after default flip)
   and complete browser OAuth when Goose first connects to the extension.
3. Shortwave / Saner: no Goose extension until a vendor ships a real MCP server;
   operator may revisit research if products change.

## Rollback

### Full E2 provider rollback

Remove only the site-managed provider configuration. Leave Homebrew packages
and any user-owned Goose state intact:

```bash
rm -f ~/.config/goose/custom_providers/litellm-local.json
rm -f ~/.config/goose/config.yaml
# Optional: remove empty dirs if nothing else lives there
rmdir ~/.config/goose/custom_providers 2>/dev/null || true
rmdir ~/.config/goose 2>/dev/null || true
```

### E3 extension-only rollback

Site-managed extensions live only inside the managed `config.yaml`. To drop
extension entries while keeping the LiteLLM provider selection:

1. Edit `roles/goose/templates/config.yaml.j2` / defaults to remove or disable
   extensions, then `just goose-apply`, **or**
2. Temporarily set `goose_ext_filesystem_enabled: false` and
   `goose_ext_fieldy_enabled: false` and re-apply (stubs remain as comments).

Do not delete the whole config if you only want to disable MCP tools. LiteLLM
and D7 front-door routes are unaffected either way.

If you previously had a non-site Goose config, restore it from backup after
removing the managed files.
