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

## Locking (multi-agent safety)

Two agents must not cut or deploy overlapping suite versions. site-djbclark
ships serialization for that:

| Layer | Path | Scope |
| ----- | ---- | ----- |
| Exclusive flock | `~/.local/state/site-djbclark/ops-release.lock` | Held for one `check`/`deploy`/`memory-sync` (or `ops_release_lock.py hold`) |
| Version claim | `~/.local/state/site-djbclark/ops-release.claim.json` | Multi-step reservation across tag + GH release + deploy |

```bash
# Before starting a cut or deploy of version X:
just ops-release-claim-status
just ops-release-claim-begin 1.0.2 cut          # or: deploy
# … tag three repos, gh release create, then:
just ops-release-deploy 1.0.2
just ops-release-claim-end --version 1.0.2
```

- `deploy_ops_release.py check|deploy|memory-sync` **always** takes the
  exclusive flock (unless `--no-lock` for unit tests).
- If a **live** claim exists for a **different** version, deploy/check exit
  **75** (`EX_TEMPFAIL`) with a clear error. Wait or clear a stale claim:
  `just ops-release-claim-wait` / `claim end --force`.
- Stale claims (older than 2h by default) can be replaced by a new
  `claim begin`. Dead holder PID alone is **not** stale — `claim begin` is a
  short CLI; crashed agents must `claim end --force` or wait out the TTL.
- Optional strict mode: `OPS_RELEASE_REQUIRE_CLAIM=1 just ops-release-deploy 1.0.2`
  refuses deploy without an active matching claim.
- Overrides: `SITE_OPS_RELEASE_STATE`, `SITE_OPS_RELEASE_LOCK`,
  `SITE_OPS_RELEASE_CLAIM`.

Ordinary feature PR merges to `master` do **not** need this lock. Only
version bumps, tagging, GitHub Releases, and `~/ops` fast-forwards do.

## Cutting a release

1. Choose the next semantic version.
2. **Claim it:** `just ops-release-claim-begin X.Y.Z cut`.
3. Update `ops-release.json` to that version in all three task worktrees.
4. Run each repository's checks, open PRs, and obtain operator confirmation
   before merging.
5. Confirm all three `master` branches are clean, synchronized, and contain
   the intended commits.
6. Create and push the same annotated tag in each repository:

   ```bash
   git tag -a ops-v1.0.0 -m "djbclark ops 1.0.0"
   git push origin ops-v1.0.0
   ```

7. Create the three stable GitHub Releases with concise, repository-specific
   notes:

   ```bash
   gh release create ops-v1.0.0 --verify-tag --title "djbclark ops 1.0.0"
   ```

8. Deploy (below), then `just ops-release-claim-end --version X.Y.Z`.

If tag or release creation fails partway through, stop. Do not deploy a
partial suite. Remove only the newly created incomplete release/tag, after
resolving its exact scope, then retry the coordinated cut. Keep or refresh
the claim until the suite is either fully published+deployed or explicitly
abandoned (`claim end --force`).

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

For `site-private`, post-release `memory/` commits are preserved. If a valid
local memory-only commit diverged from the requested later release, the gate
rebases only that verified memory-only range onto the release before advancing
the other two checkouts.

### Local Codex preferences

`site-private/codex/config.toml` is ignored machine-local state beginning with
`ops-v1.0.1`. Codex and the operator may update that file without dirtying the
deploy checkout; the tracked `codex/config.toml.example` is only a bootstrap
example.

The `ops-v1.0.0` → `ops-v1.0.1` deployment is a one-time tracked-to-ignored
transition. The deploy tool permits no other dirty path, verifies the target
release both removes and ignores `codex/config.toml`, preserves the exact local
bytes and mode, deploys `site-private` last, and atomically restores the local
file. Subsequent releases leave the ignored file untouched naturally.

Because the deployed `ops-v1.0.0` tool predates this migration, perform this
one transition with the source copy from the published `ops-v1.0.1` commit,
after verifying the source worktree is exactly on that tag:

```bash
cd ~/src/ops-worktrees/main/site-djbclark
test "$(git rev-parse HEAD)" = "$(git rev-parse ops-v1.0.1^{commit})"
python3 bin/deploy_ops_release.py --ops-root "${OPS_ROOT:-$HOME/ops}" check 1.0.1
python3 bin/deploy_ops_release.py --ops-root "${OPS_ROOT:-$HOME/ops}" deploy 1.0.1
cd "${OPS_ROOT:-$HOME/ops}/site-djbclark"
just ops-release-status
```

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
