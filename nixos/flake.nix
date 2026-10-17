{
  description = "djbclark site NixOS hosts (currently vps-primary)";

  # The stable branch is the same stream the old `nixos` channel followed. Which commit a
  # host builds is decided by flake.lock alone; the weekly workflow
  # .github/workflows/nixos-lock-update.yml bumps it, builds the host, and promotes it
  # (docs/nixos-in-git.md).
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
  # SIPB's Athena module (Kerberos, OpenAFS, moira/remctl/athrun); public, no credential
  # needed for the host's nightly fetch. Plan: docs/plans/vps-primary-athena.md.
  # services.cloudroom, published separately for reuse (docs/cloudroom-vps-primary.md).
  inputs.cloudroom-nix = {
    url = "github:djbclark/cloudroom-nix";
    inputs.nixpkgs.follows = "nixpkgs";
  };
  # services.bb, the BB agent app that replaces Cloudroom (plan: site-private memory/handoffs/
  # site-djbclark/PLAN_bb-replaces-cloudroom_2026-10-17.md). C1 runs it beside Cloudroom.
  inputs.bb-nix = {
    url = "github:djbclark/bb-nix";
    inputs.nixpkgs.follows = "nixpkgs";
  };
  inputs.nixathena = {
    url = "git+https://forgejo.mit.edu/SIPB/nixathena.git";
    inputs.nixpkgs.follows = "nixpkgs";
  };
  # Our headless Athena + pushed-ticket OpenAFS modules (extracted 2026-10-16 from the in-tree
  # copies); its nixathena follows ours, so the host keeps building the one locked nixathena.
  inputs.athena-nixos = {
    url = "git+https://forgejo.mit.edu/djbclark/athena-nixos";
    inputs.nixpkgs.follows = "nixpkgs";
    inputs.nixathena.follows = "nixathena";
  };

  outputs =
    {
      self,
      nixpkgs,
      athena-nixos,
      cloudroom-nix,
      bb-nix,
      ...
    }:
    {
      nixosConfigurations.vps-primary = nixpkgs.lib.nixosSystem {
        specialArgs = { inherit cloudroom-nix bb-nix; };
        modules = [
          athena-nixos.nixosModules.default # nixathena default + athena + athena-afs
          cloudroom-nix.nixosModules.default
          bb-nix.nixosModules.default
          ./vps-primary/configuration.nix
          # `nixos-version --configuration-revision` on the host then names the git commit.
          { system.configurationRevision = self.rev or self.dirtyRev or null; }
        ];
      };
    };
}
