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
site-sync *args:
    STAYTURGID_SITE_DIR="{{ site_dir }}" just --justfile "{{ stayturgid_root }}/justfile" site-sync dir="{{ site_dir }}" {{ args }}

inventory-check:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-inventory --list | jq -S .

lint:
    bin/registry_lint.py
