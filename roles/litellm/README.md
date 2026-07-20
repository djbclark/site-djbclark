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

### API Keys – Human Step (E4)

Provider completions need real keys. **Never commit keys.** Full operator
checklist: [`human/API-KEYS-E4.md`](../../human/API-KEYS-E4.md).

1. SecretSpec user defaults (local, not git) must use the 0.16 `[defaults]`
   table — bare top-level `provider = "dotenv"` is ignored:

   ```toml
   # ~/.config/secretspec/config.toml
   [defaults]
   provider = "dotenv"
   profile = "default"
   ```

2. Store values in the site dotenv (gitignored `*.env` / `.env`, mode 0600):

   ```bash
   cd /Users/djbclark/ops/site-djbclark
   secretspec set OPENAI_API_KEY
   secretspec set ANTHROPIC_API_KEY
   secretspec check -n --explain   # presence only; no values printed
   ```

3. Inject into the LaunchAgent at apply time (keys are not read live from
   SecretSpec by the daemon):

   ```bash
   secretspec run --reason "apply LiteLLM provider keys" -- just litellm-apply
   ```

4. Verify (expect 200 once the matching key is in the plist):

   ```bash
   curl -fsS http://127.0.0.1:4000/v1/models | jq -r '[.data[].id]|join(",")'
   # SIMPLE vs multi-step REASONING — tiers differ in the decision log
   rg 'ComplexityRouter: routing decision' ~/Library/Logs/litellm/stderr.log | tail
   ```

The committed config references `os.environ/...`; values are rendered only
into `~/Library/LaunchAgents/com.djbclark.litellm.plist`, which is mode 0600.
The proxy has no master key while it is bound to loopback. Add authentication
before any future Tailscale bind or multi-user access.

**Cold start / heal:** first launchd boot can take ~30–90s of Python import
before `:4000` listens. After missing-key completion storms, stderr can grow
large and the process can wedge — `launchctl bootout` /
`launchctl bootstrap` the label and rotate logs if needed (see human checklist).
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
