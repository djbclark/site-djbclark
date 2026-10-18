# BB on vps-primary

[BB](https://github.com/get-bb/bb) (npm package `bb-app`, upstream `get-bb/bb`) is an agent workspace: a web UI
and server that start coding agents (Claude Code, Codex, Cursor, Pi and a long list of ACP agents) as an
unprivileged account on a Linux machine, keep their threads and worktrees there, and can drive further machines
through a host daemon that dials out to the server. It replaced Cloudroom core on vps-primary on 2026-10-17
(djbclark's decision; the history is at the end of this file).

**BB has no login.** Its public API is unauthenticated and permits command execution and file reads: anyone who
can reach the port can run an agent as the service user. The tailnet is the only boundary (ACL: allow-all, djbclark's
choice, 2026-10-17, so every tailnet device and shared-in user can use it). Never `tailscale funnel`, never a public
port; the module binds the server to loopback and serves it with `tailscale serve` only.

1. **Module and packages:** [github.com/djbclark/bb-nix](https://github.com/djbclark/bb-nix) (public, MIT; local
   `~/src/bb-nix`), a flake input of `nixos/`. Its README is the documentation: options, what the module does to a
   host, logging the agents in, adding another machine, the settings that are not in Nix.
2. **This host's settings:** `services.bb` in `nixos/vps-primary/configuration.nix`.
3. **Builds:** the public Forgejo repo [forgejo.mit.edu/djbclark/bb-build](https://forgejo.mit.edu/djbclark/bb-build)
   (local `~/src/bb-build`); index of my MIT projects: [djbclark/mit](https://forgejo.mit.edu/djbclark/mit).

## Builds run in Forgejo CI by default

djbclark, 2026-10-16: build in Forgejo CI rather than on vps-primary. Compiling on the host is allowed when there
is no other good option or host, or when it is actually the fastest route. As set up, nothing compiles there:
bb-build's `build.yml` packs `bb-app` (installed with `npm ci` from a lock file, native modules checked, a smoke
test of the server on the runner) and the Codex CLI (`bb-codex-npm`) into hash-pinned linux-x64 tarballs, published
as Forgejo generic packages; bb-nix pins them by URL and hash and the host only downloads them. `crush.yml` builds
`crush-acp` the same way (section "Agents"). What the host still builds is what every NixOS switch builds
(configuration files, units, wrappers).

bb-build's `nix-build` workflow builds flake attributes on the runner: bb-nix's packages and checks (`smoke`,
`module-eval`), and this repo's vps-primary system at a commit before promotion (`dir=nixos`, attr
`nixosConfigurations.vps-primary.config.system.build.toplevel`; `docs/nixos-in-git.md`).

## On this host

| Piece | Where |
| --- | --- |
| Browser URL | `https://vps-primary.greyhound-sidemirror.ts.net/` (tailnet 443 -> `127.0.0.1:38886`). `appUrl` has no port: BB's Host and Origin check compares against it. |
| Machine URL | `https://vps-primary.greyhound-sidemirror.ts.net:38443` (the same backend; `externalUrl` = `BB_EXTERNAL_URL`, what Settings, Machines, Manual shows for host daemons). |
| Ports | `38886` bb-server and `38887` bb-host-daemon, both loopback (registry/ports.yml). Tailnet 443 and 38443 are `tailscale serve` only. |
| Account and data | User `bb`, data dir `/var/lib/bb` (BB's `bb.db`, worktrees under `plugins/environment-git-worktree`, the agents' installs and logins). Scratch repo `c1test` is a leftover smoke project. |
| Memory | `memoryHigh = "2560M"`, `memoryMax = "3G"` for BB and every agent (4 GB host, also running the Gradle cache and Athena). Idle about 850 MiB, peak about 1.1-1.6 GiB. |
| Telemetry | `BB_TELEMETRY=false` in the unit and `telemetryEnabled false` in the database. |

The module block (abridged; the file has the comments):

```nix
services.bb = {
  enable = true;
  package = bb-nix.packages.x86_64-linux.bb-app-bin;
  appUrl = "https://vps-primary.greyhound-sidemirror.ts.net";
  externalUrl = "https://vps-primary.greyhound-sidemirror.ts.net:38443";
  claudeCode = { nativeInstaller = true; executable = "/var/lib/bb/.local/bin/claude"; };
  extraPackages = [ bb-nix.packages.x86_64-linux.codex-npm-bin pkgs.git pkgs.gh pkgs.ripgrep ];
  memoryHigh = "2560M";
  memoryMax = "3G";
  tailscaleServe = { enable = true; ports = [ 443 38443 ]; };
};
programs.nix-ld.enable = true;   # downloaded generic-glibc binaries: Claude Code, Cursor's node, agy, omp, grok
```

`npmGlobalPrefix` keeps its default `/var/lib/bb/.local`. BB's own `npm install -g` (agents installed from its UI,
for example Pi) would otherwise write into the read-only Node store path and fail; with the prefix, global npm
binaries land in `~/.local/bin` beside the native Claude Code and Cursor, which is first on the unit's and the login
PATH, and Node.js is in the `bb` user's profile (npm-installed agents start with `#!/usr/bin/env node`). The
`bbcli` shorthand in the bb-nix README runs the BB CLI as `bb` against `http://127.0.0.1:38886`; run it from a
directory `bb` can enter (`cd /tmp`), or node dies with `spawn ... EACCES`.

### Settings that live in the database, set once

Done 2026-10-17 as `bb` against the running server, as bb-nix's README "Settings that are not in Nix" explains:

1. Plugins disabled through the CLI: `bbcli plugin disable connect`, `... bb-account`, `... bb-ai` (no path to getbb.app).
   Re-run `bbcli plugin list` after every BB upgrade: new built-in plugins default to enabled.
2. `bbcli settings general defaultMachineAccess direct` (the "Manual" provider for new machines) and
   `bbcli settings general telemetryEnabled false`. `push-notifications` stays on (push goes only to registered devices).
3. `bbcli plugin config provider-acp set customAgents '<json array>'` for the ACP agents BB does not ship (list below).

**Do not use `bb-app env set` or `config set` on a host** for anything the module sets: precedence is ambient
environment, then flags, then `config.json`, then `env.json`, so a stray `env.json` silently overrides the unit.

```bash
ssh vps-ts
sudo -u bb -H bash -l            # a login shell: ~/.local/bin and node are on PATH
(cd /tmp && curl -fsS http://127.0.0.1:38886/health)
```

## Logins

Every login is the `bb` user's and lives in its home, `/var/lib/bb`; none is in git, the Nix store or this repo.
Mac-side copies are not shared (single-use refresh tokens would invalidate each other).

| Agent | Where its login lives | Status |
| --- | --- | --- |
| Claude Code | `~bb/.claude/.credentials.json`, `~bb/.claude.json` | signed in (copied once from the Cloudroom account, 2026-10-17) |
| Codex | `~bb/.codex/auth.json` (its `config.toml` was deliberately not copied) | signed in |
| Cursor | `~bb/.cursor`, binary `~bb/.local/bin/cursor-agent` | signed in by djbclark |
| Pi | in `~bb`, installed from BB's UI | listed; install (and login) is djbclark's to retry in the UI |
| omp | `~bb/.omp/agent/agent.db` | signed in 2026-10-18, Anthropic OAuth only (the one provider omp is used for) |
| grok | `~bb/.grok/auth.json` | signed in 2026-10-18 |
| Hermes (bb's own) | `~bb/.hermes/auth.json` | signed in 2026-10-18 via `hermes auth add openai-codex`; `auth.adopt_external_logins` stays false |
| copilot | `~bb/.copilot/config.json` | signed in 2026-10-18, token in the 0600 config file (no keyring on the host) |
| gh | `~bb/.config/gh/hosts.yml` | signed in 2026-10-18 as djbclark (device code at github.com/login/device; `gh auth login -h github.com -p https -w --skip-ssh-key --insecure-storage`; scopes gist, read:org, repo, workflow; token in the 0600 file, no keyring; git uses gh as credential helper) |
| tea (forgejo.mit.edu) | `~bb/.config/forgejo/token`, `~bb/.config/tea/config.yml` | signed in 2026-10-18 as djbclark with the Mac's personal access token (`DJBCLARK_FORGEJO_MIT_EDU_TOKEN`), piped from `sudo-secretspec run` over ssh stdin into a 0600 file, then `tea login add --token` and `tea login default forgejo.mit.edu` on the host. OAuth (`tea login add --oauth`) fails on get only because get is a libkrun microVM and tea binds its callback listener to port 0, which TSI makes unreachable (libkrun#818, see the `forgejo-ci` skill; get preloads `portshim.so` via `LD_PRELOAD`, which fixes dynamic programs like python but not a static Go binary: python port 0 is reachable with the preload and refused with `env -u LD_PRELOAD`, verified 2026-10-18; vps-primary is plain KVM and tea's OAuth listener answers there); `--redirect-url http://127.0.0.1:<fixed port>` makes the listener answer (probed 2026-10-18, authorization itself not completed), so OAuth is possible but expires and rotates. `tea login helper setup` also made tea git's credential helper for https://forgejo.mit.edu (`[credential "https://forgejo.mit.edu"] helper = !tea login helper` in `~/.gitconfig`), so `git clone/push` over https works. Revoking the PAT signs out the Mac, get and vps-primary together. get has tea 0.16.0, vps-primary 0.14.0 |
| zcode | `~bb/.zcode/v2/credentials.json` | signed in 2026-10-18 (GLM-5.3, z.ai coding plan) |
| agy | `~bb/.gemini/antigravity-cli/antigravity-oauth-token` | signed in 2026-10-18; no prompt sent yet (hidden burst limit) |
| qwen | none | skipped: `/auth` offers only an Alibaba ModelStudio key, not OAuth |
| crush | none | parked: needs the SIPB loopback proxy, a crushrc and `MIT_SIPB_API_KEY` (plan 14.42) |
| cline | none | installed, kept, unsigned |
| opencode | `~bb/.local/share/opencode/opencode.db`, `~bb/.config/opencode/service.json` | signed in 2026-10-18 with the OpenCode Console account (web device login; the models are the paid OpenCode Go plan, none is free) |
| the rest | see "Agents" | not signed in |

The same agents on `get` (user `djbclark`, `~/`) were signed in the same way on 2026-10-18; Claude, Cursor and Codex too.

If a login ever shows as signed out, log in fresh as `bb` (do not re-copy a token that may have been refreshed
elsewhere).

## Agents

BB lists every agent that is installed for `bb`. Its native providers are Claude Code, Codex and Pi; the provider
ids of ACP agents are `acp-<id>`. All installs are done as `bb` without root (npm into `~/.local`, vendor installers
into `~/.local/bin` or `~/.grok`); nix-ld covers the generic Linux binaries.

| Agent | Install | In BB as | Sign in (as `bb`: `ssh vps-ts`, `sudo -u bb -H bash -l`) |
| --- | --- | --- | --- |
| Claude Code | `claudeCode.nativeInstaller` (Anthropic's installer) | native | `claude` |
| Codex | `codex-npm-bin` (bb-build `bb-codex-npm`, on the unit PATH) | native | `codex login --device-auth` |
| Cursor | `cursor-agent` installer | built-in | `cursor-agent login` |
| opencode | `npm i -g @opencode/cli` | built-in `acp-opencode` | `opencode auth login`, pick OpenCode Console, then "OpenCode Console account" (a device code to approve on opencode.ai; OpenCode Go itself only asks for an API key). Run it from `cd ~`: from an unreadable cwd such as `/root`, `opencode auth list` fails with `UnexpectedStatus: 500`. The shared background daemon (`opencode serve --service`, which any CLI command spawns and leaves running, about 160 MB) is off: `opencode service set disabled true` as `bb` (2026-10-18); BB starts `opencode acp` per thread, which then runs a private server that exits with it (handshake and `session/new` checked) |
| omp | vendor installer (`omp.sh`, prebuilt) | built-in `acp-omp` | `omp login` |
| grok | vendor installer (`x.ai/cli`) into `~/.grok` | built-in `acp-grok` | `grok login` (prints a URL) |
| hermes | fresh Hermes Agent, own `HERMES_HOME` `~bb/.hermes` (no gateway, no memory provider, no Mac state) | built-in `acp-hermes-agent` | `hermes auth add openai-codex --type oauth --no-browser` (route preset: provider `openai-codex`) |
| copilot | `npm i -g @github/copilot` | custom `acp-copilot` | `copilot login` |
| qwen | `npm i -g @qwen-code/qwen-code` | custom `acp-qwen` | `qwen`, then `/auth` |
| cline | `npm i -g cline` | custom `acp-cline` | `cline auth` |
| zcode | `npm i -g zcode-app-cli` (+ `zcode-acp-server`) | custom `acp-zcode` | `zcode login --oauth --no-browser`, then pick a model with `/model` |
| agy | ACP server and CLI from Google's Linux builds, `~/.local/share/agy-acp-server/` | custom `acp-agy` | `agy` over SSH, finish the Google URL on the Mac (the login may not persist without a keyring daemon; fallback `GEMINI_API_KEY` in the custom agent's env). Hidden burst limit: first use only a tiny thread. |
| crush | `crush-acp` built by bb-build `crush.yml` | custom `acp-crush` | needs a provider: run `crush-acp` once and pick one, or add a provider block to `~/.config/crush/crush.json` |

Notes that are easy to lose:

1. **Hermes `auth.adopt_external_logins` is `false`** on purpose. Its default is `true`, which would borrow and
   refresh the Codex and Claude logins that `bb` already has; those refresh tokens are single-use, so Hermes would
   break BB's own logins. Do not flip it back. The Hermes curator is paused. Hermes' bundled Python cannot verify TLS
   on NixOS (its capath has no hashed links), so `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt` is set in
   `~bb/.hermes/.env`. A module-wide `services.bb.sslCertFile` is deferred until the unit restarts anyway.
2. **crush-acp is a CI build of an unmerged upstream PR** (charmbracelet/crush#2450) from djbclark's fork branch,
   pinned by commit in bb-build's `crush.env`; the build fails if the branch tip moved. BB 0.46.1 authenticates an
   ACP agent only with the method ids `cached_token` or `xai.api_key`, and the PR's server offers only `local`, so
   CI applies `patches/crush-acp-bb-auth.patch` (adds `cached_token` as an alias). To follow the branch: bump
   `CRUSH_COMMIT` and `CRUSH_VERSION` in `crush.env`, push, and install the new `PIN crush-acp` line's file as
   `~bb/.local/bin/crush-acp` (download, check the SRI hash, `mv -f`).
3. The custom agents are one JSON array in `provider-acp` `customAgents` (read it with `bbcli plugin config
   provider-acp`). The setting is server-wide and its commands run on the thread's machine, so every entry is a
   bare command name found on that machine's login PATH, never an absolute path (absolute vps-primary paths gave
   `spawn ... ENOENT` on other machines, 2026-10-17). `cline` and `crush` carry `permissionCli` entries that add
   their yolo flag in full-permission threads. Three per-machine wrappers in `~/.local/bin` hold what a static
   entry cannot: `zcode-acp-bb` (sets `ZCODE_BIN` to the vendor `zcode.cjs` under `$(npm root -g)`), `agy-acp-bb`
   (runs the newest `~/.local/share/agy-acp-server/<version>/agy_acp_server.par`, adding `--uid=` on Linux, as the ACP registry does) and `crush-acp-bb` (sets
   `CRUSH_DISABLE_METRICS=1` and `CRUSH_GLOBAL_DATA=$HOME/.local/share/crush-acp`). Every machine needs the three
   wrappers before it runs those agents; the get repo's `scripts/get-bb-agents wrappers` writes them. Custom agents
   do run on remote machines (tested on get), although the BB docs say they need a co-located daemon.
4. A new built-in agent shows in `bbcli provider list` about two minutes after install (BB's periodic refresh).
5. Disk: `/` is about 66% used; Hermes (2.5 GB), the npm globals (2 GB) and the agy server (1 GB) are the large
   pieces. The agy server is re-downloadable and the first to drop.

## Bumping a version

1. `~/src/bb-build`: set `BB_APP_VERSION`, `BB_APP_INTEGRITY`, `BB_UPSTREAM_GITHEAD` in `pins.env` and the version
   in `bundle/package.json`, relock (lock file only, throwaway cache), push `main`; its run prints `PIN` lines
   (URL, SRI hash). Codex alone: `CODEX_VERSION`.
2. `~/src/bb-nix`: paste the lines into `pkgs/pins.json` and update `lock/`, push; the `nix-build` workflow builds
   `bb-app-bin`, `smoke` and `module-eval`.
3. Here: `nix flake update bb-nix` in `nixos/` (on the host, a download only, in a scratch copy; the Mac has no Nix),
   commit, push `master`, run `nix-build` on that commit, then promote (`docs/nixos-in-git.md`).
4. **Back up `/var/lib/bb` first**: BB migrates its database on start, so going back needs the backup. Server and
   every enrolled host daemon must run the same version. A switch that restarts the `bb` unit interrupts running
   threads: promote when none is busy. Afterwards `bbcli plugin list` (new built-ins default to enabled).

## Enrolling machines

Other machines (the Mac, `get`) run a host daemon that dials out to `:38443`; the server needs no route to them. Use
BB's Manual provider, never `bb connect`. The steps, including the enrolment header trick for NixOS (do not run BB's
own installer there) and the userspace-Tailscale variant for a libkrun microVM, are in the
[bb-nix README, "Adding another machine"](https://github.com/djbclark/bb-nix#adding-another-machine). In short:

1. In the BB UI: Settings, Machines, add a machine, Manual. The credential shown lasts 15 minutes and is a secret.
2. NixOS machine: `services.bb-host-daemon` with `serverUrl` exactly the machine URL above, then `bb machine enroll
   --bootstrap-env BB_ENROLLMENT` as the daemon's user and `systemctl start bb-host-daemon` (the unit waits for
   `<dataDir>/auth.json`). Other machines (the Mac): the same enrolment through the Manual provider.
3. Log the agents in on that machine as its user.

## Rollback

Never `nixos-rebuild` by hand on the host. Force-push a known-good commit to the deploy branch and start the
upgrade unit: `git push -f origin <good-sha>:deploy-vps-primary`, then `ssh vps-ts systemctl start nixos-upgrade`
(`docs/nixos-in-git.md`). `/var/lib/bb` is not touched by a switch, but a BB version rollback needs the pre-upgrade
database backup. Commits before 2026-10-17 ran Cloudroom, whose data is being removed: roll back only to a
commit that has `services.bb`.

## History: Cloudroom

Cloudroom core (davidondrej/cloudroom-core, behind a bearer-token API, via the
[cloudroom-nix](https://github.com/djbclark/cloudroom-nix) module and
[cloudroom-core-build](https://forgejo.mit.edu/djbclark/cloudroom-core-build) CI) ran on vps-primary from
2026-10-16 to 2026-10-17, when djbclark moved to upstream BB. Both repositories are unmaintained now (kept public,
not archived). Cloudroom's thread history was not migrated, by decision. The old Mac-app and phone workarounds
(cloudroom-gui issues #6 to #8) no longer apply.
