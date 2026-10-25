{
  config,
  lib,
  pkgs,
  modulesPath,
  ...
}:

# The entity's own host: "dann" (dann.dclark.us), an OVH VPS-3 in Beauharnois (BHS), Canada.
# Installed 2026-10-25 with nixos-anywhere from vps-primary. This file is the *installed*
# configuration; the live config is the flake at github:djbclark/site-djbclark, promoted to
# a deploy branch (docs/nixos-in-git.md). Never edit /etc/nixos on the host.
{
  imports = [
    (modulesPath + "/profiles/qemu-guest.nix")
  ];

  # ── Filesystems ──────────────────────────────────────────────────────────────────────
  # disko creates the layout at install time (nixos/dann/disko.nix) and passes the resulting
  # mounts in, so these are the *installed* filesystems, written out rather than inferred.
  # The root filesystem is labelled nixos-root by disko; naming it by label rather than
  # /dev/sda2 keeps it correct if device ordering ever changes.
  fileSystems."/" = {
    device = "/dev/disk/by-label/nixos-root";
    fsType = "ext4";
  };
  # disko creates an 8 GiB swap partition (nixos/dann/disko.nix). Declared here so the
  # installed system uses it and so evaluation does not warn about an unmanaged partition.
  swapDevices = [ { device = "/dev/disk/by-partlabel/swap"; } ];

  # ── Boot: BIOS, not UEFI ──────────────────────────────────────────────────────────────
  # Verified on the box 2026-10-25: /sys/firmware/efi is absent, so the firmware is BIOS even
  # though a /boot/efi partition existed on the *old* Debian install. A UEFI-style layout would
  # install an unbootable system. GRUB on the whole disk is correct here.
  boot.loader.grub = {
    enable = true;
    device = "/dev/sda";
    configurationLimit = 10;
  };

  # ── Network: STATIC, and the values are not guessable ────────────────────────────────
  # OVH gives a /32 address plus an explicit gateway. DHCP is not offered on this product, and
  # a wrong network config on a remote host means losing it — the only way back is the KVM
  # console (POST /vps/{serviceName}/getConsoleUrl). So these are written down literally.
  networking = {
    hostName = "dann";
    domain = "dclark.us";
    useDHCP = false;
    interfaces.ens3 = {
      useDHCP = false;
      ipv4.addresses = [ { address = "148.113.151.85"; prefixLength = 32; } ];
      ipv6.addresses = [ { address = "2607:5300:205:200::e8a2"; prefixLength = 128; } ];
    };
    defaultGateway = { address = "148.113.144.1"; interface = "ens3"; };
    defaultGateway6 = { address = "2607:5300:205:200::1"; interface = "ens3"; };
    nameservers = [ "9.9.9.9" "2620:fe::fe" ];
    # The interface must be up with its address before sshd matters; systemd-networkd is the
    # default with the settings above, and this keeps the ordering explicit.
    firewall.allowedTCPPorts = [ 22 ];
  };

  # The MAC is recorded because a rebuilt host keeps it, and it is the stable identifier if the
  # interface name ever changes: fa:16:3e:85:99:96.

  # ── SSH: key-only, and both the keeper and the operator can get in ────────────────────
  services.openssh = {
    enable = true;
    settings = {
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
      PermitRootLogin = "prohibit-password";
      MaxAuthTries = 3;
      LoginGraceTime = 30;
    };
  };

  # ── Users ────────────────────────────────────────────────────────────────────────────
  # `dann` is the entity's own account: normal user, wheel, key-only. It is NOT root — the
  # agreed rule (plan §6 Q4) is that "own" means authority over the work, not over the kernel,
  # and sudo keeps that boundary visible instead of hiding it behind uid 0.
  users.users.dann = {
    isNormalUser = true;
    description = "Dann (the entity)";
    extraGroups = [ "wheel" ];
    shell = pkgs.bash;
    openssh.authorizedKeys.keys = [
      # The keeper's key (this instance). Installed on the box 2026-10-25.
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFfX1Tx7KsxguMq3jCKJI/blGze2lHFxWJ5UrTnj7d3d dann-vps@dann.dclark.us"
      # The operator's own key, so the box is never enterable ONLY by its builder. A home that
      # only one key can open is a single point of failure, and he paid for it.
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHtqrJzIIPFly8MDXpLEZEJ2WArfc5lSiCHxGTJnL8DY djbclark@djbclarks-MacBook-Air.local"
    ];
  };
  # No local password exists to type, so wheel must not demand one.
  security.sudo.wheelNeedsPassword = false;

  # Root keeps a key too: nixos-anywhere deploys as root, and the operator's existing
  # automation key is what the rest of the fleet uses.
  users.users.root.openssh.authorizedKeys.keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFfX1Tx7KsxguMq3jCKJI/blGze2lHFxWJ5UrTnj7d3d dann-vps@dann.dclark.us"
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKaWfTezsujYpykja7WRikq6jjw3r5vKgcO8o1nSaNoB djbclark@vps-primary-automation"
  ];

  # ── Nix ──────────────────────────────────────────────────────────────────────────────
  nix.settings.experimental-features = [ "nix-command" "flakes" ];
  nix.gc = {
    automatic = true;
    dates = "weekly";
    options = "--delete-older-than 14d";
  };
  nix.optimise.automatic = true;

  # The host builds its configuration from git, exactly like vps-primary: the flake in this
  # repo, on a promotion branch, applied by the 04:00 run or `systemctl start nixos-upgrade`.
  system.autoUpgrade = {
    enable = true;
    operation = "switch";
    flake = "github:djbclark/site-djbclark/deploy-dann?dir=nixos#dann";
    upgrade = false;
    dates = "04:00";
    randomizedDelaySec = "45min";
    fixedRandomDelay = true;
    persistent = true;
    allowReboot = true;
    rebootWindow = {
      lower = "03:00";
      upper = "05:00";
    };
  };

  environment.systemPackages = with pkgs; [
    vim
    git
    python3
    curl
    htop
  ];

  services.journald.extraConfig = "SystemMaxUse=200M";

  # The state version records when the machine was created, not which channel it follows.
  # nixos-anywhere installed 26.05 on 2026-10-25. Do not bump this to track an upgrade.
  system.stateVersion = "26.05";
}

