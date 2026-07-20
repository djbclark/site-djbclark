# Goose role

This role installs Goose Desktop (`block-goose` cask) and Goose CLI
(`block-goose-cli` formula) when absent, then configures a declarative custom
OpenAI-compatible provider pointing at the site-owned loopback LiteLLM proxy.

Goose **1.43.x** (verified 2026-07-20) uses:

- `~/.config/goose/config.yaml` with structured `active_provider` /
  `providers:` keys (legacy flat `goose_provider` alone is not enough for CLI
  sessions)
- `~/.config/goose/custom_providers/*.json` for OpenAI-compatible endpoints

Managed files:

- `~/.config/goose/config.yaml`
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

## Rollback

Remove only the site-managed provider configuration. Leave Homebrew packages
and any user-owned Goose state intact:

```bash
rm -f ~/.config/goose/custom_providers/litellm-local.json
rm -f ~/.config/goose/config.yaml
# Optional: remove empty dirs if nothing else lives there
rmdir ~/.config/goose/custom_providers 2>/dev/null || true
rmdir ~/.config/goose 2>/dev/null || true
```

If you previously had a non-site Goose config, restore it from backup after
removing the managed files. LiteLLM and D7 front-door routes are unaffected.
