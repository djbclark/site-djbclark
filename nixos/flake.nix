{
  description = "djbclark site NixOS hosts (currently vps-primary)";

  # The stable branch is the same stream the old `nixos` channel followed. Which commit a
  # host builds is decided by flake.lock alone; the weekly workflow
  # .github/workflows/nixos-lock-update.yml bumps it, builds the host, and promotes it
  # (docs/nixos-in-git.md).
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
  # bb-nix: only its codex-npm-bin package (the Codex CLI on the bb user's and Paseo's PATH) is used.
  # Its services.bb module is no longer imported: the BB service was removed 2026-10-25. History:
  # BB replaced Cloudroom on 2026-10-17 (plan: site-private
  # memory/handoffs/site-djbclark/PLAN_bb-replaces-cloudroom_2026-10-17.md).
  inputs.bb-nix = {
    url = "github:djbclark/bb-nix";
    inputs.nixpkgs.follows = "nixpkgs";
  };
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

  outputs =
    {
      self,
      nixpkgs,
      athena-nixos,
      bb-nix,
      paseo-nix,
      ...
    }:
    {
      nixosConfigurations.vps-primary = nixpkgs.lib.nixosSystem {
        specialArgs = { inherit bb-nix paseo-nix; };
        modules = [
          athena-nixos.nixosModules.default # nixathena default + athena + athena-afs
          # bb-nix's services.bb module is not imported (BB service removed 2026-10-25); only its
          # codex-npm-bin package is used, through specialArgs.
          paseo-nix.nixosModules.default
          ./vps-primary/configuration.nix
          # `nixos-version --configuration-revision` on the host then names the git commit.
          { system.configurationRevision = self.rev or self.dirtyRev or null; }
        ];
      };
    };
}
