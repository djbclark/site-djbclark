{
  description = "djbclark site NixOS hosts (currently vps-primary)";

  # The stable branch is the same stream the old `nixos` channel followed. Which commit a
  # host builds is decided by flake.lock alone; the weekly workflow
  # .github/workflows/nixos-lock-update.yml bumps it, builds the host, and promotes it
  # (docs/nixos-in-git.md).
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  # services.paseo, the Paseo agent workspace and now the only interface to the agents (2026-10-18; docs/paseo.md). Its package is
  # a tarball Forgejo CI built (forgejo.mit.edu/djbclark/paseo-nix); the host only downloads it.
  inputs.paseo-nix = {
    url = "git+https://forgejo.mit.edu/djbclark/paseo-nix";
    inputs.nixpkgs.follows = "nixpkgs";
  };
  # SIPB's Athena module (Kerberos, OpenAFS, moira/remctl/athrun); public, no credential
  # needed for the host's nightly fetch. Plan: docs/plans/vps-primary-athena.md.
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

  # 2026-10-28: disko, sops-nix and hermes-agent were dropped with the `dann` output — that
  # host, its declarative disk layout, its sops secrets and its agent runtime are now their
  # own site, https://github.com/djbclark/site-dann (nixos/, deployed from its deploy-dann
  # branch). Nothing here referenced them except that one output, so this flake builds
  # exactly what it built before (proven by an identical vps-primary toplevel drv path).

  outputs =
    {
      self,
      nixpkgs,
      athena-nixos,
      paseo-nix,
      ...
    }:
    {
      # The tendcf CFEngine fork, built from source (pkgs/cfengine-tendcf.nix). Built by
      # .github/workflows/nixos-cfengine-build.yml.
      packages.x86_64-linux.cfengine-tendcf =
        nixpkgs.legacyPackages.x86_64-linux.callPackage ./pkgs/cfengine-tendcf.nix { };

      # services.cfengine-tendcf: off by default, and its cf-execd unit off by default again.
      nixosModules.cfengine-tendcf = ./modules/cfengine-tendcf.nix;

      nixosConfigurations.vps-primary = nixpkgs.lib.nixosSystem {
        specialArgs = { inherit paseo-nix; };
        modules = [
          athena-nixos.nixosModules.default # nixathena default + athena + athena-afs
          paseo-nix.nixosModules.default
          self.nixosModules.cfengine-tendcf # imported, not enabled: the host's closure is unchanged
          ./vps-primary/configuration.nix
          # `nixos-version --configuration-revision` on the host then names the git commit.
          { system.configurationRevision = self.rev or self.dirtyRev or null; }
        ];
      };
    };
}
