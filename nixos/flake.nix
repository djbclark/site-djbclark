{
  description = "djbclark site NixOS hosts (currently vps-primary)";

  # The stable branch is the same stream the old `nixos` channel followed. Which commit a
  # host builds is decided by flake.lock alone; the weekly workflow
  # .github/workflows/nixos-lock-update.yml bumps it, builds the host, and promotes it
  # (docs/nixos-in-git.md).
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs =
    { self, nixpkgs }:
    {
      nixosConfigurations.vps-primary = nixpkgs.lib.nixosSystem {
        modules = [
          ./vps-primary/configuration.nix
          # `nixos-version --configuration-revision` on the host then names the git commit.
          { system.configurationRevision = self.rev or self.dirtyRev or null; }
        ];
      };
    };
}
