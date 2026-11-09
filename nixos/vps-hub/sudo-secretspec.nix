# The sudo-secretspec broker on vps-hub (2026-11-09, migrated from vps-primary for its retirement).
# Same posture and caveats as ../vps-primary/sudo-secretspec.nix (operator djbclark is wheel/NOPASSWD, so this is
# reason-forcing friction plus a value-free audit ledger, not a boundary against the operator). Fresh vault: the
# vps-primary vault held only the never-set placeholder, so no values moved; its audit ledger stays there.
{ ... }:

{
  services.sudo-secretspec = {
    enable = true;
    operator = "djbclark";
    declarations = ./secretspec-manifest.toml;
  };
  nix.settings.allow-import-from-derivation = true;
}
