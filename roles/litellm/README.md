# LiteLLM role

This role installs `litellm[proxy,caching]>=1.94.0rc1,<2` with `uv`, renders
the current Auto Router v2 configuration, and keeps the loopback-only proxy
running as the user LaunchAgent `com.djbclark.litellm` on port 4000.

The prerelease floor is deliberate: on 2026-07-20 PyPI's newest stable release
is 1.93.0, while Auto Router v2 first appears in the 1.94 train and the newest
published build is 1.94.0rc1. Upgrade within the 1.94+ line when stable ships;
do not rewrite the configuration to the older router syntax.

The `caching` extra is required in addition to `proxy`: LiteLLM's disk-cache
backend imports the separately packaged `diskcache` dependency at startup.

## Apply and inspect

```bash
just litellm-apply
just litellm-check
just litellm-status
```

The keyless E1 state is intentional: `/v1/models` and routing classification
work, while provider completions wait for E4. After configuring a SecretSpec
provider, inject `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` at apply time:

```bash
secretspec run --reason "apply LiteLLM provider keys" -- just litellm-apply
```

The committed config references `os.environ/...`; values are rendered only
into `~/Library/LaunchAgents/com.djbclark.litellm.plist`, which is mode 0600.
The proxy has no master key while it is bound to loopback. Add authentication
before any future Tailscale bind or multi-user access.

## Routing and cache

The `smart-router` alias uses the LiteLLM Auto Router v2 tiers documented on
2026-07-20: SIMPLE `gpt-4o-mini`, MEDIUM `gpt-4o`, COMPLEX
`claude-sonnet-5`, and REASONING `gpt-5.5`. Responses are cached on disk under
`~/.litellm/cache` for one hour. Router decisions are greppable in
`~/Library/Logs/litellm/stderr.log` using `ComplexityRouter: routing decision`.

## Rollback

Stop the service without deleting configuration or cache:

```bash
launchctl bootout gui/$(id -u)/com.djbclark.litellm
```

Re-bootstrap the retained configuration with:

```bash
launchctl bootstrap gui/$(id -u) \
  ~/Library/LaunchAgents/com.djbclark.litellm.plist
```
