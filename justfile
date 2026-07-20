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

# Install/configure the loopback-only LiteLLM proxy (Phase E1).
# To inject provider keys after E4, wrap this recipe with SecretSpec:
# secretspec run --reason "apply LiteLLM provider keys" -- just litellm-apply
litellm-apply *args:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook playbooks/litellm.yml {{ args }}

litellm-check:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-playbook --check playbooks/litellm.yml

litellm-status:
    @launchctl print gui/$(id -u)/com.djbclark.litellm >/dev/null && echo "launchd: loaded"
    @curl -fsS http://127.0.0.1:4000/v1/models | jq -r '"models: " + ([.data[].id] | join(", "))'
