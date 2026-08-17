# Mission: choose the OSS stack for unattended continuous AI coding

> **RESOLVED 2026-08-16:** the final plan is in
> [`04-final-plan.md`](04-final-plan.md) — including the hands-on Q1 test
> results (ralph-orchestrator's marketed backpressure is self-report; its
> hooks are a real gate) and the fresh-sweep findings (zeroshot, Kiro Crew).

**You are Claude Fable 5. Read this file first, then the numbered files, then
the `panel/` raw answers. Produce a final plan for the operator (djbclark).**

Prepared 2026-08-16 by a Claude Opus 5 session in `~/src/tendcf` that has
now ended. Everything that session verified is in `02-verified-findings.md`.
Do not re-derive what is already verified there — extend it.

## The question

What is best practice for letting AI work on code continuously without human
intervention, and **which existing, actively-maintained open-source projects
should the operator adopt** to do it?

The operator explicitly does NOT want a bespoke in-house solution. He is
willing to throw away every piece of local tooling he has built. He wants to
land on things that are well-loved and actively maintained by real
communities.

## What you are asked to deliver

A **final plan / set of options**. Not an essay. Concretely:

1. A ranked recommendation with the actual adoption sequence (commands,
   repos, config decisions).
2. The honest risks of each option and what the fallback is if it fails.
3. A decision on each open question in `03-open-questions.md`.
4. Whatever new research changes the picture — the prior session's sweep was
   good but not exhaustive, and it explicitly did NOT do hands-on testing.

## Read in this order

| File | What it is |
|---|---|
| `01-requirements-and-local-context.md` | The operator's hard requirements, his working style, and what is being thrown away (and the one thing to keep) |
| `02-verified-findings.md` | GitHub-API-verified maturity data + every correction made during the session. **Highest-trust document here.** |
| `03-open-questions.md` | What was NOT settled. This is your work list. |
| `panel/research-brief.md` | The brief given to three external AIs |
| `panel/grok-answer.md` | Grok's 22KB answer — most current and skeptical of the three |
| `panel/cursor-answer.md` | Cursor's 20KB answer — converged independently with Grok |
| `panel/gemini-answer.md` | Gemini's answer — **stale numbers and one central false claim**, kept for completeness. Treat with suspicion; see corrections in `02`. |

## Method notes that matter

- **Star counts lie.** Two 24k+-star projects in this space are corpses. The
  prior session's test was: default-branch last commit date (`gh api
  repos/X/commits?per_page=1`) plus contributor distribution (`gh api
  repos/X/contributors`) — several high-velocity repos turn out to be one
  human plus bots. Use the same test on anything new you find.
- **`pushed_at` is not a liveness signal** — it fires on tags and non-default
  branches. Use the default-branch commit date.
- Three of five AI researchers produced usable work. **Codex died mid-run
  having hit its usage limit** — which is itself a data point about the
  problem being solved.

## Practical constraints on you

- Quota: the operator runs two cswap-managed Claude accounts. **Only
  `djbclark@gmail.com` has Fable.** Check with `cswap list` before any
  heavy run; percentages shown are percent USED. The 5-hour window is
  usually the binding constraint, not the 7-day.
- You are running at **xhigh** effort, chosen over max deliberately to
  conserve the 5h window for the operator's real work.
- Do NOT use `aiuse --json` for quota decisions — its `conserve` alert is a
  pace projection, not a real window reading. Use `cswap list`.
