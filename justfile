# site-djbclark — site inventory wrapper for the stayturgid product.

set shell := ["bash", "-uc"]

# Override when the product checkout lives somewhere other than its conventional
# sibling path. The upstream justfile preserves this site's ANSIBLE_CONFIG.
ops_root := env_var_or_default("OPS_ROOT", env_var_or_default("HOME", "") + "/ops")
stayturgid_root := env_var_or_default("STAYTURGID_ROOT", ops_root + "/stayturgid")
# This site's checkout; exported so product contract tooling (site-sync,
# validate-identity) never falls back to site-* discovery, which is ambiguous
# when more than one site-* dir exists under ~/ops.
site_dir := justfile_directory()
# Site-owned roles (litellm, goose, …) first; product roles from stayturgid.
export ANSIBLE_ROLES_PATH := site_dir + "/roles:" + stayturgid_root + "/ansible/roles"
export ANSIBLE_COLLECTIONS_PATH := stayturgid_root + "/.ansible/collections:" + stayturgid_root

# Match stayturgid's `hosts` variable.
hosts := env_var_or_default("hosts", "")

# F4: exclusive lock for brew-touching operations (see bin/brew_flock.py).
# Override: SITE_BREW_LOCK=/path/to/lock just brew-lock -- …
brew_lock := env_var_or_default("SITE_BREW_LOCK", env_var_or_default("XDG_STATE_HOME", env("HOME") + "/.local/state") + "/site-djbclark/brew.lock")

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

# Audit and reconcile this site's Mac, Linux, and Android hostnames.
# This touches live hosts; follow the stayturgid device-interaction rules.
hostnames-audit:
    bin/check_hostnames.py

lint:
    bin/registry_lint.py
    python3 -m unittest discover -s tests -v

# Serialize multi-agent release cut/deploy (see docs/OPS-RELEASES.md § locking).
# State dir: ~/.local/state/site-djbclark/ (ops-release.lock + ops-release.claim.json)
ops-release-claim-status:
    bin/ops_release_lock.py claim status

# Reserve a version before tagging/publishing or deploying.
# operation: cut | deploy | hold
ops-release-claim-begin version operation="cut" *args:
    bin/ops_release_lock.py claim begin "{{ version }}" --operation "{{ operation }}" {{ args }}

ops-release-claim-end *args:
    bin/ops_release_lock.py claim end {{ args }}

ops-release-claim-wait *args:
    bin/ops_release_lock.py claim wait {{ args }}

# Run an arbitrary command under the exclusive ops-release flock.
ops-release-lock *args:
    bin/ops_release_lock.py hold {{ args }}

# Verify that all three deploy checkouts can advance to a coordinated,
# published stable release without changing them.
# Acquires exclusive flock; refuses if another live claim owns a different version.
ops-release-check version:
    bin/deploy_ops_release.py check "{{ version }}"

# Fast-forward all three clean ~/ops checkouts to one coordinated release.
# Acquires exclusive flock; optional OPS_RELEASE_REQUIRE_CLAIM=1 enforces claim.
ops-release-deploy version:
    bin/deploy_ops_release.py deploy "{{ version }}"

# Fail if deployed code/config is ahead of its latest coordinated release.
# site-private may be ahead only by memory/ data commits.
ops-release-status:
    bin/deploy_ops_release.py status

# Sync site-private's live memory only when all remote post-release changes
# are confined to memory/. This replaces a raw git pull in ~/ops/site-private.
ops-memory-sync:
    bin/deploy_ops_release.py memory-sync

# Install/configure loopback LiteLLM (E1 + E4 keys + E5 multi-host).
# Default limit mac (live). Other hosts: --limit mac-mini-intel|vps-primary|site_litellm
# Keys: human/API-KEYS-E4.md — never commit secrets.
# secretspec run --reason "apply LiteLLM provider keys" -- just litellm-apply
litellm_hosts := env_var_or_default("LITELLM_HOSTS", "mac")

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

