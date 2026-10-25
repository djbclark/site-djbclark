{
  description = "djbclark site NixOS hosts (currently vps-primary)";

  # The stable branch is the same stream the old `nixos` channel followed. Which commit a
  # host builds is decided by flake.lock alone; the weekly workflow
  # .github/workflows/nixos-lock-update.yml bumps it, builds the host, and promotes it
  # (docs/nixos-in-git.md).
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
  # disko: declarative disk partitioning, used by nixos-anywhere to install a host from scratch
  # and to keep the layout reviewable in git. Added 2026-10-25 for the `dann` host.
  inputs.disko = {
    url = "github:nix-community/disko";
    inputs.nixpkgs.follows = "nixpkgs";
  };
  # sops-nix: secrets encrypted in git, decrypted on the host at activation by its age key.
  # The house standard for this (docs/nixos-in-git.md §4: "Secrets never go in nixos/ as plain
  # text: the Nix store is world-readable and this repo is public ... adopt one before putting
  # any secret in the configuration"). Adopted 2026-10-25 for the dann host.
  #
  # WHY THIS IS SAFE IN A PUBLIC REPO: only the CIPHERTEXT is committed. The host's private age
  # key lives at /var/lib/sops-nix/key.txt (mode 0600, generated ON the host, never transmitted)
  # and is deliberately NOT in this repo or in git anywhere.
  inputs.sops-nix = {
    url = "github:Mic92/sops-nix";
    inputs.nixpkgs.follows = "nixpkgs";
  };

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
      disko,
      paseo-nix,
      sops-nix,
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

      # The entity's own host (dann.dclark.us), installed with nixos-anywhere 2026-10-25.
      # disko.nixosModules.disko is imported HERE rather than in configuration.nix, because the
      # disk layout is an installation-time concern; keeping it in this flake is what lets
      # `nixos-anywhere --flake .#dann` find the layout and the system in one place.
      # The layout itself is ./dann/disko.nix, pulled in by disko's own `disko.devices` option.
      nixosConfigurations.dann = nixpkgs.lib.nixosSystem {
        system = "x86_64-linux";
        modules = [
          disko.nixosModules.disko
          sops-nix.nixosModules.sops
          ./dann/configuration.nix
          ./dann/disko.nix
          { system.configurationRevision = self.rev or self.dirtyRev or null; }
        ];
      };
    };
}
