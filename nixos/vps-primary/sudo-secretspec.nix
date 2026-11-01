# The sudo-secretspec privilege boundary on vps-primary.
#
# Module: `sudo-secretspec.nixosModules.default` (flake input, wired in nixos/flake.nix).
# Names only live in git: ./secretspec-manifest.toml is a DECLARATIONS template, never values.
#
# HONEST SCOPE: the boundary is NOT a security boundary against the operator here.
# modules/users.nix puts `djbclark` in wheel with `security.sudo.wheelNeedsPassword = false`
# (`%wheel ... NOPASSWD:SETENV: ALL`), so `djbclark` is root-equivalent and can `sudo cat` the
# vault directly. What the module adds is reason-forcing friction (a named broker verb with a
# required `--reason`) and a hash-chained value-free audit ledger. Same posture as site-dann:
# https://github.com/frdminc/sudo-secretspec/blob/sudo-main/docs/design/dann-deployment-threat-model.md
#
# operator = "djbclark": the interactive/agent account (Paseo's agents run as it,
# docs/agents-vps-primary.md); the module asserts it is a declared non-root user
# (modules/users.nix). root's ssh login is automation only. serviceUser, serviceGroup, vault
# (/var/lib/sudo-secretspec) and profile ("default") take the module defaults.
{ ... }:

{
  services.sudo-secretspec = {
    enable = true;
    operator = "djbclark";
    declarations = ./secretspec-manifest.toml;
  };

  # The module derives its sudoers text from the broker binary (import-from-derivation). Nix's
  # default is already true; stated so the dependency is visible, as in site-dann.
  nix.settings.allow-import-from-derivation = true;
}
