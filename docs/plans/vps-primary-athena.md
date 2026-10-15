# vps-primary: Athena/AFS and the pieces of `get` that fit a real VM

Decided with djbclark 2026-10-15. Source: the `get` project (a NixOS microVM on
SIPB Hyades, private repo `forgejo.mit.edu/djbclark/get`, `~/src/get`), whose
design works around Hyades limits (no kernel modules, no UDP, ephemeral rootfs,
40 GiB quota). vps-primary has none of those limits, so it takes the parts that
are about the machine, not about Hyades.

## 1. Decisions

1. **Role:** infra plus Athena/AFS. A slim package set (about 2 GiB: CLI tools,
   Python core, editors, nix tools) plus the Claude TUI. `get` stays the heavy dev
   box. Measured 2026-10-15: 2 vCPU, 3.7 GiB RAM, 38 GB disk, 22 GB free.
2. **No backups are stored on vps-primary.** The VPS backs itself up with restic
   to `defeat`. `get`'s restic now targets `defeat` too (changed in `get`
   2026-10-15); the VPS gets no `get-backup` user.
3. **Shared modules are copied** into `nixos/modules/` here (public, no secrets);
   `get` keeps its own copies. A private Forgejo flake input would need a
   credential on the host for the nightly auto-upgrade.
4. **AFS client: OpenAFS** (`services.openafsClient`, through SIPB's
   `nixathena`). `linuxPackages.openafs` 1.8.16.1 is built for kernel 6.18.56 at
   the current lock and is not marked broken. The weekly lock-update build is the
   gate for a kernel bump that breaks the out-of-tree module.
5. **Tickets:** the Mac pushes renewable ATHENA.MIT.EDU tickets to the VPS (the
   same mechanism as the Athena dialup); the VPS runs `aklog` and a renew timer.
   No Kerberos password login (no PAM `pam_krb5`), no host keytab.
6. **ssh:** stays public on 22 until ssh over the tailnet has been proven, then
   tailnet-only. Break-glass is the Hetzner console/rescue (root's console
   password is locked; see `vps-primary-nixos-transition.md`).
7. **Remote terminals:** mosh and et, both on the tailnet interface only.
8. **Gradle cache:** replace the Develocity Build Cache Node (unsupported after
   2026-12-31) with `get`'s nginx WebDAV module, tailnet-only. One cold cache.
9. **Nix binary cache for nixathena:** not now; revisit if `get`'s CI build
   times say so.

## 2. Phases

Every phase is developed on the branch `vps-primary-athena`, not on master:
anything under `nixos/` on master that is not on `deploy-vps-primary` blocks
the weekly lock promotion and raises its alarm (`nixos-lock-update.yml`).
Check each phase with an eval and a `nix build --dry-run` of the host on the
VPS (no build there), then merge and deploy only on djbclark's go-ahead
(`docs/nixos-in-git.md`).

### Phase A: modules and packages

1. `nixathena` flake input (follows our nixpkgs) and its NixOS module.
2. `modules/packages.nix`: the slim list plus `claude-code`
   (`allowUnfreePredicate` for that one package).
3. `modules/athena.nix`: nixathena trimmed (`workstation = false`, moira,
   remctl, athrun; no lightdm/ldap/pkgsync/hesiod/zephyr), AFS still off.
4. `modules/users.nix`: user `djbclark` (wheel, key login); root keeps the
   automation key.
5. `modules/terminals.nix`: et and mosh, ports opened on `tailscale0` only.

### Phase B: AFS and tickets

1. `services.openafsClient.enable = true`, cache about 3 GiB, `/afs`.
2. Ticket push from the Mac (extend the dialup push job) plus an `aklog` and
   renew timer on the VPS.
3. Check: `tokens`, `ls /afs/athena.mit.edu/user/d/j/djbclark`.

### Phase C: ssh

1. `PerSourcePenalties`, `AllowUsers djbclark root`, `MaxAuthTries 3`.
2. After a proven tailnet path: drop 22 from the public firewall
   (`networking.firewall.interfaces.tailscale0.allowedTCPPorts`), update
   `~/.ssh/config` so `vps` goes through the tailnet.

