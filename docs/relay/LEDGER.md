# Relay ledger

Append-only. One line per completed (or escalated) step. Newest last.

| Date | Step | AI | Commits / PR | Notes |
| --- | --- | --- | --- | --- |
| 2026-07-18 | setup | Claude Fable 5 (senior) | site: 01f6b7c, b1127ad; stayturgid PR #2 | Architecture, specs, registries, junior plan, relay protocol authored. Chain starts at B1 |
| 2026-07-18 | consolidation | Claude Fable 5 (senior) | stayturgid master 9651a45..f199000 | Merged PR #2 + feature/platform-arch + feature/logging + just-standardization (disk WIP recovered as 062cfac). `just check` + full `just test` green. Step2 plan §2.5 records what's now done; new steps D8/D9. Old worktrees removed |
| 2026-07-18 | branch cleanup | Claude Fable 5 (senior) | — | Deleted merged remote branches (feature/platform-arch, feature/logging, just-standardization, topology-and-secret-scrub) + stale local copies. hermes/main verified empty (0 commits off master, clean tree, no remote) — worktree ~/stayturgid-hermes and local branch deleted. Repo now: master only, local and origin |
| 2026-07-18 | B1 | Codex (gpt-5.x) | site: 9038c2d | Copied live `hosts.yml` and all `group_vars/` files to the site inventory; added the site `ansible.cfg` and thin just wrapper. Normalized inventories are byte-identical and registry lint passes. Generic `group_vars` remain duplicated intentionally: Ansible auto-loads them relative to the inventory source; B2 must preserve correct loading while completing the upstream/site split. |
| 2026-07-18 | B2 | Codex (gpt-5.x) | stayturgid: 9bd1650, PR #3 | Removed tracked production `hosts.yml` and site-only `group_vars/stayturgid.yml`; CI now creates an ignored generic example inventory before syntax/checks. Fresh-clone parsed inventory is free of live values; syntax and all `just check` components pass. `--warn-only` now correctly remains advisory for the intentionally site-incomplete example. PR #3 was open at confirmation; its merge remains external. |
