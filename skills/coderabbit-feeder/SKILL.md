---
name: coderabbit-feeder
description: >-
  Queue a CodeRabbit review request (attach mode for a PR on a repo djbclark
  owns, crossfork mode for one he doesn't) instead of hand-rolling throwaway
  PRs. Use when an agent needs a CodeRabbit review and CodeRabbit isn't
  installed on the target repo, or on "queue a coderabbit review", "use the
  feeder".
---

# coderabbit-feeder

## What it's for

Gets CodeRabbit reviews of source files djbclark owns or has a fork of,
working around two constraints: CodeRabbit's GitHub App is only installed
on repos djbclark owns (so it can't review a PR on someone else's repo),
and CodeRabbit's own rate limits (check the current plan and
`state.json`'s rate-limit fields before assuming how fast the queue drains).

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

## Where the queue lives (check before adding to it)

The launchd job `com.djbclark.coderabbit-feeder` runs

```
/opt/homebrew/bin/uv run --project /Users/djbclark/src/coderabbit-feeder coderabbit-feeder tick
```

with `WorkingDirectory` `/Users/djbclark/.config/coderabbit-feeder`. The package
resolves `queue.jsonl` and `state.json` from the current directory, so run every
`coderabbit-feeder add|list|...` from `~/.config/coderabbit-feeder`, or with
`uv run --project ~/src/coderabbit-feeder` from there. Never use
`uv run --directory ~/src/coderabbit-feeder`: it changes the working directory
and writes a queue the daemon never reads.
Before trusting the queue, read the plist: if it shows a direct
`python3 .../feeder.py` call instead of the `uv run --project ... tick` line
above, the old standalone script is back; report that instead of queueing.

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
the behavioral/gotcha layer on top of it.
