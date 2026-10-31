# Makes the tendcf CFEngine fork present on a NixOS host: its binaries and its work directory,
# and optionally cf-execd. Off by default at both levels; nothing starts unless
# services.cfengine-tendcf.enable and services.cfengine-tendcf.execd.enable are both true.
#
# Deliberately not here (later stages of tendcf's nixos-passthrough-plan.md): cf-serverd,
# bootstrap, policy files. The module never writes /etc/systemd/system (read-only on NixOS)
# and renders no unit for anything but cf-execd.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.cfengine-tendcf;
  # The compiled-in work directory (--with-workdir), exported by the package.
  workdir = cfg.package.workdir;
in
{
  options.services.cfengine-tendcf = {
    enable = lib.mkEnableOption "the tendcf CFEngine fork (installs the binaries, creates the work directory)";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ../pkgs/cfengine-tendcf.nix { };
      defaultText = lib.literalExpression "pkgs.callPackage ../pkgs/cfengine-tendcf.nix { }";
      description = "The CFEngine package. It must expose its compiled-in work directory as `workdir`.";
    };

    execd.enable = lib.mkEnableOption "the cfengine-tendcf-execd service (cf-execd as root; has an effect only with services.cfengine-tendcf.enable)";
  };

  config = lib.mkMerge [
    (lib.mkIf cfg.enable {
      environment.systemPackages = [ cfg.package ];

      systemd.tmpfiles.rules = [ "d ${workdir} 0755 root root -" ];
    })

    (lib.mkIf (cfg.enable && cfg.execd.enable) {
      systemd.services.cfengine-tendcf-execd = {
        description = "CFEngine execution scheduler (tendcf fork)";
        wantedBy = [ "multi-user.target" ];
        serviceConfig = {
          ExecStart = "${cfg.package}/bin/cf-execd --no-fork";
          Restart = "on-failure";
        };
      };
    })
  ];
}
