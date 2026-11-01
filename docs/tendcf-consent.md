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
  the head configuration (eval only, seconds, plus fetching the `systemd.packages` closure):
  hard check 1 and hard check 2 (declared option set of `services.cfengine-tendcf` is
  `{"execd":["enable"],"top":["enable","execd","package"]}`). Both always report; an eval
  error counts as a failure.

  Hard check 1 (`check1.nix`, applied to the whole `config`) fails when
  `cfengine-tendcf-execd` exists or when any of these names `cf-execd` or `cf-agent`, or cannot
  be evaluated:

  1. a field of a system or user service or timer (`ExecStart*`, `ExecStop*`, `ExecReload`,
     `script`, `preStart` and so on) in `systemd.services`, `systemd.timers`,
     `systemd.user.services`, `systemd.user.timers`;
  2. the rendered text of any `systemd.units` or `systemd.user.units` entry, or an
     `environment.etc` entry whose target starts with `systemd/` (target and text);
  3. `systemd.packages`: the package name (`cfengine` or `tendcf`) and the text of every regular
     file in `${pkg}/lib/systemd/system`. **Reading a package's unit files is import from
     derivation: Nix realises each package at eval**, almost always a binary-cache fetch (the
     nixpkgs ones) but a real build for a package that is not cached, such as the tendcf one if
     it were listed. It was chosen over a name-only match because a renamed package hides from
     the name; a package that cannot be fetched or built fails the eval, and so the check;
  4. `system.activationScripts` (each string or `.text`; the derived `script` entry is skipped,
     the entries cover it), `boot.postBootCommands`, `systemd.tmpfiles.rules` and
     `services.cron.systemCronJobs`.

  A guard against a vacuous pass: the result also counts what was scanned (services, units,
  activation scripts, `etc` entries, shipped unit files) and every count must be above zero.
  The check is textual: a wrapper binary that runs `cf-agent` indirectly, an `environment.etc`
  entry given only as `source`, a unit symlink pointing outside its package and
  `systemd.tmpfiles.settings` are not seen. A green check 1 does not prove the host free of
  `cf-agent`; AUTHORITY and EFFECT are the channel for those. When the change also **touches tendcf** it renders the consent
  artifact for the merge result (base = the merge commit's first parent) and also fails on a failed
  Nix step or an AUTHORITY part that could not be fetched or whose lock rev/URL looks malformed.
  The artifact (`tendcf-consent`, also in the job log and step summary) has AUTHORITY, SUMMARY,
  EFFECT, then the question. EFFECT compares against the PR's base (master), which may be ahead of
  `deploy-vps-primary`, not against what is running.
- **`tendcf push check`** (push to `master`). For each first-parent commit of the pushed range that
  touches tendcf, GitHub must list a pull request **merged into the default branch** for it (`GET
  /repos/{repo}/commits/{sha}/pulls`, `merged_at` set, `base.ref` equal to the default branch).
  That covers merge, squash and rebase merges and does not read commit messages. No such PR: red,
  with a message pointing here. When the pushed range changed anything under `nixos/` (any `.nix`
  file or the lock, which includes the weekly lock bot) or the gate's own files (`nix_changed`,
  `consent.py nix-changed`: `before` against the head), the job also installs Nix and runs the
  hard checks on the pushed head, red on failure. The text of the diff does not matter: a line
  that builds `"cf-" + "agent"` is caught on a push as it is on a PR. When the push's `before` is unknown (a force-push, a new branch) the last 20
  first-parent commits are examined, for both the touches test and the hard checks (the range
  starts at the parent of the oldest of them); older commits of such a push are not.

## Limits

1. A PR can edit the workflow that checks it. The gate guards its own files by treating them as
   tendcf paths, so the change shows up in the artifact for the reviewer, but only review stops a
   hostile edit.
2. A nixpkgs bump is shown as a lock row and a compare link, not a source diff. EFFECT shows what
   it changes in the host.
3. Direct pushes are red, never blocked, and a direct push can edit the gate it runs under. A
   pushed `nixos/` change that does not touch tendcf gets only the eval-only hard checks, not the
   AUTHORITY or EFFECT blocks.
4. JCS: `jq -cS` equals RFC 8785 for the booleans and ASCII strings in the summary.
5. The Mac has no nix. The first real run of the Nix steps (`check1.nix`, `run.sh`) is CI. The
   tests cover the Python decision code, the `jq` condition of check 1 and static guards on the Nix
   source; `test_check1_nix_flags_each_channel` evaluates `check1.nix` on a synthetic config and
   runs only where `nix` exists.

## Branch protection (lead, not this repo's code)

Require the status check named **`tendcf consent`**. Also set: strict status checks (branch up to
date before merge, since `pull_request` does not re-run when the base moves), dismiss stale
approvals on new pushes, and read-only default workflow permissions. Do not require `tendcf push check` (it only
runs on pushes) or `Build cfengine-tendcf, check vps-primary` (path-filtered).
