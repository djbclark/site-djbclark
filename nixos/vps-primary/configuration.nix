{ pkgs, cloudroom-nix, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ../modules/google-proxy.nix
    ../modules/packages.nix
    ../modules/terminals.nix
    ../modules/users.nix
  ];

  # Athena/AFS come from the athena-nixos flake input (nixos/flake.nix); the values below are
  # what the in-tree athena-afs.nix hard-coded until 2026-10-17. Plan: docs/plans/vps-primary-athena.md.
  athena-afs.user = "djbclark";
  athena-afs.pushFrom = "100.113.53.87";
  athena-afs.pushKeys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAhjpIb8xyRFKfrYvZuwsaH4GgV/ViZfvq5XoNn3SgRy djbclark@mac-athena-tgt-push"
  ];

  boot.loader.grub.enable = true;
  boot.loader.grub.device = "/dev/sda";

  networking.hostName = "vps-primary";
  networking.networkmanager.enable = true;
  networking.firewall.allowedTCPPorts = [ 22 ];

  users.users.root.openssh.authorizedKeys.keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKaWfTezsujYpykja7WRikq6jjw3r5vKgcO8o1nSaNoB djbclark@vps-primary-automation"
  ];

  services.openssh = {
    enable = true;
    settings = {
      PermitRootLogin = "prohibit-password";
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
      AuthenticationMethods = "publickey";
      # Phase C of docs/plans/vps-primary-athena.md (2026-10-15).
      AllowUsers = [
        "root"
        "djbclark"
      ];
      MaxAuthTries = 3;
      LoginGraceTime = 30;
    };
    # OpenSSH's default PerSourcePenalties stay on for the public address; the
    # tailnet (the Mac's fleet-watch probes and pushes) is never penalised. No
    # backticks or $ here: the module pastes this through a shell heredoc.
    extraConfig = ''
      PerSourcePenaltyExemptList 100.64.0.0/10
    '';
  };

  environment.systemPackages = [ pkgs.vim pkgs.python3 ];

  # Joined to the tailnet 2026-10-13 with a one-time tagged auth key
  # (tag:server: no key expiry); node state lives in /var/lib/tailscale.
  # Public SSH on 22 stays open until the tailnet path is proven.
  services.tailscale = {
    enable = true;
    openFirewall = true;
  };

  # Shared Gradle remote build cache: FosterStack cache (github.com/fosterstack/cache,
  # MIT, Go), replacing the Develocity Build Cache Node on 2026-10-15 (Gradle ends
  # that node after 2026-12-31; its successor, Develocity Edge, needs Develocity).
  # The image is pinned by index digest, v0.2.2; its build provenance was checked
  # with `gh attestation verify` (docs/gradle-remote-cache.md, "Upgrade the node").
  # Reachable only on the tailnet: a published Podman port is DNAT-ed and bypasses
  # networking.firewall, so a tailscale0 firewall rule would restrict nothing; the
  # bind address does. Host port stays 5071, so the Mac's init script is unchanged.
  # Credentials (FSCACHE_USERNAME/FSCACHE_PASSWORD, one read-write user `mac`) come
  # from a root-only env file created by hand, never the Nix store (world-readable).
  # Without them the server would start with auth OFF, which would make the cache an
  # anonymous code-injection point, so the unit refuses to start unless both are set.
  users.groups.gradle-cache.gid = 5071;
  users.users.gradle-cache = {
    isSystemUser = true;
    uid = 5071;
    group = "gradle-cache";
  };
  systemd.tmpfiles.rules = [
    "d /var/lib/gradle-cache 0750 gradle-cache gradle-cache -"
  ];

  virtualisation.podman.enable = true;
  virtualisation.oci-containers = {
    backend = "podman";
    containers.gradle-cache = {
      # ghcr.io/fosterstack/cache:0.2.2
      image = "ghcr.io/fosterstack/cache@sha256:f2b330cf27b3814405230cc001a771909ae5bbf3b1e223a90ee7a9ee5d0e53dd";
      user = "5071:5071";
      ports = [ "100.125.249.107:5071:8080" ];
      volumes = [ "/var/lib/gradle-cache:/data" ];
      environment = {
        FSCACHE_ADDR = ":8080";
        FSCACHE_DATA_DIR = "/data";
        FSCACHE_MAX_BYTES = toString (8 * 1024 * 1024 * 1024);
        FSCACHE_MAX_BODY_BYTES = toString (256 * 1024 * 1024);
        # Disk can overshoot the cap by body size x uploads in flight before
        # eviction runs: 8 x 256 MiB = 2 GiB, not the default 32 x (8 GiB).
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
        "${pkgs.coreutils}/bin/timeout 120 ${pkgs.bash}/bin/sh -c 'until ${pkgs.tailscale}/bin/tailscale ip -4 | ${pkgs.gnugrep}/bin/grep -qx 100.125.249.107; do sleep 1; done'"
      ];
      RestartSec = "10s";
    };
  };

  # Cloudroom core, an agent runner (docs/cloudroom-vps-primary.md, 2026-10-16). Module and
  # packages: github.com/djbclark/cloudroom-nix. The -bin packages are built by Forgejo CI and
  # only downloaded here: nothing compiles on this host (djbclark, 2026-10-16).
  # The caps hold the core and every agent: the host has 4 GB and also runs the Gradle cache
  # (1 GB cap) and Athena, so past them the kernel reclaims inside Cloudroom, not host-wide.
  services.cloudroom = {
    enable = true;
    package = cloudroom-nix.packages.x86_64-linux.cloudroom-core-bin;
    codex.package = cloudroom-nix.packages.x86_64-linux.codex-npm-bin;
    # The Mac's ~/.codex/config.toml default (2026-10-16); clients can pick per session.
    codex.model = "gpt-6-luna";
    # Sessions that name no harness get Claude Code (djbclark, 2026-10-16); Codex stays installed.
    environment.CLOUDROOM_HARNESS = "claude-code";
    memoryHigh = "2560M";
    memoryMax = "3G";
    tailscaleServe.enable = true;
  };

  # The host builds this configuration from git, never from /etc/nixos:
  # github:djbclark/site-djbclark, branch deploy-vps-primary, flake in nixos/. Deploy =
  # `git push origin master:deploy-vps-primary`, then `systemctl start nixos-upgrade` on
  # the host (or wait for the 04:00 run). Never run `nixos-rebuild` by hand on the host
  # (/etc/nixos holds no configuration on purpose).
  # nixpkgs is exactly nixos/flake.lock. The weekly workflow .github/workflows/nixos-lock-update.yml
  # bumps the lock, builds this system on a runner first, and promotes it to the deploy branch;
  # when that fails it opens an issue and messages Hermes (docs/nixos-in-git.md).
  # A kernel/initrd change reboots the host, but only inside the window; outside it the new
  # generation stays staged for the next boot. Supervised reboot tested 2026-10-13.
  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];

  system.autoUpgrade = {
    enable = true;
    operation = "switch";
    flake = "github:djbclark/site-djbclark/deploy-vps-primary?dir=nixos#vps-primary";
    upgrade = false;
    dates = "04:00";
    randomizedDelaySec = "45min";
    fixedRandomDelay = true;
    persistent = true;
    allowReboot = true;
    rebootWindow = {
      lower = "03:00";
      upper = "05:00";
    };
  };

  # Keep rollbacks (14 days of generations) but bound disk use.
  nix.gc = {
    automatic = true;
    dates = "weekly";
    options = "--delete-older-than 14d";
  };
  nix.optimise.automatic = true;
  boot.loader.grub.configurationLimit = 10;

  system.stateVersion = "26.05";
}
