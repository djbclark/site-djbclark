> **Amendment (2026-07-18, step1 §9):** roles are authored in this repo
> (`roles/litellm`, `roles/goose`), not a standalone `~/ai-stack/ansible`
> tree; the launchd label is `com.djbclark.litellm` (site namespace), not
> `local.litellm`; port 4000 is registered in `registry/ports.yml`; secrets
> follow the secretspec pattern. See
> `site-djbclark-step1-segmentation-architecture-v1.md`.

**Implementation Plan: Native Goose + LiteLLM Stack (Ansible + Homebrew)**

**Target machine:** Apple Silicon Mac (M1 MacBook Air)  
**Constraint:** Zero Docker / no heavy virtualization  
**Final desired state:**
- Goose Desktop + CLI installed and configured as the single pane of glass
- LiteLLM proxy running as a silent user-level `launchd` service
- LiteLLM configured with Complexity Router, budgets, fallbacks, and local disk cache
- Goose points at the local LiteLLM endpoint
- MCP servers (Shortwave, Saner.ai, Fieldy, filesystem) attached **directly** to Goose

---

### 1. High-Level Execution Order

An agent (Grok Build or equivalent) should execute these phases in order:

1. Install system prerequisites via Homebrew
2. Install Goose (Desktop + CLI)
3. Install LiteLLM in an isolated tool environment (`uv` or `pipx`)
4. Create LiteLLM config + disk cache directory
5. Create and load the `launchd` plist
6. Create Goose configuration (provider + MCP extensions)
7. Verify everything is healthy
8. Hand back to the human for API keys and first-run MCP auth

---

### 2. Recommended Directory Layout

```text
~/ai-stack/
├── ansible/
│   ├── inventory.yml
│   ├── playbook.yml
│   └── roles/
│       └── goose_litellm/
│           ├── tasks/main.yml
│           ├── templates/
│           │   ├── litellm-config.yaml.j2
│           │   ├── local.litellm.plist.j2
│           │   └── goose-config.yaml.j2   # or config.json depending on version
│           ├── defaults/main.yml
│           └── handlers/main.yml
├── secrets/                  # gitignored – human places keys here or uses Keychain
└── README.md
```

---

### 3. Core Ansible Role Tasks (`roles/goose_litellm/tasks/main.yml`)

```yaml
---
- name: Ensure Homebrew is available
  command: which brew
  register: brew_check
  changed_when: false
  failed_when: brew_check.rc != 0

- name: Update Homebrew
  homebrew:
    update_homebrew: true

- name: Install system packages
  homebrew:
    name:
      - uv                    # preferred modern Python tool runner
      - node                  # needed for many npx-based MCP servers
    state: present

- name: Install Goose Desktop
  homebrew_cask:
    name: block-goose
    state: present

- name: Install Goose CLI
  homebrew:
    name: block-goose-cli
    state: present

- name: Install LiteLLM via uv tool
  command: uv tool install "litellm[proxy]"
  args:
    creates: "{{ ansible_env.HOME }}/.local/bin/litellm"
  # Alternative if you prefer pipx: pipx install "litellm[proxy]"

- name: Create LiteLLM directories
  file:
    path: "{{ item }}"
    state: directory
    mode: "0700"
  loop:
    - "{{ ansible_env.HOME }}/.litellm"
    - "{{ ansible_env.HOME }}/.litellm/cache"
    - "{{ ansible_env.HOME }}/Library/Logs/litellm"

- name: Deploy LiteLLM config
  template:
    src: litellm-config.yaml.j2
    dest: "{{ ansible_env.HOME }}/.litellm/config.yaml"
    mode: "0600"
  notify: restart litellm

- name: Deploy launchd plist
  template:
    src: local.litellm.plist.j2
    dest: "{{ ansible_env.HOME }}/Library/LaunchAgents/local.litellm.plist"
    mode: "0644"
  notify: restart litellm

- name: Ensure Goose config directory exists
  file:
    path: "{{ ansible_env.HOME }}/.config/goose"
    state: directory
    mode: "0700"

- name: Deploy Goose configuration (provider + MCP stubs)
  template:
    src: goose-config.yaml.j2
    dest: "{{ ansible_env.HOME }}/.config/goose/config.yaml"
    mode: "0600"
  # Note: actual key path may be config.json on some versions – agent should check

- name: Load launchd service (idempotent)
  command: launchctl bootstrap gui/$(id -u) {{ ansible_env.HOME }}/Library/LaunchAgents/local.litellm.plist
  register: bootstrap
  failed_when: bootstrap.rc not in [0, 5]   # 5 = already loaded
  changed_when: bootstrap.rc == 0
```

---

### 4. Key Template Contents

**`templates/litellm-config.yaml.j2`** (minimal production-ready starting point)

