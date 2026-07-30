# Implementation Plan: Open WebUI (v2 — post-vet revision)

> **VET OUTCOME & SCOPE CHANGE:** Buzz (Block.xyz) and the local Nostr relay have been **descoped** from this v1 rollout.
> Research into the `block/buzz` repository (v0.5.2) confirmed that **no pre-compiled standalone headless relay binary exists.** The GitHub releases only provide the "Buzz Desktop" client. Self-hosting the Buzz relay requires a heavy `docker compose` stack (Postgres, Redis, MinIO) or a complex Hermit/Rust toolchain build from source. This violates the plan's constraint for a lightweight LaunchAgent-friendly binary. We will rely on Open WebUI for the private AI workspace for now, deferring Nostr/Buzz until its server packaging matures.
> 
> Additionally, the Open WebUI secrets have been scoped down: since the local LiteLLM proxy (`127.0.0.1:4000`) does not require a master key, we will only add `WEBUI_SECRET_KEY` to `secretspec.toml`.

This plan outlines the steps to integrate Open WebUI into the `site-djbclark` environment. It will be managed via an Ansible role, registered in the site port/path registries, and exposed securely behind Caddy.

## 1. Port and Path Allocation
Before deploying, we must claim registry namespace to pass `just lint`:
- **Open WebUI**: Claim TCP port `8085` (bind: `127.0.0.1`, owner: `site`, service: `open-webui`, status: `planned`) in `registry/ports.yml` (confirmed free; 8080 is Caddy health, 8088 is landing).
- **Paths**: Claim `~/.local/share/open-webui` explicitly under the `site:` prefixes in `registry/paths.yml`. LaunchAgent labels are already covered by the existing `com.djbclark.*` claim.

## 2. Ansible Role
Create a new role `roles/open-webui/` for the Mac host (following the `roles/litellm` pattern):
- Install `open-webui` via `uv tool install` (or a pinned venv), avoiding bare pip. Ensure the LaunchAgent's `ProgramArguments` points directly to the virtual environment's executable.
- Deploy a `com.djbclark.open-webui.plist` LaunchAgent.
- **Environment & Routing**: 
  - `DATA_DIR` mapped to `~/.local/share/open-webui`
  - `OPENAI_API_BASE_URL=http://127.0.0.1:4000/v1` (LiteLLM proxy)
  - `OPENAI_API_KEY=sk-dummy` (Required by Open WebUI, but LiteLLM doesn't validate it)
  - `WEBUI_BASE_URL=/chat` (To inform Open WebUI it sits behind a sub-path)
- **Secrets**: Use `secretspec.toml` to project a persistent `WEBUI_SECRET_KEY` into the plist via ambient env mode 0600 (prevents session invalidation on restart). Do *not* invent a LiteLLM master key.

## 3. Caddy Reverse Proxy Routing
Add a fragment under `generated/stayturgid/fragments/caddy/` (or amend the stayturgid one):
- Route `/chat/*` to Open WebUI on `127.0.0.1:8085`.
- Because `WEBUI_BASE_URL=/chat` is set, Caddy should proxy the request directly (e.g., `reverse_proxy 127.0.0.1:8085`) without `handle_path` stripping, as Open WebUI handles the sub-path natively. Validate this behavior during implementation.

## 4. OliveTin Dashboard Actions
Expose operational actions to the user dashboard by appending to `olivetin/user-actions.yaml`, mirroring the existing `user_litellm_*` entries:
- `user_openwebui_status`: Executes `launchctl print "gui/$(id -u)/com.djbclark.open-webui" 2>&1 | head -30` and a `curl -s -m 5 http://127.0.0.1:8085/health` check.
- `user_openwebui_restart`: Executes `launchctl kickstart -k "gui/$(id -u)/com.djbclark.open-webui"` followed by a short sleep and health curl.
- Ensure the paths and patterns match existing conventions exactly.

## Execution Steps
1. Update both registries (`registry/ports.yml` and `registry/paths.yml`) to pass `just lint`.
2. Update `secretspec.toml` schema for the new required key (`WEBUI_SECRET_KEY`).
3. Scaffold `roles/open-webui`.
4. Add the Caddy fragment and apply OliveTin configurations.
5. Verify via `just lint`, health curls, and OliveTin actions.
