# SearXNG egress proxy on vps-primary (Hyades shared IP)

Decided by djbclark 2026-10-16 (Google-only); widened 2026-10-22 to every engine the
firecrawl-searxng image enables. Every Hyades microVM leaves through one shared address
(`hyades.mit.edu`, 18.4.60.84). Module: `nixos/modules/google-proxy.nix` (unit still named
`tinyproxy-google` for continuity). Peer leg: pastebin.xvm:26370. Full design and
instrumentation: firecrawl-hyades [`docs/searxng-egress.md`](https://forgejo.mit.edu/djbclark/firecrawl-hyades/src/branch/main/docs/searxng-egress.md).

**Status (2026-10-22):** allowlist covers Google CSE, Bing, Yahoo, DuckDuckGo, Wikipedia,
Wikidata, Grokipedia, and the enabled !shortcut hosts. SearXNG sets
`outgoing.proxies.all://` to both legs (round-robin) via `SEARXNG_EGRESS_PROXIES`. Plain
`google` stays off (403 everywhere; searxng#6835). `fleet-watch vps` still alerts if
`tinyproxy-google` stops.

**Return path (2026-10-22; GlobalProtect removed 2026-10-23):** GlobalProtect (`tun0`)
used to own `18.0.0.0/8` here, which stole replies to Hyades (`18.4.60.84`) and
blackholed Hyades→`178.105.34.223` while neighbors in the same `/24` still worked.
GP was removed everywhere on 2026-10-23: the tailnet now reaches MIT 18.0.0.0/8 through a
Tailscale subnet route on pastebin.xvm.mit.edu (100.104.212.89); vps-primary cannot reach
MIT at all and is only an exit node. Unit `hyades-public-return-path` still policy-routes
`from $publicIp` via `enp1s0` (table 100) as a guard should any 18/8 route return; it is a
no-op without one. On pastebin (the other egress leg), restarting nftables drops
Tailscale's rules: restart tailscaled right after it.

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
4. **Minimum host list at deploy time: `www.google.com` only** (`cse.google.com` was added
   later for the `google cse` engine, see the status note at the top). `consent.google.com` was not needed:
   vps-primary is in the EU, so Google redirects a cookie-less client to
   `consent.google.com`, but SearXNG sends `CONSENT=YES+` and a `SOCS=` cookie, and with
   that cookie vps-primary (direct) and `get` (through the proxy) both get the search
   page with no redirect. `google.com` is allowed as well, untested.
5. **What was not proven.** No request shape reproduced the 429 from `get` without the
   proxy, so these curl tests cannot show that the proxy fixes it, only that Google does
   not block vps-primary's address: a plain request, a `gbv=1` request, and the SearXNG
   Android-app request (`asearch=arc`) all got 200, none the `sorry/index` page. The
   decisive test is SearXNG's own `google` engine with `proxies:` pointing here.
   **Answered 2026-10-16:** the plain `google` engine gets 403 through the proxy too (it
   does from every address), and `google cse` through the proxy works (SearXNG r5, its
   CONNECTs in this unit's journal, no Google errors in SearXNG's log); see the status note.

## 4. Operating it

1. Log: `journalctl -u tinyproxy-google` (refused hosts show as "Proxying refused on
   filtered domain").
2. To add a host, add its regex to `allowedHosts` in the module and promote as usual
   (`docs/nixos-in-git.md`); only the proxy unit restarts, the firewall rule is unchanged.
3. If SearXNG gets connection timeouts, check `curl -4 https://ifconfig.me` from the
   microVM: the firewall rule is keyed to that address (`hyadesEgress`).

## 5. Since 2026-10-24: reached through pastebin over the tailnet

1. **What broke.** From 2026-10-23 13:39 UTC nothing sourced inside MIT arrives at `178.105.34.223`: Hyades' SYNs, pings and
   TCP from pastebin.xvm never show up in `tcpdump -i enp1s0` on this host, while ICMP from three check-host.net nodes does.
   `traceroute` from pastebin dies right after MIT's border router `18.0.161.1`, while `178.105.0.1` (same Hetzner /16) is
   reached via `18.0.161.18` and Lumen. The firewall (`nixos-fw` accepts `18.4.60.84`), the listener, `rp_filter` (loose) and
   the table-100 return rule were all checked and correct. It is a route or filter for this address at or beyond MIT's border.
2. **What the module does now.** `tinyproxy-google` also listens on this host's tailnet address (it waits up to 30 s for it at
   boot and exits, so systemd retries, if there is none) and `Allow`s pastebin's tailnet address `100.104.212.89`
   (`relayPeer`). Hyades reaches it as Hyades → pastebin `:26371` (`tinyproxy-vpsrelay`, firecrawl-hyades
   `scripts/install-pastebin-egress-proxy`) → tailnet → here, so every request still leaves from this address. The allowlist
   is enforced at both hops. **No iptables rule guards the tailnet path:** tailscaled's `ts-input` chain accepts everything on
   `tailscale0` before `nixos-fw` (`iptables -S ts-input`: `-A ts-input -i tailscale0 -j ACCEPT`), so the gates are WireGuard
   source authentication, tinyproxy's `Allow` (tailnet peers other than pastebin get 403) and the tailscale ACL. To tighten:
   allow only `100.104.212.89` to reach this host on `tcp/26369` in the tailnet policy (admin console). The rate limit the
   public rule applies to Hyades (40 new connections/s per source) therefore does not apply on this path; the same limit is
   enforced on pastebin's nftables rule for `:26371` instead.
3. **Restoring the direct path** by MIT fixing the route to `178.105.34.223` would need nothing else on this host (the public
   listener and the `18.4.60.84` rule are untouched).
4. **The fix that worked, 2026-10-24 evening: a second public address.** MIT's border drops traffic to and from
   `178.105.34.223` only; a Hetzner Floating IPv4, `78.47.225.34` (id 157592860, nbg1, 3.50 EUR a month, created through the
   Hetzner Cloud API with `HETZNER_CLOUD_TOKEN`), is reachable from MIT. The module's `floatingIp`: `hyades-public-return-path`
   puts it on `enp1s0` (Hetzner routes it here but does not configure it) and gives it the same source rule as the primary
   address (without it, replies to 18/8 follow the tailnet subnet route and vanish), and `tinyproxy-google` listens on it.
   Hyades connects to `http://78.47.225.34:26369` directly, so the pastebin relay and the tailnet hop are no longer needed
   (the relay stays as a spare). Outgoing requests still leave from the primary address. Undo: `DELETE
   /v1/floating_ips/157592860` and remove `floatingIp`. Details and the fallback plan: firecrawl-hyades `docs/rendezvous-plan.md`.
