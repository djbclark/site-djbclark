# site-djbclark — site inventory wrapper for the stayturgid product.

set shell := ["bash", "-uc"]

# Match stayturgid's `hosts` variable and its direct Ansible `limit_flag`.
hosts := env_var_or_default("hosts", "")
limit_flag := env_var_or_default("limit_flag", if hosts == "" { "" } else { "-l " + hosts })

deploy:
    ANSIBLE_CONFIG=$PWD/ansible.cfg ansible-playbook /Users/djbclark/ops/stayturgid/ansible/playbooks/site.yml {{ limit_flag }}

inventory-check:
    ANSIBLE_CONFIG=$PWD/ansible.cfg ansible-inventory --list | jq -S .

lint:
    bin/registry_lint.py
