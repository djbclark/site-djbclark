# Implementation Plan: Open WebUI & Buzz Integration

This plan outlines the steps to integrate Open WebUI and Block.xyz's Buzz into the `site-djbclark` environment. Both will be managed via Ansible roles, registered in the site port/path registries, and exposed securely behind Caddy.

## 1. Port and Path Allocation
Before deploying, we must claim registry namespace to pass `just lint`:
- **Open WebUI**: Claim TCP port `8085` (loopback) in `registry/ports.yml` (port 8080 is used by Caddy health).
- **Buzz (Block.xyz)**: Claim TCP port `8086` (loopback) in `registry/ports.yml`.
- **Paths**: Claim `~/.local/share/open-webui` and `~/.local/share/buzz` in `registry/paths.yml` under the `site` owner.

## 2. Ansible Roles
Create two new roles under `roles/` for the Mac host:
- **`roles/open-webui/`**: 
  - Install `open-webui` (e.g., via a dedicated Python venv or Brew).
  - Deploy a `com.djbclark.open-webui.plist` LaunchAgent.
  - Set the `OPENAI_API_BASE_URL` env var to point to the site's LiteLLM proxy (`http://127.0.0.1:4000/v1`) and pass the `OPENAI_API_KEY` via `secretspec.toml` projection.
- **`roles/buzz/`**:
  - Install the Buzz collaboration binary (from block.xyz releases).
  - Deploy a `com.djbclark.buzz.plist` LaunchAgent.
  - Configure Buzz with a Nostr keypair and direct it to the local workspace parameters.

## 3. Caddy Reverse Proxy Routing
Following the Phase D route scheme in `README.md`, map stable lowercase paths:
- Update the site Caddyfile to route `/chat/*` to Open WebUI on `127.0.0.1:8085`.
- Update the site Caddyfile to route `/buzz/*` to Buzz on `127.0.0.1:8086`.
- Both routes remain protected by the site's Tailscale TLS front door.

## 4. OliveTin Dashboard Actions
Expose operational actions to the user dashboard by appending to `olivetin/user-actions.yaml`:
- `user_openwebui_restart`: Executes `launchctl kickstart -k gui/$(id -u)/com.djbclark.open-webui`
- `user_openwebui_status`: Executes `launchctl print gui/$(id -u)/com.djbclark.open-webui`
- `user_buzz_restart`: Executes `launchctl kickstart -k gui/$(id -u)/com.djbclark.buzz`
- `user_buzz_status`: Executes `launchctl print gui/$(id -u)/com.djbclark.buzz`

## 5. Security & Secret Management
- Do not commit any Nostr nsec keys or LiteLLM master keys. 
- Use `secretspec.toml` to inject `LITELLM_MASTER_KEY` into the Open WebUI environment securely.
- Ensure both services listen exclusively on `127.0.0.1` — no public binding without Caddy's Tailscale auth layer.

## Execution Steps
1. Create `docs/plans/site-djbclark-open-webui-buzz-v1.md` (this file).
2. Modify `registry/ports.yml` and `registry/paths.yml`.
3. Scaffold `roles/open-webui` and `roles/buzz`.
4. Update `secretspec.toml` schema for new required keys.
5. Apply Caddy and OliveTin configurations.
6. Verify via `just lint` and `just ops-release-deploy`.
