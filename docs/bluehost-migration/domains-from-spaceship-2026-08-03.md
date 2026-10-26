# Domain inventory and live disposition

Updated: 2026-08-09. This supersedes the 2026-08-03 browser capture as the
current migration record. The old capture listed only domains visible in
Spaceship and did not establish the complete hosting inventory.

## Current public domains

| Domain | Current live disposition | Registrar / DNS | Status |
|---|---|---|---|
| `maynardchess.club` | Miraheze MediaWiki canonical site | Spaceship / Cloudflare | Complete; HTTPS, DNS, branding, content, media, and permissions verified |
| `maynarddaycare.com` | Cloudflare Pages static site | Spaceship / Cloudflare | Complete; HTTPS, `www` redirect, and canonical tags verified |
| `maynard.wiki` | Redirects to `maynardchess.club` | NameCheap / Cloudflare | Complete; intentional legacy redirect |
| `chess.maynard.wiki` | Redirects to `maynardchess.club` | NameCheap / Cloudflare | Complete; intentional legacy redirect |
| `vibemakerhacks.com` | WordPress.com site | Spaceship / WordPress.com DNS | Live; not on Bluehost and not part of the VPS migration |
| `dclark.us` | **Mail (Google) plus a small set of hostnames** — see the zone table below | Spaceship / **DynDNS** | Live; mail verified intact 2026-10-25. **NOT mail-only**: it carries 14 A records and 5 Google CNAMEs |

## Live checks recorded 2026-08-09

- `maynardchess.club`: Cloudflare nameservers, Cloudflare Email Routing MX,
  SPF, HTTPS, and canonical site behavior are live.
- `maynarddaycare.com`: Cloudflare nameservers, Cloudflare Pages binding,
  Cloudflare Email Routing MX, SPF, DMARC, HTTPS, and apex canonicalization are
  live. `www` redirects to the apex with paths and query strings preserved.
- `maynard.wiki` and `chess.maynard.wiki`: both redirect to the canonical
  Maynard Chess domain.
- `vibemakerhacks.com`: WordPress.com nameservers, apex HTTP 200, `www` 301 to
  apex, SPF, and DMARC are live.
- `dclark.us`: DynDNS nameservers, Google MX, SPF, DMARC and DKIM are live. **This line
  used to say "no web host is configured", which was wrong** — see the correction below.

## `dclark.us` zone — CORRECTED 2026-10-25

**The 2026-08-09 record above was wrong in two ways, and the error mattered.** It described
`dclark.us` as "Mail-only Google configuration; **no web A/AAAA record**". In fact the zone carried
an A record at the apex (`10.0.0.25`) plus `www` and `mail` — and `10.0.0.25` is an RFC1918
**private** address published in public DNS, which is the DNS-rebinding pattern and left those names
unreachable from the internet. `mail.dclark.us` was also recorded as an A record when it is a
**Google CNAME** (`ghs.googlehosted.com`).

**How the error was made, recorded so it is not repeated:** the original check used `dig` **without
an `@server`**, i.e. it read a recursive resolver's cache rather than the zone's authoritative
nameservers. A cached answer can be stale for its whole TTL and beyond. **Query the authoritative
nameserver for any zone you are about to describe or change.**

**Verified against the authoritative server (`ns2164.dns.dyn.com`), 2026-10-25, after a cleanup that
removed 26 A records, 6 CNAMEs and 2 redirects:**

| Name | A | Notes |
|---|---|---|
| `dclark.us` (apex) | `148.113.151.85` | the `dann` host (OVH); **no service on 80/443 yet** |
| `dann` | `148.113.151.85` | the entity's host |
| `keeper` | `148.113.151.85` | alias for the same host |
| `vps-primary` | `178.105.34.223` | Hetzner, shared agent infrastructure |
| `pastebin` | `18.25.134.227` | MIT XVM |
| `mac` | `209.177.145.97` | this Mac, via Tailscale Funnel |
| `athena` | `18.9.64.17` | MIT |
| `freedo` | `18.214.0.239` | |
| `loongson2f-1` | `18.214.0.170` | |
| `pika` | `18.214.0.179` | |
| `x220` | `18.214.0.171` | |
| `lates.pika` | `18.214.0.83` | |
| `subtlety.pika` | `18.214.0.85` | |
| `admin` | `132.226.44.1` | Oracle Cloud; behind a Dyn **redirect** to admin.google.com |
| `defeat` | `192.168.0.106` | **private address, deliberate** — internal-only name |

**CNAMEs (all Google):** `cal`, `docs`, `mail`, `sites` → `ghs.googlehosted.com`;
`mjdajtbfsbmw` → `gv-6ig4fhbbruownc.dv.googlehosted.com` (site verification);
`conference.athena` → `athena.dclark.us`.

**Mail (verified intact 2026-10-25):** five Google MX (`aspmx.l.google.com`, `alt1`–`alt4`),
SPF `v=spf1 include:_spf.google.com ~all`, DMARC `p=quarantine` with
`rua=mailto:postmaster@dclark.us`, and the `google._domainkey` DKIM record.

**No `www` record exists** (deliberate), and `kev`/`laya`/`home` are absent — the Hyades microVMs
cannot use custom names because Hyades' Caddy serves only `*.sipb.cloud`.

**Editing the zone:** Dyn's key here is a **client-updater** key — it can change the IP of an
**existing** hostname but **cannot create one** (`nohost` = "not in this account"). New hostnames are
made in the Dyn panel. The tool is `~/ops/site-djbclark/bin/dyn-update.py` (run under
`sudo-secretspec run`; it refuses non-public IPs and checks DNS first to avoid an abuse-triggering
`nochg`). **Panel/UI work on this zone goes to Eve's "One-offs" Grok Bot**, which drives the UI
directly — do not ask Eve to relay it onward.


## Migration conclusion

No audited public site currently depends on Bluehost. Bluehost is deleted and
unavailable, so the old request to inventory the Bluehost console cannot be
completed retrospectively. Retained files and their provenance are documented
in `~/maynarddaycare-backup/README.md`; the deployed sites are authoritative.

The Hetzner VPS is a separate deferred infrastructure project. It is running,
but the current sites do not require it.

## Historical Spaceship capture

The 2026-08-03 capture recorded these domains in the Spaceship manager:

- `maynardchess.club` — expiration May 2, 2027
- `vibemakerhacks.com` — expiration May 2, 2027
- `dclark.us` — expiration April 5, 2028

That capture was a registrar view, not a complete list of every active DNS
zone or historical domain. `maynarddaycare.com` and `maynard.wiki` were verified
separately through live DNS and registry checks.
