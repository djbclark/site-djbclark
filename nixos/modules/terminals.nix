# Roaming terminals, reachable on the tailnet only (docs/plans/vps-primary-athena.md 1.7).
#   mosh vps-ts            (UDP 60000-61000)
#   et vps-ts:2022         (TCP; the client runs etterminal over ssh first)
{ ... }:
{
  programs.mosh = {
    enable = true;
    openFirewall = false;
  };
  services.eternal-terminal = {
    enable = true;
    port = 2022;
  };
  networking.firewall.interfaces.tailscale0 = {
    allowedTCPPorts = [ 2022 ];
    allowedUDPPortRanges = [
      {
        from = 60000;
        to = 61000;
      }
    ];
  };
}
