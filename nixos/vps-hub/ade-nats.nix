{ ... }:
{
  imports = [ ../modules/ade-nats.nix ];

  services.ade-nats = {
    # Prepared infrastructure only. Enable in a reviewed activation commit
    # after CI, runtime credential provisioning and the two-host proof.
    enable = false;
    listenAddress = "100.82.208.87";
    authFile = "/etc/credstore/ade-nats-auth.json";
  };
}
