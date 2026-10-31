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
5. nixpkgs is **exactly `flake.lock`** (textbook: the lock names what is deployed). A weekly
   workflow, `.github/workflows/nixos-lock-update.yml` (Mondays 02:23 UTC, also runnable with
   `gh workflow run nixos-lock-update.yml`), does: `nix flake update`, then **builds the whole
   vps-primary system on the runner as the gate**, commits the lock to `master`, and
   fast-forwards `deploy-vps-primary` to it **only if nothing else under `nixos/` is waiting
   there** (a pending config change is never promoted for you). The host's 04:00 run then
   applies it. Until the first scheduled run the lock is the revision the host already had.
6. **It does not fail quietly.** Any failed run, and any bump that is built but not promoted
   (`blocked`: other changes under `nixos/` are pending; `diverged`: someone committed to the
   deploy branch), opens or comments on one GitHub issue labelled `nixos-lock` and sends a
   Telegram message to the standing Hermes topic (the repo's existing `TELEGRAM_BOT_TOKEN`
   secret, same chat and topic as `hermes-ping`). GitHub also emails the failed run. A later run
   that finds `master` and the branch agreeing comments, closes the issue and says so. The
   host side is covered separately by `fleet-watch vps` (upgrade failed, unreachable).
   Both alarms were exercised on 2026-10-13: a simulated failure (issue + Telegram), then a real
   bump against a throwaway deploy branch (update, runner build, bot commit, fast-forward
   promotion, issue closed + Telegram), using the workflow's `deploy_branch` input.

## Rules

1. **Never run `nixos-rebuild` by hand on the host.** Use `systemctl start nixos-upgrade`.
   The same trap hit on 2026-10-13 with the channel-based setup (`autoUpgrade.channel` left
   root's channel stale; a manual rebuild went 11767 -> 4364). `/etc/nixos` now holds only a
   README, so a bare `nixos-rebuild switch` fails instead of deploying stale config (checked:
   "file 'nixos-config' was not found"). The pre-flake files are in `/root/etc-nixos-pre-flake/`.
2. Edit `nixos/` in the repo, commit, push `master`, then promote. Rollback of a config:
   `git push -f origin <good-commit>:deploy-vps-primary` and `systemctl start nixos-upgrade`,
   or switch the host back to a known generation (below), or pick an older generation in GRUB
   from the Hetzner console.

   **Host rollback: do not use `nixos-rebuild switch --rollback`.** It re-execs through
   `<nixpkgs/nixos>`, and these flake hosts have no channel; in a systemd unit there is no
   `NIX_PATH` at all, so it fails before doing anything (seen 2026-10-22 on vps-primary:
   "file 'nixpkgs/nixos' was not found in the Nix search path"). What works anywhere:

   ```sh
   G=$(readlink -f /nix/var/nix/profiles/system-39-link)   # the known-good generation
   nix-env -p /nix/var/nix/profiles/system --set "$G"
   "$G"/bin/switch-to-configuration switch
   ```

   `nix-env --list-generations -p /nix/var/nix/profiles/system` lists generations. Resolve the
   generation to its store path when you arm anything, so later profile changes cannot move it.
   In a systemd unit (`systemd-run`) `PATH` is minimal: use full store paths for every command,
   and call the `nix-env` symlink in the Nix package (`/nix/store/...-nix-X/bin/nix-env`), not
   `readlink -f` of it, which resolves to the multi-call `nix` binary and changes its meaning
   (coreutils is multi-call too: use `.../bin/readlink`, `.../bin/sleep`).

   **Network note (2026-10-23):** GlobalProtect (gpclient, `gp-mit`) was removed everywhere
   (6875819). vps-primary cannot reach MIT 18.0.0.0/8 at all and is only a Tailscale exit
   node; the tailnet reaches MITnet through the subnet route advertised by
   pastebin.xvm.mit.edu (100.104.212.89). On pastebin, restarting nftables drops Tailscale's
   rules: restart tailscaled right after it.

   **Dead-man switch for a risky deploy** (used for gpclient 3.1.0, 2026-10-22; gpclient is
   gone since 2026-10-23, the recipe still applies). A timer that
   rolls back unless cancelled. `nixos-upgrade` can spend most of its time compiling (26 minutes
   for gpclient on the VPS), so a timer armed before `systemctl start nixos-upgrade` can fire
   before the switch: arm it **at the profile switch, not before the build**:
   - `/root/gp-deadman-rollback.sh`: the three lines above with full store paths and the old
     generation's store path written in.
   - A watcher, started with `systemd-run --unit=deadman-arm /bin/sh <script>`, loops on
     `.../readlink /nix/var/nix/profiles/system` once a second while it still names the old
     `system-N-link`. It exits without arming if `systemctl is-active nixos-upgrade` is no longer
     `activating`/`active` (note `is-active -q` is non-zero for `activating`). When the profile
     moves, it runs `systemd-run --unit=deadman --on-active=10min /bin/sh /root/...rollback.sh`.
   - Verify, then `systemctl stop deadman.timer`; remove the scripts and
     `systemctl reset-failed` the transient units.
   - Restarting a client in tmux: if the program is the window's only process (no shell), C-c
     ends the window, the tmux server and, without linger, `user@UID`. Start tmux sessions with a
     shell and type the command into it.
3. A change that evaluates and builds but is wrong (locks out SSH, breaks the firewall) is not
   caught by the build. The unit applies it live. Check a risky change with a dry build first:
   on the host, `nixos-rebuild build --flake path:<copy>#vps-primary` (the lock decides nixpkgs), then `nix store diff-closures /run/current-system ./result`
   (what was done for the migration; the Mac has no Nix). The weekly workflow does this build
   for lock bumps automatically.
4. Secrets never go in `nixos/` as plain text: the Nix store is world-readable and this repo is
   public. The Gradle cache node's `config.yaml` (a password hash) is therefore kept out of git
   (see gradle-remote-cache.md). The standard way to bring such files into the repo is encrypted:
   **sops-nix** (age or GPG, templates for secrets inside plain config files) or **agenix**
   (age/SSH keys only, simpler). Not adopted yet; adopt one before putting any secret in the
   configuration.
5. **Lock and build on Forgejo CI, not on the host** (djbclark, 2026-10-18: faster): hyades-nix-build's `nix-build`
   workflow with `repo=https://github.com/djbclark/site-djbclark.git`, `dir=nixos`, `update='<input> ...'`
   (runs `nix flake update` and prints the new `flake.lock` as base64 between `LOCK-BEGIN`/`LOCK-END`) and
   `attrs=nixosConfigurations.vps-primary.config.system.build.toplevel`. One run locks and proves the
   build; commit the printed lock to `master`.
6. **Rebuilds are shared** (`~/CLAUDE.md` 36): several agents change `nixos/`. Fold other agents' pending
   input bumps into yours (for example `update='paseo-nix <other-input>'`),
   promote `master`'s head only, tell the agents waiting on it, and check
   `nixos-version --configuration-revision` afterwards.

## What the migration changed on the host

1. `system.copySystemConfiguration` removed (unsupported with flakes); `nix.settings.
   experimental-features` now enables `nix-command flakes`.
2. `autoUpgrade`: `channel` replaced by `flake` (the deploy branch), `upgrade = false`. For the first
   day it also overrode nixpkgs to the stable branch head; that override was dropped the same day
   when the lock-bump workflow went in.
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
