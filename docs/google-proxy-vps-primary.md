# Google proxy on vps-primary (for SearXNG on SIPB Hyades)

Decided by djbclark 2026-10-16. Every Hyades microVM leaves through one shared address
(`hyades.mit.edu`, 18.4.60.84, measured from `get` the same day), and Google answers
SearXNG's Google engines from it with "unusual traffic" 429s. Only the Google engines
are routed through a proxy on vps-primary; every other engine keeps going out directly.
Module: `nixos/modules/google-proxy.nix`. The SearXNG side (the per-engine `proxies:`
setting) lives with the SearXNG image, not here.

## 1. Why tinyproxy, and what was searched first

1. **Nothing new on the SearXNG side.** SearXNG already has a per-engine `proxies:`
   setting (`engines:` in `settings.yml`; `outgoing.proxies` is the global one), with
   `retries` and `retry_on_http_error` for failover. No plugin or fork is needed.
   (docs.searxng.org, "engines:" and "outgoing:".)
2. **Proxy: tinyproxy 1.11.3** (in nixpkgs 26.05; the 2023 CVE is fixed from 1.11.2).
   It has exactly the three controls needed and nothing else: `ConnectPort 443`,
   `Allow <ip>`, and a `Filter` file with `FilterDefaultDeny Yes` that is matched against
   the CONNECT host name (`FilterURLs Off`, `FilterType ere`). It has no cache. One small
   daemon, packaged as `pkgs.tinyproxy`.
3. **Rejected.** Caddy needs the `forwardproxy` plugin built in (`withPlugins`), a
   custom build for one feature. Squid does the job but is a large daemon with a cache
   to switch off. An SSH `-D` SOCKS tunnel would need a private key inside a public
   image and has no domain allowlist. A paid SERP/proxy API was not wanted.
4. tinyproxy cannot filter URL paths inside CONNECT (tinyproxy issue #345), which is
   fine: the goal is a host allowlist, not content inspection.

## 2. Controls

1. Firewall (iptables backend; nftables is off on this host): the port accepts TCP only
   from the Hyades egress address, with `connlimit` 40 and a `hashlimit` of 30 new
   connections per second (burst 60). Everyone else is dropped.
2. tinyproxy repeats the source check (`Allow`), allows CONNECT only to port 443, and
   only to the hosts in `allowedHosts` in the module; anything else gets 403.
3. It binds the public interface address only, read from `enp1s0` at service start so
   the address is not written into git. Not the tailnet, loopback or the Podman bridge.
4. The unit runs as a `DynamicUser` with no capabilities, `ProtectSystem=strict`,
   a 128 MiB memory cap and a syscall filter. Access log: `journalctl -u tinyproxy-google`.
5. The proxy URL carries no credential, because the SearXNG image is public. The
   firewall rule is the only authentication, so a change of the Hyades egress address
   makes the proxy unreachable (fail closed) until `hyadesEgress` is updated.

## 3. Acceptance record

Filled in after deploy (see the end of this file).
