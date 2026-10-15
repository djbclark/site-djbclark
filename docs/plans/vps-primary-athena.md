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

## 3. Open checks

1. Does `nixathena` (tested by SIPB on nixos-unstable) evaluate and build on
   nixos-26.05?
2. Which slim-list attributes are missing on 26.05 (the `get` list was checked
   against unstable)?
3. The real closure growth from the dry-run, against the 2 GiB estimate.