```yaml
model_list:
  # Cheap tier
  - model_name: gpt-4o-mini
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY

  # Strong reasoning tier (adjust model name to whatever you currently use)
  - model_name: claude-sonnet
    litellm_params:
      model: anthropic/claude-sonnet-4-20250514   # update to current ID
      api_key: os.environ/ANTHROPIC_API_KEY

  # Complexity router – this is what Goose will call
  - model_name: smart-router
    litellm_params:
      model: auto_router/complexity_router
      complexity_router_config:
        tiers:
          SIMPLE: gpt-4o-mini
          MEDIUM: gpt-4o-mini
          COMPLEX: claude-sonnet
          REASONING: claude-sonnet
        tier_boundaries:
          simple_medium: 0.15
          medium_complex: 0.35
          complex_reasoning: 0.60
      complexity_router_default_model: gpt-4o-mini

litellm_settings:
  cache: true
  cache_params:
    type: disk
    disk_cache_dir: "{{ ansible_env.HOME }}/.litellm/cache"
    ttl: 3600

  drop_params: true
  set_verbose: false

  # Optional global budget example – tune to your monthly spend
  # max_budget: 50
  # budget_duration: 30d

router_settings:
  num_retries: 2
  timeout: 120
  fallbacks:
    - claude-sonnet: ["gpt-4o-mini"]

general_settings:
  master_key: sk-local-{{ lookup('password', '/dev/null length=24 chars=ascii_letters,digits') }}
  # Keep the master key local-only; Goose will use it or you can disable auth for localhost
```

**`templates/local.litellm.plist.j2`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>local.litellm</string>
  <key>ProgramArguments</key>
  <array>
    <string>{{ ansible_env.HOME }}/.local/bin/litellm</string>
    <string>--config</string>
    <string>{{ ansible_env.HOME }}/.litellm/config.yaml</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>4000</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{{ ansible_env.HOME }}/Library/Logs/litellm/stdout.log</string>
  <key>StandardErrorPath</key>
  <string>{{ ansible_env.HOME }}/Library/Logs/litellm/stderr.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{{ ansible_env.HOME }}/.local/bin</string>
    <!-- API keys should be injected here or loaded from a secure source -->
    <!-- Prefer using launchctl setenv or a small wrapper that reads from Keychain -->
  </dict>
</dict>
</plist>
```

**Goose provider configuration** (template should create a custom OpenAI-compatible provider pointing at `http://127.0.0.1:4000` with model `smart-router`).

MCP section example (stdio style – adjust package names to the real ones you use):

```yaml
extensions:
  - name: shortwave
    enabled: true
    transport:
      type: stdio
      command: npx
      args: ["-y", "@shortwave/mcp-server"]   # verify exact package
  - name: sanerai
    enabled: true
    transport:
      type: stdio
      command: npx
      args: ["-y", "@saner-ai/mcp-server"]
  - name: fieldy
    enabled: true
    transport:
      type: stdio
      command: python
      args: ["-m", "fieldy_mcp"]
  - name: filesystem
    enabled: true
    transport:
      type: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "{{ ansible_env.HOME }}"]
```

---

### 5. Secrets Handling (Critical)

Do **not** put real API keys in the Ansible templates or in the repo.

Recommended options (pick one):

- Human places keys in `~/.zshrc` / `~/.zprofile` and the launchd plist sources them, **or**
- Use `security` (macOS Keychain) + a tiny wrapper script that exports the keys before starting LiteLLM, **or**
- `launchctl setenv` after the service is loaded (less ideal for reboots).

The agent should leave clear placeholders and a short README section titled “API Keys – Human Step”.

---

### 6. Verification Steps (agent must run these)

```bash
# 1. LiteLLM is listening
curl -s http://127.0.0.1:4000/v1/models | head

# 2. launchd status
launchctl print gui/$(id -u)/local.litellm

# 3. Goose CLI is available
goose --version   # or block-goose / whatever the binary is named

# 4. Config files exist and are readable only by user
ls -la ~/.litellm/config.yaml
ls -la ~/Library/LaunchAgents/local.litellm.plist
```

---

### 7. Post-Ansible Human Steps

1. Add real `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` (and any others).
2. Restart the LiteLLM service:  
   `launchctl kickstart -k gui/$(id -u)/local.litellm`
3. Launch Goose Desktop → configure / select the local “smart-router” provider.
4. Authenticate the individual MCP servers (Shortwave, Saner.ai, etc.) the first time they are used.
5. Test a simple prompt and a tool-using prompt.

---

### 8. Hand-off Instructions for the Agent

You can paste something close to this to the agent:

> Implement the native Goose + LiteLLM stack on this M1 Mac exactly as described in the plan.  
> Use Homebrew for Goose (`block-goose` cask + `block-goose-cli`) and `uv tool install "litellm[proxy]"`.  
> Create an Ansible role under `~/ai-stack/ansible/roles/goose_litellm` that is fully idempotent.  
> Do not hard-code any API keys. Leave clear placeholders and a short human checklist.  
> After the playbook succeeds, run the verification commands and report the status of the LiteLLM service and Goose installation.

---

This plan is deliberately lean, fully native, and matches the architecture we settled on (Goose as client, LiteLLM as local cost/routing layer, MCP servers attached directly to Goose).