# Install/configure local Hindsight memory service for #92. Opt-in and
# deliberately separate from LiteLLM; no Hermes provider mutation occurs here.
hindsight_hosts := env_var_or_default("HINDSIGHT_HOSTS", "mac")

hindsight-apply *args:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook playbooks/hindsight.yml --limit "{{ hindsight_hosts }}" {{ args }}

hindsight-check *args:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook --check playbooks/hindsight.yml --limit "{{ hindsight_hosts }}" {{ args }}

hindsight-status:
    @if launchctl print "gui/$(id -u)/com.djbclark.hindsight-api" >/dev/null 2>&1; then \
      echo "launchd: loaded (com.djbclark.hindsight-api)"; \
    else \
      echo "launchd: not loaded (com.djbclark.hindsight-api)"; \
    fi
    @curl -fsS --max-time 5 http://127.0.0.1:8888/health || echo "HTTP 8888 not responding"

# Install/configure Open WebUI.
# Default limit mac (live).
open_webui_hosts := env_var_or_default("OPEN_WEBUI_HOSTS", "mac")

open-webui-apply *args:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook playbooks/open_webui.yml --limit "{{ open_webui_hosts }}" {{ args }}

open-webui-apply-secrets *args:
    secretspec run --reason "apply Open WebUI secret" -- just open-webui-apply {{ args }}

open-webui-check *args:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook --check playbooks/open_webui.yml --limit "{{ open_webui_hosts }}" {{ args }}

open-webui-status:
    @if launchctl print "gui/$(id -u)/com.djbclark.open-webui" >/dev/null 2>&1; then \
      echo "launchd: loaded (com.djbclark.open-webui)"; \
    else \
      echo "service: not loaded on this host"; \
    fi
    @curl -fsS --max-time 5 http://127.0.0.1:8085/health || echo "HTTP 8085 not responding"

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
    @if launchctl print "gui/$(id -u)/com.djbclark.cswap-auto" >/dev/null 2>&1; then \
      echo "launchd: loaded (com.djbclark.cswap-auto)"; \
    else \
      echo "launchd: not loaded (com.djbclark.cswap-auto)"; \
    fi
    @if launchctl print "gui/$(id -u)/com.djbclark.aiuse" >/dev/null 2>&1; then \
      echo "launchd: loaded (com.djbclark.aiuse)"; \
    else \
      echo "launchd: not loaded (com.djbclark.aiuse)"; \
    fi
    @if launchctl print "gui/$(id -u)/homebrew.mxcl.jobber" >/dev/null 2>&1; then \
      echo "launchd: loaded (homebrew.mxcl.jobber)"; \
    else \
      echo "launchd: not loaded (homebrew.mxcl.jobber)"; \
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

# AI quota collectors for aiuse multi-source cross-checks (caut + OpenUsage).
# OpenUsage: brew cask (fragment brew/fragments/ai-quota-tools.yml).
# caut: cargo install from GitHub (no Homebrew formula).
install-caut:
    #!/usr/bin/env bash
    set -euo pipefail
    cargo install --locked --git https://github.com/Dicklesworthstone/coding_agent_usage_tracker
    mkdir -p "${HOME}/.local/bin"
    ln -sfn "${HOME}/.cargo/bin/caut" "${HOME}/.local/bin/caut"
    echo "caut → $(command -v caut || true)"
    caut --version

install-openusage:
    SITE_BREW_LOCK="{{ brew_lock }}" bin/brew_flock.py -- brew install --cask openusage
    @echo "Open OpenUsage once, then: Settings → Command Line → Install (for PATH CLI)."
    @echo "aiuse also uses http://127.0.0.1:6736/v1/limits while the app is running."

install-ai-quota-tools: install-openusage install-caut
    @echo "Done. Verify: just ai-quota-status"

# Full aiuse collector set: cswap, CodexBar, caut, OpenUsage, tokscale.
# Prefers repo packaging/install-deps.sh when aiuse checkout is present.
aiuse_root := env_var_or_default("AIUSE_ROOT", env("HOME") + "/src/aiuse")

