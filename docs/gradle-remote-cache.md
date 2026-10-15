# Shared Gradle remote build cache (vps-primary)

Set up 2026-10-13. Every Gradle build on the Mac reads from and writes to one cache node
on `vps-primary`, over the tailnet only. If the node is unreachable the build uses the local
disk cache and carries on.

## Pieces

1. **Node.** [FosterStack cache](https://github.com/fosterstack/cache) (MIT, one Go binary,
   distroless image) `ghcr.io/fosterstack/cache:0.2.2`, pinned by index digest, in rootful
   Podman on vps-primary (`nixos/vps-primary/configuration.nix`: `virtualisation.oci-containers`,
   container `gradle-cache`, unit `podman-gradle-cache.service`). Runs as uid/gid 5071
   (`gradle-cache`), read-only root filesystem, `--cap-drop=ALL`, `no-new-privileges`, 1 GiB
   memory limit. Data in `/var/lib/gradle-cache` (8 GiB cap, `FSCACHE_MAX_BYTES`,
   least-recently-used eviction; 256 MiB per entry). Replaced the Develocity Build Cache Node
   on 2026-10-15 (see "Node choice").
2. **Reachability.** The published port is bound to the VPS's tailnet address only:
   `100.125.249.107:5071`. **Do not rely on `networking.firewall` for this:** a published
   Podman port is DNAT-ed and never reaches the NixOS INPUT rules, so a `tailscale0`
   firewall rule would restrict nothing (checked against the `oci-containers` option docs).
   The unit waits (up to 120 s) for the tailnet address before starting, so a reboot does
   not race `tailscaled`. Port 6011 (Bazel) is not published.
3. **Access control.** HTTP Basic auth, one read-write user `mac`, no anonymous access. A
   cache write is code injection into your builds (Android release builds included) and the
   tailnet has another person's device on it, so there is no anonymous push. The
   credentials are `FSCACHE_USERNAME=mac` and `FSCACHE_PASSWORD=...` in
   `/var/lib/gradle-cache.env` on the VPS (root, mode 0600, outside the data mount). It
   holds the password, so it is **not** in the Nix config (the store is world-readable) and
   is not tracked. **With those unset the server runs with auth off**, so the unit's
   `ExecStartPre` refuses to start unless both lines are present. `/healthz` and `/metrics`
   answer without auth (tailnet only).
4. **Password.** sudo-secretspec name `GRADLE_BUILD_CACHE_PASSWORD` (optional, a runtime
   declaration). The env file is a plain `KEY=value` file, read by Podman literally: no
   quotes, no `#` or newline in the password.
5. **Client.** `gradle/init.d/global-remote-cache.init.gradle.kts`, linked into every Gradle
   home's `init.d` by `bin/gradle-limits link` (like `machine-slot.gradle`).

## What the init script does

1. Root build only (Gradle ignores build cache settings of included builds).
2. Turns the local build cache on for every build, so there is always a local fallback.
3. Probes the node with a 1 s TCP connect. If that fails (tailnet down, VPS off), it skips
   the remote cache quietly and remembers the failure for 60 s in the daemon.
4. Gets the password from `$GRADLE_REMOTE_CACHE_PASSWORD`, else
   `sudo-secretspec get GRADLE_BUILD_CACHE_PASSWORD` (5 s limit). No password: local only.
5. Attaches `HttpBuildCache` (`http://100.125.249.107:5071/cache/`, push on, plain HTTP is
   deliberate because the transport is the tailnet) inside a try/catch. If the node fails
   mid-build, Gradle itself disables the remote cache for the rest of that build.

Switches: `GRADLE_REMOTE_CACHE=off` (skip everything), `GRADLE_REMOTE_CACHE_URL=...`,
`GRADLE_REMOTE_CACHE_PUSH=false` (read-only).

## Tested 2026-10-13 (Develocity node; the client side still holds)

1. Server: anonymous GET/PUT 403; wrong password 403; correct password PUT 200 / GET 200;
   miss 404; `/ping` 200; UI 404; the public address does not answer on 5071.
2. Build 1 stored the Kotlin DSL script and `:compileJava` entries; after wiping the local
   cache, build 2 reported `:compileJava FROM-CACHE`, so the hit came from the VPS.
