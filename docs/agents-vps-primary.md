# Agents on vps-primary

The coding agents on vps-primary run under Paseo ([paseo.md](paseo.md)) as the unix user `djbclark`. Their logins and
installs live in that user's home, `/home/djbclark`; none is in git, the Nix store or this repo. Paseo has no daemon
password: the tailnet is the only boundary (never `tailscale funnel`, never a public port).

## On this host

| Piece | Where |
| --- | --- |
| Browser URL | `https://vps-primary.greyhound-sidemirror.ts.net:7263` ([paseo.md](paseo.md)). |
| Configuration | `nixos/vps-primary/configuration.nix` (login-shell environment, session bus, volume, nix-ld, `paseo.service`); changes ship as in `docs/nixos-in-git.md`. |
| Account and data | User `djbclark`, home `/home/djbclark` (the agents' installs, logins, checkouts, Paseo state in `~/.paseo`), on its own Hetzner Volume `vps-primary-home` (ext4, UUID `cef32561-f50a-4332-ae46-b5ee5a1570eb`, mounted by UUID with `nofail,nosuid,nodev`; not `noexec` because nix-ld binaries run from `~/.local`). `paseo` has `RequiresMountsFor`, so without the volume it fails to start instead of making an empty home. |
| Memory | `agents.slice` (`MemoryHigh` 2816M, `MemoryMax` 3G) holds Paseo and every agent it starts (4 GB host, also running the Gradle cache and Athena). |
| Session bus | `agent-session-bus.service` serves `/run/agent-session-bus/bus`; `DBUS_SESSION_BUS_ADDRESS` points at it for login shells and `paseo`. |
| nix-ld | `programs.nix-ld.enable`: downloaded generic-glibc binaries (Claude Code, Cursor's node, agy, omp, grok) run. |
| Installs | All as `djbclark` without root: npm globals into `~/.local` (`NPM_CONFIG_PREFIX=/home/djbclark/.local`, so `npm i -g` never hits the read-only Node store path), vendor installers into `~/.local/bin` or `~/.grok`. `~/.local/bin` is first on the login PATH; Node.js is system-wide (npm-installed agents start with `#!/usr/bin/env node`). |

```bash
ssh vps-ts
sudo -u djbclark -H bash -l      # a login shell: ~/.local/bin and node are on PATH
```

### Growing the volume

Enlarge `vps-primary-home` in the Hetzner console or API, then on the mounted host:
`resize2fs /dev/disk/by-uuid/cef32561-f50a-4332-ae46-b5ee5a1570eb`.

### Session bus

`djbclark` has no login session, so a keyring lookup (Copilot CLI 1.0.98 above all, Hermes, `gh auth login`)
autolaunched a `dbus-daemon` that never exits; 22 (54 MiB) had piled up in a day. `agent-session-bus.service`
serves one bus; the lookups still fail (no Secret Service) and the agents fall back to their files. More than one
`dbus-daemon` owned by `djbclark` (`ps -u djbclark -o comm= | grep -c dbus-daemon`) means something bypasses
`DBUS_SESSION_BUS_ADDRESS`.

## Builds

Nothing compiles on the host beyond what every NixOS switch builds (configuration files, units, wrappers). Flake
builds and lock bumps run on the Forgejo runner through the
[`nix-build` workflow of hyades-nix-build](https://forgejo.mit.edu/djbclark/hyades-nix-build) (local
`~/src/hyades-nix-build`), including this repo's vps-primary system at a commit before promotion (`dir=nixos`, attr
`nixosConfigurations.vps-primary.config.system.build.toplevel`; `docs/nixos-in-git.md`). Index of my MIT projects:
[djbclark/mit](https://forgejo.mit.edu/djbclark/mit).

## Logins

Every login is the `djbclark` user's and lives in `/home/djbclark`. Mac-side copies are not shared (single-use
refresh tokens would invalidate each other).

| Agent | Where its login lives | Status |
| --- | --- | --- |
| Claude Code | `~djbclark/.claude/.credentials.json`, `~djbclark/.claude.json` | signed in |
| Codex | `~djbclark/.codex/auth.json` (its `config.toml` was deliberately not copied) | signed in |
| Cursor | `~djbclark/.cursor`, binary `~djbclark/.local/bin/cursor-agent` | signed in by djbclark |
| Pi | none | not installed |
| omp | `~djbclark/.omp/agent/agent.db` | signed in 2026-10-18, Anthropic OAuth only (the one provider omp is used for) |
| grok | `~djbclark/.grok/auth.json` | signed in 2026-10-18 |
| Hermes | `~djbclark/.hermes/auth.json` | signed in 2026-10-18 via `hermes auth add openai-codex`; `auth.adopt_external_logins` stays false |
| copilot | `~djbclark/.copilot/config.json` | signed in 2026-10-18, token in the 0600 config file (no keyring on the host) |
| gh | `~djbclark/.config/gh/hosts.yml` | signed in 2026-10-18 as djbclark (device code at github.com/login/device; `gh auth login -h github.com -p https -w --skip-ssh-key --insecure-storage`; scopes gist, read:org, repo, workflow; token in the 0600 file, no keyring; git uses gh as credential helper) |
| tea (forgejo.mit.edu) | `~djbclark/.config/forgejo/token`, `~djbclark/.config/tea/config.yml` | signed in 2026-10-18 as djbclark with the Mac's personal access token (`DJBCLARK_FORGEJO_MIT_EDU_TOKEN`), piped from `sudo-secretspec run` over ssh stdin into a 0600 file, then `tea login add --token` and `tea login default forgejo.mit.edu` on the host. OAuth (`tea login add --oauth`) fails on get.sipb.cloud only because that host is a libkrun microVM and tea binds its callback listener to port 0, which TSI makes unreachable (libkrun#818, see the `forgejo-ci` skill; get.sipb.cloud preloads `portshim.so` via `LD_PRELOAD`, which fixes dynamic programs like python but not a static Go binary: python port 0 is reachable with the preload and refused with `env -u LD_PRELOAD`, verified 2026-10-18; vps-primary is plain KVM and tea's OAuth listener answers there); `--redirect-url http://127.0.0.1:<fixed port>` makes the listener answer (probed 2026-10-18, authorization itself not completed), so OAuth is possible but expires and rotates. `tea login helper setup` also made tea git's credential helper for https://forgejo.mit.edu (`[credential "https://forgejo.mit.edu"] helper = !tea login helper` in `~/.gitconfig`), so `git clone/push` over https works. Revoking the PAT signs out the Mac, get.sipb.cloud and vps-primary together. get.sipb.cloud has tea 0.16.0, vps-primary 0.14.0 |
| zcode | `~djbclark/.zcode/v2/credentials.json` | signed in 2026-10-18 (GLM-5.3, z.ai coding plan) |
| agy | `~djbclark/.gemini/antigravity-cli/antigravity-oauth-token` | signed in 2026-10-18; no prompt sent yet (hidden burst limit) |
| qwen | none | skipped: `/auth` offers only an Alibaba ModelStudio key, not OAuth |
| crush | none | not installed |
| cline | none | installed, kept, unsigned |
| opencode | `~djbclark/.local/share/opencode/opencode.db`, `~djbclark/.config/opencode/service.json` | signed in 2026-10-18 with the OpenCode Console account (web device login; the models are the paid OpenCode Go plan, none is free) |
| the rest | see "Install and sign in" | not signed in |

