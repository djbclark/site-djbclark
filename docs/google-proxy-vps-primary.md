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

## 3. Acceptance record (2026-10-16, deployed at b66d70b)

1. From `get` (egress measured 18.4.60.84), through the proxy: `https://www.google.com`
   CONNECT succeeds (HTTP 200 from Google); `https://example.com` and
   `https://consent.google.com` get `CONNECT tunnel failed, response 403`.
2. From the Mac (not the Hyades address) the port times out (curl exit 28, 8 s).
3. The first deploy failed in `tinyproxy-google` only: `ip` in the start script needs
   `AF_NETLINK`, which the unit's `RestrictAddressFamilies` had left out. The firewall
   rules applied, nothing listened, and the fix (b66d70b) was deployed minutes later.
4. **Minimum host list: `www.google.com` only.** `consent.google.com` was not needed:
   vps-primary is in the EU, so Google redirects a cookie-less client to
   `consent.google.com`, but SearXNG sends `CONSENT=YES+` and a `SOCS=` cookie, and with
   that cookie vps-primary (direct) and `get` (through the proxy) both get the search
   page with no redirect. `google.com` is allowed as well, untested.
5. **What was not proven.** No request shape reproduced the 429 from `get` without the
   proxy, so these curl tests cannot show that the proxy fixes it, only that Google does
   not block vps-primary's address: a plain request, a `gbv=1` request, and the SearXNG
   Android-app request (`asearch=arc`) all got 200, none the `sorry/index` page. The
   decisive test is SearXNG's own `google` engine with `proxies:` pointing here.

## 4. Operating it

1. Log: `journalctl -u tinyproxy-google` (refused hosts show as "Proxying refused on
   filtered domain").
2. To add a host, add its regex to `allowedHosts` in the module and promote as usual
   (`docs/nixos-in-git.md`); only the proxy unit restarts, the firewall rule is unchanged.
3. If SearXNG gets connection timeouts, check `curl -4 https://ifconfig.me` from the
   microVM: the firewall rule is keyed to that address (`hyadesEgress`).
