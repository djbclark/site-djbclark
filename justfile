# site-djbclark — site inventory wrapper for the stayturgid product.

set shell := ["bash", "-uc"]

# Override when the product checkout lives somewhere other than its conventional
# sibling path. The upstream justfile preserves this site's ANSIBLE_CONFIG.
stayturgid_root := env_var_or_default("STAYTURGID_ROOT", "/Users/djbclark/ops/stayturgid")

# Match stayturgid's `hosts` variable.
hosts := env_var_or_default("hosts", "")

deploy:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" STAYTURGID_ROOT="{{ stayturgid_root }}" hosts="{{ hosts }}" just --justfile "{{ stayturgid_root }}/justfile" deploy

deploy-check:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" STAYTURGID_ROOT="{{ stayturgid_root }}" hosts="{{ hosts }}" just --justfile "{{ stayturgid_root }}/justfile" deploy-check

dryrun-termux:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" STAYTURGID_ROOT="{{ stayturgid_root }}" hosts="{{ hosts }}" just --justfile "{{ stayturgid_root }}/justfile" dryrun-termux

inventory-check:
    ANSIBLE_CONFIG="${ANSIBLE_CONFIG:-$PWD/ansible.cfg}" ansible-inventory --list | jq -S .

lint:
    bin/registry_lint.py