The same agents on get.sipb.cloud (user `djbclark`, `~/`) were signed in the same way on 2026-10-18; Claude, Cursor
and Codex too. They are driven by Paseo there, with the same logins.

If a login ever shows as signed out, log in fresh as `djbclark` (do not re-copy a token that may have been refreshed
elsewhere).

## Install and sign in

Sign in as `djbclark`: `ssh vps-ts`, `sudo -u djbclark -H bash -l`.

| Agent | Install | Sign in |
| --- | --- | --- |
| Claude Code | Anthropic's native installer | `claude` |
| Codex | `npm i -g @openai/codex@latest` (into `~/.local`; tracks latest, never pinned) | `codex login --device-auth` |
| Cursor | `cursor-agent` installer | `cursor-agent login` |
| opencode | `npm i -g @opencode/cli` | `opencode auth login`, pick OpenCode Console, then "OpenCode Console account" (a device code to approve on opencode.ai; OpenCode Go itself only asks for an API key). Run it from `cd ~`: from an unreadable cwd such as `/root`, `opencode auth list` fails with `UnexpectedStatus: 500`. The shared background daemon (`opencode serve --service`, which any CLI command spawns and leaves running, about 160 MB) is off: `opencode service set disabled true` as `djbclark` (2026-10-18); `opencode acp` then runs a private server that exits with it. |
| omp | vendor installer (`omp.sh`, prebuilt) | `omp login` |
| grok | vendor installer (`x.ai/cli`) into `~/.grok` | `grok login` (prints a URL) |
| hermes | fresh Hermes Agent, own `HERMES_HOME` `~djbclark/.hermes` (no gateway, no memory provider, no Mac state) | `hermes auth add openai-codex --type oauth --no-browser` |
| copilot | `npm i -g @github/copilot` | `copilot login` |
| qwen | `npm i -g @qwen-code/qwen-code` | `qwen`, then `/auth` |
| cline | `npm i -g cline` | `cline auth` |
| zcode | `npm i -g zcode-app-cli` (+ `zcode-acp-server`) | `zcode login --oauth --no-browser`, then pick a model with `/model` |
| agy | ACP server and CLI from Google's Linux builds, `~/.local/share/agy-acp-server/` | `agy` over SSH, finish the Google URL on the Mac (the login may not persist without a keyring daemon; fallback `GEMINI_API_KEY`). Hidden burst limit: first use only a tiny thread. |

Notes that are easy to lose:

1. **Hermes `auth.adopt_external_logins` is `false`** on purpose. Its default is `true`, which would borrow and
   refresh the Codex and Claude logins that `djbclark` already has; those refresh tokens are single-use, so Hermes
   would break the other agents' logins. Do not flip it back. The Hermes curator is paused. Hermes' bundled Python
   cannot verify TLS on NixOS (its capath has no hashed links), so `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt`
   is set in `~djbclark/.hermes/.env`.
2. Disk: Hermes (2.5 GB), the npm globals (2 GB) and the agy server (1 GB) are the large pieces. The agy server is
   re-downloadable and the first to drop. The home volume reached 73% on 2026-10-31 (the npm cache alone was 1.5 GB);
   `systemd.tmpfiles.rules` in `configuration.nix` now ages `~/.cache` and `~/.npm/_cacache` out after 14 days and
   `/tmp` after 3 days (`systemd-tmpfiles-clean.timer`, daily; NixOS's packaged rule is 10 days, ours is the earlier
   file so it wins; ticket caches `krb5cc_*` are kept). Check with `systemd-tmpfiles --cat-config | grep -E 'djbclark|/tmp'`.

## Rollback

Never `nixos-rebuild` by hand on the host. Force-push a known-good commit to the deploy branch and start the
upgrade unit: `git push -f origin <good-sha>:deploy-vps-primary`, then `ssh vps-ts systemctl start nixos-upgrade`
(`docs/nixos-in-git.md`). A switch never changes the contents of `/home/djbclark` (it may remount the volume when its
options change). `djbclark` is declared in `nixos/modules/users.nix` (uid 1000, which the volume's files belong to).
