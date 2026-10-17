# Cloudroom core on vps-primary

[cloudroom-core](https://github.com/davidondrej/cloudroom-core) (Apache-2.0) runs coding agents
(Codex, Claude Code, Pi, Cursor) on a Linux machine as an unprivileged account, behind a
token-protected HTTP API, and keeps their history on that machine. Installed on vps-primary
2026-10-16 by djbclark's decision.

1. **Module and packages:** [github.com/djbclark/cloudroom-nix](https://github.com/djbclark/cloudroom-nix)
   (public, Apache-2.0 like upstream; local `~/src/cloudroom-nix`), a flake input of `nixos/`.
   Its README is the documentation: options, what the module does to a host, harness logins.
2. **This host's settings:** `services.cloudroom` in `nixos/vps-primary/configuration.nix`.
3. **Builds:** the private Forgejo repo forgejo.mit.edu/djbclark/cloudroom-core-build (local
   `~/src/cloudroom-core-build`).

## Builds run in Forgejo CI by default

djbclark, 2026-10-16: build in Forgejo CI rather than on vps-primary. Compiling on the host is
allowed when there is no other good option or host, or when it is actually the fastest route
(relaxed the same day from "no builds on the host"). As set up, nothing compiles there: vps-primary
uses cloudroom-nix's `cloudroom-core-bin` (static musl, built from upstream's pinned tag in a
digest-pinned `rust:alpine` container, `cargo test` as the gate) and `codex-npm-bin` (the
`@openai/codex` release upstream tested), both Forgejo generic packages pinned by URL and hash:
the host only downloads them. What it still builds itself is what every NixOS switch builds
(configuration files, units, wrappers).

The build repo's `nix-build` workflow builds flake attributes on the Forgejo runner: cloudroom-nix's
packages, and this repo's vps-primary system at a commit before promotion
(`dir=nixos`, attr `nixosConfigurations.vps-primary.config.system.build.toplevel`).

## On this host

| Piece | Where |
| --- | --- |
| API | `127.0.0.1:9840` (registry/ports.yml); `https://vps-primary.greyhound-sidemirror.ts.net/` on the tailnet only (`tailscaleServe`). Never `tailscale funnel`. |
| Token | `/etc/cloudroom/core.env` on the host (root 0600), made once by `cloudroom-setup.service`; never in git or the store. The Mac's copy: sudo-secretspec `CLOUDROOM_VPS_PRIMARY_TOKEN`. |
| Accounts | `cloudroom` (uid 9840), `cloudroom-agent` (uid 9841, no sudo, no SSH key). |
| History | `/var/lib/cloudroom/history`; workspaces `/code`. |
| Memory | `memoryHigh = "2560M"`, `memoryMax = "3G"` for the core and every agent (4 GB host, also running the Gradle cache and Athena). |
| Codex model | `gpt-5.6-luna` (2026-10-17). The Mac's default `gpt-6-luna` failed: "not supported when using Codex with a ChatGPT account"; the host login's choices are in `~cloudroom-agent/.codex/models_cache.json`. |
| Harnesses | Default `claude-code` (`CLOUDROOM_HARNESS`, djbclark 2026-10-16); Codex also logged in. Both logins done 2026-10-16 as `cloudroom-agent`; smoke tests passed for Claude Code (2026-10-16) and Codex on `gpt-5.6-luna` (2026-10-17). |

```bash
ssh vps-ts
api() { sudo awk -F= '/^CLOUDROOM_TOKEN=/{print "header = \"Authorization: Bearer " $2 "\""}' /etc/cloudroom/core.env |
  curl --config - --silent --show-error --fail-with-body "$@"; }
api http://127.0.0.1:9840/v1/ready
```

The Mac app (`/Applications/Cloudroom.app`, v106) keeps its Core connection in
`~/.gui-cloudroom/cloudroom.json` (mode 600). It insists on a hosted cloudroom.dev sign-in
(`account`, `sandboxToken`) and rewrites the file at that login screen, but the same file may also
hold `url` and `token`. While `sandboxToken` is there too, new Cloud threads go to cloudroom.dev's
hosted sandboxes (a queue), not this Core (`newThreadsInSandboxes()` in cloudroom-gui's
`commands.ts`); only sign-in writes it. So: quit the app, add
`"url": "https://vps-primary.greyhound-sidemirror.ts.net"` and `"token"` (sudo-secretspec
`CLOUDROOM_VPS_PRIMARY_TOKEN`), delete `sandboxToken`, keep `account` (without it the onboarding
screen locks, cloudroom-gui PR #5), relaunch. Reported upstream as
cloudroom-gui#6. The app's sync helper pins `[url, account id]` in
`~/.gui-cloudroom/cloudroom-sync/config.json` (`binding`); after changing `account` by hand, set `binding` to
match, or Codex "Connect" (Cloud) fails with "Sync setup failed" (real error: "connection changed; review sync
setup again", 2026-10-17). Verified 2026-10-17: a Cloud thread ran Claude Code
on vps-primary.

**Phone (2026-10-17, djbclark):** the Mac app's own server is on the tailnet with
`tailscale serve --bg --https=8790 http://127.0.0.1:39886` (registry/ports.yml; never :443, which is
caddy-https; never funnel). Open `https://mac.greyhound-sidemirror.ts.net:8790/` on the phone. It has no
login of its own, so the tailnet is the only boundary, and it works only while the Mac is awake with the
app open. A new browser shows the setup screen again (dismissal is per browser): tap Skip setup
(cloudroom-gui#7). The Cloudroom Connect relay (cloudroom.run) is inactive because `sandboxToken` is gone. Running
the app server on vps-primary instead (phone works with the Mac off; requested upstream as
cloudroom-gui#8) waits for cloudroom-gui PR #5:
until it merges, a fresh browser is locked on onboarding; research in site-private
`memory/handoffs/site-djbclark/RESEARCH_cloudroom-app-server-on-vps-primary_2026-10-17.md`; plan: CI repackages the Linux AppImage's Node tree, Nix module with a dedicated user, nft rule keeping
`cloudroom-agent` off its ports, about 300-450 MB.

Harness logins (Codex device auth, Claude Code's native installer) are djbclark's, by browser, as
`cloudroom-agent`: cloudroom-nix README, "Log the harnesses in".

## Upgrade

1. `~/src/cloudroom-core-build`: bump `pins.env` (tag and commit together), push `main`; its run
   prints two `PIN` lines (URL, SRI hash).
2. `~/src/cloudroom-nix`: paste them into `pkgs/prebuilt.nix`, bump `pkgs/cloudroom-core.nix`
   (rev, hash; set `cargoHash = lib.fakeHash` and read the real one from a `nix-build` run), push.
3. Here: update the `cloudroom-nix` node in `nixos/flake.lock` (on the host, a download only:
   `nix flake prefetch github:djbclark/cloudroom-nix/<rev> --json` gives `narHash` and
   `lastModified`), commit, push `master`, run `nix-build` on that commit, then promote
   (`docs/nixos-in-git.md`).
4. A restart interrupts running agent work: promote when no session is busy.
