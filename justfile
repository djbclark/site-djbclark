# site-djbclark — site inventory wrapper for the stayturgid product.

set shell := ["bash", "-uc"]

# Override when the product checkout lives somewhere other than its conventional
# sibling path. The upstream justfile preserves this site's ANSIBLE_CONFIG.
stayturgid_root := env_var_or_default("STAYTURGID_ROOT", "/Users/djbclark/ops/stayturgid")

# Match stayturgid's `hosts` variable.
hosts := env_var_or_default("hosts", "")

# This site's checkout; exported so product contract tooling (site-sync,
# validate-identity) never falls back to site-* discovery, which is ambiguous
# when more than one site-* dir exists under ~/ops.
site_dir := justfile_directory()

# F4: exclusive lock for brew-touching operations (see bin/brew_flock.py).
# Override: SITE_BREW_LOCK=/path/to/lock just brew-lock -- …
brew_lock := env_var_or_default("SITE_BREW_LOCK", "/tmp/site-djbclark-brew.lock")

deploy:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" STAYTURGID_ROOT="{{ stayturgid_root }}" STAYTURGID_SITE_DIR="{{ site_dir }}" hosts="{{ hosts }}" just --justfile "{{ stayturgid_root }}/justfile" deploy

deploy-check:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" STAYTURGID_ROOT="{{ stayturgid_root }}" STAYTURGID_SITE_DIR="{{ site_dir }}" hosts="{{ hosts }}" just --justfile "{{ stayturgid_root }}/justfile" deploy-check

dryrun-termux:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" STAYTURGID_ROOT="{{ stayturgid_root }}" STAYTURGID_SITE_DIR="{{ site_dir }}" hosts="{{ hosts }}" just --justfile "{{ stayturgid_root }}/justfile" dryrun-termux

# Re-render generated/stayturgid/ from the product checkout (Site Contract v1).
# Extra args pass through: just site-sync mode=dry-run
# Always export STAYTURGID_SITE_DIR so product tooling never falls back to
# ambiguous site-* discovery under ~/ops.
site-sync *args:
    STAYTURGID_SITE_DIR="{{ site_dir }}" just --justfile "{{ stayturgid_root }}/justfile" site-sync dir="{{ site_dir }}" {{ args }}

# Activate serverapp adapters (Phase D). Exports STAYTURGID_SITE_DIR.
# Extra args: just site-serverapps mode=dry-run apps=caddy
site-serverapps *args:
    STAYTURGID_SITE_DIR="{{ site_dir }}" just --justfile "{{ stayturgid_root }}/justfile" site-serverapps dir="{{ site_dir }}" {{ args }}

# Landing page (Phase D4: com.djbclark.landing). Exports site-namespace labels.
landing-status:
    LANDING_LABEL=com.djbclark.landing LANDING_DISCOVER_LABEL=com.djbclark.landing-discover \
      just --justfile "{{ stayturgid_root }}/justfile" landing-status

landing-discover:
    STAYTURGID_SITE_DIR="{{ site_dir }}" just --justfile "{{ stayturgid_root }}/justfile" landing-discover

inventory-check:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-inventory --list | jq -S .

lint:
    bin/registry_lint.py

# Install/configure loopback LiteLLM (E1 + E4 keys + E5 multi-host).
# Default limit m1-air (live). Other hosts: --limit mac-mini-intel|vps-primary|site_litellm
# Keys: human/API-KEYS-E4.md — never commit secrets.
# secretspec run --reason "apply LiteLLM provider keys" -- just litellm-apply
litellm_hosts := env_var_or_default("LITELLM_HOSTS", "m1-air")

litellm-apply *args:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook playbooks/litellm.yml --limit "{{ litellm_hosts }}" {{ args }}

# Apply with SecretSpec injection from site .env (requires TELEGRAM_BOT_TOKEN
# resolved because it is required in secretspec.toml; OPENAI/ANTHROPIC optional
# until set). Same limit as litellm-apply (LITELLM_HOSTS / default m1-air).
litellm-apply-secrets *args:
    secretspec run --reason "apply LiteLLM provider keys" -- just litellm-apply {{ args }}

litellm-check *args:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook --check playbooks/litellm.yml --limit "{{ litellm_hosts }}" {{ args }}

# Local host status (Air). Remote: ssh + curl loopback on that host, or
# LITELLM_HOSTS=mac-mini-intel just litellm-status after it is online.
litellm-status:
    @if launchctl print "gui/$(id -u)/com.djbclark.litellm" >/dev/null 2>&1; then \
      echo "launchd: loaded (com.djbclark.litellm)"; \
    elif systemctl --user is-active com.djbclark.litellm.service >/dev/null 2>&1; then \
      echo "systemd-user: active (com.djbclark.litellm.service)"; \
    else \
      echo "service: not loaded on this host"; \
    fi
    @curl -fsS --max-time 5 http://127.0.0.1:4000/v1/models | jq -r '"models: " + ([.data[].id] | join(", "))'

