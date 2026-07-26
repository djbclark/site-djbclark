# API Keys – Human Step (Phase E4)

> **For AI agents:** Do not invent API keys or paste secret values into chat,
> ledger, or git. Point the operator here; after they set keys, re-run the
> apply/verify commands below without reading secret values.
>
> **Index:** [human/README.md](README.md) · LiteLLM:
> [roles/litellm/README.md](../roles/litellm/README.md) · Goose:
> [roles/goose/README.md](../roles/goose/README.md) · Declarations:
> [secretspec.toml](../secretspec.toml)

Last updated: **2026-07-20** (E4 + E5 multi-host notes)

This checklist is the step0 §5 / §7 human boundary for LiteLLM provider
credentials (and Fieldy OAuth). E1–E4 established the M1 Air control node;
**E5** reuses the same SecretSpec inject pattern on every host that runs
LiteLLM — do not invent a second secrets path.

**Never commit** `.env`, API keys, or OAuth tokens. Site `.gitignore` already
ignores `*.env`.

---

## 0. SecretSpec is operational (agent-verified 2026-07-20)

| Item | Expected |
| --- | --- |
| CLI | `secretspec` 0.16.x (`brew`) |
| User config | `~/.config/secretspec/config.toml` with **`[defaults]`** `provider = "dotenv"` and `profile = "default"` |
| Site store | `${OPS_ROOT:-~/ops}/site-djbclark/.env` mode **0600** (gitignored) |
| Manifest | `${OPS_ROOT:-~/ops}/site-djbclark/secretspec.toml` (declarations only; in git) |

**Important:** SecretSpec 0.16 ignores a bare top-level `provider = "dotenv"`
line. Defaults must live under `[defaults]` or `secretspec config show`
reports `Provider: (none)` and every resolve fails.

Quick checks (safe — no secret values printed):

```bash
cd ${OPS_ROOT:-/Users/djbclark/ops}/site-djbclark
secretspec config show
# Provider: dotenv  Profile: default

secretspec check -n --json | jq -r '.secrets[] | select(.name|test("OPENAI|ANTHROPIC|TELEGRAM_BOT")) | "\(.name) \(.status)"'
# Expect ANTHROPIC_API_KEY resolved when seeded; OPENAI may be missing_optional
# until you set it. TELEGRAM_BOT_TOKEN is required for any secretspec run.
```

---

## 1. Enter provider keys (you)

LiteLLM Auto Router v2 tiers (see `roles/litellm`):

| Tier | Model | Needs |
| --- | --- | --- |
| SIMPLE | `gpt-4o-mini` | `OPENAI_API_KEY` |
| MEDIUM | `gpt-4o` | `OPENAI_API_KEY` |
| COMPLEX | `claude-sonnet-5` | `ANTHROPIC_API_KEY` |
| REASONING | `gpt-5.5` | `OPENAI_API_KEY` |

### Preferred: SecretSpec CLI

```bash
cd ${OPS_ROOT:-/Users/djbclark/ops}/site-djbclark

# Prompts once; stores into dotenv ./.env (mode should stay 0600)
secretspec set OPENAI_API_KEY
secretspec set ANTHROPIC_API_KEY   # skip if already resolved

# Or one-shot from a value you type at the prompt (still never paste into chat):
# secretspec set OPENAI_API_KEY
```

### Alternate: edit the dotenv file

```bash
chmod 600 ${OPS_ROOT:-/Users/djbclark/ops}/site-djbclark/.env
${EDITOR:-nano} ${OPS_ROOT:-/Users/djbclark/ops}/site-djbclark/.env
# Add or update (values from your provider dashboards — never paste into chat/git):
#   OPENAI_API_KEY=<your-openai-key>
#   ANTHROPIC_API_KEY=<your-anthropic-key>
```

### Notes from E4 live state

- `ANTHROPIC_API_KEY` may already exist under
  `~/.config/stayturgid/anthropic.env` (older stayturgid layout). E4 seeded
  site `.env` from that file when present — do not re-paste into chat.
- `OPENAI_API_KEY` was **not** present on the control node during E4; SIMPLE /
  MEDIUM / REASONING completions stay missing-credential until you set it.
