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
| Codex model | `gpt-6-luna`, the Mac's `~/.codex/config.toml` default on 2026-10-16. |
| Harnesses | Default `claude-code` (`CLOUDROOM_HARNESS`, djbclark 2026-10-16); Codex also logged in. Both logins done 2026-10-16 as `cloudroom-agent`; smoke test passed for Claude Code (Codex was out of quota at the time). |

```bash
ssh vps-ts
api() { sudo awk -F= '/^CLOUDROOM_TOKEN=/{print "header = \"Authorization: Bearer " $2 "\""}' /etc/cloudroom/core.env |
  curl --config - --silent --show-error --fail-with-body "$@"; }
api http://127.0.0.1:9840/v1/ready
```

The Mac app (`/Applications/Cloudroom.app`, v106) keeps its Core connection in
`~/.gui-cloudroom/cloudroom.json` (mode 600). It insists on a hosted cloudroom.dev sign-in
(`account`, `sandboxToken`) and rewrites the file at that login screen, but the same file may also
hold `url` and `token`, and threads then use that Core. So: quit the app, add
`"url": "https://vps-primary.greyhound-sidemirror.ts.net"` and `"token"` (sudo-secretspec
`CLOUDROOM_VPS_PRIMARY_TOKEN`) beside the sign-in, relaunch (2026-10-17).

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
