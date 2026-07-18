# NEXT: B1 — Site inventory tree + ansible.cfg + justfile wrapper   (difficulty 45/100)

**Recommended AI:** Codex (gpt-5.x-codex, high reasoning — quota abundant as of 2026-07-18) · alt: Claude Sonnet 5 or Copilot premium (Sonnet/GPT-5 class) · escalate to: Claude Fable 5 (low effort)
**Working dir:** `/Users/djbclark/ops/site-djbclark`   **Operator gate:** none for B1 (read-only toward stayturgid)

---
You are a junior developer AI working on a two-repo Ansible system:
`~/ops/stayturgid` (public product repo — android fleet management) and
`~/ops/site-djbclark` (private site repo — the operator's identity, registries,
and site config). You are executing **step B1** of a phased plan. Do not make
architecture decisions; the specs below are authoritative.

> **Consolidation note (2026-07-18):** stayturgid master now contains the
> merged platform-arch / logging / just-standardization work (identity
> validator, Ansible-managed vector+openobserve, structured device logging,
> standardized just recipes). See step2 plan §2.5. This does not change B1's
> task, but `just validate-identity` now exists — do not "fix" its warnings
> in this session (that is step B5).

## Read first (in this order)

1. `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
   — §0 ground rules, §1 model routing, §2 risk register, §3 row B1.
2. `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step1-segmentation-architecture-v1.md`
   — the architecture you are implementing (skim §3, §4).
3. `/Users/djbclark/ops/stayturgid/docs/architecture/multi-site-topology.md` §4
   — the upstream/site split this step begins.
4. `/Users/djbclark/ops/site-djbclark/registry/ports.yml` and `paths.yml`
   — allocation authorities (B1 should not need new ports/paths).

## Task (B1): create the site-side inventory, copying — NOT moving

Everything below happens in `/Users/djbclark/ops/site-djbclark`. **Do not
modify anything under `/Users/djbclark/ops/stayturgid` in this step** —
upstream removal is step B2, a separate session.

1. Create `inventory/` by copying from the product repo:
   - `~/ops/stayturgid/ansible/inventory/hosts.yml` → `inventory/hosts.yml`
   - the entire `~/ops/stayturgid/ansible/inventory/group_vars/` →
     `inventory/group_vars/` (copy ALL files, including the generic taxonomy
     ones — deduplication of generic vs site vars is deliberately deferred
     to B2, because Ansible auto-loads group_vars relative to the inventory
     source and the split mechanics get decided there; record this in the
     B2 prompt when you write it).
2. Create `ansible.cfg` at the site repo root, mirroring the upstream
   `~/ops/stayturgid/ansible/ansible.cfg` settings but with:
   - `inventory = inventory/hosts.yml`
   - `roles_path = /Users/djbclark/ops/stayturgid/ansible/roles`
   - `collections_path = /Users/djbclark/ops/stayturgid/.ansible/collections:/Users/djbclark/ops/stayturgid`
   - keep `host_key_checking = False`, `retry_files_enabled = False`,
     `interpreter_python = auto_silent`, `[ssh_connection] pipelining = True`.
3. Create a `justfile` at the site repo root with at least:
   - `deploy hosts=<h>`: runs
     `ANSIBLE_CONFIG=$PWD/ansible.cfg ansible-playbook /Users/djbclark/ops/stayturgid/ansible/playbooks/site.yml` with the hosts limit the upstream justfile uses (inspect `~/ops/stayturgid/justfile` + `just/fleet.just` for the exact variable it passes — match it, do not invent a new one)
   - `inventory-check`: the verification command below
   - `lint`: runs `bin/registry_lint.py`
4. Commit on `master` with a clear message; push to origin.

## Verification (run all; paste outputs for the human)

```bash
cd ~/ops/site-djbclark
ANSIBLE_CONFIG=$PWD/ansible.cfg ansible-inventory --list | jq -S . > /tmp/site-inv.json
cd ~/ops/stayturgid
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-inventory --list | jq -S . > /tmp/product-inv.json
diff /tmp/site-inv.json /tmp/product-inv.json && echo "INVENTORIES IDENTICAL"
cd ~/ops/site-djbclark && uv run bin/registry_lint.py
```

## Human-verification checklist (present with evidence; wait for confirmation)

- [ ] `diff` says INVENTORIES IDENTICAL (byte-identical normalized JSON)
- [ ] `just --list` in site-djbclark shows deploy / inventory-check / lint
- [ ] registry lint passes
- [ ] Nothing under `~/ops/stayturgid` changed (`git -C ~/ops/stayturgid status --short` is clean apart from pre-existing untracked `.claude/`)
- [ ] site-djbclark committed and pushed

## End of session

Follow `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` exactly:
after the human confirms the checklist, append the LEDGER line, rewrite
`docs/relay/NEXT-PROMPT.md` for **step B2** (from the step2 plan §3 row B2 —
recommended AI Codex high; include the deferred group_vars-deduplication
nuance above and B2's own verification), commit, push, and print the new
prompt in chat. If blocked twice on the same error, use protocol ending B
(escalation to Fable 5 low) instead.
