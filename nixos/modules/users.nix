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
    # ~/.ssh/id_ed25519.pub on the Mac.
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHtqrJzIIPFly8MDXpLEZEJ2WArfc5lSiCHxGTJnL8DY djbclark@djbclarks-MacBook-Air.local"
    ];
  };
  programs.zsh.enable = true;
  # wheel without a password: there is no local password to type.
  security.sudo.wheelNeedsPassword = false;
}
