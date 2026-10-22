{
  lib,
  pkgs,
  bb-nix,
  paseo-nix,
  ...
}:

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
  # athena-afs hard-codes a 3000000 KiB (2.9 GiB) cache; the root disk had 8.4 GB free and AFS
  # use here is light, so cap it at about 490 MiB (djbclark, 2026-10-18). afsd reads this at start;
  # the running client was resized with `fs setcachesize 500000`.
  services.openafsClient.cache.blocks = lib.mkForce 500000;

  boot.loader.grub.enable = true;
  boot.loader.grub.device = "/dev/sda";

  networking.hostName = "vps-primary";
  networking.networkmanager.enable = true;
  networking.firewall.allowedTCPPorts = [ 22 ];

  users.users.root.openssh.authorizedKeys.keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKaWfTezsujYpykja7WRikq6jjw3r5vKgcO8o1nSaNoB djbclark@vps-primary-automation"
    # Radar security-watch inventory (restrict,pty; needs root for rootful podman ps/images)
    "restrict,pty,port-forwarding,permitopen=\"18.25.134.227:22\",permitopen=\"18.4.60.84:47301\",permitopen=\"pastebin.xvm.mit.edu:22\",permitopen=\"hyades.mit.edu:47301\" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFQXxbEeAZywfsQt/WRbFgYHKhTNjcQP7wLmFVnvHxpt radar-security-watch@box"
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

  # /etc/hosts as a writable regular file instead of a store symlink: vpn-slice
  # (the GlobalProtect split-tunnel script, modules/packages.nix) aborts with
  # "Cannot read/write /etc/hosts" otherwise (2026-10-17).
  environment.etc.hosts.mode = "0644";

  # Joined to the tailnet 2026-10-13 with a one-time tagged auth key
  # (tag:server: no key expiry); node state lives in /var/lib/tailscale.
  # Public SSH on 22 stays open until the tailnet path is proven.
  # Exit node (2026-10-17): the Mac routes through here while GlobalProtect breaks its
  # path to MITnet (home ISP SYNs to forgejo.mit.edu go unanswered; this host reaches it).
  # "server" turns on IPv4/IPv6 forwarding; the route still needs approving once in the
  # admin console (the policy has no autoApprovers).
  # Subnet route 18.0.0.0/8 (2026-10-18): the Mac now sends only MITnet here and the rest
  # direct; the full exit node hairpinned everything via Nuremberg (~240 ms, 30% loss).
  # The exit node stays advertised as a fallback.
  services.tailscale = {
    enable = true;
    openFirewall = true;
    useRoutingFeatures = "server";
    extraSetFlags = [ "--advertise-exit-node" "--advertise-routes=18.0.0.0/8" ];
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

  # BB (github.com/get-bb/bb), the agent app that replaced Cloudroom (C2, 2026-10-17). Tailnet
  # 443 is the web UI; 38443 is the address other machines' host daemons use (externalUrl).
  # BB has no login: the tailnet is the only boundary, and it must never be funnelled. Packages
  # are built by Forgejo CI (forgejo.mit.edu/djbclark/bb-build) and only downloaded here.
  # The caps hold the server and every agent: the host has 4 GB and also runs the Gradle cache
  # (1 GB cap) and Athena, so past them the kernel reclaims inside BB, not host-wide.
  services.bb = {
    enable = true;
    package = bb-nix.packages.x86_64-linux.bb-app-bin;
    appUrl = "https://vps-primary.greyhound-sidemirror.ts.net";
    externalUrl = "https://vps-primary.greyhound-sidemirror.ts.net:38443";
    # Anthropic's native installer, run once as the bb user (nix-ld is enabled by nativeInstaller).
    claudeCode = {
      nativeInstaller = true;
      executable = "/var/lib/bb/.local/bin/claude";
    };
    # npmGlobalPrefix keeps its default (/var/lib/bb/.local): BB's own `npm install -g` (Pi and
    # other agents installed from the UI) fails on the read-only Node store path without it.
    extraPackages = [
      bb-nix.packages.x86_64-linux.codex-npm-bin
      pkgs.git
      pkgs.gh
      pkgs.ripgrep
    ];
    memoryHigh = "2560M";
    memoryMax = "3G";
    tailscaleServe = {
      enable = true;
      ports = [
        443
        38443
      ];
    };
  };

  # Paseo (github.com/getpaseo/paseo), a second agent workspace beside BB (djbclark, 2026-10-18).
  # It runs as BB's `bb` user, so its agents use the logins already in /var/lib/bb (docs/
  # bb-vps-primary.md, "Logins"); state in /var/lib/bb/.paseo. Tailnet 7263 serves the web UI, the
  # apps and the CLI. No password and no relay: like BB, the tailnet is the only boundary, and it
  # must never be funnelled. Built by Forgejo CI (forgejo.mit.edu/djbclark/paseo-nix). docs/paseo.md.
  services.paseo = {
    enable = true;
    package = paseo-nix.packages.x86_64-linux.paseo-bin;
    user = "bb";
    hostnames = [ "vps-primary.greyhound-sidemirror.ts.net" ];
    extraPackages = [
      bb-nix.packages.x86_64-linux.codex-npm-bin
      pkgs.git
      pkgs.gh
      pkgs.ripgrep
    ];
    slice = "agents.slice";
    tailscaleServe.enable = true;
    # Paseo's agents run as bb too: use bb's one session bus (bb-nix `sessionBus`), or Copilot/Hermes
    # keyring lookups autolaunch dbus-daemons that never exit (djbclark-ade-9e, 2026-10-18).
    environment.DBUS_SESSION_BUS_ADDRESS = "unix:path=/run/bb-session-bus/bus";
  };

  # One memory cap for BB, Paseo and every agent either starts (the per-unit BB caps above still
  # apply inside it): the 4 GB host also runs the Gradle cache and Athena.
  systemd.slices.agents = {
    description = "Agent workspaces (BB, Paseo) and their agents";
    sliceConfig = {
      MemoryHigh = "2816M";
      MemoryMax = "3G";
    };
  };
  systemd.services.bb.serviceConfig.Slice = "agents.slice";
  systemd.services.paseo = {
    wants = [ "bb-session-bus.service" ];
    after = [ "bb-session-bus.service" ];
  };

  # Generic-glibc binaries that agents download run only with nix-ld: the native Claude Code and
  # Cursor's bundled node (both installed into /var/lib/bb/.local). claudeCode.nativeInstaller
  # also turns it on; it is stated here so it does not depend on that option.
  programs.nix-ld.enable = true;

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

  # Builds happen off-host (docs/nixos-in-git.md): gpclient/gpauth come prebuilt from the signed
  # cache that GitHub Actions publishes on GitHub Pages (github.com/djbclark/nix-globalprotect,
  # mirrored from forgejo.mit.edu). cache.nixos.org stays first (Priority 40 vs 50); on a miss
  # (nixpkgs rev not built there yet) Nix just compiles locally as before.
  nix.settings.extra-substituters = [ "https://djbclark.github.io/nix-globalprotect" ];
  nix.settings.extra-trusted-public-keys = [
    "djbclark-nix-globalprotect-1:bV0OVului8Zgq+MiJjq0CBGg+zlI6Vz6/4mVyqx68WQ="
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
