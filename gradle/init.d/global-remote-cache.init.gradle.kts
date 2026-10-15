// Machine-wide Gradle remote build cache (2026-10-13).
//
// Every build on this Mac pulls from and pushes to the shared cache on vps-primary
// (FosterStack cache in Podman, reachable only on the tailnet; see
// nixos/vps-primary/configuration.nix and docs/gradle-remote-cache.md). Linked into every
// Gradle home's init.d by `gradle-limits link`, like machine-slot.gradle.
//
// It must never break a build. Everything below runs inside try/catch, and the remote cache
// is only attached when all of these hold, otherwise Gradle just uses the local disk cache:
//   1. this is the root build (Gradle ignores build cache settings of included builds);
//   2. the node answers a TCP connect within 1 s (tailnet down or VPS off: skipped quietly,
//      and remembered for 60 s by the daemon so later builds do not each pay the wait);
//   3. credentials were found: $GRADLE_REMOTE_CACHE_PASSWORD, else the sudo-secretspec
//      name GRADLE_BUILD_CACHE_PASSWORD (anonymous access to the node is off, and a cache
//      write is code injection into your builds, so there is no anonymous push).
// Even then, if the node fails mid-build Gradle disables the remote cache for the rest of
// that build and carries on.
//
// Switches: GRADLE_REMOTE_CACHE=off skips all of this; GRADLE_REMOTE_CACHE_URL points
// elsewhere (default http://100.125.249.107:5071/cache/, the VPS's tailnet address);
// GRADLE_REMOTE_CACHE_PUSH=false makes this machine read-only. Plain HTTP is deliberate:
// the transport is the encrypted tailnet.
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.TimeUnit

val cacheUser = "mac"
val downUntilKey = "djbclark.remoteCache.downUntil"

fun cachePassword(): String? {
    System.getenv("GRADLE_REMOTE_CACHE_PASSWORD")?.takeIf { it.isNotBlank() }?.let { return it }
    val bin = File("/usr/local/bin/sudo-secretspec")
    if (!bin.canExecute()) return null
    val proc = ProcessBuilder(
        bin.path, "get", "GRADLE_BUILD_CACHE_PASSWORD", "--reason", "Gradle remote build cache credentials"
    ).redirectError(ProcessBuilder.Redirect.DISCARD).start()
    if (!proc.waitFor(5, TimeUnit.SECONDS)) {
        proc.destroyForcibly()
        return null
    }
    if (proc.exitValue() != 0) return null
    return proc.inputStream.bufferedReader().readText().trim().takeIf { it.isNotEmpty() }
}

fun nodeReachable(cacheUri: java.net.URI): Boolean {
    val downUntil = System.getProperty(downUntilKey)?.toLongOrNull() ?: 0L
    if (System.currentTimeMillis() < downUntil) return false
    return try {
        Socket().use { it.connect(InetSocketAddress(cacheUri.host, cacheUri.port.takeIf { p -> p > 0 } ?: 80), 1000) }
        true
    } catch (e: Exception) {
        System.setProperty(downUntilKey, (System.currentTimeMillis() + 60_000).toString())
        false
    }
}

if (gradle.parent == null && System.getenv("GRADLE_REMOTE_CACHE") != "off") {
    try {
        // Local disk cache on for every build, so there is always something to fall back to.
        gradle.startParameter.isBuildCacheEnabled = true
    } catch (e: Exception) {
        logger.info("global-remote-cache: could not enable the build cache: ${e.message}")
    }
    gradle.settingsEvaluated {
        try {
            val cacheUrl = uri(System.getenv("GRADLE_REMOTE_CACHE_URL") ?: "http://100.125.249.107:5071/cache/")
            if (!nodeReachable(cacheUrl)) {
                logger.info("global-remote-cache: $cacheUrl not reachable, using the local cache only")
            } else {
                val password = cachePassword()
                if (password == null) {
                    logger.lifecycle("global-remote-cache: no credentials (GRADLE_BUILD_CACHE_PASSWORD), using the local cache only")
                } else {
                    val push = System.getenv("GRADLE_REMOTE_CACHE_PUSH") != "false"
                    buildCache {
                        remote<HttpBuildCache> {
                            url = cacheUrl
                            isAllowInsecureProtocol = true
                            isPush = push
                            credentials {
                                username = cacheUser
                                this.password = password
                            }
                        }
                    }
                    logger.info("global-remote-cache: using $cacheUrl (push=$push)")
                }
            }
        } catch (e: Exception) {
            logger.warn("global-remote-cache: skipped (${e.javaClass.simpleName}: ${e.message}); using the local cache only")
        }
    }
}
