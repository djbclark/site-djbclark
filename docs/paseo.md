# Paseo across the fleet

[Paseo](https://paseo.sh) ([github.com/getpaseo/paseo](https://github.com/getpaseo/paseo), Apache-2.0) is an
agentic development environment: a daemon runs coding agents (Claude Code, Codex, Copilot, OpenCode, Pi and
more, each in its own worktree) and desktop, web, Android/iOS and CLI clients connect to it. Installed
2026-10-18 at djbclark's request on every machine of the fleet. Decisions (djbclark, 2026-10-18):

1. One daemon per host, all on port **7263** (upstream default 6767), bound to loopback and published on the
   tailnet with `tailscale serve --https=7263`. Never `tailscale funnel`, never a public port.
2. **No daemon password and no relay** (app.paseo.sh): the tailnet is the boundary
   ([agents-vps-primary.md](agents-vps-primary.md)). Paseo runs commands for anyone who reaches it.
3. Linux builds happen in Forgejo CI, never on a host: [forgejo.mit.edu/djbclark/paseo-nix](https://forgejo.mit.edu/djbclark/paseo-nix)
   packs the npm release into a hash-pinned tarball and carries the NixOS module (`services.paseo`).
4. Voice mode and dictation are off on the servers (`speech.enable = false`): on, the daemon downloads about
   200 MB of speech models at startup. The Mac app keeps them.

## Hosts

| Host | Daemon | Runs as | URL (tailnet only) | Config |
| --- | --- | --- | --- | --- |
| mac | Paseo.app (`brew install --cask paseo`) starts and owns it; LaunchAgent `com.djbclark.paseo-desktop` opens the app hidden at login and `keepRunningAfterQuit` keeps the daemon up after quitting (djbclark, 2026-10-18) | djbclark | https://mac.greyhound-sidemirror.ts.net:7263 | `roles/paseo_desktop` (`just paseo-desktop-apply`): `~/.paseo/config.json` keys, the serve and the LaunchAgent |
| vps-primary | `services.paseo` (systemd `paseo.service`) | djbclark, using the agent logins in `/home/djbclark` ([agents-vps-primary.md](agents-vps-primary.md)); state `/home/djbclark/.paseo` | https://vps-primary.greyhound-sidemirror.ts.net:7263 | `nixos/vps-primary/configuration.nix`; Paseo and its agents run in `agents.slice` (MemoryMax 3G) |
| get.sipb.cloud | `services.paseo` in the image (`hostName = "get"`: clients would show the container ID) | djbclark; state `~/.paseo` on `/persist` | https://get.greyhound-sidemirror.ts.net:7263 | `~/src/get` `nixos/paseo.nix`; the TSI port shim is preloaded; get's Tailscale shields are down for this (get `docs/runbook.md` 8.4) |

Clients: the Mac app adds the other two as hosts (Settings, Add host, Direct connection, `<name>.greyhound-sidemirror.ts.net`,
port 7263, SSL on); the Android app on the stayturgid phones the same way over Tailscale; any tailnet browser
opens the URLs above (the bundled web UI); the CLI takes `--host wss://<name>.greyhound-sidemirror.ts.net:7263` (the bare `<name>…:7263` form fails with HTTP 400; checked 2026-10-30)
(the local daemon needs no `--host`).

Status 2026-10-18: all three daemons answer `/api/health` and the web UI over the tailnet (vps-primary at
site-djbclark f919386, get.sipb.cloud at image `ci-eb12788`, Mac app 0.11.4). Android `sh.paseo` 0.11.4 (stayturgid
`bootstrap_apks`, `just deploy-apks`) is on s24 and t2e; hd8 and p7a were off the tailnet and get it on their
next `deploy-apks`. t2e has all three hosts. On s24 the app ignores taps (finger and adb alike, even
after `pm clear`); djbclark will debug it later.

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

## Qualified local fork installer (source adapter)

`bin/paseo-local-upgrade` requires controller-owned authorization at the fixed
real account home path `.local/state/djbclark-ade/forks/paseo-desktop-policy.json`.
Caller `HOME`, `--home`, `--state-dir`, a candidate marker and confirmation flags
cannot replace that policy. The file must be owned by the account, private to it,
regular and reached through protected nonsymlink parents. Missing/revoked policy
holds, including dry runs. No live installation is performed by CI.

Schema v1 requires `component: paseo-desktop`, positive integer `generation`,
`stateCompatibility: binary-only` and a literal-true `operations.activate` or
`operations.recover` grant. Each binds `transactionId`, `receiptSha256`, exact
`version`, `bundleSha256` and `previousBundleSha256`; activation also requires
`archiveSha256` and the exact CI-stamped `Contents/Resources/managed-release.json`
object `{"schemaVersion":1,"component":"paseo-desktop"}`. The marker selects managed
code but grants no authority. This installer accepts already-staged bundles, does
not download packages, and refuses pending updater archives even at the same
version (another updater's cached identity is not this transaction).

Bundle identity is SHA256 of compact UTF8 JSONL records sorted by relative POSIX
path in code-point order, excluding the root: `["d",path,mode]`,
`["f",path,mode,size,contentSha256]`, `["l",path,mode,literalTarget]`.
Mode is permission bits masked by 0777. Unicode is literal, records end in LF.
Traversal never follows symlinks; external links, special files, invalid Unicode
and unstable metadata/content/closure hold. Two complete observations include
empty directories and all files; there is no candidate-controlled exclusion.

The adapter consumes native `daemon maintenance begin/status/end --json` with
transaction/generation and a private owner token. Tokens are never logged or
journaled; end uses `--owner-token-fd 0`. Unsupported/busy/malformed status holds.
Reservation remains held across quit/swap/verification; each boundary revalidates
the current controller policy and both exact bundles. Rollback requires a fresh,
independent recover grant under a newer generation, retains both bundle artifacts,
and never restores writable state or restarts a revoked baseline. Existing
codesign, daemon PID/executable vnode, sessions/plugins and absolute old-bundle
CLI checks remain; idle observations and the local installer lock are not a drain.

The native source interface includes `daemon maintenance verify-offline --generation
N --transaction-id ID --json`. It reads only protected canonical real-account
`~/.paseo` enrollment/reservation state. Installer passes no home override to this
command, and requires the selected daemon home to match that canonical home.
An online native maintenance response comes from client methods that require
`maintenanceReservationV1=true`; the separately qualified old bundle hash binds
that CLI implementation. A live status failure is never an excuse to use an
offline file. Offline verification is used only after existing daemon/PID-lock
checks independently prove shutdown, and its generation/transaction must match
the retained BEGIN reservation. Native source implementation still requires its
own CI/adversary/security qualification; source presence is not live support.
First adoption on an unsupported old daemon remains separately operator-approved.

END releases admission. Its atomic idle-tombstone rename is the native logical
commit point, directory fsync establishes durability, and response acknowledgment
is not the commit point. The installer persists `verified-held`, then
`release-intent`, before END. Lost/uncertain END response records
`release-uncertain`, holds, and never automatically retries END, rolls back a
binary or restarts a daemon after a possible release. Reconciliation requires an
independent status observation and controller decision. Tokens remain only in
memory and private stdin, never argv/logs/journal. An interrupted holder that
loses its once-only token stays held for explicit native recovery; a new
invocation cannot invent fallback permission or silently acquire that hold.

Both legacy swap and new qualification suites run on Linux in
`paseo-qualified-upgrade`. Legacy tests inject an explicit fake controller and
native reservation in process, while using the real production authorization
checks. Former assumptions that confirmation/terminal flags, same-version cached
ZIPs or a lost native owner allow progress now assert holds. Tests cover protected
reader ownership/permissions, symlinks, hardlinks, FIFOs, stable file and ancestor
identity, missing/malformed/duplicate/oversized policy, offline continuity,
revocation, retained artifacts, recovery and END response uncertainty. Shared
Unicode hash parity runs the installer Python encoder, the desktop Python
reference and a snapshot of the actual desktop TypeScript encoder against the
same fixture (including astral/private-use characters, links and empty dirs).
No local pytest or Mac build is part of this change. Dry-run creates no state,
logs or lock directory and never reserves or mutates the application.
