# Implementation Plan: Open WebUI, Buzz, & Local Nostr Relay Integration

This plan outlines the steps to integrate Open WebUI and Block.xyz's Buzz into the `site-djbclark` environment. Both will be managed via Ansible roles, registered in the site port/path registries, and exposed securely behind Caddy. To support Buzz's self-hosting architecture within our Tailscale perimeter, a lightweight local Nostr relay will also be deployed.

## 1. Port and Path Allocation
Before deploying, we must claim registry namespace to pass `just lint`:
- **Open WebUI**: Claim TCP port `8085` (bind: `127.0.0.1`, owner: `site`, status: `planned`) in `registry/ports.yml` (port 8080 is used by Caddy health).
- **Buzz (Block.xyz)**: Claim TCP port `8086` (bind: `127.0.0.1`, owner: `site`, status: `planned`) in `registry/ports.yml`.
- **Local Nostr Relay**: Claim TCP port `8087` (bind: `127.0.0.1`, owner: `site`, status: `planned`) in `registry/ports.yml`.
- **Paths**: Claim `~/.local/share/open-webui`, `~/.local/share/buzz`, and `~/.local/share/nostr-relay` explicitly under the `site:` prefixes in `registry/paths.yml`. LaunchAgent labels are already covered by the existing `com.djbclark.*` claim.

## 2. Ansible Roles
Create three new roles under `roles/` for the Mac host (following the `roles/litellm` pattern with `site_ns`-templated labels, loopback-only bind asserts, health-wait after bootstrap, and `just *-apply` wrappers):
- **`roles/open-webui/`**: 
  - Install `open-webui` via `uv tool install` (or a pinned venv), avoiding bare pip. Ensure the LaunchAgent's `ProgramArguments` points directly to the virtual environment's executable.
  - Deploy a `com.djbclark.open-webui.plist` LaunchAgent, passing the `DATA_DIR` env var explicitly mapped to `~/.local/share/open-webui`.
  - Point `OPENAI_API_BASE_URL` to the site's LiteLLM proxy (`http://127.0.0.1:4000/v1`).
  - Use `secretspec.toml` to project `OPENAI_API_KEY` and a persistent `WEBUI_SECRET_KEY` (to prevent session invalidation on restart) into the plist via ambient env mode 0600.
- **`roles/nostr-relay/`**:
  - Deploy a lightweight local relay (e.g., `strfry` or `nostr-rs-relay`) to keep data inside the Tailscale perimeter.
  - Deploy a `com.djbclark.nostr-relay.plist` LaunchAgent.
- **`roles/buzz/`**:
  - Install the Buzz collaboration service (treat native bootstrap vs Docker Compose as a decision point for the scaffolding phase).
  - Deploy a `com.djbclark.buzz.plist` LaunchAgent.
  - Configure Buzz with a Nostr keypair (treated as a secretspec secret) and point it to the local Nostr relay.

## 3. Caddy Reverse Proxy Routing
Do not hand-edit a monolithic Caddyfile. Add a fragment under `generated/stayturgid/fragments/caddy/` (or amend the stayturgid one):
- Route `/chat/*` to Open WebUI on `127.0.0.1:8085`. Set the `WEBUI_BASE_URL` environment variable or use Caddy's `handle_path` to strip the prefix to avoid SPA asset 404s.
- Route `/buzz/*` to Buzz on `127.0.0.1:8086`.
- Add a route for the Nostr relay on `127.0.0.1:8087` so devices can sync over the tailnet.
- *(Alternative: consider Tailscale MagicDNS subdomains instead of subpaths if asset resolution becomes problematic).*

## 4. OliveTin Dashboard Actions
Expose operational actions to the user dashboard by appending to `olivetin/user-actions.yaml`, mirroring the existing `user_litellm_*` entries (PATH exports, health curls):
- `user_openwebui_restart` / `user_buzz_restart` / `user_relay_restart`: Executes `launchctl kickstart -k gui/$(id -u)/com.djbclark.[service]`
- `user_openwebui_status` / `user_buzz_status` / `user_relay_status`: Executes `launchctl print gui/$(id -u)/com.djbclark.[service] | head`
- `user_openwebui_logs` / `user_buzz_logs` / `user_relay_logs`: Executes `tail -n 50` against the `StandardOutPath` and `StandardErrorPath` files defined in their `.plist` configurations to expose application-level errors.

## 5. Security & Secret Management
- Do not commit any Nostr nsec keys or LiteLLM master keys. 
- Ensure all services bind exclusively to `127.0.0.1` — preventing data from leaving the Tailscale perimeter without Caddy's auth layer.
- Ensure all secrets are passed exclusively via `secretspec run`.

## Execution Steps
1. Update this plan file (`docs/plans/site-djbclark-open-webui-buzz-v1.md`).
2. Update both registries (`registry/ports.yml` and `registry/paths.yml`) to pass `just lint`.
3. Scaffold `roles/open-webui`, `roles/nostr-relay`, and `roles/buzz` following the LiteLLM role pattern.
4. Update `secretspec.toml` schema for new required keys (`WEBUI_SECRET_KEY`, Buzz `nsec`).
5. Add the Caddy fragment and apply OliveTin configurations.
6. Verify via `just lint` and `just ops-release-deploy`.
