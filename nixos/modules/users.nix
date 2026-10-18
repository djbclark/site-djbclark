# The login user. No local password: key login only. Root keeps its own
# automation key (vps-primary/configuration.nix).
{ pkgs, ... }:
{
  users.users.djbclark = {
    isNormalUser = true;
    uid = 1000;
    description = "Daniel Clark";
    shell = pkgs.zsh;
    extraGroups = [ "wheel" ];
    # ~/.ssh/id_ed25519.pub on the Mac (passphrase-protected, needs the agent) and
    # the passphrase-less ~/.ssh/vps_primary_key the `vps`/`vps-primary` ssh alias
    # uses (IdentityAgent none), so `ssh djbclark@vps-primary` and BatchMode work.
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHtqrJzIIPFly8MDXpLEZEJ2WArfc5lSiCHxGTJnL8DY djbclark@djbclarks-MacBook-Air.local"
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKaWfTezsujYpykja7WRikq6jjw3r5vKgcO8o1nSaNoB djbclark@vps-primary-automation"
    ];
  };
  programs.zsh.enable = true;
  # wheel without a password: there is no local password to type.
  security.sudo.wheelNeedsPassword = false;
}
