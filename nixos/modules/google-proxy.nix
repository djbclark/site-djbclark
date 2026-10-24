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
# 2026-10-23: GlobalProtect removed everywhere; this host has no tun0/18-8 route now and
# cannot reach MIT at all (it is only a Tailscale exit node). The tailnet reaches
# 18.0.0.0/8 via the subnet route on pastebin.xvm.mit.edu (100.104.212.89). The table-100
# rule stays as a cheap guard in case an 18/8 route ever returns.
{ pkgs, lib, ... }:
let
  port = 26369;
  # hyades.mit.edu; every Hyades microVM leaves through this one address.
  hyadesEgress = "18.4.60.84";
  # 2026-10-24: MIT's border stopped forwarding anything to this host's public address (pastebin.xvm and Hyades
  # SYNs and pings never arrive on enp1s0 while check-host.net probes do; traceroute from pastebin dies after 18.0.161.1;
  # firecrawl-hyades/docs/hyades-watch.md). pastebin.xvm reaches this host over the tailnet, so it relays: Hyades ->
  # pastebin:26371 (tinyproxy-vpsrelay) -> tailnet -> this proxy -> the internet from this host's address. This is
  # pastebin's tailnet address. The proxy also listens on this host's tailnet address, but NO iptables rule guards that
  # path: tailscaled's `ts-input` chain accepts everything arriving on tailscale0 before nixos-fw (checked 2026-10-24:
  # `-A ts-input -i tailscale0 -j ACCEPT`, and a rule here showed 0 packets). The gates are WireGuard source
  # authentication, the tailscale ACL (should allow only this peer to tcp/26369) and tinyproxy's `Allow` below.
  relayPeer = "100.104.212.89";
  tailnetInterface = "tailscale0";
  # 2026-10-24 (firecrawl-hyades docs/tunnel.md): a reverse WebSocket tunnel is held open to a wstunnel server inside the
  # SearXNG microVM on Hyades (wss://tunnelHost through Hyades' Caddy). That server listens on 127.0.0.1:tunnelPort THERE and
  # forwards every connection back here to this proxy on 127.0.0.1:port. CAVEAT: this host cannot reach MIT's own networks over
  # the public Internet either (the block is both ways), so the client only connects because this host's route to 18.0.0.0/8
  # is the tailnet subnet route through pastebin: today the tunnel does not remove the pastebin dependency. Nothing on Hyades
  # uses it yet.
  tunnelHost = "djbclark-firecrawl-tunnel.sipb.cloud";
  tunnelPort = 26372;
  publicInterface = "enp1s0";
  # Separate routing table so "from $publicIp" never follows an 18/8 route (was GP tun0).
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
    # devsearch (firecrawl-hyades, 2026-10-24): the GitHub search API for Firecrawl's developer search
    "^api\\.github\\.com$"
  ];

  filterFile = pkgs.writeText "tinyproxy-google.filter" (lib.concatStringsSep "\n" allowedHosts + "\n");

  baseConf = pkgs.writeText "tinyproxy-google.base.conf" ''
    Port ${toString port}
    Allow ${hyadesEgress}
    Allow ${relayPeer}
    Allow 127.0.0.1
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
    # tailnet listener for the pastebin relay; tailscaled may still be coming up at boot, so wait a little for its address.
    # No address after 30 s: exit, so systemd retries every 10 s. The public address is unreachable from MIT, so a
    # public-only proxy would be a leg that looks up and carries nothing.
    ts=""
    for _ in $(${pkgs.coreutils}/bin/seq 1 30); do
      ts=$(${pkgs.iproute2}/bin/ip -4 -o addr show dev ${tailnetInterface} | ${pkgs.gawk}/bin/awk '{ sub(/\/.*/, "", $4); print $4; exit }' || true)
      [ -n "$ts" ] && break
      ${pkgs.coreutils}/bin/sleep 1
    done
    [ -n "$ts" ] || { echo "tinyproxy-google: no IPv4 address on ${tailnetInterface}" >&2; exit 1; }
    { cat ${baseConf}; echo "Listen $ip"; echo "Listen $ts"; echo "Listen 127.0.0.1"; } > "$RUNTIME_DIRECTORY/tinyproxy.conf"
    exec ${pkgs.tinyproxy}/bin/tinyproxy -d -c "$RUNTIME_DIRECTORY/tinyproxy.conf"
  '';
in
{
  systemd.services.tinyproxy-google = {
    description = "Allowlisted CONNECT proxy for Hyades SearXNG engine egress (vps-primary leg)";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" "tailscaled.service" ];
    wants = [ "network-online.target" "tailscaled.service" ];
    # A crash loop stops: 5 failed starts in 15 minutes leave the unit `failed` instead of retrying every 10 s for ever.
    # hyades-watch sees `failed`, alerts (Hermes Watch topic) and restarts it at most twice an hour (after reset-failed).
    unitConfig = {
      StartLimitIntervalSec = 900;
      StartLimitBurst = 5;
    };
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

  # The reverse tunnel client. The shared secret (the WebSocket path prefix the Hyades server requires) is in a root-only
  # file that is not in git or the Nix store: /etc/wstunnel-hyades.env containing one line,
  # WSTUNNEL_HTTP_UPGRADE_PATH_PREFIX=<secret> (docs/google-proxy-vps-primary.md section 6). It keeps reconnecting by itself
  # (at most a minute apart); a start limit stops a real crash loop and hyades-watch notices either.
  systemd.services.wstunnel-hyades = {
    description = "Reverse WebSocket tunnel from Hyades (SearXNG microVM) back to tinyproxy-google";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" "tinyproxy-google.service" ];
    wants = [ "network-online.target" "tinyproxy-google.service" ];
    unitConfig = {
      StartLimitIntervalSec = 900;
      StartLimitBurst = 5;
    };
    serviceConfig = {
      EnvironmentFile = "/etc/wstunnel-hyades.env";
      ExecStart = lib.concatStringsSep " " [
        "${pkgs.wstunnel}/bin/wstunnel client"
        "--tls-verify-certificate"
        "--reverse-tunnel-connection-retry-max-backoff 60s"
        "-R tcp://127.0.0.1:${toString tunnelPort}:127.0.0.1:${toString port}"
        "wss://${tunnelHost}:443"
      ];
      Restart = "on-failure";
      RestartSec = "10s";
      DynamicUser = true;
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
        "AF_INET6"
        "AF_UNIX"
      ];
      SystemCallFilter = [ "@system-service" ];
    };
  };

  # The firewall is the iptables backend (nftables is off), so extraInputRules does not
  # apply; extraCommands runs after the allowed-port rules and before the final refuse.
  networking.firewall.extraCommands = ''
    iptables -A nixos-fw -i ${publicInterface} -p tcp -s ${hyadesEgress} --dport ${toString port} \
      -m connlimit --connlimit-above 80 --connlimit-mask 32 -j DROP
    iptables -A nixos-fw -i ${publicInterface} -p tcp -s ${hyadesEgress} --dport ${toString port} \
      -m conntrack --ctstate NEW \
      -m hashlimit --hashlimit-name gproxy --hashlimit-mode srcip \
      --hashlimit-above 40/second --hashlimit-burst 80 -j DROP
    iptables -A nixos-fw -i ${publicInterface} -p tcp -s ${hyadesEgress} --dport ${toString port} -j nixos-fw-accept
  '';

  # Keep Hyades→public-IP replies on enp1s0 even if something (formerly GlobalProtect)
  # owns 18/8.
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
