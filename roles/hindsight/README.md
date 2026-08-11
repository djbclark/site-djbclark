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
- The service uses `openai-codex` and local embeddings; it does not use a new
  pay-per-token API key or a local LLM.

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
