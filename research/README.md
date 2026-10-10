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
| [`apply-dev-toolchain/`](apply-dev-toolchain/) | **Moved 2026-10-09** to [`djbclark-ade/docs/apply-toolchain-prompt.md`](https://github.com/djbclark/djbclark-ade/blob/master/docs/apply-toolchain-prompt.md) (v5.1). The directory holds only a pointer. |
| [`mac-tcc-boot-race/`](mac-tcc-boot-race/) | 2026-10-05 diagnosis + workaround: on macOS 27.0.1, tccd fails code-identity lookups for ~2 min after login, so apps launching in that window get TCC refusals and re-show permission dialogs despite intact grants. Includes `stagger-login`, a self-contained LaunchAgent script that delays/staggers app launches past the window (handles login items and launchd agents, with the disable/enable/kickstart/bootstrap dance). |
| [`acp-trial/`](acp-trial/) | 2026-10-03 trial: should headless delegation to other agent CLIs use the Agent Client Protocol instead of each CLI's `-p`/`run` mode? Harness, fixture and results. |
| [`orca-vs-herdr/`](orca-vs-herdr/) | 2026-10-08 verdict: after the move to ACP (`acp-run`) in herdr panes, does Orca still earn its place? |
| [`src-navigation-view/`](src-navigation-view/) | 2026-10-06 research behind `tools/s-farm` (the symlink farm at `~/s`): prior art and the virtual-filesystem question. |
