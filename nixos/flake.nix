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
  inputs.nixathena = {
    url = "git+https://forgejo.mit.edu/SIPB/nixathena.git";
    inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    {
      self,
      nixpkgs,
      nixathena,
      cloudroom-nix,
    }:
    {
      nixosConfigurations.vps-primary = nixpkgs.lib.nixosSystem {
        specialArgs = { inherit nixathena cloudroom-nix; };
        modules = [
          nixathena.nixosModules.default
          cloudroom-nix.nixosModules.default
          ./vps-primary/configuration.nix
          # `nixos-version --configuration-revision` on the host then names the git commit.
          { system.configurationRevision = self.rev or self.dirtyRev or null; }
        ];
      };
    };
}
