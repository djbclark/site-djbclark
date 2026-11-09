# Shared Gradle remote build cache on vps-hub (2026-11-09, migrated from vps-primary for its retirement).
# Same FosterStack cache container and hardening as vps-primary/configuration.nix (see docs/gradle-remote-cache.md);
# only the bind address differs: vps-hub's tailnet IPv4 100.82.208.87. A published Podman port is DNAT-ed and bypasses
# networking.firewall, so the bind address is what keeps it tailnet-only.
# Credentials: /var/lib/gradle-cache.env (root 0600, FSCACHE_USERNAME/FSCACHE_PASSWORD), copied by hand from
# vps-primary, never in git or the store. The unit refuses to start without them (auth off = open cache).
# Clients (the Mac's Gradle init script) still point at vps-primary's 100.125.249.107:5071 until cut over.
{ pkgs, ... }:
let
  tailnetIp = "100.82.208.87";
in
{
  users.groups.gradle-cache.gid = 5071;
  users.users.gradle-cache = {
    isSystemUser = true;
    uid = 5071;
    group = "gradle-cache";
  };

  virtualisation.oci-containers = {
    backend = "podman";
    containers.gradle-cache = {
      # ghcr.io/fosterstack/cache:0.2.2 (same digest as vps-primary)
      image = "ghcr.io/fosterstack/cache@sha256:f2b330cf27b3814405230cc001a771909ae5bbf3b1e223a90ee7a9ee5d0e53dd";
      user = "5071:5071";
      ports = [ "${tailnetIp}:5071:8080" ];
      volumes = [ "/var/lib/gradle-cache:/data" ];
      environment = {
        FSCACHE_ADDR = ":8080";
        FSCACHE_DATA_DIR = "/data";
        FSCACHE_MAX_BYTES = toString (8 * 1024 * 1024 * 1024);
        FSCACHE_MAX_BODY_BYTES = toString (256 * 1024 * 1024);
        FSCACHE_MAX_CONCURRENT_UPLOADS = "8";
      };
      environmentFiles = [ "/var/lib/gradle-cache.env" ];
      extraOptions = [
        "--memory=1g"
        "--read-only"
        "--cap-drop=ALL"
        "--security-opt=no-new-privileges"
      ];
    };
  };

  # The bind address exists only once tailscaled has brought the tailnet up.
  systemd.services.podman-gradle-cache = {
    after = [ "tailscaled.service" ];
    wants = [ "tailscaled.service" ];
    serviceConfig = {
      ExecStartPre = [
        "${pkgs.bash}/bin/sh -c '${pkgs.gnugrep}/bin/grep -q \"^FSCACHE_USERNAME=.\" /var/lib/gradle-cache.env && ${pkgs.gnugrep}/bin/grep -q \"^FSCACHE_PASSWORD=.\" /var/lib/gradle-cache.env || { echo \"gradle-cache: /var/lib/gradle-cache.env lacks FSCACHE_USERNAME/FSCACHE_PASSWORD; refusing to start with auth off\" >&2; exit 1; }'"
        "${pkgs.coreutils}/bin/timeout 120 ${pkgs.bash}/bin/sh -c 'until ${pkgs.tailscale}/bin/tailscale ip -4 | ${pkgs.gnugrep}/bin/grep -qx ${tailnetIp}; do sleep 1; done'"
      ];
      RestartSec = "10s";
    };
  };
}
