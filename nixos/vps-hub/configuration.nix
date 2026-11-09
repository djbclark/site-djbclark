{
  lib,
  pkgs,
  paseo-nix,
  ...
}:

{
  imports = [
    ./hardware-configuration.nix
    ./disko.nix
    ../modules/packages.nix
    ../modules/terminals.nix
    ../modules/users.nix
    ./rustdesk.nix
    ./gradle-cache.nix
    ./sudo-secretspec.nix
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

  # vps-hub (Contabo 203736421): a clone of vps-primary/configuration.nix. Differences: hostname, disk/boot
  # (disko, BIOS + UEFI grub), static Contabo network, extra root keys, and everything that needs a secret
  # or vps-primary's identity is left out (google-proxy, the Hetzner home volume, auto-upgrade).
  # Added back 2026-11-09 for vps-primary's retirement: sudo-secretspec (./sudo-secretspec.nix), the Gradle cache
  # (./gradle-cache.nix); also new here: RustDesk (./rustdesk.nix). Tailscale is installed but not joined.
  boot.loader.grub = {
    enable = true;
    efiSupport = true;
    efiInstallAsRemovable = true;
  };

  networking.hostName = "vps-hub";
  networking.useDHCP = false;
  networking.useNetworkd = true;
  systemd.network.networks."10-uplink" = {
    # Debian named it eth0 (net.ifnames=0); NixOS uses predictable names (ens18 on Contabo's QEMU).
    # Matching both kept the first install from coming up unreachable.
    matchConfig.Name = "en* eth*";
    address = [ "91.90.82.78/22" "2a02:c207:2373:6421::1/64" ];
    routes = [
      { Gateway = "91.90.80.1"; GatewayOnLink = true; }
      { Gateway = "fe80::1"; GatewayOnLink = true; }
    ];
    networkConfig.IPv6AcceptRA = false;
  };
  networking.nameservers = [ "1.1.1.1" "9.9.9.9" "2606:4700:4700::1111" ];
  networking.firewall.allowedTCPPorts = [ 22 ];

  users.users.root.openssh.authorizedKeys.keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKaWfTezsujYpykja7WRikq6jjw3r5vKgcO8o1nSaNoB djbclark@vps-primary-automation"
    # Radar security-watch inventory (restrict,pty; needs root for rootful podman ps/images)
    "restrict,pty,port-forwarding,permitopen=\"18.25.134.227:22\",permitopen=\"18.4.60.84:47301\",permitopen=\"pastebin.xvm.mit.edu:22\",permitopen=\"hyades.mit.edu:47301\" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFQXxbEeAZywfsQt/WRbFgYHKhTNjcQP7wLmFVnvHxpt radar-security-watch@box"
    # vps-hub only: the box agent and the Mac's dedicated vps-hub key.
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINaVVumZREGAsE6kC0BdPYgcylrrVtXZFgLm8qp3JsMb box@grok-bot-vm-353483708"
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEctUwAnenMPBTnUER+av7j7Z79anThVkNt6Ymxz8fUQ djbclark-mac-vps-hub"
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

  systemd.tmpfiles.rules = [
    "d /var/lib/gradle-cache 0750 gradle-cache gradle-cache -"
    # Scheduled clean-up (systemd-tmpfiles-clean.timer, daily), 2026-10-31: the agents' download caches on the
    # home volume (73% full) and /tmp. An entry goes when its mtime, atime and ctime are all older than the age,
    # so anything in use stays. NixOS's packaged rule is `q /tmp 1777 root root 10d`; this one (the earliest file
    # name wins) is stricter. The packaged rules already keep ssh-*, sshauth.*, tmux-* and systemd-private-*;
    # krb5cc_* are Athena ticket caches.
    "e /home/djbclark/.cache - - - 14d"
    "e /home/djbclark/.npm/_cacache - - - 14d"
    "q /tmp 1777 root root 3d"
    "x /tmp/krb5cc_*"
  ];

  virtualisation.podman.enable = true;

  # The agents (Paseo and everything it starts) run as `djbclark` (declared in modules/users.nix: uid 1000, so the
  # volume's files keep their owner on a rebuilt host), whose home is /home/djbclark on its own Hetzner Volume
  # (below): every agent login and install lives there. createHome is off: the home is the volume's root, and a
  # mount that failed must not leave an empty home on the root disk (paseo requires the mount, below).
  users.users.djbclark.createHome = true; # vps-hub: home on the root disk (no volume)
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
    hostnames = [ "vps-hub.greyhound-sidemirror.ts.net" ];
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

  # Generic-glibc binaries that agents download run only with nix-ld: the native Claude Code and
  # Cursor's bundled node (both installed into /home/djbclark/.local).
  programs.nix-ld.enable = true;

  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];

  # Follow-up: auto-upgrade from a deploy-vps-hub branch, once one exists.

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

  # tendcf's CFEngine fork: package and work directory only. cf-execd stays off: tendcf
  # enforces nothing on a Nix host (tendcf spec D3; djbclark go-ahead 2026-11-01).
  services.cfengine-tendcf.enable = true;
  services.cfengine-tendcf.execd.enable = false;

  system.stateVersion = "26.05";
}
