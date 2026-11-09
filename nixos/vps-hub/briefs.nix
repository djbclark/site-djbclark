# Bot Briefs dashboard on vps-hub (moved into this repo 2026-11-09; before that a host-local wrapper flake in
# /var/lib/briefs/deployment). Module and package: the bot-briefs flake input (github:djbclark/bot-briefs,
# nixosModules.briefs + overlays.default), pinned by nixos/flake.lock.
#
# Private settings never enter git: the runtime TOML (bots, allowlist, [todo_review]) is
# /var/lib/briefs/config/briefs.toml and the secrets are under /var/lib/briefs/secrets (root 0600, by hand).
# The dashboard is the tailnet mirror of the box's authoritative copy (the box pushes over /sync with the token).
{ config, pkgs, bot-briefs, ... }:

let
  ts = "${config.services.tailscale.package}/bin/tailscale";
in
{
  imports = [ bot-briefs.nixosModules.briefs ];
  nixpkgs.overlays = [ bot-briefs.overlays.default ];

  services.briefs = {
    enable = true;
    package = pkgs.briefs;
    user = "root";
    configFile = "/var/lib/briefs/config/briefs.toml";
    bindHost = "127.0.0.1";
    port = 8642;
    syncTokenFile = "/var/lib/briefs/secrets/sync-token";
    webhookEnvFile = "/var/lib/briefs/secrets/webhook.env";
    backup.enable = true;
    # On since the 2026-11-09 cutover from vps-primary (spool was empty, so nothing old replays).
    wakeRetry.enable = true;
  };

  # /todo-review export: the static Saner-retirement dataset (todo-review-candidates.json + shortwave-thread-map.json),
  # copied by hand; its path is [todo_review] export_dir in the runtime TOML.
  systemd.tmpfiles.rules = [ "d /var/lib/briefs/todo-review 0700 root root -" ];

  # Tailscale Serve for the dashboard: tailnet-only HTTPS 443 -> 127.0.0.1:8642 (same shape as paseo's 7263 unit).
  systemd.services.briefs-tailscale-serve = {
    description = "Serve the Briefs dashboard on the tailnet over HTTPS 443";
    wantedBy = [ "multi-user.target" ];
    after = [ "tailscaled.service" "briefs-web.service" ];
    bindsTo = [ "tailscaled.service" ];
    wants = [ "briefs-web.service" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStartPre = "${pkgs.coreutils}/bin/timeout 120 ${pkgs.bash}/bin/sh -c 'until ${ts} status >/dev/null 2>&1; do sleep 1; done'";
      ExecStart = "${pkgs.bash}/bin/sh -c 'for i in 1 2 3 4 5 6; do ${ts} serve --bg --https=443 http://127.0.0.1:8642 && exit 0; sleep $$i; done; exit 1'";
      ExecStop = "${pkgs.bash}/bin/sh -c 'for i in 1 2 3 4 5 6; do ${ts} serve --https=443 off && exit 0; sleep $$i; done; exit 1'";
    };
  };
}
