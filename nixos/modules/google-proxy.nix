# Locked-down forward proxy so SearXNG on SIPB Hyades can reach search engines from an
# IP that is not shared by every Hyades user (docs/google-proxy-vps-primary.md).
#
# Defence in depth, because the SearXNG image is public and the proxy URL carries no
# credential:
#   1. firewall: the port accepts TCP only from the Hyades egress address, with a
#      connection cap and a new-connection rate limit; everyone else is dropped.
#   2. tinyproxy: `Allow` repeats the source check, CONNECT only to port 443, and only
#      to the hosts in `allowedHosts` (FilterDefaultDeny: anything else gets 403).
#   3. bound to the public address only (read from the interface at start, so the
#      address is not written into git), never the tailnet, loopback or Podman bridge.
# tinyproxy has no cache and adds no Via header; the access log goes to the journal
# (`journalctl -u tinyproxy-google`). Refused hosts: "Proxying refused on filtered domain".
#
# 2026-10-22: allowlist widened from Google-only to every engine the firecrawl-searxng
# image enables (general + !shortcuts). Round-robin peer: pastebin.xvm:26370
# (firecrawl-hyades/scripts/install-pastebin-egress-proxy).
#
# 2026-10-22: MIT GlobalProtect (openconnect tun0 + vpn-slice) installs 18.0.0.0/8
# via tun0. Replies to Hyades (18.4.60.84) then leave the VPN instead of enp1s0,
# so Hyades→public-IP TCP blackholes (neighbors in the same /24 still work).
# Policy-route anything sourced from the public address out enp1s0.
{ pkgs, lib, ... }:
let
  port = 26369;
  # hyades.mit.edu; every Hyades microVM leaves through this one address.
  hyadesEgress = "18.4.60.84";
  publicInterface = "enp1s0";
  # Separate routing table so "from $publicIp" does not follow tun0's 18/8.
  returnPathTable = 100;
  returnPathPriority = 100;
  # Hosts a CONNECT may reach (extended regex, case-insensitive, matched against the
  # host name only). Keep in sync with firecrawl-hyades/docs/searxng-egress.md.
  allowedHosts = [
    # Google CSE (plain "google" 403s everywhere: searxng#6359 / #6835)
    "^google\\.com$"
    "^www\\.google\\.com$"
    "^cse\\.google\\.com$"
    # Bing / Yahoo / DuckDuckGo
    "^bing\\.com$"
    "^www\\.bing\\.com$"
    "^cn\\.bing\\.com$"
    "^yahoo\\.com$"
    "^search\\.yahoo\\.com$"
    "^duckduckgo\\.com$"
    "^www\\.duckduckgo\\.com$"
    "^html\\.duckduckgo\\.com$"
    "^links\\.duckduckgo\\.com$"
    "^safe\\.duckduckgo\\.com$"
    # Wikipedia / Wikidata / Grokipedia
    "^wikipedia\\.org$"
    "^.*\\.wikipedia\\.org$"
    "^wikidata\\.org$"
    "^www\\.wikidata\\.org$"
    "^query\\.wikidata\\.org$"
    "^grokipedia\\.com$"
    "^www\\.grokipedia\\.com$"
    # Shortcut engines enabled in firecrawl-searxng settings
    "^news\\.ycombinator\\.com$"
    "^registry\\.npmjs\\.org$"
    "^crates\\.io$"
    "^static\\.crates\\.io$"
    "^lib\\.rs$"
    "^pkg\\.go\\.dev$"
    "^proxy\\.golang\\.org$"
    "^huggingface\\.co$"
    "^cdn-lfs\\.huggingface\\.co$"
    "^codeberg\\.org$"
    "^gitlab\\.com$"
    "^api\\.openalex\\.org$"
    "^api\\.crossref\\.org$"
    "^wiki\\.nixos\\.org$"
    "^nixos\\.org$"
  ];

  filterFile = pkgs.writeText "tinyproxy-google.filter" (lib.concatStringsSep "\n" allowedHosts + "\n");

  baseConf = pkgs.writeText "tinyproxy-google.base.conf" ''
    Port ${toString port}
    Allow ${hyadesEgress}
    Timeout 60
    MaxClients 40
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
    description = "Allowlisted CONNECT proxy for Hyades SearXNG engine egress (vps-primary leg)";
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
      -m connlimit --connlimit-above 80 --connlimit-mask 32 -j DROP
    iptables -A nixos-fw -p tcp -s ${hyadesEgress} --dport ${toString port} \
      -m conntrack --ctstate NEW \
      -m hashlimit --hashlimit-name gproxy --hashlimit-mode srcip \
      --hashlimit-above 40/second --hashlimit-burst 80 -j DROP
    iptables -A nixos-fw -p tcp -s ${hyadesEgress} --dport ${toString port} -j nixos-fw-accept
  '';

  # Keep Hyades→public-IP replies on enp1s0 even while GlobalProtect owns 18/8.
  systemd.services.hyades-public-return-path = {
    description = "Policy-route replies from public IP via ${publicInterface} (not MIT VPN tun0)";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    # Re-run after DHCP renews the public address / default via.
    partOf = [ "network-online.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = pkgs.writeShellScript "hyades-public-return-path-up" ''
        set -eu
        IF=${publicInterface}
        TABLE=${toString returnPathTable}
        PRIO=${toString returnPathPriority}
        IP=$(${pkgs.iproute2}/bin/ip -4 -o addr show dev "$IF" scope global \
          | ${pkgs.gawk}/bin/awk '{ sub(/\/.*/, "", $4); print $4; exit }')
        GW=$(${pkgs.iproute2}/bin/ip -4 route show default dev "$IF" \
          | ${pkgs.gawk}/bin/awk '{ print $3; exit }')
        [ -n "$IP" ] || { echo "hyades-public-return-path: no IPv4 on $IF" >&2; exit 1; }
        [ -n "$GW" ] || { echo "hyades-public-return-path: no default via on $IF" >&2; exit 1; }
        ${pkgs.iproute2}/bin/ip route replace default via "$GW" dev "$IF" table "$TABLE"
        ${pkgs.iproute2}/bin/ip rule del from "$IP" table "$TABLE" 2>/dev/null || true
        ${pkgs.iproute2}/bin/ip rule add from "$IP" table "$TABLE" priority "$PRIO"
        echo "hyades-public-return-path: from $IP via $GW dev $IF table $TABLE"
      '';
      ExecStop = pkgs.writeShellScript "hyades-public-return-path-down" ''
        set -eu
        IF=${publicInterface}
        TABLE=${toString returnPathTable}
        IP=$(${pkgs.iproute2}/bin/ip -4 -o addr show dev "$IF" scope global \
          | ${pkgs.gawk}/bin/awk '{ sub(/\/.*/, "", $4); print $4; exit }' || true)
        if [ -n "''${IP:-}" ]; then
          ${pkgs.iproute2}/bin/ip rule del from "$IP" table "$TABLE" 2>/dev/null || true
        fi
        ${pkgs.iproute2}/bin/ip route flush table "$TABLE" 2>/dev/null || true
      '';
    };
  };
}
