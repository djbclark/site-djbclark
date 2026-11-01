# tendcf consent gate

The consent channel for changes that touch tendcf (the CFEngine fork) on the NixOS host
`vps-primary`. Spec: tendcf `docs/architecture/schema-v4-reconciliation-2026-10-31.md` section 5.
Implementation: `.github/workflows/tendcf-consent.yml` and `.github/scripts/tendcf-consent/`.

**It is not an approval record.** It has no nonce, sequence number or signature. The consent is
the PR approver reading the artifact and answering its closing question.

## Rules (operator djbclark, 2026-10-31)

1. Only changes that touch tendcf go through a PR with the required job **`tendcf consent`**. Other
   pushes stay direct.
2. A direct push to `master` that touches tendcf turns **`tendcf push check`** red. It never blocks
   or reverts anything.
3. The effect block (`nix store diff-closures`) is built on the runner, not skipped.

## What "touches tendcf" means (`consent.py`, constants at the top)

1. Any change to `nixos/modules/cfengine-tendcf.nix`, `nixos/pkgs/cfengine-tendcf.nix`,
   `.github/workflows/nixos-cfengine-build.yml`, `.github/workflows/tendcf-consent.yml` or
   anything under `.github/scripts/tendcf-consent/` (the gate guards itself).
2. Any other file under `nixos/` (except `flake.lock`) with an added or removed line that mentions
   `cfengine`, `tendcf`, `cf-execd` or `cf-agent`: a host line setting `services.cfengine-tendcf.*`, or a
   flake line importing the module or package.
3. On a **pull request only**: any change to `nixos/flake.nix` or `nixos/flake.lock`. On a push,
   `flake.lock` never counts as touching tendcf (`nixos-lock-update.yml` pushes it to `master`
   directly) and `flake.nix` counts only under rule 2. A pushed lock change still gets the hard
   checks (see the push job below).

The same module also computes `nix_changed`: any change under `nixos/` (lock included) or to the
gate's own files. That, not the text of the diff, decides whether the hard checks run.

## The two jobs

- **`tendcf consent`** (pull_request, every PR, no path filter). Step 1 decides. If nothing under
  `nixos/` or the gate files changed it succeeds with `no tendcf-touching change`. On every
  `nixos/**` or gate-file change (`nix_changed`) it installs Nix and runs the **hard checks** on
  the head configuration (eval only, seconds): hard check 1 (an execd unit, or any service or
  timer field, rendered unit text or `systemd.packages` entry that names `cf-execd`, `cf-agent`,
  `cfengine` or `tendcf`) and hard check 2 (declared option set of `services.cfengine-tendcf` is
  not `{"execd":["enable"],"top":["enable","execd","package"]}`). Both always report; an eval
  error counts as a failure. When the change also **touches tendcf** it renders the consent
  artifact for the merge result (base = the merge commit's first parent) and also fails on a failed
  Nix step or an AUTHORITY part that could not be fetched or whose lock rev/URL looks malformed.
  The artifact (`tendcf-consent`, also in the job log and step summary) has AUTHORITY, SUMMARY,
  EFFECT, then the question. EFFECT compares against the PR's base (master), which may be ahead of
  `deploy-vps-primary`, not against what is running.
- **`tendcf push check`** (push to `master`). For each first-parent commit of the pushed range that
  touches tendcf, GitHub must list a pull request **merged into the default branch** for it (`GET
  /repos/{repo}/commits/{sha}/pulls`, `merged_at` set, `base.ref` equal to the default branch).
  That covers merge, squash and rebase merges and does not read commit messages. No such PR: red,
  with a message pointing here. When any pushed commit changed `nixos/flake.lock` (this includes
  the weekly lock bot), the job also installs Nix and runs the hard checks on the pushed head,
  red on failure. When the push's `before` is unknown (a force-push, a new branch) the last 20
  first-parent commits are examined; older commits of such a push are not.

## Limits

1. A PR can edit the workflow that checks it. The gate guards its own files by treating them as
   tendcf paths, so the change shows up in the artifact for the reviewer, but only review stops a
   hostile edit.
2. A nixpkgs bump is shown as a lock row and a compare link, not a source diff. EFFECT shows what
   it changes in the host.
3. Direct pushes are red, never blocked, and a direct push can edit the gate it runs under. A
   pushed lock change gets only the eval-only hard checks, not the AUTHORITY or EFFECT blocks.
4. JCS: `jq -cS` equals RFC 8785 for the booleans and ASCII strings in the summary.
5. The Mac has no nix. The first real run of the Nix steps is CI.

## Branch protection (lead, not this repo's code)

Require the status check named **`tendcf consent`**. Also set: strict status checks (branch up to
date before merge, since `pull_request` does not re-run when the base moves), dismiss stale
approvals on new pushes, and read-only default workflow permissions. Do not require `tendcf push check` (it only
runs on pushes) or `Build cfengine-tendcf, check vps-primary` (path-filtered).