- `TELEGRAM_BOT_TOKEN` is `required = true` in `secretspec.toml` (Hermes). Any
  `secretspec run` needs it resolved (E4 seeded it from existing local dotenv
  fragments when available). Hermes is out of scope for E4; only presence is
  required so LiteLLM apply can run under SecretSpec.

Confirm presence without printing values:

```bash
cd ${OPS_ROOT:-/Users/djbclark/ops}/site-djbclark
secretspec check -n --explain | rg 'OPENAI|ANTHROPIC|TELEGRAM_BOT'
```

---

## 2. Inject keys into LiteLLM LaunchAgent

Keys are **not** read live from SecretSpec by the daemon. Ansible renders them
into `~/Library/LaunchAgents/com.djbclark.litellm.plist` (mode **0600**) from
the apply-time environment:

```bash
cd ${OPS_ROOT:-/Users/djbclark/ops}/site-djbclark
secretspec run --reason "apply LiteLLM provider keys" -- just litellm-apply
```

Equivalent without SecretSpec (if keys are already exported in your shell):

```bash
# Only if OPENAI_API_KEY / ANTHROPIC_API_KEY are already in the environment
just litellm-apply
```

After apply:

```bash
just litellm-status
# launchd: loaded
# models: gpt-4o-mini,gpt-4o,claude-sonnet-5,gpt-5.5,smart-router

# Presence only — never paste launchctl env output into chat (it prints values)
python3 - <<'PY'
import plistlib, pathlib
p = pathlib.Path.home() / "Library/LaunchAgents/com.djbclark.litellm.plist"
env = plistlib.loads(p.read_bytes()).get("EnvironmentVariables", {})
for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
    v = env.get(k)
    print(f"{k}: {'present len='+str(len(v)) if v else 'absent'}")
print("mode", oct(p.stat().st_mode & 0o777))
PY
```

**Cold start:** first launchd boot of LiteLLM can take ~30–90s of Python import
before `:4000` listens (E3/E4 observed). If `/v1/models` stalls, wait; if the
process is wedged after missing-key retry storms, heal:

```bash
UID_N=$(id -u)
launchctl bootout "gui/${UID_N}/com.djbclark.litellm"
# optional: rotate huge stderr (E3 saw 12MB+ under missing-key storms)
# mv ~/Library/Logs/litellm/stderr.log ~/Library/Logs/litellm/stderr.log.old
launchctl bootstrap "gui/${UID_N}" \
  "$HOME/Library/LaunchAgents/com.djbclark.litellm.plist"
```

---

## 3. Verify completions (after keys)

```bash
# Models always work once the proxy is up
curl -fsS http://127.0.0.1:4000/v1/models | jq -r '[.data[].id] | join(",")'

# SIMPLE — needs OPENAI_API_KEY (expect 200 after you set it)
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"smart-router","messages":[{"role":"user","content":"What is 2+2?"}],"max_tokens":16}' \
  | jq -r '.choices[0].message.content // .error.message'

# REASONING-ish multi-step — routes differently from SIMPLE (check decision log)
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"smart-router","messages":[{"role":"user","content":"Prove step by step that the halting problem is undecidable and discuss verification implications."}],"max_tokens":32}' \
  | jq -r '.choices[0].message.content // .error.message'

# Decision log (tiers should differ for SIMPLE vs REASONING)
rg 'ComplexityRouter: routing decision' ~/Library/Logs/litellm/stderr.log | tail

# COMPLEX path works with ANTHROPIC alone (E4 proven):
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"claude-sonnet-5","messages":[{"role":"user","content":"Reply with exactly the word OK"}],"max_tokens":16}' \
  | jq -r '.choices[0].message.content // .error.message'
```

Goose against loopback LiteLLM:

```bash
goose info -v | rg -i 'litellm-local|smart-router'
goose run --no-session -t "Reply with exactly the word PONG and nothing else."
```

If Goose hangs after LiteLLM is healthy, check which tier `smart-router` chose
and whether that tier’s key is in the LaunchAgent. Partial keys (Anthropic only)
mean SIMPLE Goose prompts may still fail or hang on OpenAI missing-credential
retries — prefer a COMPLEX-style prompt, or set `OPENAI_API_KEY` and re-apply.

