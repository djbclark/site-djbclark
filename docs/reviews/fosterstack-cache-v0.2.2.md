# FosterStack cache v0.2.2: source review

Security review of github.com/fosterstack/cache at tag v0.2.2 (commit 0ac0586), done
2026-10-15 before deploying it as vps-primary's Gradle cache
([gradle-remote-cache.md](../gradle-remote-cache.md)). Read-only review by an agent;
the source was never built or run. Kept as the baseline for reviewing later upgrades.
M1 (auth off when credentials are unset) and L2 (length leak vs the comment at
server.go:200) were reported upstream as
[fosterstack/cache#367](https://github.com/fosterstack/cache/issues/367) on 2026-10-15.

```text
VERDICT: APPROVE for deployment as described, with 2 deployment conditions. No critical or high findings. Findings, ranked:
  M1 (medium) auth silently disabled when both env vars are empty (you plan to guard; confirmed necessary)
  M2 (medium, inherent) no content integrity: the read-write credential can replace any entry, and Gradle will trust it
  L1-L6 (low/info) see section 7.

Target: github.com/fosterstack/cache tag v0.2.2, commit 0ac0586dc1b2de70318b82469fa5b35bfa090068, cloned shallow to
<scratch>/fscache-src. Never built or run.
Paths below are relative to that clone. App code is ~1,250 non-test lines: cmd/fscache/main.go, internal/{server,cache,blobstore,metadata,metrics,buildinfo}.

SCOPE / WHAT I DID NOT DO
 - Read every non-test Go file in full (main.go, server.go, status.go, cache.go, blobstore.go, metadata.go, metrics.go, buildinfo.go).
 - Did not read tests, bin/, .github/, tools/requirements (CI/dev tooling, not in the binary), nor the docs beyond grepping.
 - Did not verify the container image contents or that the image binary equals this source (you said provenance is verified).
 - Dependency source: fetched the 11 module zips from proxy.golang.org into scratchpad/deps (not into any Go cache) and recomputed
   each h1 hash: all 11 match go.sum. I did not run `go list -deps` (that would be build tooling), so the "actually linked" package set
   below comes from manual reading of imports, not the compiler. Module-wide greps were done for net/exec/init; I did not line-audit
   protobuf, x/sys, bbolt or procfs.

1. OUTBOUND NETWORK ACTIVITY: none found
 - App code: ripgrep over all non-test, non-tools .go files for net.Dial/Listen, http.Get/Post/Client/NewRequest, LookupHost/IP,
   os/exec, os.TempDir, CreateTemp, MkdirTemp: zero hits. The only env reads are the FSCACHE_* vars (main.go:41-60, 114, 127).
   The only network code is the inbound http.Server (server/server.go:81, main.go:286). README.md:242 and SECURITY.md:119 also claim no telemetry; code agrees.
   No update/license check (README.md:130 "no license key").
 - Dependencies: the network-capable packages in client_golang (api/prometheus/v1/api.go, prometheus/push/push.go:111,243,296,
   prometheus/graphite/bridge.go:181, prometheus/testutil/testutil.go:167) and prometheus/common/config/http_config.go are NOT imported by the app. Imports used by the app: prometheus, promauto, promhttp, client_model/go.
 - init() functions on the linked path: client_golang prometheus/registry.go:60 (registers the process and Go collectors; reads /proc and runtime, no network),
   promhttp/delegator.go:128 (table setup), internal gddo header init, client_model metrics.pb.go:1229 (protobuf registration). None dials out.
 - klauspost/compress is in go.sum/the module graph but only reachable via promhttp/zstd, which is imported only by client_golang tests
   (promhttp/http_test.go:36); not linked into the binary. expfmt imports net/http only for header types.
 - Other greps (net.Dial/http.Get/os/exec/LookupHost) in protobuf, x/sys, procfs, perks, xxhash, goautoneg, client_model, bbolt hit only code generators
   (internal/cmd/generate-*, mk*.go), x/sys/execabs, and bbolt tests/cmd (dmflakey, bench): none imported.
 - Caveat: no DNS lookups from the app itself; Go's net.Listen on a literal IP does none. The Tailscale bind address should be a literal IP.

2. AUTH CORRECTNESS: sound when credentials are set
 - Every method on every non-reserved path goes through withAuth (server/server.go:120-121, handler at :211-234): GET/HEAD/PUT/DELETE/OPTIONS/PATCH all return 401 without
   valid creds. Auth happens before cacheEndpoint and before withUploadBound, so an unauthenticated PUT never touches the body or the store.
 - Reserved paths (server.go:136-155): /, /healthz, /metrics, /statusz accept only GET/HEAD; any other method gets 405 and writes nothing, so PUT /healthz cannot store a key.
   Reserved set is matched on decoded r.URL.Path (server.go:147), so "%68ealthz" is the same as /healthz and is still read-only.
 - Path tricks: rawPathIsMalformed (server.go:174-192) rejects empty, ".", ".." segments (also percent-encoded) with 400 before the mux, so no 307 redirect path-clean bypass.
   "//healthz", "/%2Fhealthz", "/metrics/", "/statusz/" all fall to the authed cache handler or 400; a decoded key with a leading "/" fails ValidateKey. No route lets a write reach the cache handler without withAuth.
 - Compare: crypto/subtle.ConstantTimeCompare (server.go:217-220), all four compared every request, no short-circuit. Minor: ConstantTimeCompare returns immediately on length mismatch, so length leaks (L2).
 - One-of-two set: loadConfig rejects username-xor-password at startup (main.go:64-66), and Credentials.enabled() requires both non-empty (server.go:37). Same for RO pair (main.go:67-77); RO requires RW, usernames must differ.
 - RO pair: GET/HEAD only, 403 on writes (server.go:228-231). Empty-username/empty-password credentials cannot match because enabled() requires non-empty and the RO branch requires ro.enabled() (server.go:222).
 - Open without auth: GET/HEAD /healthz (server.go:105, returns "ok"), GET/HEAD /metrics (server.go:106). Everything else, including /statusz and "/", is behind auth when auth is on (server.go:113, 118).
   /metrics content: fscache_http_requests_total{method,status}, cache hits/misses, bytes read/written, store_bytes, store_entries, evictions, latency histogram (metrics/metrics.go:30-75), plus default Go runtime and process collectors
   (go_info version, RSS, fds, start time). No cache keys, no usernames, no payload data. Labels are method and status only, so there is no cardinality or key leak.
 - Failed-auth requests are not logged and not rate-limited (L2).

3. UNSET / EMPTY CREDENTIALS (M1)
 - Both empty: starts with auth DISABLED, no error. main.go:57-58 reads the env, :64 only rejects a mismatch; withAuth returns next unwrapped (server.go:212-214), so open PUT/GET/DELETE... (DELETE is 405; PUT is open).
 - Warning: none. The only signal is an Info line {"msg":"fscache: starting", ..., "auth":"disabled"} (main.go:264-282), plus "Auth: disabled" on the authed-only /statusz page and "auth_enabled": false in /statusz JSON (status.go:44, 74).
   README.md:186 documents "unset (auth disabled)" as the default.
 - Partial set (user only or password only): refuses to start (main.go:64-66). Whitespace is not trimmed, so a password of " " counts as set.
 - Fix expected upstream (optional): fail closed unless FSCACHE_ALLOW_ANONYMOUS=1, or at least log at Warn. For us: the guard you planned (assert a non-empty password in the unit/env before start, and probe that an unauthenticated PUT returns 401 after start).

4. PATH TRAVERSAL / KEY HANDLING / INTEGRITY
 - Traversal: not exploitable. Keys come from r.URL.Path (server.go:290). ValidateKey (blobstore.go:92-109): max 16 segments, each must match ^[A-Za-z0-9._-]{1,255}$ and not be "." or "..". No NUL, no backslash, no encoded slash can survive (decoded Path is validated).
   All I/O goes through os.Root (blobstore.go:81, 139, 149, 171, 184, 206, 223), which the OS confines to the root and which refuses symlink escape. Sharding: the first 2 chars of the leaf (blobstore.go:114-126). Reads and writes cannot leave <data>/blobs.
 - Integrity: NO hashing or verification. blobstore.go:1-5 states "the store never hashes, parses, or interprets the bytes". Gradle's key is computed client-side and the server accepts any bytes under any valid key.
   What it does guarantee: atomic publish (temp file in same dir, fsync, close, rename: blobstore.go:143-173), so a GET never sees a partial PUT; an aborted or truncated upload errors in io.Copy and the temp file is removed (:153-159), so a truncated body is never committed;
   body capped by MaxBodyBytes (server.go:346) and capReader (cache.go:198-218). There is no check that returned bytes match what was PUT (no checksum at rest): disk bit-rot, or anyone with write access to /data, is served as-is.
 - M2: overwrite is allowed for any key (rename over dest, blobstore.go:171; no create-only/If-None-Match semantics). Anyone holding the RW credential can replace the entry for a legitimate cache key with a malicious one, and Gradle will extract and use it
   (compiled classes, dex, and so on). This is inherent to the Gradle HTTP cache protocol, not an implementation bug, but given Android release builds it is the main risk.
   Required mitigations on your side: (a) create FSCACHE_RO_USERNAME/PASSWORD (main.go:59-60) and give builds that must not publish (release builds, CI of untrusted code) the RO pair, `push = false` in Gradle; only trusted local builds get RW;
   (b) keep the RW secret out of any build that executes untrusted code; (c) consider not using the remote cache for signed release artifacts at all, or run release with --no-build-cache; (d) cache entries persist until LRU eviction, so a poisoned entry stays; rotating means wiping /data.
 - L5: key namespace collisions between nested keys and shard files (blobstore.go:114-126): PUT "ab" creates blobs/ab/ab as a file, a later PUT "ab/ab" needs blobs/ab/ab as a directory and fails 500. Keys beginning ".tmp-" are treated as stale temp by Walk (:270) and deleted at reconciliation.
   Only reachable with write credentials, not a security boundary issue for Gradle's 32-hex keys.

5. WRITES OUTSIDE FSCACHE_DATA_DIR
 - None in app code (no os.TempDir/CreateTemp/MkdirTemp; confirmed by grep). Writes: <data>/.unclean-shutdown marker (main.go:83-103, written at EVERY start, removed on clean shutdown), <data>/blobs/** (blobstore temp files live inside the shard dir, not os.TempDir), <data>/meta.db (bbolt; flock on that file, mmap, no sidecar files). Logs go to stdout only (main.go:170).
 - Under --read-only: you MUST set FSCACHE_DATA_DIR=/data (default is ./data -> /home/nonroot/data in the image: Dockerfile.production WORKDIR; read-only rootfs would fail at startup with "write shutdown marker"). /data must be a writable mount owned by uid 5071 (dirs 0750, files 0600; use podman `:U` or pre-chown). No tmpfs needed for /tmp.
 - Dependency CreateTemp (client_golang registry.go:636, WriteToTextfile) and bbolt cmd bench are not called/linked.
 - Memory notes (2 GiB): eviction loads the whole bbolt index into memory and sorts it per PUT (metadata.go LeastRecentlyUsed ~line 150-170); fine for 10 GiB of Gradle entries, grows with entry count. bbolt mmaps meta.db.

6. DEPENDENCIES (go.mod; go 1.27.2; all 11 h1 hashes verified against go.sum)
 Direct: prometheus/client_golang v1.24.1, prometheus/client_model v0.6.3, go.etcd.io/bbolt v1.5.0.
 Indirect: beorn7/perks v1.0.1, cespare/xxhash/v2 v2.3.0, munnerz/goautoneg v0.0.0-20191010083416-a7dc8b61c822, prometheus/common v0.70.1,
 prometheus/procfs v0.21.1, golang.org/x/sys v0.47.0, google.golang.org/protobuf v1.36.12.
 Also in go.sum only (test or graph pruning, not linked into the binary): klauspost/compress v1.19.1, go-spew, go-cmp, godebug, go-difflib, testify, goleak, yaml.v2/v3, x/sync.
 Nothing unusual: all well-known, pure Go, zero CGO (ci.yml:31 builds CGO_ENABLED=0), no replace directives, no vendored or forked modules, no exotic registry. goautoneg is an old pseudo-version but is the standard prometheus transitive dep.
 Not checked: known CVEs against these exact versions (no scanner run; the repo has bin/grype-scan.sh and docs/scanning.md). Image base is distroless static:nonroot pinned by digest (Dockerfile.production), zero RUN steps.

7. OTHER (low / informational)
 L1  No TLS: ListenAndServe (main.go:286); Basic auth credentials travel cleartext. Acceptable on a Tailscale (WireGuard) address only. Do not expose elsewhere.
 L2  withAuth: no failed-auth logging, no rate limit or lockout (server.go:223-227); ConstantTimeCompare on raw values leaks credential length (server.go:217-220, the comment claims it avoids length leakage; it does not). Use a long random password (>= 32 chars). Tailnet ACLs are the real control.
 L3  /metrics and /healthz are unauthenticated (server.go:105-106) while /statusz is authed: any tailnet node can read store size, entry count, hit rates, Go/process info. No keys or data. Restrict with a Tailscale ACL if wanted.
 L4  FSCACHE_ADDR defaults to ":8080" (all interfaces) (main.go:54). Under rootful Podman with a published port bound to the Tailscale IP this is fine; with --network=host it would listen on every interface. Set FSCACHE_ADDR=<tailscale-ip>:8080 explicitly.
 L5  See section 4 (key collisions, ".tmp-" keys).
 L6  Availability: every GET does a bbolt write transaction (cache.go:248, metadata.go Touch) and eviction scans/sorts the full index; disk can transiently exceed FSCACHE_MAX_BYTES by up to MAX_BODY_BYTES x MAX_CONCURRENT_UPLOADS = 32 GiB with defaults before eviction runs (cache.go:236-238). Size the volume with headroom (>= 10 GiB + 32 GiB worst case, or lower FSCACHE_MAX_CONCURRENT_UPLOADS / FSCACHE_MAX_BODY_BYTES). Only an authenticated client can trigger this.

DEPLOYMENT CONDITIONS (approval is conditional on both)
 1. Credentials non-empty, verified at deploy time (M1), and an unauthenticated PUT must return 401 in the post-start probe.
 2. Use the RO credential pair for every build that does not need to publish, especially Android release builds (M2), and set FSCACHE_DATA_DIR=/data and FSCACHE_ADDR to the Tailscale IP.
```