3. Failure cases, both `BUILD SUCCESSFUL`: node unreachable (blackholed address): the 1 s
   probe skips the remote cache ("not reachable, using the local cache only"), 3 s build, no
   hang; node reachable but credentials rejected: the 403 makes Gradle disable the remote
   cache for the build ("The remote build cache was disabled during the build due to
   errors") and the build carries on.
4. Reboot: after `systemctl reboot` the container started on its own once the tailnet
   address was up (cache `/ping` 200 at 35 s, one start, no restart loop, no failed units).
5. Gradle versions: pushed and pulled on 9.7.1 (JDK 25), and pushed on 8.14 under JDK 21.
   **Gradle 8.13 (4 of the projects under `~/src`) was not run and is assumed the same as 8.14.**
   **Gradle 8.x cannot run on this Mac's default JDK 25** (`JAVA_HOME` is `openjdk@25`): the
   build fails in its own Kotlin DSL compilation with "What went wrong: 25.0.4.1", with or
   without this init script (checked against an empty Gradle home). An 8.x build needs JDK 17
   or 21 (`/opt/homebrew/opt/openjdk@21` is installed). Do not read that failure as a cache
   problem.

## Node choice (2026-10-15)

Gradle's manual says the Build Cache Node "will no longer be distributed, supported or
available after December 31, 2026" and points to Develocity Edge, which needs a Develocity
server. Gradle's HTTP cache contract is small (200/404 on GET, any 2xx on PUT, anything else
disables the remote cache for the build), so any server speaking it fits. Considered: the
`get` nginx WebDAV module (`~/src/get/nixos/gradle-cache.nix`, no third-party code but ours
to maintain), FosterStack cache, chrisjenx/silo (Kotlin/JVM, quieter since July 2026),
woggioni/rbcs (Java). djbclark chose a prebuilt image, FosterStack: smallest, env-only
config, signed releases with GitHub build provenance. Caveat: a young project (started
2026-08, few users), hence the digest pin, the provenance check and a source review before
each upgrade. The Mac uses this cache, not `get-cache.sipb.cloud` (decided with the SIPB
session, 2026-10-15), so hits are not split across two caches.

## Operations

1. Status: `ssh vps-ts 'systemctl status podman-gradle-cache; podman logs gradle-cache | tail'`;
   liveness `curl -s http://100.125.249.107:5071/healthz` (prints `ok`).
   `fleet-watch vps` already alerts on a failed unit (`units-failed`).
2. Restart: `ssh vps-ts systemctl restart podman-gradle-cache`.
3. Clear the cache: stop the unit, delete the contents of `/var/lib/gradle-cache`, start.
4. Set or rotate the password: `sudo-secretspec set GRADLE_BUILD_CACHE_PASSWORD --reason ...`
   over stdin, then write `/var/lib/gradle-cache.env` on the VPS (mode 0600, root) with the
   two lines `FSCACHE_USERNAME=mac` and `FSCACHE_PASSWORD=<it>`, piping the password over
   ssh stdin so it never appears in a command line, and restart the unit.
5. Upgrade the image: pick the release, then on the Mac
   `crane digest ghcr.io/fosterstack/cache:<ver>` and
   `gh attestation verify oci://ghcr.io/fosterstack/cache@<digest> --repo fosterstack/cache
   --signer-workflow fosterstack/cache/.github/workflows/stage-image.yml --source-ref
   refs/tags/v<ver>` (must print a verified result naming that tag); read the release's
   changes for anything touching auth, storage or network. Put the digest in
   `configuration.nix`, commit, then promote and apply it as in
   [nixos-in-git.md](nixos-in-git.md) (`git push origin master:deploy-vps-primary`, then
   `systemctl start nixos-upgrade` on the VPS).

## Pitfalls met

1. Develocity node era (gone): it required 8+ character passwords with a digit and a special
   character, and logged a generated UI password at first start.
2. A build's time includes waiting for the machine-wide Gradle slot
   (`machine-slot.gradle`); a 7 min "build" was 467 s of queueing behind another build, not
   the cache.
