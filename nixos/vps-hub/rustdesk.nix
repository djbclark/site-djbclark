# RustDesk self-hosted hub (2026-11-09): the upstream nixpkgs module services.rustdesk-server
# runs hbbs (ID/rendezvous "signal") and hbbr (relay). Reachable only over the tailnet: the module's
# openFirewall stays false and the ports are opened on tailscale0 alone (same pattern as
# ../modules/terminals.nix). The web client (TCP 21118/21119) is not used, so those stay closed.
#
# Keys: hbbs creates id_ed25519 / id_ed25519.pub in its StateDirectory (/var/lib/rustdesk, a
# DynamicUser dir under /var/lib/private) on first start; hbbr reads the same pair. `-k _` makes
# both servers require that key, so only clients configured with the public key can use the hub.
#
# Client settings: ID server and relay server = 100.82.208.87 (vps-hub on the tailnet),
# key = contents of /var/lib/rustdesk/id_ed25519.pub.
{ ... }:

{
  services.rustdesk-server = {
    enable = true;
    openFirewall = false;
    # Handed to clients as the relay address. The tailnet IP (stable for this node) rather than
    # the MagicDNS name, so clients that don't use MagicDNS still reach it.
    signal.relayHosts = [ "100.82.208.87" ];
    signal.extraArgs = [ "-k" "_" ];
    relay.extraArgs = [ "-k" "_" ];
  };

  # hbbs generates the key pair on first start; start hbbr after it so both use one pair.
  systemd.services.rustdesk-relay = {
    after = [ "rustdesk-signal.service" ];
    wants = [ "rustdesk-signal.service" ];
  };

  networking.firewall.interfaces.tailscale0 = {
    # 21115 NAT test, 21116 ID/rendezvous (TCP hole punching), 21117 relay.
    allowedTCPPorts = [ 21115 21116 21117 ];
    # 21116 ID registration and heartbeats.
    allowedUDPPorts = [ 21116 ];
  };
}
