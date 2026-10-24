# Inbox split — record (2026-10-23)

Old single Telegram Inbox topic **22158** (chat 838808636) was split into 4 forum topics,
all created 2026-10-23 via the Bot API (createForumTopic + seed message):

| topic  | thread_id | kind                                  | used by                                                              |
|--------|-----------|---------------------------------------|----------------------------------------------------------------------|
| Pings  | 44130     | quiet sink (ignored_threads)          | hermes-ping, fleet-watch, GHA monitors (4), jobber-notify, apk, restart-watcher |
| Watch  | 44132     | quiet sink (ignored_threads)          | health/invariant cron + watchdogs (memory, launchd, tcc, dns, disk)    |
| Digests| 44134     | quiet sink (ignored_threads)          | Gmail x2, session audit, memory curator, Shortwave, weekly research     |
| Triage | 44136     | bound (NOT ignored) — Bedrock Scout   | user pastes content to ask; /bigteam for hard work                     |

Mechanism:
- hermes config.yaml platforms.telegram.channel_overrides['44136'] = {model, provider: goose-scout}
- hermes config.yaml platforms.telegram.extra.ignored_threads = [44130, 44132, 44134]
  (takes effect on gateway restart — requested at end of this session)
- ~/.hermes/cron/jobs.json: all 37 jobs deliver to new thread ids (atomically rewritten)
- Repos retargeted + pushed: site-djbclark (9 files), stayturgid (3 files), site-private docs (2 files)
- ~/.hermes/bin, ~/.hermes/scripts, ~/.hermes/skills/ops/agent-notifications: edited in place (not git)

User archived old Inbox 22158 in Telegram (Delete Topic).

## The pain this exposed
Retargeting the destination thread ID touches ~15 senders across 5 trees + a cron JSON
+ hermes config. Thread IDs are copied literals everywhere. To reorganize again (add a topic,
rename, re-partition) would repeat this scattered multi-repo diff. Requested future design:
a single central register (e.g. one TOML) every sender reads, so a reorg is a one-file change.

## 2026-10-23 late - cleanup pass (post-register)
- jobs.json: 2 stragglers (Gmail index summary, Memory curator) moved 22158 -> Digests 44134.
- config.yaml: ignored_threads += 22158 (safety window to 2026-10-30); backup config.yaml.bak-inboxsplit.
  (Operator must restart the gateway from a Terminal outside it, so ignored_threads loads.)
- site-djbclark master: senders + GHA composite action .github/actions/inbox-send (4 workflows) pushed 3c09c2d.
- Verified GHA route resolution for all 11 routes by sourcing registry/telegram-inbox.env.
- Worktrees retargeted+pushed: feature/secretspec-drift-hardening f496b6b/67365ab; watchdogd f34ec2c.
- Live skills retargeted 5ed2d3a (messaging SKILL/patterns/recipe note, GHA template, ops-scheduling, gateway-log-watchdog).
- Note: that ~/.hermes commit also carried pre-existing uncommitted curator edits in the same files (content preserved).
- setup-modern-cli footgun fixed (djbclark-ade 1cb91a9).

## OPEN ITEMS when this topic was archived (2026-10-24)
1. S5 host-side checks NOT built: no `bin/inbox-check`; `[cron.routes]` in telegram-inbox.toml is
   still an empty placeholder, so cron destinations live only in `~/.hermes/cron/jobs.json`.
   Plan: a read-only `inbox-check config|cron` that asserts jobs.json + config.yaml match the
   register, plus a literal-ID guard flipped from warn to hard-fail in CI.
2. S4 adversary security review never run (the composite action `.github/actions/inbox-send` was
   pushed straight to master; the plan required an adversary verdict because it handles the bot
   token and does a sparse checkout).
3. S6 docs sweep: done for skills/memory/plan doc; `docs/plans/memory-architecture-v2.md` updated
   03ff57e. Any remaining historical mention is narrative, not routing.
4. 2026-10-30: decide whether to drop 22158 from `platforms.telegram.extra.ignored_threads` and
   truly delete the Inbox topic in Telegram.
Refs: plan-central-register.md/central-register-design-report.md (full design + per-slice agents).

## 2026-10-24 - closing the two open slices
- S5 (claude-sonnet-5): bin/inbox-check (config|cron|all, read-only) + tests + justfile
  inbox-check-host + registry_lint --strict with fallback allowlist. Dispatched.
- AD adversary review (omp opus-5-5, judgment high): .github/actions/inbox-send security.
  Dispatched; report to adversary-gha-review.md.
- My own pre-check of the 4 workflows: triggers are schedule/workflow_dispatch only (no
  pull_request / pull_request_target), so `. registry/telegram-inbox.env` is not fork-reachable;
  NONE set `permissions:` (repo default applies) - flagged for the adversary to rule on.
- loose SKILL.md updated (djbclark-ade 32d1dcd): Rule 2 now counts plan items against artifacts.

## 2026-10-24 - slices closed (both open items)
S5 (3790c66): bin/inbox-check (config|cron|all, read-only) + tests (56 pass) + justfile
  inbox-check-host + registry_lint --strict allowlist. Live: config OK, cron OK=34 SKIP=2 WARN=1.
  WARN = f821be766a47 (Funnel Health) delivers to bare `telegram` (DM general topic), not a sink.
AD adversary (omp opus-5-5): VERDICT changes-required. F1 HIGH ${{ }}->run: injection in
  track-issue-activity (pre-existing 90d0dea, but we hand it the bot token); F2 fixed heredoc
  delimiters; F3 unescaped HTML + strict:false + cache-before-send; F4 empty token exit 0;
  F5 jq splice. Verified each claim against the files myself before fixing.
FIX (3acf24b): env-var interpolation, random delimiters (incl. gradle-cache-repin), html.escape,
  strict default, cache-after-send, ::warning::, exit 1 on empty token, jq --arg.
VERIFIED: scheduled run 16:06Z green; workflow_dispatch 40110121894 sent a real message
  ("Telegram accepted the notification."), token masked, STRICT:true, escaped HTML.

## 2026-10-24 - funnel-health route + AD2 re-review
- funnel-health -> watch route added (832d5bd): jobs.json deliver telegram -> 44132 for
  f821be766a47 (job is DISABLED, so this only prevents a future misroute). inbox-check cron now
  OK=35 SKIP=2 WARN=0; no bare-telegram delivery remains.
- AD2 re-review (omp opus-5-5): F1/F2/F4 CLOSED, F5 PARTIAL->fixed, F3 PARTIAL.
  N1 MEDIUM: restore key gh-tracker-v3 vs save key v2 -> track-issue-activity NEVER restored state,
  so scheduled runs never notified (only manual dispatch with notify_even_if_unchanged did). Live
  proof: every cache entry lastAccessedAt == createdAt; run log "Cache not found for input keys:
  gh-tracker-v3-...". Introduced 67a7fe2.
  N2 LOW: herdr dedupe step had no pipefail -> gh failure silently suppressed the alert, green run.
- Fixed e125901: save key v2->v3; herdr step gets set -euo pipefail + non-numeric count guard.
- VERIFIED: seed run 40110775871 wrote gh-tracker-v3-*; second run 40110881267 logged
  "Cache restored from key: gh-tracker-v3-secretspec-64-40110775871"; herdr dispatch 40111121205 green.
- CORRECTION to earlier claim: the hourly monitor was green but had not been sending on schedule.
  Seed captured current state, so no backlog burst; future changes will notify normally.