---

## 4. Fieldy MCP — enable + browser OAuth (optional until you are ready)

Fieldy is a **real** remote MCP at `https://api.fieldy.ai/mcp` (streamable HTTP).
Default remains **disabled** so Goose sessions do not block on OAuth.

When you are ready:

1. Set in inventory/group_vars (or pass as extra-var) and re-apply Goose:

   ```bash
   # example extra-var one-shot
   just goose-apply -- -e goose_ext_fieldy_enabled=true
   ```

2. Start Goose Desktop or CLI so it loads extensions.
3. On first Fieldy tool use, complete **browser OAuth** with your Fieldy account
   email (vendor flow; tokens stay in Goose’s local state — not in git).
4. Confirm the extension shows enabled in `goose info -v` / config
   (`~/.config/goose/config.yaml`, mode 0600).

Do **not** flip the role default to `true` until OAuth succeeds on this host.

---

## 5. Explicitly out of scope (E3 research; do not invent packages)

| Product | Goose-facing MCP? | Action |
| --- | --- | --- |
| **Shortwave** | **No** — Shortwave is an MCP *client* only | Leave comment stub; no package install |
| **Saner.ai** | **No** MCP found (npm 404) | Leave comment stub; revisit if vendor ships |
| **filesystem** | Yes — already templated and enabled | First use may `npx -y` download the package |
| **Fieldy** | Yes — remote MCP; OAuth above | Enable only when ready |

---

## 6. Multi-host LiteLLM keys (E5)

Inventory group `site_litellm`: `m1-air` (online), `mac-mini-intel` and
`vps-primary` (planned / offline until you set `ansible_host` and clear
`site_host_status`). See [`roles/litellm/README.md`](../roles/litellm/README.md).

| Host | Service unit | Keys land in (mode 0600) |
| --- | --- | --- |
| `m1-air` | launchd `com.djbclark.litellm` | `~/Library/LaunchAgents/com.djbclark.litellm.plist` |
| `mac-mini-intel` | same launchd label | same path on the mini (Intel Homebrew `/usr/local`) |
| `vps-primary` | systemd user `com.djbclark.litellm.service` | `~/.config/systemd/user/com.djbclark.litellm.service` |

**Preferred:** keep one site dotenv on the control node and inject at apply
time (keys travel only into the remote unit file via Ansible, never into git):

```bash
cd ${OPS_ROOT:-/Users/djbclark/ops}/site-djbclark
# After mini/VPS are online and inventory ansible_host is set:
LITELLM_HOSTS=mac-mini-intel secretspec run --reason "LiteLLM keys mini" -- just litellm-apply
LITELLM_HOSTS=vps-primary secretspec run --reason "LiteLLM keys vps" -- just litellm-apply
```

**Alternate:** on each host, install SecretSpec, mirror `[defaults]` + a local
0600 dotenv with the same declarations, and run apply on-host. Do not commit
per-host `.env` files.

Linux once-per-host: `loginctl enable-linger "$USER"` so the user unit survives
logout. Still bind loopback only until a master-key / Tailscale auth design
exists — **no public bind**.

Verify per host (on that machine or via SSH to its loopback):

```bash
curl -fsS http://127.0.0.1:4000/v1/models | jq -r '[.data[].id]|join(",")'
# Presence only — never paste unit env output into chat
```

## 7. Record outcomes

Copy `RESPONSES.md.example` → `RESPONSES.md` (gitignored) and note, without
pasting secrets:

- [ ] `OPENAI_API_KEY` set in SecretSpec dotenv
- [ ] `ANTHROPIC_API_KEY` set / resolved
- [ ] `secretspec run --reason "…" -- just litellm-apply` succeeded
- [ ] SIMPLE + REASONING completions 200 with different router tiers in log
- [ ] `goose run` returned a model response
- [ ] Fieldy OAuth done (or deferred)
- [ ] Shortwave/Saner acknowledged as no Goose MCP
- [ ] (E5) mini/VPS: inventory online + keys applied when hosts exist

Tell the agent: _Read human/RESPONSES.md and continue._
