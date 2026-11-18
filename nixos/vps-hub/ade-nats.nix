{ ... }:
{
  imports = [ ../modules/ade-nats.nix ];

  services.ade-nats = {
    # Candidate activation config: build/review the enabled system in CI,
    # then provision runtime authentication and approve promotion before deploy.
    # Enroll live roles only after the two-host shadow and recovery proof.
    enable = true;
    listenAddress = "100.82.208.87";
    authFile = "/etc/credstore/ade-nats-auth.json";
  };
}
