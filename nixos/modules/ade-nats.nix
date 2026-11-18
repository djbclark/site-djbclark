{ config, lib, pkgs, ... }:

let
  cfg = config.services.ade-nats;
  publicConfig = (pkgs.formats.json { }).generate "ade-nats-public.json" config.services.nats.settings;
  start = pkgs.writeShellScript "ade-nats-start" ''
    set -eu
    umask 077
    # Only authentication may come from the credential. It cannot change the
    # listener, persistence policy or data directory in the reviewed config.
    ${pkgs.jq}/bin/jq -e '
      type == "object" and keys == ["authorization"] and
      (.authorization | type == "object" and keys == ["token"]) and
      (.authorization.token | type == "string" and test("^[A-Za-z0-9_-]{32,}$"))
    ' "$CREDENTIALS_DIRECTORY/nats-auth.json" >/dev/null
    ${pkgs.jq}/bin/jq --slurpfile auth "$CREDENTIALS_DIRECTORY/nats-auth.json" \
      '.authorization = $auth[0].authorization' ${publicConfig} > "$RUNTIME_DIRECTORY/server.json"
    exec ${pkgs.nats-server}/bin/nats-server --config "$RUNTIME_DIRECTORY/server.json"
  '';
in
{
  options.services.ade-nats = {
    enable = lib.mkEnableOption "ADE's single-node JetStream coordination broker";
    listenAddress = lib.mkOption {
      type = lib.types.str;
      description = "The host's Tailscale IPv4 address; never a wildcard listener.";
    };
    port = lib.mkOption { type = lib.types.port; default = 4222; };
    monitorPort = lib.mkOption { type = lib.types.port; default = 8222; };
    authFile = lib.mkOption {
      type = lib.types.str;
      default = "/etc/credstore/ade-nats-auth.json";
      description = "Root-owned runtime JSON credential; provision through sudo-secretspec, never Nix store.";
    };
    dataDir = lib.mkOption { type = lib.types.str; default = "/var/lib/nats"; };
    maxFileStore = lib.mkOption { type = lib.types.ints.positive; default = 10737418240; };
    maxMemoryStore = lib.mkOption { type = lib.types.ints.positive; default = 268435456; };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      { assertion = config.services.tailscale.enable; message = "ADE NATS requires Tailscale."; }
      { assertion = config.networking.firewall.enable; message = "ADE NATS requires the host firewall."; }
      { assertion = builtins.match "100\\.[0-9]+\\.[0-9]+\\.[0-9]+" cfg.listenAddress != null;
        message = "ADE NATS must bind an explicit Tailscale IPv4 address."; }
      { assertion = lib.hasPrefix "/" cfg.authFile && !(lib.hasPrefix "/nix/store/" cfg.authFile);
        message = "ADE NATS authentication must be a runtime credential outside the Nix store."; }
    ];

    services.nats = {
      enable = true;
      jetstream = true;
      serverName = "ade-coord-${config.networking.hostName}";
      port = cfg.port;
      dataDir = cfg.dataDir;
      settings = {
        host = cfg.listenAddress;
        http = "127.0.0.1:${toString cfg.monitorPort}";
        jetstream = {
          max_file_store = cfg.maxFileStore;
          max_memory_store = cfg.maxMemoryStore;
          sync_interval = "always";
        };
      };
    };

    networking.firewall.interfaces.tailscale0.allowedTCPPorts = [ cfg.port ];
    systemd.services.nats = {
      requires = [ "tailscaled.service" ];
      after = [ "tailscaled.service" "network-online.target" ];
      wants = [ "network-online.target" ];
      unitConfig = {
        RequiresMountsFor = cfg.dataDir;
        StartLimitIntervalSec = 0;
      };
      restartTriggers = [ publicConfig ];
      serviceConfig = {
        ExecStart = lib.mkForce start;
        LoadCredential = [ "nats-auth.json:${cfg.authFile}" ];
        RuntimeDirectory = "ade-nats";
        RuntimeDirectoryMode = "0700";
        RestartSec = "5s";
        MemoryMax = "1G";
      };
    };
  };
}
