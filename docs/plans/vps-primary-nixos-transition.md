# vps-primary: Ubuntu to NixOS transition

## Current state — 2026-10-04

Installation and SSD boot are complete and verified after operator authorization.
NixOS 26.05 runs as `vps-primary`, with BIOS GRUB on `/dev/sda`, ext4 root
on `/dev/sda1`, and swap on `/dev/sda2`. NetworkManager obtains the retained
IPv4 address by DHCP on `enp1s0`, with gateway `172.31.1.1`.

Root SSH works with the existing Mac `~/.ssh/vps_primary_key`; effective
settings require public-key authentication and disable password and
keyboard-interactive authentication. The installed ED25519 host fingerprint
`SHA256:frTI5lQmM1o5kBYX83dGj0tD+3pozafMJYiyl0AMMs8` was independently confirmed
through the Hetzner console before updating only this server's known-hosts entry.

Root's console password is locked. Console-password recovery is deferred by the
operator; provider rescue/ISO is the fallback, not a verified password login.
Inventory remains `provisioning`: Python, Ansible/NixOS role compatibility,
non-root accounts, IPv6, Tailscale and service rollout are outside the completed
installation. Do not reinstall this host or apply the whole stack.

The installer temporarily lost access to its virtual CD-ROM and reported
`Medium not present` and SquashFS read errors. Reattachment alone did not restore
executable reads; a fresh ISO boot did. Detachment cause remains unknown.

## Historical preparation checklist

Recorded before installation on 2026-10-04. **Historical preparation only; do not execute until the operator
authorizes the next step.** The operator plans to replace Ubuntu with NixOS
while retaining public IPv4 `178.105.34.223`.

## Identity and evidence

1. Inventory alias: `vps-primary`, in [`inventory/hosts.yml`](../../inventory/hosts.yml).
2. Last recorded Hetzner server name: `ubuntu-4gb-nbg1-1`, server ID
   `131169181`, CX23, location `nbg1`. This is the provider name, not a
   freshly verified guest OS hostname. No VPS connection or provider query
   was made for this preparation.
3. Last recorded OS: Ubuntu 24.04, verified 2026-08-09. The inventory uses
   `djbclark`, TCP port 22, and `site_host_status: provisioning`.
   The recorded SSH key was rejected; do not assume working access today.
4. Keep `vps-primary` as the inventory/registry identity unless explicitly
   renamed. A NixOS guest hostname and a renamed Hetzner display name are
   separate decisions; the Ubuntu-derived provider name need not remain.
5. The [Bluehost closure notes](kill-bluehost-migration-v1.md) record that
   audited deployed sites do not depend on this VPS. Verify current
   dependencies before reinstalling; this historical observation is not
   permission to erase data.

## Before any destructive installation

1. Confirm whether the operator has already installed NixOS or still needs
   installation assistance. Do not reinstall an already migrated host.
2. Confirm the same Hetzner server and retained IP, console/rescue access,
   required data backups, disk layout, network configuration (including
   IPv6), NixOS release, and intended hostname. Do not invent disk devices,
   gateway addresses, hardware configuration, or a flake layout.
3. Identify the existing Mac SSH identity intended for this server. Inspect
   local SSH configuration and public-key fingerprints only; never copy a
   private key onto the VPS or commit it. Prefer an existing appropriate
   key; generate another only if needed and approved.
4. Decide where the declarative NixOS configuration is owned in `~/ops`.
   Keep site-specific configuration in this site repo, not the generic
   `stayturgid` repo. Keep secrets outside tracked files.

## Restore SSH access after installation

1. Use the Hetzner console/rescue path or an already authorized bootstrap
   login. Do not assume that Ubuntu users, authorized keys, SSH host keys,
   sudo rules, Tailscale identity, or installed packages survived.
2. Record the new SSH host-key fingerprint through the trusted console.
   Compare it with the key presented over SSH. A reinstall can legitimately
   change host keys, but never bypass host verification or trust
   `ssh-keyscan` alone.
