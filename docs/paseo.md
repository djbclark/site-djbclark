# Paseo across the fleet

[Paseo](https://paseo.sh) ([github.com/getpaseo/paseo](https://github.com/getpaseo/paseo), Apache-2.0) is an
agentic development environment: a daemon runs coding agents (Claude Code, Codex, Copilot, OpenCode, Pi and
more, each in its own worktree) and desktop, web, Android/iOS and CLI clients connect to it. Installed
2026-10-18 at djbclark's request on every machine of the fleet. Decisions (djbclark, 2026-10-18):

1. One daemon per host, all on port **7263** (upstream default 6767), bound to loopback and published on the
   tailnet with `tailscale serve --https=7263`. Never `tailscale funnel`, never a public port.
   On the Mac only, tailnet HTTPS **3333** is an alias of 7263 (djbclark, 2026-11-21): a second
   `tailscale serve --https=3333` front for the same loopback daemon; 7263 stays so no client breaks.
2. **No daemon password and no relay** (app.paseo.sh): the tailnet is the boundary
   ([agents-vps-primary.md](agents-vps-primary.md)). Paseo runs commands for anyone who reaches it. On the
   Mac a Tailscale grant narrows that to the operator's own devices (below).
3. Linux builds happen in Forgejo CI, never on a host: [forgejo.mit.edu/djbclark/paseo-nix](https://forgejo.mit.edu/djbclark/paseo-nix)
   packs the npm release into a hash-pinned tarball and carries the NixOS module (`services.paseo`).
4. Voice mode and dictation are off on the servers (`speech.enable = false`): on, the daemon downloads about
   200 MB of speech models at startup. The Mac app keeps them.

## Hosts

| Host | Daemon | Runs as | URL (tailnet only) | Config |
| --- | --- | --- | --- | --- |
| bigmac | Paseo.app (`brew install --cask paseo`) starts and owns it; LaunchAgent `com.djbclark.paseo-desktop` opens the app hidden at login and `keepRunningAfterQuit` keeps the daemon up after quitting (djbclark, 2026-10-18) | djbclark | https://bigmac.greyhound-sidemirror.ts.net:7263 and (alias, same daemon) https://bigmac.greyhound-sidemirror.ts.net:3333 | `roles/paseo_desktop` (`just paseo-desktop-apply`; `just paseo-desktop-check` first): `~/.paseo/config.json` keys, one serve per `paseo_desktop_serve_ports` entry (7263, 3333) and the LaunchAgent |
| vps-primary | `services.paseo` (systemd `paseo.service`) | djbclark, using the agent logins in `/home/djbclark` ([agents-vps-primary.md](agents-vps-primary.md)); state `/home/djbclark/.paseo` | https://vps-primary.greyhound-sidemirror.ts.net:7263 | `nixos/vps-primary/configuration.nix`; Paseo and its agents run in `agents.slice` (MemoryMax 3G) |
| get.sipb.cloud | `services.paseo` in the image (`hostName = "get"`: clients would show the container ID) | djbclark; state `~/.paseo` on `/persist` | https://get.greyhound-sidemirror.ts.net:7263 | `~/src/get` `nixos/paseo.nix`; the TSI port shim is preloaded; get's Tailscale shields are down for this (get `docs/runbook.md` 8.4) |

Clients: the Mac app adds the other two as hosts (Settings, Add host, Direct connection, `<name>.greyhound-sidemirror.ts.net`,
port 7263, SSL on); the Android app on the stayturgid phones the same way over Tailscale; any tailnet browser
opens the URLs above (the bundled web UI); the CLI takes `--host wss://<name>.greyhound-sidemirror.ts.net:7263` (the bare `<name>…:7263` form fails with HTTP 400; checked 2026-10-30)
(the local daemon needs no `--host`). For the Mac, `:3333` works anywhere `:7263` does (same daemon, same
`daemon.hostnames` entry; `--host wss://bigmac.greyhound-sidemirror.ts.net:3333`). Remove the alias with
`tailscale serve --https=3333 off` and drop 3333 from `paseo_desktop_serve_ports`.

Status 2026-10-18: all three daemons answer `/api/health` and the web UI over the tailnet (vps-primary at
site-djbclark f919386, get.sipb.cloud at image `ci-eb12788`, Mac app 0.11.4). Android `sh.paseo` 0.11.4 (stayturgid
`bootstrap_apks`, `just deploy-apks`) is on s24 and t2e; hd8 and p7a were off the tailnet and get it on their
next `deploy-apks`. t2e has all three hosts. On s24 the app ignores taps (finger and adb alike, even
after `pm clear`); djbclark will debug it later.

## Who may reach the Mac's daemon (Tailscale grant, 2026-11-21)

The daemon has no password, so on the Mac the boundary is a tailnet grant, not the whole tailnet (djbclark,
2026-11-21). The former single grant `* -> * ip *` was split three ways, keeping all other access as it was:

1. `* -> *` on every TCP port except 3333 and 7263, plus all UDP and ICMP (grant `ip: "*"` means TCP, UDP and ICMP).
2. `* -> ipset:all-but-mac` on tcp 7263 and 3333: the other Paseo daemons (vps-primary, get) stay reachable.
   The ipset lists the tailnet ranges and the approved subnet and app-connector routes, minus the Mac;
   **add any newly approved subnet route to it.**
3. `ipset:paseo-mac-clients -> ipset:mac` on tcp 7263 and 3333: this Mac, the operator's other Mac
   (`defeat`), the Paseo Android phones (s24, t2e, hd8, p7a) and the operator's Windows PC, IPv4 and IPv6.
   Servers, bot VMs, connectors and other users' devices are left out (no Paseo client config of this Mac was
   found on them). **A new client device of this daemon needs its two addresses added here.**

The policy carries `tests` (allowed phones accept, vps-primary and another user's device deny, Funnel and ssh
paths still accept), so the admin API rejects an edit that breaks them. The policy before and after, with
their ETags, are in site-private `tailscale/2026-11-21/` (they name other people's devices, so never here).

Roll back (restores the former `* -> *` policy; the token stays out of argv):

```sh
sudo-secretspec run --reason "roll back Tailscale policy" -- sh -c 'T=$(printf "client_id=%s&client_secret=%s&grant_type=client_credentials&scope=policy_file" "$TAILSCALE_OAUTH_CLIENT_ID" "$TAILSCALE_OAUTH_CLIENT_SECRET" | curl -sS --max-time 30 -d @- https://api.tailscale.com/api/v2/oauth/token | python3 -c "import json,sys; print(json.load(sys.stdin)[\"access_token\"])") && printf "header = \"Authorization: Bearer %s\"\n" "$T" | curl -sS --max-time 60 -K - -H "Content-Type: application/hujson" --data-binary @$HOME/ops/site-private-djbclark/tailscale/2026-11-21/policy-before-paseo-grant.hujson -w " http=%{http_code}\n" https://api.tailscale.com/api/v2/tailnet/-/acl'
```

Swap the last path segment `/acl` for `/acl/validate` to check a file without applying it.

## Skills

Paseo's six agent skills are vendored in djbclark-ade (`skills/paseo*`, `skills/paseo/UPSTREAM.md`) and linked
into every TUI; `paseo-advisor`, `paseo-committee` and `paseo-handoff` fire only on explicit Paseo requests, so
the plain "handoff" and "second opinion" stay with the `handoff` skill and `acp-run`.

## Upgrading

1. Bump `pins.env` and relock `bundle/` in paseo-nix, push: the `build` workflow publishes a tarball and prints
   `PIN paseo <url> <hash>`; put that in `pkgs/pins.json` and push.
2. Build the checks on the runner: hyades-nix-build's `nix-build` workflow with `repo=https://forgejo.mit.edu/djbclark/paseo-nix.git`.
3. Update the consumers on the runner too (`update=paseo-nix`, `attrs=none` to only lock; it prints the new `flake.lock`): vps-primary
   (`dir=nixos`, then promote, [nixos-in-git.md](nixos-in-git.md)) and get.sipb.cloud (its `paseo-nix` input is pinned by `rev`;
   deploy with `scripts/deploy`). Deploy only the pushed branch head (`~/CLAUDE.md` 36: rebuilds are shared).
4. The Mac app updates itself (or `brew upgrade --cask paseo`). Keep the daemons on one version: the apps talk
   to all three.
