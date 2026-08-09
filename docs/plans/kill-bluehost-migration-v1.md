# Kill Bluehost Migration — v1 Plan

**Task workspace**: `~/src/ops-worktrees/kill-bluehost/`
**Branch**: `feature/kill-bluehost` (in site-djbclark, site-private, stayturgid, etc.)
**Handoff dir**: `~/.local/state/handoffs/site-djbclark/kill-bluehost/` (create SESSION_LOG.md after this session)

**Goal**
Fully decommission Bluehost by migrating all websites, databases, DNS, and related services to the Hetzner Linux VPS (`vps-primary` in inventory). Integrate it into the site-djbclark Ansible fleet so it runs the Caddy front-end, LiteLLM (E5), observability stack, and any migrated web apps. Update DNS to point to the VPS (or Cloudflare + VPS). End all Bluehost billing.

**Hetzner Details (saved to memory)**
- Client Number: K0516037826
- Login: djbclark@gmail.com
- Accounts: https://accounts.hetzner.com
- Cloud Console: https://console.hetzner.com

**Current State (verified 2026-08-09)**
- Bluehost account is deleted and unavailable; no cancellation or Bluehost-console step remains possible.
- The audited live sites no longer depend on Bluehost: Maynard Chess is on Miraheze, Maynard Daycare is on Cloudflare Pages, VibeMakerHacks is on WordPress.com, and `dclark.us` is mail-only on Google/DynDNS.
- `vps-primary` is running in Hetzner (`178.105.34.223`, Ubuntu 24.04), but SSH authentication is not currently available and the host is not proven bootstrapped or Ansible-managed.
- The VPS is not required by any currently audited deployed site; VPS bootstrap is deferred as separate infrastructure work.
- The current deployed sites are authoritative. Retained historical material is documented in `~/maynarddaycare-backup/README.md`.

**Historical migration result**
- Migration completed through operational workarounds. Repairing the script was not required for the cutover.
- A repaired, read-only provider health-check remains worthwhile for future domain/VPS automation, but it is not a migration blocker.

**Risks & Dependencies**
- Retained Bluehost/migration archives are historical recovery material; the live deployed sites are the authoritative copies.
- Email migration from Bluehost is no longer a blocker for the audited sites; current Cloudflare Email Routing and Google mail records must be treated as the live configuration.
- Future VPS work requires authorized SSH access and an explicit decision that the VPS is still needed.

## Phase 0: Preparation (this session)
1. Verify Hetzner VPS exists and note its IP, OS, resources (use console).
2. Create SESSION_LOG.md in handoff dir with head_sha, resume plan.
3. Update inventory/hosts.yml with real ansible_host (Tailscale IP preferred) and set `site_host_status: online`.
4. Bootstrap VPS (SSH key, basic hardening, Tailscale if used).
5. Full Bluehost inventory: list all domains, sites, DBs, email forwards/mailboxes (user to provide or screenshot console).
6. Backup everything from Bluehost (files via FTP/rsync, DB exports, full account backup).

## Phase 1: VPS Bootstrap & Fleet Integration
- Extend Ansible roles in site-djbclark to fully manage `vps-primary` (systemd user units for services, Caddy config for new sites).
- Deploy core stack: Caddy (with Tailscale/Let's Encrypt), Vector, OpenObserve, LiteLLM proxy, Grafana, etc.
- Test `just litellm-apply LITELLM_HOSTS=vps-primary` style targeting.
- Add to registry/ports.yml for any new listeners.
- Set up automated backups (restic/Arq to match existing policy).

## Phase 2: Content & Service Migration
- Migrate static sites → Caddy static files or Hugo.
- Dynamic sites → Docker/Podman containers or native (prefer static where possible).
- Databases → PostgreSQL/MySQL on VPS or managed (e.g. Hetzner DBaaS if available).
- Update all internal references (API keys, DB strings) via secretspec.
- Test migrated sites on VPS with temporary DNS (hosts file or private domain).

## Phase 3: DNS Cutover & Verification
- Lower TTLs on Bluehost.
- Update A/AAAA or NS records to VPS IP (or Cloudflare proxy for DDoS protection).
- Verify all sites, email, forms work.
- Monitor with Blackbox exporter / OpenObserve.
- Update any hardcoded Bluehost references in code/docs.

## Phase 4: Decommission
- Cancel Bluehost hosting/domain renewal.
- Transfer domains to preferred registrar (Cloudflare, Hetzner, or Namecheap) if not already.
- Update memory/docs with new architecture (VPS as primary host).
- Coordinated ops-vX.Y.Z release with the changes.

**Next Actions (deferred Priority 3)**
- Decide whether the running Hetzner VPS is still wanted; if yes, obtain authorized SSH access and bootstrap it as a separate infrastructure task.
- Decide whether outbound mail is needed for the domains; add DKIM/stricter DMARC only if required.
- Keep the retained archive in place and use `~/maynarddaycare-backup/README.md` to identify its provenance.

**Success Criteria — migration closure**
- [x] Audited deployed sites no longer depend on Bluehost.
- [x] Current deployed sites are documented as authoritative.
- [x] Historical Bluehost/migration material is retained and documented.
- [x] DNS, HTTPS, redirects, and canonical behavior were independently verified for the in-scope public sites.
- [ ] Optional future VPS bootstrap and provider automation are explicitly separate from migration completion.

See also: site-djbclark/docs/OPS-RELEASES.md for release process, AGENTS.md for worktree rules, and `~/maynarddaycare-backup/README.md` for retained artifact provenance.

*This plan lives in the task workspace. Edit here, PR via normal flow, then deploy with `just ops-release-deploy`.*