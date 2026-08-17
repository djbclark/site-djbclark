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

<!-- markdownlint-disable MD013 -->

| Layer           | Path                                                  | Scope                                                                       |
| --------------- | ----------------------------------------------------- | --------------------------------------------------------------------------- |
| Exclusive flock | `~/.local/state/site-djbclark/ops-release.lock`       | Held for one `check`/`deploy`/`memory-sync` (or `ops_release_lock.py hold`) |
| Version claim   | `~/.local/state/site-djbclark/ops-release.claim.json` | Multi-step reservation across tag + GH release + deploy                     |

<!-- markdownlint-enable MD013 -->

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

### Applying the release to the running stack

`ops-release-deploy` only fast-forwards the three `~/ops` checkouts — it does
**not**, by itself, apply anything to the running Android fleet or the Mac
control node's own services. Depending on what the release changed, run the
relevant command(s) from the now-advanced `~/ops/stayturgid` checkout:

- **Android fleet** (device roles/config): `just deploy` (or `just
  deploy-check` for a dry run first).
- **Mac control node** (launchd agents, control_node role): `just deploy-mac`
  (`--tags mac`).
- **Mac-hosted serverapps** (`caddy`/`grafana`/`vector`/`victoriametrics`/
  `openobserve`/`blackbox_exporter`/`olivetin`/`landing` — including their
  brew-pin tasks): **neither of the above covers these.** They only run via
  `just site-serverapps`, a separate own/inject/off adapter-activation entry
  point (`control/site_contract/serverapps.py`). If a release touches a
  `serverapp_*` role, `just site-serverapps` must be run explicitly or the
  change won't reach the running service.

For the data-directory exceptions (`site-private/memory/`,
`site-djbclark/research/` — see `DATA_DIRS` in `bin/deploy_ops_release.py`),
post-release data commits are preserved. If a valid local data-only commit
diverged from the requested later release, the gate rebases only that verified
data-only range onto the release before advancing the other checkouts.

### Local Codex preferences

`site-private/codex/config.toml` is ignored machine-local state beginning with
`ops-v1.0.1`. Codex and the operator may update that file without dirtying the
deploy checkout; the tracked `codex/config.toml.example` is only a bootstrap
example.

The `ops-v1.0.0` → `ops-v1.0.1` deployment is a one-time tracked-to-ignored
transition. The deploy tool permits no other dirty path, verifies the target
release both removes and ignores `codex/config.toml`, preserves the exact local
bytes and mode in Git metadata, deploys `site-private` last, and atomically
restores the local file. A later invocation automatically recovers that backup
if the deploy process is interrupted. Subsequent releases leave the ignored
file untouched naturally.

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

### Canonical SecretSpec runtime store

The only live manifest/provider store is `/var/db/sudo-secretspec/`, owned by
the `_sudo_secretspec` service identity with mode `0700` and reached only
through the root-owned `sudo-secretspec` broker. There is no tracked
declarations file and no manifest path for any caller to know or specify —
`sudo-secretspec add`/`set`/`check`/`schema` against the runtime manifest are
the only record, and nothing needs mirroring into a release.

No runtime secret file remains in any Git checkout, so a release no longer has
to bridge one. The `_secretspec` wrapper boundary and its
`/var/db/stayturgid-secrets` store were retired on 2026-08-15; the legacy
directory is locked `root:wheel 0000` and holds no live role. Deploying a
release performs no privileged SecretSpec cutover.

Boundary changes are installed out of band, from a real TTY, not by the
deployer:

```bash
brew upgrade frdminc/sudo-secretspec/sudo-secretspec
sudo-secretspec install --adopt-existing
sudo-secretspec doctor
```

`install` authenticates every time (`timestamp_timeout=0`) and cannot prompt
from a backgrounded process. Pass `--adopt-existing` whenever a vault already
exists: without it, `install` truncates `<vault>/.env`.

## Live data-directory exceptions

Two directories are live data committed directly to `master` in place,
exempt from the worktree/PR/release flow (the `DATA_DIRS` mapping in
`bin/deploy_ops_release.py` is the machine-readable authority):

| Repo | Directory | Contents |
|---|---|---|
| `site-private` | `memory/` | Agent memory (one fact per file, handoffs) |
| `site-djbclark` | `research/` | Research/plan document packages (**public repo** — no secrets, no private-only context) |

Agents must run:

```bash
cd "${OPS_ROOT:-$HOME/ops}/site-djbclark"
just ops-memory-sync
```

before writing to either directory. The command fetches each data-dir repo
and refuses to sync if any remote change since its latest coordinated release
touches a path outside that repo's data directory. This prevents an ordinary
data rebase from silently deploying unreleased code or configuration.

After the guarded sync, make one data-only commit, push immediately, and
leave the tree clean. `just ops-release-status` permits each repo to be
ahead of its release only by its own data-directory paths.