### Phase D: services

1. Gradle cache: nginx WebDAV module, data under `/var/lib/gradle-cache`, basic
   auth file created by hand on the host (never in the store), bound to the
   tailnet address; remove the podman container and its user once clients use
   the new URL.
2. restic to `defeat` for `/var/lib` and `/home` (secrets on the host only).
   **Prerequisite: `defeat` is not on the tailnet yet** (also blocks `get`'s
   backup; `get` runbook 5.2).

## 3. Checks

1. Phase A (branch `vps-primary-athena`, landed as 107fa94) was checked 2026-10-15 on the
   host with eval plus `nix build --dry-run` (no build): nixathena `99ddc9fe`
   evaluates on nixos-26.05; every slim-list attribute exists; 1.4 GiB unpacked
   to fetch, and the host would build moira, remctl, athrun, hesiod and
   claude-code from source (small; helix was dropped because it compiled Rust).
2. Differences from `get` found on 26.05: `services.eternal-terminal.telemetry`
   does not exist; `services.openafsClient.enable` must be a plain value
   (nixathena's `mkDefault` collides with another `mkDefault`).
3. The host has no `git` on root's PATH outside the upgrade service; the
   `git+https` nixathena input is fetched by `nixos-upgrade`, which has its own
   git. Manual checks use `nix build nixpkgs#gitMinimal`.
4. **Phase A deployed 2026-10-15** (107fa94 promoted; `nixos-upgrade` 1m34s, peak
   1.7 GiB RAM, root 20 GB free after). Verified: user `djbclark` (zsh, passwordless
   sudo), claude-code 2.1.223, kinit/moira/remctl/athrun on PATH, etserver on 2022
   and mosh-server start, firewall opening 2022/tcp and 60000-61000/udp only on
   `tailscale0` (public 2022 closed). Not verified by an agent: djbclark's own key
   login (`~/.ssh/id_ed25519` is passphrase-protected and not in an agent).
5. `security.sudo.wheelNeedsPassword = false` for `djbclark`: no local password
   exists, and root is already reachable with a key.
6. **Phase B deployed 2026-10-15** (63fc0b8): OpenAFS 1.8.16.1 loaded without a
   reboot, `/afs/athena.mit.edu` mounted, 2.9 GiB cache. The Mac's `athena-kinit`
   pushes the TGT hourly with `~/.ssh/athena_tgt_push`, whose authorized_keys entry
   is `restrict`, `from=` the Mac's tailnet address and forced to
   `athena-tgt-receive`; tickets live in `FILE:/var/lib/krb5cc/<uid>/tgt` (nixathena's
   keyring default is overridden). Verified: renewable TGT, rxkad tokens,
   `~/Private` readable, `athena-tgt-renew` (every 4 h) succeeds.
7. Seen during phase B: root logs in over the **public** address
   (137.83.218.121) with the automation key, alongside the tailnet logins. Find
   that client before phase C closes port 22 publicly.
8. **Phase C step 1 deployed 2026-10-15** (5dc4189): `AllowUsers root djbclark`,
   `MaxAuthTries 3`, `LoginGraceTime 30`, the tailnet exempt from
   `PerSourcePenalties`. On the Mac, `vps`/`vps-primary` now resolve to the tailnet
   address and `vps-public` is the break-glass alias (`~/.ssh/config`, not in a
   repo); `inventory/hosts.yml` `ansible_host` is the tailnet address. Step 2,
   closing 22 publicly, waits a few days of clean tailnet-only use. It will also
   make `bin/fleet-watch`'s public-address fallback probe (`VPS_PUBLIC`) fail
   whenever the tailnet is down, which is the intended signal.
9. **The weekly lock-update path works with nixathena and claude-code** (run
   38779609242, started by hand 2026-10-15): the GitHub runner fetched
   nixathena from forgejo.mit.edu, built the whole host including the unfree
   claude-code, bumped nixpkgs 7993f34 -> a033e66 (7137b77) and promoted it;
   the host applies it at its nightly run. nixathena is tracked by the weekly
   bump on purpose (djbclark, 2026-10-15). `djbclark` keeps passwordless sudo
   (djbclark, 2026-10-15).
