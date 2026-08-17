# Research brief: unattended continuous AI coding — what OSS should we adopt?

You are being asked for a RESEARCH ANSWER, not code. Use web search
aggressively. Cite GitHub URLs. Today is 2026-08-16. Say plainly when you
do not know something rather than guessing.

## The situation

A solo developer wants AI coding agents to work on his repos CONTINUOUSLY
and UNATTENDED — for hours or days — without a human performing manual
restart rituals.

The wall he keeps hitting: any long-lived LLM orchestrator eventually
exhausts its context window. His current workaround is a manual ritual
(write a handoff doc, quit, relaunch, re-brief, continue). He tried adding
a supervisor LLM above the orchestrator; that supervisor also runs out of
context. Stacking another supervisor is obviously an infinite regress.

He is willing to THROW AWAY every piece of bespoke local tooling he has
built and replace it with well-maintained open source. Do not recommend
"write your own script." Assume greenfield.

## Hard requirements

1. **Actively maintained open source with a real community.** Commits in
   the last ~60 days, multiple contributors, real releases. A clever repo
   with one author and no commits since spring is a NON-answer. Explicitly
   flag anything abandoned, archived, or vaporware.
2. **Subscription quota, not metered API billing.** He runs on flat-rate
   vendor subscriptions with ROLLING USAGE WINDOWS (e.g. 5-hour and 7-day
   caps). Running out of quota mid-loop is as real a failure as running out
   of context, and a fresh session does NOT fix a capped account. Tools that
   assume pay-per-token API keys and just retry are a poor fit. Quota-aware
   pacing / backoff / multi-account rotation is a major plus.
3. **Terminal-native, self-hosted, local-first.** macOS. Not a SaaS that
   wants his source code uploaded. Self-hostable is fine.
4. **Multi-vendor agent support is a plus.** He has Claude Code, Codex,
   Gemini CLI, Grok, Cursor CLI, OpenCode installed and rotates between them
   for quota reasons.
5. **Unattended execution, human-gated integration.** He does NOT want
   per-action approval prompts. He DOES want work to land as PRs he reviews.
   Safety comes from tightly-scoped task definitions, not a human watching
   every tool call.
6. **Multi-repo.** Several independent git repos, git worktrees for
   isolation of parallel work.
7. **Verifiability.** He distrusts agent self-reports — he has been burned
   by clean exit codes on wrong work and by "INTERRUPTED" statuses on work
   that actually succeeded. Independent verification of what an agent
   ACTUALLY did (tests, diffs, tracker state) matters more to him than a
   pretty status UI.

## What to answer

For each candidate project:
- Name + GitHub URL + license
- What it actually does, in two sentences
- **Maturity signals**: stars, last commit, contributor count, release
  cadence, whether a company or an individual is behind it
- **How it handles context exhaustion.** This is the crux. Fresh context per
  iteration? Compaction? Structured handoff files? Something else?
- **Is the thing that never dies a PROGRAM or an LLM?** Be specific.
- Where durable state lives (files, git, issue tracker, database)
- Quota / rate-limit awareness, if any
- Multi-vendor agent support, if any
- Honest weaknesses and who it is a bad fit for

Then:
- What is the DOMINANT architectural pattern for this problem as of Aug
  2026? Has anything gone out of favor?
- What genuinely does NOT exist yet — where would he still have to build
  something himself?
- Your top 3 recommendations, ranked, with reasoning.

Be skeptical and concrete. Prefer projects you can actually verify exist.
Do not pad the list with things you are unsure about — mark uncertainty
explicitly instead.
