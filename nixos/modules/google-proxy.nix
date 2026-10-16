# Locked-down forward proxy so SearXNG on SIPB Hyades can reach Google from an IP that
# is not shared by every Hyades user (docs/google-proxy-vps-primary.md).
#
# Defence in depth, because the SearXNG image is public and the proxy URL carries no
# credential:
#   1. firewall: the port accepts TCP only from the Hyades egress address, with a
#      connection cap and a new-connection rate limit; everyone else is dropped.
#   2. tinyproxy: `Allow` repeats the source check, CONNECT only to port 443, and only
#      to the hosts in `allowedHosts` (FilterDefaultDeny: anything else gets 403).
#   3. bound to the public address only (read from the interface at start, so the
#      address is not written into git), never the tailnet, loopback or Podman bridge.
# tinyproxy has no cache and adds no Via header; the access log goes to the journal.
{ pkgs, lib, ... }:
let
  port = 26369;
  # hyades.mit.edu; every Hyades microVM leaves through this one address.
  hyadesEgress = "18.4.60.84";
  publicInterface = "enp1s0";
  # Hosts a CONNECT may reach (extended regex, case-insensitive, matched against the
  # host name only). Keep this the measured minimum (docs/google-proxy-vps-primary.md).
  # cse.google.com: SearXNG's "google cse" engine (results from /cse/element/v1; its
  # token comes from www.google.com/cse/cse.js). The plain "google" engine 403s from
  # every address since 2026-07 (searxng#6359, #6835), so "google cse" is the one in use.
  allowedHosts = [
    "^google\\.com$"
    "^www\\.google\\.com$"
    "^cse\\.google\\.com$"
  ];

  filterFile = pkgs.writeText "tinyproxy-google.filter" (lib.concatStringsSep "\n" allowedHosts + "\n");

  baseConf = pkgs.writeText "tinyproxy-google.base.conf" ''
    Port ${toString port}
    Allow ${hyadesEgress}
    Timeout 60
    MaxClients 20
    ConnectPort 443
    Filter "${filterFile}"
    FilterType ere
    FilterURLs Off
    FilterCaseSensitive Off
    FilterDefaultDeny Yes
    DisableViaHeader Yes
    Syslog On
    LogLevel Info
  '';

  start = pkgs.writeShellScript "tinyproxy-google-start" ''
    set -eu
    ip=$(${pkgs.iproute2}/bin/ip -4 -o addr show dev ${publicInterface} scope global \
      | ${pkgs.gawk}/bin/awk '{ sub(/\/.*/, "", $4); print $4; exit }')
    [ -n "$ip" ] || { echo "tinyproxy-google: no IPv4 address on ${publicInterface}" >&2; exit 1; }
    { cat ${baseConf}; echo "Listen $ip"; } > "$RUNTIME_DIRECTORY/tinyproxy.conf"
    exec ${pkgs.tinyproxy}/bin/tinyproxy -d -c "$RUNTIME_DIRECTORY/tinyproxy.conf"
  '';
in
{
  systemd.services.tinyproxy-google = {
    description = "Allowlisted CONNECT proxy for SearXNG's Google engines";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    serviceConfig = {
      ExecStart = start;
      Restart = "on-failure";
      RestartSec = "10s";
      DynamicUser = true;
      RuntimeDirectory = "tinyproxy-google";
      MemoryMax = "128M";
      NoNewPrivileges = true;
      CapabilityBoundingSet = "";
      ProtectSystem = "strict";
      ProtectHome = true;
      PrivateTmp = true;
      PrivateDevices = true;
      ProtectKernelTunables = true;
      ProtectControlGroups = true;
      RestrictAddressFamilies = [
        "AF_INET"
        "AF_UNIX"
        "AF_NETLINK" # `ip addr` in the start script
      ];
      SystemCallFilter = [ "@system-service" ];
    };
  };

  # The firewall is the iptables backend (nftables is off), so extraInputRules does not
  # apply; extraCommands runs after the allowed-port rules and before the final refuse.
  networking.firewall.extraCommands = ''
    iptables -A nixos-fw -p tcp -s ${hyadesEgress} --dport ${toString port} \
      -m connlimit --connlimit-above 40 --connlimit-mask 32 -j DROP
    iptables -A nixos-fw -p tcp -s ${hyadesEgress} --dport ${toString port} \
      -m conntrack --ctstate NEW \
      -m hashlimit --hashlimit-name gproxy --hashlimit-mode srcip \
      --hashlimit-above 30/second --hashlimit-burst 60 -j DROP
    iptables -A nixos-fw -p tcp -s ${hyadesEgress} --dport ${toString port} -j nixos-fw-accept
  '';
}
