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

  # Unattended updates: follow the stable channel, apply daily with a random
  # delay. Kernel/initrd changes are staged (applied by the next manual reboot)
  # until a reboot has been tested with console recovery; to reboot
  # automatically set allowReboot = true plus a rebootWindow.
  system.autoUpgrade = {
    enable = true;
    operation = "switch";
    channel = "https://channels.nixos.org/nixos-26.05";
    dates = "04:00";
    randomizedDelaySec = "45min";
    fixedRandomDelay = true;
    persistent = true;
    allowReboot = false;
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
