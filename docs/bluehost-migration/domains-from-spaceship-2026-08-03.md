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
| `dclark.us` | Mail-only Google configuration; no web A/AAAA record | Spaceship / DynDNS | Live mail DNS; no website migration required unless scope changes |

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
- `dclark.us`: DynDNS nameservers, Google MX, SPF, and DMARC are live; no web
  host is configured.

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