install-aiuse-deps:
    #!/usr/bin/env bash
    set -euo pipefail
    script="{{ aiuse_root }}/packaging/install-deps.sh"
    if [[ -x "${script}" ]]; then
      exec "${script}"
    fi
    echo "aiuse install-deps.sh not found at ${script}; installing via just recipes…"
    just install-cswap || true
    just install-codexbar || true
    just install-tokscale || true
    just install-caut
    just install-openusage
    just aiuse-deps-status

install-cswap:
    #!/usr/bin/env bash
    set -euo pipefail
    if command -v cswap >/dev/null; then echo "cswap already on PATH"; exit 0; fi
    if command -v uv >/dev/null; then uv tool install claude-swap
    elif command -v pipx >/dev/null; then pipx install claude-swap
    else echo "need uv or pipx for claude-swap"; exit 1; fi
    mkdir -p "${HOME}/.local/bin"
    if [[ -x "${HOME}/.local/share/uv/tools/claude-swap/bin/cswap" ]]; then
      ln -sfn "${HOME}/.local/share/uv/tools/claude-swap/bin/cswap" "${HOME}/.local/bin/cswap"
    fi
    command -v cswap && cswap --version

install-codexbar:
    #!/usr/bin/env bash
    set -euo pipefail
    if command -v codexbar >/dev/null; then echo "codexbar already on PATH"; exit 0; fi
    SITE_BREW_LOCK="{{ brew_lock }}" bin/brew_flock.py -- brew install --cask codexbar
    command -v codexbar && codexbar -V || true

install-tokscale:
    #!/usr/bin/env bash
    set -euo pipefail
    if command -v tokscale >/dev/null; then echo "tokscale already on PATH"; exit 0; fi
    mkdir -p "${HOME}/.local/bin"
    printf '%s\n' '#!/usr/bin/env bash' 'exec npx --yes tokscale@latest "$@"' >"${HOME}/.local/bin/tokscale"
    chmod +x "${HOME}/.local/bin/tokscale"
    echo "tokscale → ${HOME}/.local/bin/tokscale"

ai-quota-status:
    @echo "=== caut ==="
    @command -v caut >/dev/null && caut --version || echo "MISSING (just install-caut)"
    @echo "=== openusage CLI ==="
    @command -v openusage >/dev/null && echo "on PATH: $(command -v openusage)" || echo "CLI not on PATH (install from OpenUsage Settings → Command Line)"
    @echo "=== OpenUsage.app ==="
    @test -d /Applications/OpenUsage.app && echo "installed" || echo "missing (just install-openusage)"
    @echo "=== OpenUsage HTTP :6736 ==="
    @curl -fsS --max-time 2 http://127.0.0.1:6736/v1/limits >/dev/null 2>&1 \
      && echo "responding" || echo "not responding (launch OpenUsage.app)"

aiuse-deps-status:
    #!/usr/bin/env bash
    set -euo pipefail
    script="{{ aiuse_root }}/packaging/install-deps.sh"
    if [[ -x "${script}" ]]; then
      "${script}" --check || true
    else
      echo "cswap:     $(command -v cswap || echo MISSING)"
      echo "codexbar:  $(command -v codexbar || echo MISSING)"
      echo "caut:      $(command -v caut || echo MISSING)"
      echo "openusage: $(command -v openusage || echo 'CLI missing')"
      echo "tokscale:  $(command -v tokscale || echo MISSING)"
      test -d /Applications/OpenUsage.app && echo "OpenUsage.app: installed" || echo "OpenUsage.app: MISSING"
    fi
    just ai-quota-status
# Herdr server (homebrew.mxcl.herdr) — UDS-only agent multiplexer.
# Registry: paths.yml brew_services + ~/.config/herdr/**; ports.yml UDS note.
# OliveTin: olivetin/user-actions.yaml (user_herdr_*); reproject with just site-sync.
# Docs: docs/reference/herdr-brew-service.md
herdr-status:
    @echo "=== brew services info herdr ==="
    @brew services info herdr || true
    @echo ""
    @echo "=== herdr status ==="
    @herdr status || true
    @echo ""
    @echo "=== socket ==="
    @ls -la "${HOME}/.config/herdr/herdr.sock" 2>&1 || true

