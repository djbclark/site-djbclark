# Coordinated ops releases

The three repositories under `${OPS_ROOT:-~/ops}` are one deployed suite:

- `stayturgid`
- `site-djbclark`
- `site-private`

Development continues on `master` in task workspaces under
`~/src/ops-worktrees/`. Deployment checkouts do **not** pull arbitrary
`master` commits. They advance only to a coordinated, published stable GitHub
release named `ops-vMAJOR.MINOR.PATCH`.

## Release contract

Every coordinated release has all of the following:

1. The same annotated `ops-vMAJOR.MINOR.PATCH` tag in all three repositories.
2. A published, non-draft, non-prerelease GitHub Release for that tag in all
   three repositories.
3. An `ops-release.json` at each tagged commit whose `suite` is
   `djbclark-ops` and whose `version` exactly matches the tag.
4. Merged review PRs and green repository-specific checks before any tag is
   created.

Tags are immutable. Never retag or force-push a release. Rollback is a new
patch release that reverts the bad change, so deployment history remains
forward-only and auditable.

`stayturgid/version.json` is the older on-device fleet-content notifier. It is
independent of the coordinated suite version in `ops-release.json`.

## Cutting a release

1. Choose the next semantic version.
2. Update `ops-release.json` to that version in all three task worktrees.
3. Run each repository's checks, open PRs, and obtain operator confirmation
   before merging.
4. Confirm all three `master` branches are clean, synchronized, and contain
   the intended commits.
5. Create and push the same annotated tag in each repository:

   ```bash
   git tag -a ops-v1.0.0 -m "djbclark ops 1.0.0"
   git push origin ops-v1.0.0
   ```

6. Create the three stable GitHub Releases with concise, repository-specific
   notes:

   ```bash
   gh release create ops-v1.0.0 --verify-tag --title "djbclark ops 1.0.0"
   ```

If tag or release creation fails partway through, stop. Do not deploy a
partial suite. Remove only the newly created incomplete release/tag, after
resolving its exact scope, then retry the coordinated cut.

## Deploying

From the released `site-djbclark` checkout:

```bash
cd "${OPS_ROOT:-$HOME/ops}/site-djbclark"
just ops-release-check 1.0.0
just ops-release-deploy 1.0.0
just ops-release-status
```

The deploy command preflights all three repositories before changing any:

- checkout is clean and on local `master`;
- tag exists, declares the requested version, and is reachable from
  `origin/master`;
- matching stable GitHub Release exists;
- update is a fast-forward from the current deployed commit.

It then fast-forwards each local `master` only to the tag commit, even when
`origin/master` contains newer unreleased work.

For the initial `ops-v1.0.0` bootstrap, run the same script from the
synchronized source baseline after merging and publishing:

```bash
python3 ~/src/ops-worktrees/main/site-djbclark/bin/deploy_ops_release.py \
  --ops-root "${OPS_ROOT:-$HOME/ops}" check 1.0.0
python3 ~/src/ops-worktrees/main/site-djbclark/bin/deploy_ops_release.py \
  --ops-root "${OPS_ROOT:-$HOME/ops}" deploy 1.0.0
```

## Live memory exception

`site-private/memory/` remains live data committed directly to `master`.
Agents must run:

```bash
cd "${OPS_ROOT:-$HOME/ops}/site-djbclark"
just ops-memory-sync
```

before writing memory. The command fetches `site-private` and refuses to sync
if any remote change since its latest coordinated release touches a path
outside `memory/`. This prevents an ordinary memory rebase from silently
deploying unreleased code or configuration.

After the guarded sync, make one memory-only commit, push immediately, and
leave the tree clean. `just ops-release-status` permits `site-private` to be
ahead of its release only by `memory/` paths.