3. Only after verification, back up the relevant local known-hosts file
   and remove obsolete entries for this IP and any configured hostname
   aliases, accounting for custom ports and `HostKeyAlias`. Do not clear
   unrelated entries or disable `StrictHostKeyChecking`.
4. Configure OpenSSH and the login account declaratively in NixOS:
   `services.openssh.enable`, `networking.hostName`,
   `users.users.djbclark.isNormalUser`, and
   `users.users.djbclark.openssh.authorizedKeys.keys` (or tracked public
   `keyFiles`). Configure SSH port/firewall rules and any Hetzner firewall
   consistently. Use the operator's chosen public key, not a placeholder
   accidentally deployed as configuration.
5. Decide administrative access separately: wheel membership and sudo
   policy may be needed, but passwordless SSH does not require or authorize
   passwordless sudo. Preserve console recovery and a bootstrap session
   until a second, independent key-authenticated login succeeds.
6. After key login succeeds, disable SSH password and keyboard-interactive
   authentication through `services.openssh.settings` if appropriate, and
   settle `PermitRootLogin` without cutting off the only recovery path.
   Rebuild and retest before closing the bootstrap session. Do not rely on
   imperative edits to generated `sshd_config` or `authorized_keys` as the
   lasting NixOS configuration.
7. After approval, verify from the Mac using the chosen identity:

   ```bash
   rtk proxy ssh -o BatchMode=yes -o PreferredAuthentications=publickey \
     -o StrictHostKeyChecking=yes djbclark@178.105.34.223 \
     'id -un; hostname; cat /etc/os-release'
   ```

   If the identity is not selected by SSH configuration/agent, add
   `-i /absolute/path/to/chosen-key -o IdentitiesOnly=yes`. A passphrase-
   protected key can use the local agent; server passwordless login does
   not require removing the key's passphrase.

## Integrate into ops, only after SSH works

1. Update `inventory/hosts.yml` to describe the verified NixOS state,
   retaining `ansible_host: 178.105.34.223`, the verified user and port,
   and the `vps-primary` identity. Leave it `provisioning` until bootstrap
   and compatibility checks pass; OS installation alone is not readiness.
2. Provide Python declaratively if Ansible will manage the host, and set
   `ansible_python_interpreter` to its verified NixOS path (commonly
   `/run/current-system/sw/bin/python3`). Do not use Ubuntu apt/bootstrap
   assumptions on NixOS.
3. Audit relevant roles before applying them: NixOS package management,
   executable paths, dynamic-library compatibility, generated `/etc`,
   service ownership, and systemd user-session/linger behavior differ.
   The [LiteLLM role](../../roles/litellm/README.md) does not install its
   editable checkout or prerequisites; Linux support is not proof of
   NixOS readiness. Do not run the whole fleet or deploy the stack just
   because SSH starts working.
4. Scope any later Ansible connectivity check explicitly to this host:

   ```bash
   cd ~/ops/site-djbclark
   rtk proxy ansible -i inventory/hosts.yml vps-primary \
     -m ansible.builtin.ping
   ```

   Use the verified interpreter/identity settings first. This check needs
   authorization too; it has not been run during preparation.
5. Tailscale enrollment is a separate, optional post-bootstrap step.
   Do not assume the old tailnet node survives, delete it blindly, or
   store enrollment credentials in git. Keep LiteLLM loopback-only until
   an authenticated access design is approved.
6. Check existing `vps-primary` allocations in `registry/ports.yml` and
   `registry/paths.yml` before any service rollout; mark planned entries
   active only after actual deployment. Update dated OS/bootstrap notes
   without rewriting historical migration evidence.

## Completion criteria for the future execution

NixOS and the chosen hostname are verified on the retained IP; host keys
are independently verified; `djbclark` key-only SSH works from the Mac;
administrative and recovery access work under the chosen policy; SSH works
after a controlled reboot; inventory matches reality; and any enabled
automation has passed host-scoped compatibility checks. Service deployment
is separate scope, not implied by this transition.

## Preparation performed

Only local documentation was read and this deferred checklist saved.
No VPS connections, reinstall, SSH/known-hosts changes, key generation,
inventory edits, NixOS rebuilds, firewall changes, or service deployments
were performed.
