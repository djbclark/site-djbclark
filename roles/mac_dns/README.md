# mac_dns — this Mac's tailnet DNS plumbing

Keeps three things in sync with the canonical host facts in
[`inventory/group_vars/all.yml`](../../inventory/group_vars/all.yml)
(`tailnet_magicdns_suffix`, `tailnet_magicdns_nameservers`,
`tailnet_search_domains`):

| What | Where | From |
| ---- | ----- | ---- |
| MagicDNS resolver file | `/etc/resolver/<tailnet_magicdns_suffix>` (`nameserver 100.100.100.100`, …) | `tailnet_magicdns_*` |
| Manual DNS servers | cleared (`networksetup -setdnsservers <service> Empty`) on every service except Tailscale's (`mac_dns_services`/`mac_dns_exclude_services`) | fixed: DHCP only |
| Search domains | `networksetup -setsearchdomains <service> …` on the same services | `tailnet_search_domains` |
| Tailscale OS DNS takeover | `tailscale set --accept-dns=false` | `mac_dns_tailscale_accept_dns` |

Then it probes the real system resolver for `mac.<tailnet>` and `example.com`
and fails the run if either has no answer.

## Why

Tailscale's macOS DNS forwarder has two open upstream bugs:
[tailscale/tailscale#20417](https://github.com/tailscale/tailscale/issues/20417)
(forwarder SERVFAILs every upstream for a whole boot) and
[#21154](https://github.com/tailscale/tailscale/issues/21154) (forwarder
stalls for minutes after a link change). With "Use Tailscale DNS" on, either
one takes down all name resolution on the Mac. The workaround from #20417 is
to let the OS use its DHCP resolvers directly and route only `*.<tailnet>` to
100.100.100.100 through an `/etc/resolver` file. Tailscale then stops
supplying the tailnet search domains, so they are pinned on Wi-Fi.

This was first applied by hand on 2026-10-02 after the Moshi daemon's log
showed ~1-minute DNS outages at ~03:01 on most nights (a Wi-Fi link event) and
a full outage from a stale manual resolver. Hand-applied state drifts; this
role makes `~/ops` the source of truth and re-applies it daily.

## Privilege model

No `become`. The one privileged piece is
[`files/mac-dns-apply`](files/mac-dns-apply), a POSIX `sh` script installed
**root-owned** at `/usr/local/libexec/mac-dns-apply` with a one-line sudoers
rule (`/etc/sudoers.d/mac-dns`, `NOPASSWD` for the operator, that script
only). It validates every argument (domain syntax, IP literals, network
service must appear in `networksetup -listallnetworkservices`), ignores the
environment, and only writes under `/etc/resolver` or via `networksetup`.
Ansible calls it with `sudo -n`, so an unattended run fails closed instead of
prompting. The role also refuses to run if the installed copy differs from the
repo copy, so a change to the script is never half-applied (re-run
`just mac-dns-setup` after editing it).

The applier is further fenced by a root-owned allow-list,
`/etc/mac-dns.allow`, rendered by `mac-dns-setup` from the same `tailnet_*`
facts ([`files/render-allow-list.py`](files/render-allow-list.py)). Every
resolver domain, nameserver and search domain must appear in it verbatim, and
`dnsservers` accepts only `Empty`. So the NOPASSWD rule can reproduce exactly
the declared tailnet configuration and nothing else: no other resolver file,
no other nameserver, no other search domain, no manual DNS servers. Changing
the facts in `group_vars` therefore requires one `just mac-dns-setup` (Touch
ID) to re-render the allow-list; the role refuses to run until it matches.

Residual risk after that: an attacker with local code execution as the
operator can re-apply the already-declared config, or remove the tailnet
resolver file. Neither redirects traffic.

## Commands

```bash
just mac-dns-setup    # Touch ID: install root-owned applier, sudoers rule, allow-list (re-run after editing those or the tailnet_* facts)
just mac-dns-check    # ansible --check: shows would-change without touching anything
just mac-dns-apply    # converge (what Jobber runs daily at 03:30)
just mac-dns-status   # files, search domains, accept-dns, live probes
```

Schedule: `mac-dns-apply` in the Jobber config rendered by `site_agents`
(`roles/site_agents/templates/jobber.yaml.j2`), `0 30 3 * * *`, failures go to
`jobber-notify` (macOS banner + Telegram).

## Revert

Set `mac_dns_tailscale_accept_dns: true`, `tailnet_search_domains: []`, run
`just mac-dns-apply`, then `sudo /usr/local/libexec/mac-dns-apply
resolver-remove <tailnet>` (or `sudo rm /etc/resolver/<tailnet>`). Remove
`/etc/sudoers.d/mac-dns` and the applier if the role is retired.

## Every service, not just Wi-Fi

The role enumerates `networksetup -listallnetworkservices` on each run, so a
newly plugged-in adapter (a new USB NIC, an iPhone tether) gets the same
settings the next time it converges. Manual DNS servers are cleared on all of
them: the 2026-10-02 outage was a hand-set `10.128.0.1` on five services,
unreachable from this LAN, and the copy on the Tailscale service won for every
lookup. The Tailscale service itself is excluded because the extension owns
that service's DNS state; a manual entry on it is the failure mode.

DHCP-provided DNS is the only setting that follows the Mac between networks,
so the applier accepts nothing else. If a fixed resolver is ever genuinely
wanted, extend `files/mac-dns-apply` and re-run `just mac-dns-setup`.
