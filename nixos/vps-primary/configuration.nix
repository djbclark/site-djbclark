{ pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ../modules/athena.nix
    ../modules/packages.nix
    ../modules/terminals.nix
    ../modules/users.nix
  ];

  boot.loader.grub.enable = true;
  boot.loader.grub.device = "/dev/sda";

  networking.hostName = "vps-primary";
  networking.networkmanager.enable = true;
  networking.firewall.allowedTCPPorts = [ 22 ];

  users.users.root.openssh.authorizedKeys.keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKaWfTezsujYpykja7WRikq6jjw3r5vKgcO8o1nSaNoB djbclark@vps-primary-automation"
  ];

  services.openssh = {
    enable = true;
    settings = {
      PermitRootLogin = "prohibit-password";
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
      AuthenticationMethods = "publickey";
    };
  };

  environment.systemPackages = [ pkgs.vim pkgs.python3 ];

  # Joined to the tailnet 2026-10-13 with a one-time tagged auth key
  # (tag:server: no key expiry); node state lives in /var/lib/tailscale.
  # Public SSH on 22 stays open until the tailnet path is proven.
  services.tailscale = {
    enable = true;
    openFirewall = true;
  };

  # Shared Gradle remote build cache (2026-10-13): Develocity Build Cache Node,
  # pinned. Gradle deprecated it ("no longer distributed, supported or available
  # after 2026-12-31"; the replacement, Develocity Edge, needs Develocity), so the
  # image is pinned and a replacement is due by then. Reachable only on the tailnet:
  # a published Podman port is DNAT-ed and bypasses networking.firewall, so a
  # tailscale0 firewall rule would restrict nothing; the bind address does. Access
  # control lives in /var/lib/gradle-build-cache/conf/config.yaml (anonymous none,
  # one readwrite user, UI off); that file holds a password hash, so it is not
  # managed here (the Nix store is world-readable).
  users.groups.gradle-cache.gid = 5071;
  users.users.gradle-cache = {
    isSystemUser = true;
    uid = 5071;
    group = "gradle-cache";
  };
  systemd.tmpfiles.rules = [
    "d /var/lib/gradle-build-cache 0750 gradle-cache gradle-cache -"
  ];

  virtualisation.podman.enable = true;
  virtualisation.oci-containers = {
    backend = "podman";
    containers.gradle-cache = {
      image = "gradle/build-cache-node:21.2";
      cmd = [ "start" ];
      user = "5071:5071";
      ports = [ "100.125.249.107:5071:5071" ];
      volumes = [ "/var/lib/gradle-build-cache:/data" ];
      extraOptions = [
        "--memory=2g"
        "--cap-drop=ALL"
        "--security-opt=no-new-privileges"
      ];
    };
  };
  # The bind address exists only once tailscaled has brought the tailnet up.
  systemd.services.podman-gradle-cache = {
    after = [ "tailscaled.service" ];
    wants = [ "tailscaled.service" ];
    serviceConfig = {
      ExecStartPre = [
        "${pkgs.coreutils}/bin/timeout 120 ${pkgs.bash}/bin/sh -c 'until ${pkgs.tailscale}/bin/tailscale ip -4 | ${pkgs.gnugrep}/bin/grep -qx 100.125.249.107; do sleep 1; done'"
      ];
      RestartSec = "10s";
    };
  };

  # The host builds this configuration from git, never from /etc/nixos:
  # github:djbclark/site-djbclark, branch deploy-vps-primary, flake in nixos/. Deploy =
  # `git push origin master:deploy-vps-primary`, then `systemctl start nixos-upgrade` on
  # the host (or wait for the 04:00 run). Never run `nixos-rebuild` by hand on the host
  # (/etc/nixos holds no configuration on purpose).
  # nixpkgs is exactly nixos/flake.lock. The weekly workflow .github/workflows/nixos-lock-update.yml
  # bumps the lock, builds this system on a runner first, and promotes it to the deploy branch;
  # when that fails it opens an issue and messages Hermes (docs/nixos-in-git.md).
  # A kernel/initrd change reboots the host, but only inside the window; outside it the new
  # generation stays staged for the next boot. Supervised reboot tested 2026-10-13.
  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];

  system.autoUpgrade = {
    enable = true;
    operation = "switch";
    flake = "github:djbclark/site-djbclark/deploy-vps-primary?dir=nixos#vps-primary";
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

  # Keep rollbacks (14 days of generations) but bound disk use.
  nix.gc = {
    automatic = true;
    dates = "weekly";
    options = "--delete-older-than 14d";
  };
  nix.optimise.automatic = true;
  boot.loader.grub.configurationLimit = 10;

  system.stateVersion = "26.05";
}
