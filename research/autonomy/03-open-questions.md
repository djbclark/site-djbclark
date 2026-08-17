# Open questions — your work list

Ordered by how much they change the recommendation. Nothing below was
settled by the prior session. **Nothing in this package was tested
hands-on** — the entire prior sweep is documentation reading plus GitHub API
verification. That is the single biggest gap.

## Q1. Is `ralph-orchestrator` actually what its README says? (highest value)

Two independent AIs ranked it #1 on the strength of its *stated*
architecture. Nobody ran it. Given the operator's culture (see
`01-...md` — he mutation-tests his own tests), a recommendation resting on a
README is not good enough.

Verify hands-on, in a throwaway repo:
- Does `--backend` genuinely rotate among the CLIs he has installed
  (Claude Code, Codex, Gemini, Grok, Cursor, OpenCode)? Grok explicitly
  refused to claim Grok/Cursor are supported backends without testing.
  Cursor listed Cursor/Grok support as "unverified".
- Is each iteration genuinely a **fresh process with a fresh context**, or
  does it resume a session anywhere? (`frankbria/ralph-claude-code` defaults
  to `--resume`, which is the anti-Ralph choice — check for the same trap.)
- Do the backpressure gates actually reject work? **Test by mutation:** make
  a task whose output fails the test command and confirm the loop refuses to
  advance. A gate that never fires is indistinguishable from no gate.
- Is the beads integration real or aspirational?
- What happens on machine sleep / SSH drop / reboot?

Repo: https://github.com/mikeyobrien/ralph-orchestrator

## Q2. Is the solo-maintainer risk acceptable, and what is the fallback?

`ralph-orchestrator` is 457 commits from one author, 16 from the next. It
fails the operator's stated "real community" bar, and it is nonetheless the
consensus #1. That tension needs an explicit answer, not a shrug.

Cursor's framing was: if the author stops, you have an MIT Rust codebase and
beads still works — a better failure mode than a SaaS. Is that good enough?
What is the concrete fallback — fork, or swap in which alternative?

Consider whether a *less* ideal but *better maintained* option wins on this
axis: `OpenHands` (84k, institutional) or `paperclip` (78.5k, company-backed,
heartbeat-based ticket claiming, Postgres) — both were rated real communities
but neither is terminal-native-plus-subscription-shaped. Note `paperclip`'s
budgets are **dollars, not rolling windows**, and it is aimed at business
teams rather than coding specifically.

## Q3. Settle Maestro vs. ralph-orchestrator with evidence

The prior session first picked `RunMaestro/Maestro` (it has the only verified
subscription-aware wait), then withdrew in favour of `ralph-orchestrator`
after Grok and Cursor both ranked it first. The reasoning given was: *you can
bolt a quota sleep onto a loop more easily than you can bolt real
verification onto one.* That is plausible, not proven.

Against Maestro: AGPL-3.0 (a real constraint if ever vendored), Electron-first,
no Gemini backend, **its Auto Run loop controller does not survive restart**,
and its goal-run progress is self-scored — the exact self-report he distrusts.
For Maestro: fresh session per task is documented rather than implied,
worktree dispatch plus auto-PR is the integration gate he wants, and
`maestro-cli` exists for cron.

Decide it, and say what evidence decided it.

## Q4. Design the verification judge — nobody shipped it

This is the operator's own manual protocol and the gap both external AIs
independently named. It is probably the highest-leverage thing to build,
*because* it is the one piece of local knowledge worth keeping.

Spec sketch: after each iteration, a small program that reconciles
  (a) the tracker (`bd show <id>` — closed? real close reason?)
  (b) the git range for that iteration (`git diff`, actual files touched)
  (c) the test/CI log
and **refuses to mark the unit done if those three disagree** — without ever
asking the agent "did you finish?"

Answer: does this belong inside the loop as a backpressure gate, as a
post-hoc auditor, or as a CI check on the PR? Is there anything OSS that gets
closer than `ralph-orchestrator`'s backpressure or gastown's refinery? Give
him a concrete design he can implement in an afternoon, or a project that
already does it.

## Q5. The quota glue — minimal design

Cross-vendor rolling-window pacing does not exist (see `02-...md` §5). He
will have to write thin glue. Specify it:
- Should it wrap the loop (a supervisor that pauses the whole thing) or live
  inside it (a pre-iteration check)?
- Read from `cswap list` — **not** `aiuse --json`, whose `conserve` alert is
  a pace projection. Note `cswap` percentages are percent USED, auto-rotation
  is deliberately DISABLED, and only `djbclark@gmail.com` has Fable.
- Is failing over to a different *vendor* (Codex/Gemini/Grok) on a Claude cap
  actually desirable, or does the model change break task continuity?
- Is `razzant/claudexor` worth adopting despite being one person, or worth
  reading for its design (`oauth/usage` polling, credential profiles,
  "continuation packet") and reimplementing in 100 lines?

## Q6. Multi-repo strategy

He has several independent repos. beads is per-repo; federation exists but is
not simple. gastown is natively multi-repo but decelerating and re-imports
the LLM-coordinator regress. `thrashr888/AllBeads` looked early.

Options to weigh: N independent loops (one per repo, simplest), beads
federation, gastown's program half, or `github/gh-aw` pushing the work into
GitHub Actions per repo.

## Q7. Where does work land?

`github/gh-aw` (GitHub-maintained, 1517 commits/4wk) compiles Markdown +
YAML agentic workflows into Actions, and its **"safe outputs"** design —
agent runs read-only, writes are buffered, validated, and applied by a
separate scoped job — is his *unattended execution, gated integration* rule
enforced mechanically rather than by convention.

The catch: it runs on Actions runners, so it bills Copilot/API rather than
his local flat-rate subscriptions — which cuts against requirement #2.
Releases 0.68.4–0.71.3 were retired over billing bugs.

Is it worth it for some repos and not others? Or does it lose on quota?

## Q8. Fresh research — what did the panel miss?

The sweep was broad but not exhaustive, and one source used
(`bradAGI/awesome-cli-coding-agents`, `andyrewlee/awesome-agent-orchestrators`)
lists dead and one-author projects identically to live ones. Do not trust
awesome-lists without applying the maturity test in `02-...md`.

Specifically worth a fresh look:
- Anything published in the last ~6 weeks that post-dates the panel.
- `the-open-engine/zeroshot` (planner / implementer / **independent
  validator**, looping until verified) — the "independent validator" framing
  maps directly onto Q4 and was never investigated.
- `getpaseo/paseo` (13.9k, self-hosted daemon running agents in parallel,
  very active) — surfaced early, never examined.
- Whether `beads` migrating its storage to Dolt (from SQLite+JSONL) is an
  operational tax worth caring about. `Dicklesworthstone/beads_rust` froze
  the older SQLite architecture (1052 stars, effectively solo).

## Deliverable

A ranked plan with the actual adoption sequence, the risks, the fallback for
each, and an explicit list of what you verified hands-on versus what you are
still taking on documentation. He would rather have three honest options with
their failure modes than one confident recommendation.
