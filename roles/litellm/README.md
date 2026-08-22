# LiteLLM role

This role renders the current Auto Router v2 configuration and keeps the
**loopback-only** proxy running as:

| OS | Service | Unit path |
| --- | --- | --- |
| Darwin | LaunchAgent `com.<site_ns>.litellm` | `~/Library/LaunchAgents/…plist` |
| Linux | systemd **user** unit `com.<site_ns>.litellm.service` | `~/.config/systemd/user/…service` |

Port **4000** on `127.0.0.1` (registry: `litellm-proxy` per host).

## The install is NOT managed by this role

Since 2026-08-21 LiteLLM runs from a **git checkout** — a fork of
`BerriAI/litellm` at `~/src/litellm` — so provider work done here can be
contributed upstream. It is installed by hand:

```bash
uv tool install --editable "$HOME/src/litellm[proxy,caching]"
```

That keeps the same `~/.local/bin/litellm` shim the service unit already
points at, so the unit itself is unchanged.

This role deliberately performs **no install step**. It previously ran
`uv tool install <pypi-spec>`, including a "repair" task that reinstalled
whenever the version floor or the `diskcache` import check failed — which
would silently replace the editable checkout with an upstream PyPI build and
drop any fork-only provider, with no error surfaced anywhere. Ansible has no
way to express a git-checkout source today, so the install lives outside it.

What the role does instead is *verify*, failing loudly with remediation
instructions if any of these drift:

- `litellm --version` runs and meets `litellm_minimum_version`
- the tool environment's `litellm` package still resolves to
  `{{ litellm_source_dir }}/litellm` (this is the guard that catches a PyPI
  reinstall)
- `import diskcache` succeeds in the tool environment

The prerelease floor is deliberate: on 2026-07-20 PyPI's newest stable release
is 1.93.0, while Auto Router v2 first appears in the 1.94 train and the newest
published build is 1.94.0rc1. Upgrade within the 1.94+ line when stable ships;
do not rewrite the configuration to the older router syntax.

The `caching` extra is required in addition to `proxy`: LiteLLM's disk-cache
backend imports the separately packaged `diskcache` dependency at startup.

## Multi-host inventory (E5)

Hosts live under inventory group **`site_litellm`** (must match
`registry/ports.yml` keys):

| Host | Arch note | Status (E5) |
| --- | --- | --- |
| `m1-air` | Apple Silicon; Homebrew `/opt/homebrew` | **online** (default apply) |
| `mac-mini-intel` | Intel; Homebrew `/usr/local` | `offline_unprovisioned` |
| `vps-primary` | Linux; systemd user unit | `offline_unprovisioned` |

Planned hosts set `site_host_status: offline_unprovisioned` so the role
`meta: end_host`s without SSH. When a host joins the tailnet:

1. Set `ansible_host` to its Tailscale IP or MagicDNS name.
2. Clear or set `site_host_status: online`.
3. Flip the host's port registry `status` from `planned` → `active` after
   first successful apply.
4. Apply with keys (from the control node or on-host SecretSpec):

   ```bash
   LITELLM_HOSTS=mac-mini-intel sudo-secretspec run --reason "LiteLLM mini" -- just litellm-apply
   # or: just litellm-apply -- --limit vps-primary
   ```

Homebrew prefix follows the stayturgid `stayturgid_homebrew_prefix` pattern
(arm64/aarch64 → `/opt/homebrew`, else `/usr/local`). Do not hardcode only
`/opt/homebrew`.

**Bind policy:** loopback remains the default until a multi-host design
explicitly chooses Tailscale-only **and** a master key / auth story. No public
bind without auth. Preserve REVIEW-1: do not casually open OliveTin/VM.

## Apply and inspect

```bash
# Default: m1-air only (safe; does not attempt offline mini/VPS)
just litellm-apply
just litellm-check
just litellm-status

# All inventory members (skips offline_unprovisioned; fails on bad SSH if online)
LITELLM_HOSTS=site_litellm just litellm-apply

# Secrets via sudo-secretspec (E4 pattern)
sudo-secretspec run --reason "apply LiteLLM provider keys" -- just litellm-apply
# or: just litellm-apply-secrets
```

### API Keys – Human Step (E4 + multi-host)

Provider completions need real keys. **Never commit keys.** Full operator
checklist: [`human/API-KEYS-E4.md`](../../human/API-KEYS-E4.md) (includes E5
per-host notes).

1. No provider config to set up — `sudo-secretspec` resolves everything from
   its own vault automatically. There is no `~/.config/secretspec/config.toml`
   to maintain and no manifest path to specify.

2. Set each key through the broker (each prompts for the value, no echo):

   ClinePass is the only backend this proxy serves, so `CLINE_API_KEY` is the
   only key it needs. (It is already declared and set; this is the rotation
   command, not a first-run step. The five other provider keys this list used
   to carry were dropped on 2026-08-21 along with their `model_list` entries.)

   ```bash
   sudo-secretspec set CLINE_API_KEY --reason "LiteLLM provider key"
   sudo-secretspec check --reason "verify LiteLLM provider keys" </dev/null
   ```

