{
  lib,
  pkgs,
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

  # nodejs_24: `npm install -g` scripts of the agents start with `#!/usr/bin/env node`.
  environment.systemPackages = [
    pkgs.vim
    pkgs.python3
    pkgs.nodejs_24
  ];

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
  # 2026-10-23: GlobalProtect removed; MITnet now reaches the tailnet through
  # pastebin.xvm.mit.edu (an XVM VM on MITnet advertising 18.0.0.0/8). This host's
  # own SYNs to 18/8 were timing out. The empty --advertise-routes= drops 18/8
  # (tailscale set only changes the flags given), the exit node stays.
  # 2026-10-23 (later): no longer an exit node either; instead this host accepts
  # pastebin.xvm's 18.0.0.0/8 route so it reaches MITnet over the tailnet again.
  # useRoutingFeatures "both": "server" keeps forwarding on, "client" sets the
  # reverse-path check to loose so replies from 18/8 via tailscale0 are not dropped.
  services.tailscale = {
    enable = true;
    openFirewall = true;
    useRoutingFeatures = "both";
    extraSetFlags = [ "--advertise-exit-node=false" "--advertise-routes=" "--accept-routes" ];
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

  # The agents (Paseo and everything it starts) run as `djbclark`, whose home is /home/djbclark on its
  # own Hetzner Volume (below): every agent login and install lives there. `djbclark` (uid 1000, group
  # users, wheel, zsh) is not declared here: it predates this config and NixOS leaves it alone, so its
  # uid is not pinned by Nix; the volume holds files owned by uid 1000, so keep it that way if the host
  # is ever rebuilt.
  # Anthropic's native Claude Code installer, run once as djbclark, puts its binary in ~/.local/bin.
  environment.localBinInPath = true;
  # Login shells of djbclark only (the guard on the user name keeps it from touching anyone else): npm
  # global installs go to ~/.local (npm's default prefix is the read-only Node store path), the
  # system CA bundle for Python's stdlib (uv-managed interpreters look in hashed links NixOS does not
  # create), and the one D-Bus session bus below.
  environment.extraInit = ''
    if [ "$(${pkgs.coreutils}/bin/id -un 2>/dev/null)" = djbclark ]; then
      export NPM_CONFIG_PREFIX=/home/djbclark/.local
      export PATH=/home/djbclark/.local/bin:"$PATH"
      export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
      export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/agent-session-bus/bus
    fi
  '';
  # One D-Bus session bus for the agents. Without a login session an agent that looks up a keyring
  # (Copilot CLI, Hermes, gh) autolaunches a dbus-daemon that never exits (22 had piled up in a
  # day). Paseo's agents use it through DBUS_SESSION_BUS_ADDRESS below.
  systemd.services.agent-session-bus = {
    description = "D-Bus session bus for the agents (djbclark)";
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      ExecStart = "${pkgs.dbus}/bin/dbus-daemon --session --nofork --nopidfile --address=unix:path=/run/agent-session-bus/bus";
      User = "djbclark";
      Group = "users";
      RuntimeDirectory = "agent-session-bus";
      RuntimeDirectoryMode = "0700";
      Restart = "on-failure";
      RestartSec = 5;
    };
  };

  # Paseo (github.com/getpaseo/paseo), the agent workspace and the only interface to the agents
  # (djbclark, 2026-10-25). It runs as djbclark, so its agents use the logins in /home/djbclark
  # (docs/agents-vps-primary.md, "Logins"); state in /home/djbclark/.paseo. Tailnet
  # 7263 serves the web UI, the apps and the CLI. No password and no relay: the tailnet is the only
  # boundary, and it must never be funnelled. Built by Forgejo CI (forgejo.mit.edu/djbclark/paseo-nix).
  # docs/paseo.md.
  services.paseo = {
    enable = true;
    package = paseo-nix.packages.x86_64-linux.paseo-bin;
    user = "djbclark";
    hostnames = [ "vps-primary.greyhound-sidemirror.ts.net" ];
    extraPackages = [
      pkgs.git
      pkgs.gh
      pkgs.ripgrep
    ];
    slice = "agents.slice";
    tailscaleServe.enable = true;
    # Use the one session bus above, or Copilot/Hermes keyring lookups autolaunch dbus-daemons that
    # never exit (djbclark-ade-9e, 2026-10-18).
    environment.DBUS_SESSION_BUS_ADDRESS = "unix:path=/run/agent-session-bus/bus";
  };

  # One memory cap for Paseo and every agent it starts: the 4 GB host also runs the Gradle cache
  # and Athena.
  systemd.slices.agents = {
    description = "Agent workspace (Paseo) and its agents";
    sliceConfig = {
      MemoryHigh = "2816M";
      MemoryMax = "3G";
    };
  };
  systemd.services.paseo = {
    wants = [ "agent-session-bus.service" ];
    after = [ "agent-session-bus.service" ];
  };

  # djbclark's home, /home/djbclark (tool installs, caches, agent checkouts: ~10 GB), lives on a Hetzner
  # Volume, not the 85%-full root disk (2026-10-25; renamed and remounted from the agents' old home
  # 2026-10-30): Volume 107263872 "vps-primary-home", ext4, nbg1. Mounted by filesystem UUID, which
  # belongs to the filesystem, not to a /dev/sdX name.
  # It grows in place: enlarge it in the Hetzner console or API, then
  # `resize2fs /dev/disk/by-uuid/cef32561-f50a-4332-ae46-b5ee5a1570eb` on the mounted host.
  # `nofail` keeps a missing or slow volume from dropping the boot into emergency mode, which
  # would cut off SSH and Tailscale; x-systemd.device-timeout bounds the wait. The price is that
  # the mount can fail unnoticed, so paseo requires it below. `nosuid,nodev`: the volume holds
  # only agent-controlled downloads and checkouts, so setuid bits and device nodes there are never
  # legitimate. Not `noexec`: nix-ld binaries (Claude Code, Cursor's node) run from ~/.local.
  fileSystems."/home/djbclark" = {
    device = "/dev/disk/by-uuid/cef32561-f50a-4332-ae46-b5ee5a1570eb";
    fsType = "ext4";
    options = [
      "nofail"
      "nosuid"
      "nodev"
      "x-systemd.device-timeout=30s"
    ];
  };
  # With the volume absent, paseo must fail to start, never recreate an empty home (and fresh
  # logins and installs) on the root disk underneath the mount point. systemd derives this from
  # WorkingDirectory already; stated so it does not depend on that.
  # agent-session-bus and the tailscale-serve unit never touch the home, so they need nothing.
  systemd.services.paseo.unitConfig.RequiresMountsFor = [ "/home/djbclark" ];

  # Generic-glibc binaries that agents download run only with nix-ld: the native Claude Code and
  # Cursor's bundled node (both installed into /home/djbclark/.local).
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

  # Cap the persistent journal (754 MB on 2026-10-24 on a 30 GB root, djbclark disk hygiene).
  services.journald.extraConfig = "SystemMaxUse=200M";

  system.stateVersion = "26.05";
}
