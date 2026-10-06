---
name: coderabbit-feeder
description: Queue a CodeRabbit review request (attach mode for a PR on a repo djbclark owns, or crossfork mode for a PR on a repo he doesn't) instead of hand-rolling throwaway PRs or triggering CodeRabbit directly. Use when an AI orchestrator/agent needs a CodeRabbit review and CodeRabbit isn't installed on the target repo, or when told to "queue a coderabbit review", "use the feeder", or "add to coderabbit-feeder".
---

# coderabbit-feeder

Written 2026-08-02, the same day this project split out of a single
`~/.config/coderabbit-feeder/` script, and the split-brain problem
described below (dev repo vs. live daemon disagreeing) was fixed the
same day too — see "Migration status" for the resolved state and how to
re-verify it hasn't regressed.

## What it's for

Gets CodeRabbit reviews of source files djbclark owns or has a fork of,
working around two constraints: CodeRabbit's GitHub App is only installed
on repos djbclark owns (so it can't review a PR on someone else's repo),
and CodeRabbit's own rate limits (a Pro+ trial being drained on purpose,
was showing 298 consecutive rate-limited attempts as of 2026-08-02, with
the trial itself expiring 2026-08-03 — check current trial/plan status
before assuming any of this still applies).

Three modes (per `~/src/coderabbit-feeder/README.md`, the source of truth
for how each mode is *supposed* to work):

- **attach**: an existing PR on a repo djbclark owns — just labels it and
  triggers `@coderabbitai review`.
- **originate**: `build_queue.py` walks `repos.toml`, chunks a repo's own
  tracked files into ≤300-file batches, opens throwaway PRs for each.
- **crossfork**: a PR on a repo djbclark does **not** own (e.g. a PR from
  his fork against upstream). CodeRabbit can't see that PR at all, so this
  mode clones djbclark's fork, opens a twin PR entirely inside the fork
  with the identical diff, gets CodeRabbit to review the twin, then relays
  the findings as a comment on the real PR and closes the twin without
  merging. This is the pattern the ops-djbclark Shizuku-API work needed.

## Migration status: resolved 2026-08-02, verified end-to-end

The split-brain problem this section used to warn about (dev repo and
live daemon disagreeing) is fixed. History, in case it's useful context
or the fix ever regresses:

**What was wrong**: the live `com.djbclark.coderabbit-feeder` launchd job
ran the old standalone `~/.config/coderabbit-feeder/feeder.py` directly —
no `mode` concept at all, `queue.jsonl`/`state.json` resolved via
`Path(__file__).parent` (cwd-independent). The new package
(`~/src/coderabbit-feeder`) resolves `ROOT` via `Path.cwd()` instead. The
README's own documented invocation,
`uv run --directory ~/src/coderabbit-feeder coderabbit-feeder add ...`,
silently wrote into the dev repo's own `queue.jsonl` — `uv run --directory X`
actually changes the process cwd to `X` (confirmed via `os.getcwd()`) — a
file the live daemon never read.

**The fix**: `uv run --project X` (not `--directory X`) discovers the
project at `X` for dependency/venv resolution **without** changing cwd
(confirmed: `os.getcwd()` still reports the caller's real cwd). The
launchd plist now runs:

```
/opt/homebrew/bin/uv run --project /Users/djbclark/src/coderabbit-feeder coderabbit-feeder tick
```

with `WorkingDirectory` set to `/Users/djbclark/.config/coderabbit-feeder`
— so the new code runs, but `queue.jsonl`/`state.json` stay exactly where
they always were, no data migration needed. Also fixed while cutting over:
a stuck entry (`stayturgid-batch-0001`, PR #203, 299 consecutive
rate-limited attempts against a PR that had actually already been closed
manually outside the tool) was marked `"done"` and `state.json`'s stale
tracking fields were cleared, so the queue could actually progress.

**Verified live**, not just a clean exit code: manually triggered
(`launchctl start com.djbclark.coderabbit-feeder`), confirmed in
`launchd.out.log` that it picked up the next pending entry
(`stayturgid-batch-0002`) and opened a real PR
(`djbclark/stayturgid#212`), and confirmed via
`coderabbit-feeder list` (run from `~/.config/coderabbit-feeder`, matching
the daemon's own `WorkingDirectory`) that the queue state advanced
correctly.

**Before trusting any of this in a future session**: re-verify it hasn't
drifted — `cat ~/Library/LaunchAgents/com.djbclark.coderabbit-feeder.plist`
should still show the `uv run --project ... coderabbit-feeder tick`
invocation above, not a direct `python3 .../feeder.py` call. If someone
reinstalls/edits the plist back to the old form, this whole section goes
stale again.

## Shared responsibilities (from the README, written for AI orchestrators)

- **The feeder handles**: rate-limit backoff (5-minute wait loop, checks
  `state.json`'s `consecutive_rate_limited`/`retry_after_epoch`), opening
  scratch/twin PRs, posting the trigger comment, harvesting findings.
- **You (the orchestrator) handle**: deciding a review is actually needed
  (don't spam the queue with redundant requests for the same PR), whether
  to use `--front` (genuinely urgent/blocking) vs. default `--back`
  (can wait — this is explicitly your call to make, not the feeder's), and
  — for crossfork specifically — actually reading `findings/<id>.md` and
  applying fixes to the real PR's branch yourself; the feeder relays
  findings as a comment but never auto-commits fixes onto the real PR.

## Reference

Full command docs and the crossfork queue-entry JSON shape:
`~/src/coderabbit-feeder/README.md`. Don't duplicate that content here —
re-read it fresh each time in case it's changed, and treat this skill as
the behavioral/gotcha layer on top of it (same split as the
`herdr-orchestration` skill vs. `herdr`'s own docs).
