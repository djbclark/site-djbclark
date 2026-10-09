# research/ — live data-directory

Research and plan document packages, one subdirectory per package. This
directory is **data, not code**, like `site-private/memory/`. Update it with
direct-to-master commits made in place in `~/ops/site-djbclark` (since
2026-08-23 the whole repo is worked this way):

```bash
cd "${OPS_ROOT:-$HOME/ops}/site-djbclark"
git pull --rebase           # or `just ops-memory-sync`: fetch + rebase of
                            # site-private and site-djbclark; refuses on a dirty tree
# edit research/..., then one research-only commit, push immediately
```

The old release-flow exemption (the `DATA_DIRS` mapping in
`bin/deploy_ops_release.py`, documented in `docs/OPS-RELEASES.md`, "Live
data-directory exceptions") now matters only to the optional release tooling:
the worktree/PR/release flow was retired for the whole repo on 2026-08-23.

**This repository is public.** No secrets, no private-only context; that
material belongs in `site-private`.

## Packages

| Directory | What it is |
|---|---|
| [`autonomy/`](autonomy/) | The 2026-08-16 plan for unattended continuous AI coding (beads + ralph-orchestrator + verification judge + quota gate; zeroshot trial). Start at its `README.md`, final decisions in `04-final-plan.md`. |
| [`cfengine-community-review-coverage/`](cfengine-community-review-coverage/) | 2026-08-18 idea: whitespace-only C minification to fit more of `cfengine/core` under ultrareview's line cap, spread across contributors. **Idea stage, not started** — open premises unverified. |
| [`apply-dev-toolchain/`](apply-dev-toolchain/) | 2026-10-01 drop-in prompt (v5) that has a Claude Code orchestrator apply the stayturgid/aiuse/Graft toolchain, subagents, skills/plugins, tests, CI and CodeRabbit to another repo (currently `Kuriboh493/perp-option-pricer`). Preamble explains how to run it or cut it to a budget. |
| [`mac-tcc-boot-race/`](mac-tcc-boot-race/) | 2026-10-05 diagnosis + workaround: on macOS 27.0.1, tccd fails code-identity lookups for ~2 min after login, so apps launching in that window get TCC refusals and re-show permission dialogs despite intact grants. Includes `stagger-login`, a self-contained LaunchAgent script that delays/staggers app launches past the window (handles login items and launchd agents, with the disable/enable/kickstart/bootstrap dance). |
