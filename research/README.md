# research/ — live data-directory (release-flow exempt)

Research and plan document packages, one subdirectory per package. This
directory is **data, not code**: like `site-private/memory/`, it is exempt
from the branch/PR/worktree/release flow. Update it with direct-to-master
commits made in place in the `~/ops/site-djbclark` deploy checkout:

```bash
cd "${OPS_ROOT:-$HOME/ops}/site-djbclark"
just ops-memory-sync        # optional: fetch+rebase all three repos first
                            # (plain `git pull --rebase` here does the same)
# edit research/..., then one research-only commit, push immediately
```

The exemption is enforced by the `DATA_DIRS` mapping in
`bin/deploy_ops_release.py` and documented in `AGENTS.md` and
`docs/OPS-RELEASES.md` ("Live data-directory exceptions"). It covers this
directory only — code or config changes anywhere else still use the
worktree/PR/release flow.

**This repository is public.** No secrets, no private-only context; that
material belongs in `site-private`.

## Packages

| Directory | What it is |
|---|---|
| [`autonomy/`](autonomy/) | The 2026-08-16 plan for unattended continuous AI coding (beads + ralph-orchestrator + verification judge + quota gate; zeroshot trial). Start at its `README.md`, final decisions in `04-final-plan.md`. |
| [`cfengine-community-review-coverage/`](cfengine-community-review-coverage/) | 2026-08-18 idea: whitespace-only C minification to fit more of `cfengine/core` under ultrareview's line cap, spread across contributors. **Idea stage, not started** — open premises unverified. |