herdr-start:
    brew services start herdr
    @sleep 1
    just herdr-status

herdr-stop:
    brew services stop herdr
    @sleep 1
    just herdr-status

herdr-restart:
    brew services restart herdr
    @sleep 2
    just herdr-status

herdr-reload:
    herdr server reload-config
    herdr status

# Goose/Aider Herdr agent-state prototype (site-djbclark#12). Herdr has no
# built-in "kind" for either binary, so these wrappers self-report pane
# lifecycle over `herdr pane report-agent`/`release-agent` instead of relying
# on process-name detection. Symlinks the real binaries stay untouched;
# `goose`/`aider` on PATH keep meaning the upstream CLI everywhere else.
# Docs: docs/reference/herdr-workstation.md.
herdr-agents-install:
    mkdir -p "${HOME}/.local/bin"
    ln -sfn "{{ site_dir }}/bin/herdr_agent_wrapper.py" "${HOME}/.local/bin/herdr_agent_wrapper.py"
    ln -sfn "{{ site_dir }}/bin/herdr-goose" "${HOME}/.local/bin/herdr-goose"
    ln -sfn "{{ site_dir }}/bin/herdr-aider" "${HOME}/.local/bin/herdr-aider"
    @echo "herdr-goose → $(command -v herdr-goose || true)"
    @echo "herdr-aider → $(command -v herdr-aider || true)"
    @echo "Add the [[keys.command]] launcher entries from docs/reference/herdr-workstation.md to ~/.config/herdr/config.toml, then: hreload"

# F2: re-survey homebrew.mxcl services (read-only). Audit doc:
# docs/relay/audits/F2-brew-services-audit.md — decisions: human/F2-BREW-SERVICES-DECISIONS.md
brew-services-audit:
    @echo "=== brew services list ==="
    @brew services list
    @echo ""
    @echo "=== launchctl homebrew.mxcl.* ==="
    @launchctl list 2>/dev/null | rg 'homebrew\.mxcl' || true
    @echo ""
    @echo "=== listeners (postgres/redis/mysql/et ports) ==="
    @lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | rg -i 'postgres|redis|mysql|maria|etserver|:6379|:5432|:3306|:2022' || true
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
    @for f in et postgresql@14 postgresql@18 redis mariadb herdr; do \
      if brew list --formula "$$f" >/dev/null 2>&1; then echo "INSTALLED $$f"; else echo "ABSENT   $$f"; fi; \
    done
    @echo "omlx: intentionally absent (removed 2026-07-29)"
    @echo ""
    @echo "Full write-up: docs/relay/audits/F2-brew-services-audit.md"

# Full procedure — exact Arq glob/regex exclusions, pitfalls, verification —
# lives in the system-maintenance skill at
# ~/.hermes/skills/system-maintenance/SKILL.md (out of tree). Background:
# memory/project_arq_backup_paused.md in site-private.
# Replaces the old cache-cleaner.
# Reclaim disk space: APFS local snapshots + brew cache.
maintenance:
    @echo "=== system-maintenance ==="
    @echo "Full procedure: ~/.hermes/skills/system-maintenance/SKILL.md"
    tmutil thinlocalsnapshots / 200000000000 || true
    brew cleanup -s --prune=all
    @echo ""
    @echo "Not automated — run manually if still short on space:"
    @echo "  - Arq: Clear Cache (UI)"
    @echo "  - OmniDiskSweeper"
    @echo "  - colima prune"
    @echo ""
    @echo "Verify: df -h /System/Volumes/Data && tmutil listlocalsnapshots /"
    @echo "Also confirm Arq's exclusions are still present in the UI — they"
    @echo "are set by hand and are not asserted by anything in this repo."
ralph_herdr_supervisor = "$(dirname "$0")/ralph_herdr_supervisor.py"
