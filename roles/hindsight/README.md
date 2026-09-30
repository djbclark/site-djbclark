# Hindsight role

Installs and manages the local Hindsight API as the loopback-only macOS
LaunchAgent `com.<site_ns>.hindsight-api` on `127.0.0.1:8888`.

The role is intentionally fail-closed:

- Hindsight is pinned to `0.9.0` in an isolated `~/.hindsight/venv`.
- The canonical candidate-ledger CLI is installed from
  `bin/hindsight_memory_candidates.py` to
  `~/.hindsight/bin/hindsight_memory_candidates.py` with mode `0700`; the role
  is the authoritative deployment path for that runtime copy.
- Codex authentication must already exist at `~/.hindsight/codex/auth.json`
  with mode `0600`.
- Credentials are never copied into Hermes, Ansible variables, plist templates,
  Git, or chat.
- No public/Tailscale bind is permitted until authentication and multi-user
  isolation are designed.
- The service reaches its LLM through the site-local LiteLLM proxy
  (`roles/litellm`, `127.0.0.1:4000`), which serves exactly one model,
  `clinepass-deepseek`, and holds the only real credential in its own mode-0600
  unit. Embeddings stay local and reranking is RRF, so no pay-per-token API key
  is embedded here or in the rendered plist. `HINDSIGHT_API_LLM_API_KEY` is a
  placeholder: Hindsight's `requires_api_key()` rejects an empty key for the
  `openai` provider, and the proxy sets no `master_key`.
- The provider is `openai`, not `clinepass` or `litellm` — Hindsight's
  `create_llm_provider()` routes `openai` to `OpenAICompatibleLLM`, which is
  what an OpenAI-compatible proxy needs. The `clinepass/` routing happens
  inside the proxy.
- Reflect uses the same proxy. It cannot inherit a base URL once the provider
  is `openai`, so `HINDSIGHT_API_REFLECT_LLM_BASE_URL` is set explicitly.
- **Every LLM setting is rendered from role defaults.** Before 1.4.1 the live
  plist had been hand-edited to use OpenRouter while this template still said
  `openai-codex`, so applying the role would silently revert the running
  service's model configuration. The template is the source of truth; change
  the defaults, not the plist.
- The role preflights the proxy (`GET {{ base_url }}/models`) and refuses to
  configure Hindsight against a model the proxy does not serve, rather than
  rendering a dead config and waiting out 30 health-check retries. The Codex
  auth assert now applies only when `hindsight_llm_provider` is `openai-codex`.

Apply only through the dedicated playbook after the Phase 2 acceptance matrix
passes:

```bash
just hindsight-apply
just hindsight-check
```

The service can be stopped and reloaded without touching the Hermes gateway:

```bash
launchctl bootout gui/$(id -u)/com.djbclark.hindsight-api
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.djbclark.hindsight-api.plist
curl -fsS http://127.0.0.1:8888/health
```

## Plugin patches

The role also installs local patches for the Claude Code plugin
(`@vectorize-io/hindsight-coding-agents`) into `~/.hindsight/coding-agents/` and
loads the `com.<site>.hindsight-plugin-patch` LaunchAgent. It re-runs every patch
when the plugin's `dist/` changes (an `npx … install|update` rewrites it), at
login, and hourly. Log: `~/Library/Logs/hindsight/plugin-patch.log`.

1. `patch-page-trigger.sh`: sets `exclude_mental_models: true` on the page
   trigger, without which knowledge pages stay blank.
2. `patch-reflect-timeout.sh`: makes the `hindsight_reflect` MCP tool honor
   `reflectTimeoutMs`; stock 0.3.4 always aborts at 120 s.

## Directory syncs

`hindsight_dir_syncs` mirrors directories of Markdown into a bank with
`bin/hindsight_sync_dir.py`, one document per file (`document_id` =
`<name>/<filename>`, replaced on change, deleted when the file goes). One
LaunchAgent per entry runs it when the directory changes, at login, and hourly.
Files with secret-shaped content are skipped and listed in
`~/Library/Logs/hindsight/sync-<name>.log`, never sent.
