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
   `cfengine`, `cf-execd` or `cf-agent`: a host line setting `services.cfengine-tendcf.*`, or a
   flake line importing the module or package.
3. On a **pull request only**: any change to `nixos/flake.nix` or `nixos/flake.lock`. A push does
   not count them, because `nixos-lock-update.yml` pushes `flake.lock` to `master` directly.

## The two jobs

- **`tendcf consent`** (pull_request, every PR, no path filter). Step 1 decides; if nothing
  touches tendcf it succeeds with `no tendcf-touching change`. Otherwise it renders the consent
  artifact for the merge result (base = the merge commit's first parent) and fails on: hard check 1
  (an execd unit, or any unit/timer whose command or script names `cf-execd` or `cf-agent`), hard
  check 2 (declared option set of `services.cfengine-tendcf` is not
  `{"execd":["enable"],"top":["enable","execd","package"]}`), a failed Nix step, or an AUTHORITY
  part that could not be fetched. The artifact (`tendcf-consent`, also in the job log and step
  summary) has AUTHORITY, SUMMARY, EFFECT, then the question.
- **`tendcf push check`** (push to `master`). For each first-parent commit of the pushed range that
  touches tendcf, GitHub must list a **merged pull request** for it (`GET
  /repos/{repo}/commits/{sha}/pulls`). That covers merge, squash and rebase merges and does not
  read commit messages. No merged PR: red, with a message pointing here.

## Limits

1. A PR can edit the workflow that checks it. The gate guards its own files by treating them as
   tendcf paths, so the change shows up in the artifact for the reviewer, but only review stops a
   hostile edit.
2. A nixpkgs bump is shown as a lock row and a compare link, not a source diff. EFFECT shows what
   it changes in the host.
3. Direct pushes of `flake.lock` (the weekly bot) are never checked for the hard invariants.
4. JCS: `jq -cS` equals RFC 8785 for the booleans and ASCII strings in the summary.
5. The Mac has no nix. The first real run of the Nix steps is CI.

## Branch protection (lead, not this repo's code)

Require the status check named **`tendcf consent`**. Do not require `tendcf push check` (it only
runs on pushes) or `Build cfengine-tendcf, check vps-primary` (path-filtered).
