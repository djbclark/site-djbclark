# MIT Athena pieces from SIPB's nixathena flake, trimmed to a headless server.
# Copied from `get` (forgejo.mit.edu/djbclark/get, nixos/athena.nix) and adapted:
# no Kerberos password login (tickets are pushed from the Mac instead), and AFS
# and the ticket push are in ./athena-afs.nix (phase B).
{

  pkgs,
  nixathena,
  ...
}:
let
  athena = nixathena.packages.${pkgs.stdenv.hostPlatform.system};
in
{
  nixathena = {
    enable = true;
    workstation = false; # no "any Athena user may log in", no LDAP/lightdm profile
    packages = [
      athena.moira
      athena.remctl
      athena.athrun
    ];
    pam-afs-session.enable = false; # no password logins to hand tokens to
    pyhesiodfs.enable = false;
    lightdm.enable = false;
    ldap.enable = false;
    pkgsync.enable = false;
    hesiod.enable = false;
    zephyr.enable = false;
  };
}