# Install/configure Goose Desktop + CLI against loopback LiteLLM (Phase E2).
# Holds the site brew flock (F4) because the role may brew install cask/formula.
goose-apply *args:
    SITE_BREW_LOCK="{{ brew_lock }}" bin/brew_flock.py -- env ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook playbooks/goose.yml {{ args }}

goose-check:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook --check playbooks/goose.yml

goose-status:
    @test -d /Applications/Goose.app && echo "app: /Applications/Goose.app" || echo "app: missing"
    @goose --version
    @goose info -v 2>/dev/null | rg -i 'config yaml|goose_provider|goose_model|active_provider|litellm-local|smart-router|filesystem|fieldy|extensions:' || true
    @stat -f '%Sp %N' ~/.config/goose ~/.config/goose/config.yaml ~/.config/goose/custom_providers/litellm-local.json 2>/dev/null || true

# Control-node maintenance LaunchAgents (Phase F1): system-state-backup +
# hibernate-disk-check. No secrets; localhost only.
site-agents-apply *args:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook playbooks/site_agents.yml {{ args }}

site-agents-check *args:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook --check playbooks/site_agents.yml {{ args }}

site-agents-status:
    @if launchctl print "gui/$(id -u)/com.djbclark.system-state-backup" >/dev/null 2>&1; then \
      echo "launchd: loaded (com.djbclark.system-state-backup)"; \
    else \
      echo "launchd: not loaded (com.djbclark.system-state-backup)"; \
    fi
    @if launchctl print "gui/$(id -u)/com.djbclark.hibernate-disk-check" >/dev/null 2>&1; then \
      echo "launchd: loaded (com.djbclark.hibernate-disk-check)"; \
    else \
      echo "launchd: not loaded (com.djbclark.hibernate-disk-check)"; \
    fi

# ---------------------------------------------------------------------------
# F4 — Merged-Brewfile projection + flock serialization (step1 §4.3)
# Fragments: brew/fragments/*.yml  Projection: generated/Merged-Brewfile
# Docs: brew/README.md
# Never runs brew bundle cleanup / mass uninstall (operator gate only).
# ---------------------------------------------------------------------------

# Write generated/Merged-Brewfile from brew/fragments/*.yml (idempotent).
brew-project:
    bin/project_merged_brewfile.py project

# Project then diff against system-state Brewfile snapshot (read-only).
# Extra args: just brew-diff -- --strict
brew-diff *args:
    bin/project_merged_brewfile.py both {{ args }}

# Run any command while holding the site brew exclusive lock.
# Example: just brew-lock -- brew install just
# Example: just brew-lock --nonblock -- true   # exit 75 if busy
brew-lock *args:
    SITE_BREW_LOCK="{{ brew_lock }}" bin/brew_flock.py {{ args }}

# F2: re-survey homebrew.mxcl services (read-only). Audit doc:
# docs/relay/audits/F2-brew-services-audit.md — decisions: human/F2-BREW-SERVICES-DECISIONS.md
brew-services-audit:
    @echo "=== brew services list ==="
    @brew services list
    @echo ""
    @echo "=== launchctl homebrew.mxcl.* ==="
    @launchctl list 2>/dev/null | rg 'homebrew\.mxcl' || true
    @echo ""
    @echo "=== listeners (postgres/redis/mysql/omlx/et/ui-tars ports) ==="
    @lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | rg -i 'postgres|redis|mysql|maria|omlx|llama|etserver|:6379|:5432|:3306|:2022|:8000|:8081' || true
    @echo ""
    @echo "=== probes ==="
    @nc -z -w 2 127.0.0.1 2022 >/dev/null 2>&1 && echo "et :2022 open" || echo "et :2022 closed"
    @if command -v redis-cli >/dev/null 2>&1; then \
      echo -n "redis: "; redis-cli -h 127.0.0.1 ping 2>/dev/null || echo "unreachable"; \
      echo -n "redis DBSIZE: "; redis-cli -h 127.0.0.1 DBSIZE 2>/dev/null || true; \
    else \
      echo "redis-cli: not installed"; \
    fi
    @echo ""
    @echo "=== formula presence (key F2 candidates) ==="
    @for f in et postgresql@14 postgresql@18 redis mariadb herdr omlx; do \
      if brew list --formula "$$f" >/dev/null 2>&1; then echo "INSTALLED $$f"; else echo "ABSENT   $$f"; fi; \
    done
    @echo ""
    @echo "Full write-up: docs/relay/audits/F2-brew-services-audit.md"
