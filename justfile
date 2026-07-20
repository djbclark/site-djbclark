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
goose-apply *args:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook playbooks/goose.yml {{ args }}

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

# Immich system-domain LaunchDaemons (Phase F3). Needs become/root.
# Preferred (GUI askpass, no password on argv):
#   just immich-apply-sudo
# Or: just immich-apply -- --ask-become-pass
# Pre-F3 plists archived: docs/relay/audits/f3-immich-pre-plists/
immich-apply *args:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook playbooks/immich.yml {{ args }}

# System-domain apply using macOS GUI password dialog (bin/sudo-askpass-osascript).
immich-apply-sudo *args:
    #!/usr/bin/env bash
    set -euo pipefail
    export SUDO_ASKPASS="${SUDO_ASKPASS:-$PWD/bin/sudo-askpass-osascript}"
    BECOME_PASS="$("$SUDO_ASKPASS")"
    export ANSIBLE_BECOME_PASSWORD="$BECOME_PASS"
    unset BECOME_PASS
    # Double braces escaped for just → ansible jinja lookup
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook playbooks/immich.yml --become \
      -e "ansible_become_password={{{{ lookup('env', 'ANSIBLE_BECOME_PASSWORD') }}}}" {{ args }}
    unset ANSIBLE_BECOME_PASSWORD

immich-check *args:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook --check playbooks/immich.yml {{ args }}

immich-status:
    @echo "=== launchctl system/com.immich ==="
    @launchctl print system/com.immich 2>&1 | rg -i 'path|state|program|username|last exit|runs |pid =' || echo "(print failed or not loaded)"
    @echo "=== launchctl system/com.immich.machine-learning ==="
    @launchctl print system/com.immich.machine-learning 2>&1 | rg -i 'path|state|program|username|last exit|runs |pid =' || echo "(print failed or not loaded)"
    @echo "=== print-disabled (immich) ==="
    @launchctl print-disabled system 2>&1 | rg -i immich || echo "(none listed)"
    @echo "=== app scripts ==="
    @test -x /opt/services/immich/app/start.sh && echo "server start.sh: present" || echo "server start.sh: MISSING"
    @test -x /opt/services/immich/app/machine-learning/start.sh && echo "ml start.sh: present" || echo "ml start.sh: MISSING"
    @echo "=== ports 3001/3002/3003 ==="
    @bash -c 'for p in 3001 3002 3003; do nc -z -w 1 127.0.0.1 "$p" 2>/dev/null && echo "port $p OPEN" || echo "port $p closed"; done'
    @echo "=== HTTP health ==="
    @curl -fsS --max-time 5 http://127.0.0.1:3001/api/server/ping 2>&1 || echo "health: unreachable (expected if app absent)"

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
