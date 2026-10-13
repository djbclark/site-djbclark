# NixOS configuration in git (vps-primary)

Since 2026-10-13 vps-primary builds its configuration **from git**, not from `/etc/nixos`.
Before that, `nixos/vps-primary/configuration.nix` was a tracked copy that was `scp`-ed onto
the host: nothing stopped the copy and the host from drifting apart.

## How it works

1. `nixos/flake.nix` + `nixos/flake.lock` define `nixosConfigurations.vps-primary`
   (modules: `nixos/vps-primary/configuration.nix`, `hardware-configuration.nix`).
2. The host's `system.autoUpgrade` pulls
   `github:djbclark/site-djbclark/deploy-vps-primary?dir=nixos#vps-primary` (this repo is
   public, so no credentials) every night at 04:00 UTC (plus a random delay of up to 45 min).
3. **`deploy-vps-primary` is a promotion branch**, not `master`. Many agents commit to
   `master`, and an unattended host that also reboots itself must not run whatever landed
   there. A config change reaches the host only when someone moves the branch:

   ```bash
   git push origin master:deploy-vps-primary     # promote
   ssh vps-ts systemctl start nixos-upgrade      # apply now (else the 04:00 run applies it)
   ```

   It is a fast-forward as long as nobody commits to the branch directly; do not.
4. `nixos-version --configuration-revision` on the host prints the deployed git commit.
5. nixpkgs: the autoUpgrade flags override the `nixpkgs` input to the head of
   `github:NixOS/nixpkgs/nixos-26.05`, so updates keep arriving as they did with the channel,
   without a job that bumps the lock. `flake.lock` pins nixpkgs for reproducible builds from
   a checkout (it was created at the revision that was already running, `7993f34`), but it is
   **not** what the nightly run builds.

## Rules

1. **Never run `nixos-rebuild` by hand on the host.** Use `systemctl start nixos-upgrade`.
   A hand run builds the lock file's nixpkgs (older than what autoUpgrade installed), which is a
   downgrade. The same trap hit on 2026-10-13 with the channel-based setup
   (`autoUpgrade.channel` left root's channel stale; a manual rebuild went 11767 -> 4364).
   `/etc/nixos` now holds only a README, so a bare `nixos-rebuild switch` fails instead of
   deploying stale config. The pre-flake files are in `/root/etc-nixos-pre-flake/`.
2. Edit `nixos/` in the repo, commit, push `master`, then promote. Rollback of a config:
   `git push -f origin <good-commit>:deploy-vps-primary` and `systemctl start nixos-upgrade`,
   or on the host `nixos-rebuild switch --rollback` (previous generation), or pick an older
   generation in GRUB from the Hetzner console.
3. A change that evaluates and builds but is wrong (locks out SSH, breaks the firewall) is not
   caught by the build. The unit applies it live. Check a risky change with a dry build first:
   on the host, `nixos-rebuild build --flake path:<copy>#vps-primary --override-input nixpkgs
   github:NixOS/nixpkgs/nixos-26.05` then `nix store diff-closures /run/current-system ./result`
   (what was done for the migration; the Mac has no Nix).
4. Secrets never go in `nixos/` as plain text: the Nix store is world-readable and this repo is
   public. The Gradle cache node's `config.yaml` (a password hash) is therefore kept out of git
   (see gradle-remote-cache.md). The standard way to bring such files into the repo is encrypted:
   **sops-nix** (age or GPG, templates for secrets inside plain config files) or **agenix**
   (age/SSH keys only, simpler). Not adopted yet; adopt one before putting any secret in the
   configuration.

## What the migration changed on the host

1. `system.copySystemConfiguration` removed (unsupported with flakes); `nix.settings.
   experimental-features` now enables `nix-command flakes`.
2. `autoUpgrade`: `channel` replaced by `flake` + `--override-input nixpkgs ...`, `upgrade = false`.
3. Closure diff against the running system before switching: `command-not-found` and its perl
   database packages gone (flake systems have no channel database), the `/etc/nixos` copy gone,
   the nixpkgs source added to the store (+197 MiB), version label
   `26.05.11767.7993f34ee47e` -> `26.05.20261012.7993f34`. No service or package changes.
4. Root's `nixos` channel is now unused (still listed; harmless).

## Alternatives considered

1. **comin** (pull-based GitOps: polls a git branch and deploys each commit, with a Prometheus
   exporter and CLI): more moving parts than `autoUpgrade` for one host; revisit if there are
   several.
2. **deploy-rs / colmena / `nixos-rebuild --target-host`** (push from a workstation, deploy-rs has a
   rollback if the host stops answering): needs Nix on the Mac, which is not installed, and pushes
   from a laptop that is often off. The pull model fits; its weakness (no automatic rollback if a
   switch cuts off access) is the same as before, and `fleet-watch vps` alerts on an outage.
3. **CI that bumps `flake.lock`** (e.g. a weekly GitHub Action), then autoUpgrade builds the
   locked revision: the most reproducible setup, because the lock names what is deployed. It would
   also let the override above be dropped. Worth doing if reproducibility matters more than
   having no extra moving part.
