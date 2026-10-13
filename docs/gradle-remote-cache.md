# Shared Gradle remote build cache (vps-primary)

Set up 2026-10-13. Every Gradle build on the Mac reads from and writes to one cache node
on `vps-primary`, over the tailnet only. If the node is unreachable the build uses the local
disk cache and carries on.

## Pieces

1. **Node.** Develocity Build Cache Node `gradle/build-cache-node:21.2` in rootful Podman on
   vps-primary (`nixos/vps-primary/configuration.nix`: `virtualisation.oci-containers`,
   container `gradle-cache`, unit `podman-gradle-cache.service`). Runs as uid/gid 5071
   (`gradle-cache`), `--cap-drop=ALL`, `no-new-privileges`, 2 GB memory limit. Data in
   `/var/lib/gradle-build-cache` (cache 10 GiB default, least-recently-used eviction).
2. **Reachability.** The published port is bound to the VPS's tailnet address only:
   `100.125.249.107:5071`. **Do not rely on `networking.firewall` for this:** a published
   Podman port is DNAT-ed and never reaches the NixOS INPUT rules, so a `tailscale0`
   firewall rule would restrict nothing (checked against the `oci-containers` option docs).
   The unit waits (up to 120 s) for the tailnet address before starting, so a reboot does
   not race `tailscaled`. Port 6011 (Bazel) is not published.
3. **Access control.** Anonymous access off (`anonymousLevel: "none"`), one `readwrite` user
   `mac`, UI disabled. A cache write is code injection into your builds (Android release
   builds included) and the tailnet has another person's device on it, so there is no
   anonymous push. The config is `/var/lib/gradle-build-cache/conf/config.yaml` on the VPS
   (owner 5071, mode 0640). It holds a password hash, so it is **not** in the Nix config
   (the store is world-readable) and is not tracked; its content is in "Rebuild the node
   config" below.
4. **Password.** sudo-secretspec name `GRADLE_BUILD_CACHE_PASSWORD` (optional, a runtime
   declaration). The node enforces 8+ characters with a digit and a special character.
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

## Tested 2026-10-13

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

## Deprecated: replace before 2026-12-31

Gradle's manual says the Build Cache Node "will no longer be distributed, supported or
available after December 31, 2026" and recommends Develocity Edge, which appears to need
Develocity (not confirmed). The image is pinned to `21.2` and stays usable once pulled, but
it will get no fixes. Before the end of the year pick a successor: an nginx WebDAV
endpoint handling `GET`/`PUT` (Gradle's HTTP cache contract is only that: 200/404 on GET,
any 2xx on PUT, anything else disables the remote cache for the build) fits this host with
no container. Keep the access model (no anonymous write, tailnet-only bind).

## Operations

1. Status: `ssh vps-ts 'systemctl status podman-gradle-cache; podman logs gradle-cache | tail'`.
   `fleet-watch vps` already alerts on a failed unit (`units-failed`).
2. Restart: `ssh vps-ts systemctl restart podman-gradle-cache`.
3. Clear the cache: stop the unit, delete `/var/lib/gradle-build-cache/system/cache`, start.
4. Rotate the password: generate a compliant one (8+ chars, a digit, a special character),
   `sudo-secretspec set GRADLE_BUILD_CACHE_PASSWORD --reason ...` over stdin, hash it with
   `podman run --rm -i docker.io/gradle/build-cache-node:21.2 hash --password -` on the VPS
   (password on stdin), put the result in `config.yaml`, restart the unit.
5. Rebuild the node config (lost `config.yaml`): the node writes none until something
   changes. Layout (schema 5), `users` is a map keyed by username:

   ```yaml
   version: 5
   cache:
     accessControl:
       anonymousLevel: "none"
       users:
         mac:
           password: "<salt:hash from the hash subcommand>"
           level: "readwrite"
   uiAccess:
     type: "disabled"
   ```

6. Update the image: change the tag in `configuration.nix` deliberately (it is pinned, and
   the node is deprecated), commit, then promote and apply it as in
   [nixos-in-git.md](nixos-in-git.md) (`git push origin master:deploy-vps-primary`, then
   `systemctl start nixos-upgrade` on the VPS).

## Pitfalls met

1. First `hash` attempt failed with "Password must be at least 8 characters long and contain
   at least 1 number and 1 special character": an alphanumeric-only password is rejected.
2. The node logs its generated UI username and password at first start (UI access defaults
   to "generated"); `journalctl -u podman-gradle-cache` prints them. The UI is now disabled.
3. A build's time includes waiting for the machine-wide Gradle slot
   (`machine-slot.gradle`); a 7 min "build" was 467 s of queueing behind another build, not
   the cache.
