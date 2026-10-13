{ pkgs, ... }:

{
  imports = [ ./hardware-configuration.nix ];

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

  # Unattended updates: follow root's `nixos` channel (nixos-26.05, set with
  # nix-channel; the module runs `nix-channel --update` itself, so manual
  # `nixos-rebuild` sees the same nixpkgs). Do not set `channel` here: it makes the
  # module fetch the URL without updating root's channel, and a manual rebuild
  # then downgrades the host. Apply daily with a random
  # delay. A kernel/initrd change reboots the host, but only inside the window;
  # outside it the new generation stays staged for the next boot. Supervised
  # reboot tested 2026-10-13 (back in ~22 s).
  system.autoUpgrade = {
    enable = true;
    operation = "switch";
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

  system.copySystemConfiguration = true;
  system.stateVersion = "26.05";
}