3. Inject at apply time (keys are not read live from the broker by the
   daemon). Values render only into the mode-0600 LaunchAgent or systemd
   unit:

   ```bash
   sudo-secretspec run --reason "apply LiteLLM provider keys" -- just litellm-apply
   ```

4. Verify (expect 200 once the matching key is in the unit):

   ```bash
   curl -fsS http://127.0.0.1:4000/v1/models | jq -r '[.data[].id]|join(",")'
   # Expect exactly: clinepass-deepseek,clinepass-minimax-m3,clinepass-kimi-k3
   # There is no fallback chain, so a failure here is a real ClinePass failure
   # and never a silent substitution by another provider.
   curl -fsS http://127.0.0.1:4000/v1/chat/completions \
     -H 'Content-Type: application/json' \
     -d '{"model":"clinepass-deepseek","messages":[{"role":"user","content":"ping"}]}'
   # Linux logs: ~/.local/state/litellm/logs/stderr.log
   ```

The proxy has no master key while it is bound to loopback. Add authentication
before any Tailscale bind or multi-user access.

### Linux host prerequisites (operator)

- `uv` on the host (`~/.local/bin/uv` or distro package).
- User systemd available; for boot without interactive login once:

  ```bash
  loginctl enable-linger "$USER"
  ```

- Prefer Tailscale for SSH management; still keep LiteLLM on `127.0.0.1`
  until auth is designed.

**Cold start / heal:** first launchd boot can take ~30–90s of Python import
before `:4000` listens. After missing-key completion storms, stderr can grow
large and the process can wedge — heal and rotate logs if needed:

```bash
# Darwin
UID_N=$(id -u)
launchctl bootout "gui/${UID_N}/com.djbclark.litellm"
launchctl bootstrap "gui/${UID_N}" \
  "$HOME/Library/LaunchAgents/com.djbclark.litellm.plist"

# Linux
systemctl --user restart com.djbclark.litellm.service
```

## Routing and cache

Since 2026-08-21 the proxy serves ClinePass only and has **no fallback
chain**. The former `smart-router` Auto Router v2 alias and the DeepSeek /
OpenRouter / OpenCode-Zen / OpenAI / Anthropic / Gemini entries were all
removed. On 2026-08-22 two more ClinePass models (`clinepass-minimax-m3`,
`clinepass-kimi-k3`) joined `clinepass-deepseek` so Hermes's non-streaming
MoA slots could leave the pay-per-token DeepSeek account; all three entries
reach the same subscription through the same key, so the single-provider
safety property is unchanged.

That is a safety property, not just simplification. LiteLLM's router silently
falls back whenever a model's `api_key` env var is unset or empty, with no
error surfaced to the caller — on 2026-08-02 this proxy served `claude-sonnet-5`
and `gpt-4o` requests from `google/gemini-3.5-flash-lite` via OpenRouter, and
`gpt-5.5`/`gpt-4o-mini`/`gemini-flash` from opencode-zen, spending real prepaid
balance while returning plausible responses. With a single model and no
fallbacks there is nothing to silently substitute. Do not re-add a fallback
chain without reading `templates/litellm-config.yaml.j2`'s header.

ClinePass is reached through the LiteLLM **git checkout**'s `clinepass`
provider module (`litellm/llms/clinepass/`), which unwraps Cline's
`{"data": {"choices": …}}` non-streaming response envelope and re-adds the
`modelType/` qualifier LiteLLM strips from the model id. Streaming responses are
not enveloped, so they need neither. A stock PyPI LiteLLM does not have that
provider — which is what the tool-install drift guard in `tasks/main.yml`
exists to catch.

Note the two prefixes are **different strings** and it matters:

| Prefix | Whose it is | Where it appears |
|---|---|---|
| `clinepass/` | LiteLLM's provider routing prefix | `model:` in this role's config; stripped before the HTTP request is built |
| `cline-pass/` | Cline's catalog namespace | re-added by the provider module on the outbound request |

Until 2026-08-22 the module re-added `clinepass/`, a namespace that does not
exist. It failed **silently** because the API validates only the *shape* of a
model id — `totallybogus/deepseek-v4-flash` also returns HTTP 200. It was not
harmless, though: an unrecognised namespace resolved `deepseek-v4-flash` to the
date-pinned `deepseek/deepseek-v4-flash-0731`, while the correct `cline-pass/`
resolves it to `deepseek/deepseek-v4-flash`. So this proxy was quietly serving
a different model snapshot than the one Hermes talks to. Verified against the
live API and fixed in the fork; do not "simplify" the two prefixes back into
one.

Responses are cached on disk under `~/.litellm/cache` for one hour.

## Rollback

Stop the service without deleting configuration or cache:

```bash
# Darwin
launchctl bootout gui/$(id -u)/com.djbclark.litellm

# Linux
systemctl --user stop com.djbclark.litellm.service
systemctl --user disable com.djbclark.litellm.service
```

Re-bootstrap:

```bash
# Darwin
launchctl bootstrap gui/$(id -u) \
  ~/Library/LaunchAgents/com.djbclark.litellm.plist

# Linux
systemctl --user enable --now com.djbclark.litellm.service
```
