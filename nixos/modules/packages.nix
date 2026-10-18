# Slim package set for vps-primary (decision 1.1 of docs/plans/vps-primary-athena.md):
# the CLI part of `get`'s `core` list (forgejo.mit.edu/djbclark/get,
# modules/package-lists.nix) without JDKs, Go, the C toolchain, containers or
# Android tools, plus the Claude Code TUI. About 2 GiB on top of the base system.
{ lib, pkgs, ... }:
{
  # claude-code is unfree; allow that one package, nothing else.
  nixpkgs.config.allowUnfreePredicate = pkg: builtins.elem (lib.getName pkg) [ "claude-code" ];

  environment.systemPackages = with pkgs; [
    # --- core CLI ---
    file
    lsof
    man-pages
    moreutils
    rsync
    strace
    tree
    unzip
    wget
    zip

    # --- modern CLI replacements ---
    ast-grep
    bat
    btop
    delta
    dust
    eza
    fd
    fzf
    gdu
    htop
    hyperfine
    procs
    ripgrep
    sd
    srgn
    tealdeer
    xh
    zoxide

    # --- VCS / forge ---
    gh
    git
    lazygit
    tea

    # --- text / data / lint ---
    glow
    jq
    miller
    shellcheck
    shfmt
    yq-go

    # --- Python core ---
    python3
    ruff
    uv

    # --- Nix ---
    nix-tree
    nixd
    nixfmt

    # --- network / diagnostics ---
    dnsutils
    doggo
    tailscale
    traceroute
    # MIT GlobalProtect VPN from a headless box (2026-10-17): gpclient does the
    # Touchstone/Duo SAML login with `--browser remote` (URL opened on the Mac),
    # openconnect carries the tunnel, vpn-slice keeps only MIT routes in it so
    # the VPS's default route (and the Tailscale exit node) stay intact.
    openconnect
    gpclient
    gpauth
    vpn-slice

    # --- editors / terminal ---
    ghostty.terminfo
    tmux
    vim

    # --- agents ---
    claude-code
  ];
}
