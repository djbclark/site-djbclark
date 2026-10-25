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
  # DISKO OWNS THESE. It derives `fileSystems."/"` from the layout in nixos/dann/disko.nix
  # (`/dev/disk/by-partlabel/disk-main-root`) and defines it itself, so declaring it here
  # conflicts: "The option `fileSystems."/".device' has conflicting definition values".
  # Verified 2026-10-25 — this comment replaces a manual definition that failed evaluation.
  #
  # The one thing that DOES need declaring is swap: disko creates the partition but does not
  # add it to `swapDevices`.
  swapDevices = [ { device = "/dev/disk/by-partlabel/disk-main-swap"; } ];

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
  # `dann` is the entity's own account. It is root-equivalent, and that is deliberate
  # (djbclark, 2026-10-25: "give the entity root — simpler for automation, larger blast
  # radius accepted").
  #
  # BE ACCURATE ABOUT WHAT THIS IS. An earlier version of this comment claimed sudo "keeps
  # that boundary visible instead of hiding it behind uid 0". That was WRONG and is corrected
  # here, because a false claim of a boundary is worse than no boundary: someone will trust it.
  # The verified truth on this host (2026-10-25):
  #
  #     /etc/sudoers: %wheel ALL=(ALL:ALL) NOPASSWD:SETENV: ALL
  #     $ sudo -n id -u   ->  0
  #
  # So sudo is FRICTION, NOT A BOUNDARY. It costs one command prefix; it does not restrict
  # anything. The only real difference from uid 0 is that files dann creates without sudo are
  # owned by dann, and that a careless command has to be prefixed with `sudo` to be destructive.
  #
  # Why not make uid literally 0: it buys no security (the power is already there) and breaks
  # real things — /home/dann ownership, systemd --user units, NixOS's own user expectations.
  # "Root" here means root-equivalent, which is what this is.
  #
  # What actually mitigates the blast radius (and this is the honest list):
  #   1. The box is DISPOSABLE. Its whole configuration is in git
  #      (site-djbclark nixos/dann/, on deploy-dann), and a full reinstall measured ~2 minutes
  #      on 2026-10-25. There is nothing on it that cannot be rebuilt.
  #   2. It holds no data of its own yet — the entity's memory still lives on the Mac, which is
  #      exactly why phase 1 (memory) must add its own guards rather than relying on this one.
  #   3. Everything outward-facing, billable or irreversible still needs a fresh yes from the
  #      operator. That rule is about ACTIONS, and it survives root.
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
  # No local password exists to type, so wheel must not demand one. This is what makes the
  # account root-equivalent — see the note above, which is the accurate version.
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

  # ── Secrets: sops-nix with age ────────────────────────────────────────────────────────
  # The house standard (docs/nixos-in-git.md §4). Only CIPHERTEXT is committed; this repo is
  # public, which is safe because an age public key encrypts but cannot decrypt.
  #
  # The host's private age key was generated ON the host on 2026-10-25 and has never been
  # transmitted: /var/lib/sops-nix/key.txt, mode 0600, root-owned. It is not in git anywhere.
  # Public key (in .sops.yaml): age1kpu8804m763x7aet9pwhm92k4h44qmk34xmxg3yynhdsct5f4pfqrv548p
  #
  # LEAST PRIVILEGE IS THE POINT (main instance's ruling, 2026-10-25): this host holds only the
  # credentials its own work needs, NOT the operator's full set. A file store holding three
  # scoped credentials is a smaller exposure than a perfect boundary holding all of them, so the
  # rule is that a secret is added here only when a service on THIS host actually consumes it.
  sops = {
    age.keyFile = "/var/lib/sops-nix/key.txt";
    defaultSopsFile = ./secrets/dann.yaml;
    defaultSopsFormat = "yaml";
    # Validate the secret declarations against the encrypted file at evaluation time, so a
    # renamed or removed key is caught before the switch rather than at activation.
    validateSopsFiles = true;

    # Each secret is declared with its consumer's identity and mode.
    #
    # `sops_probe` is a CANARY, and it is deliberately permanent rather than a one-off test. It
    # proves encrypt -> commit -> deploy -> decrypt end to end, so a break in the sops path shows up
    # here (`/run/secrets/sops_probe` missing or empty) rather than silently waiting for the first
    # real credential to fail. An earlier comment said to remove it once a real secret had been
    # through the same path; on reflection that would delete the only canary and make a future
    # failure invisible, so it stays.
    secrets."sops_probe" = {
      owner = "dann";
      group = "users";
      mode = "0400";
    };
  };

  environment.systemPackages = with pkgs; [
    vim
    git
    python3
    curl
    htop
    # age is here so the operator (or a future session) can inspect or re-key without a nix shell.
    age
    sops
  ];

  services.journald.extraConfig = "SystemMaxUse=200M";

  # The state version records when the machine was created, not which channel it follows.
  # nixos-anywhere installed 26.05 on 2026-10-25. Do not bump this to track an upgrade.
  system.stateVersion = "26.05";
}

