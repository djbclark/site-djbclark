# Verified findings

All GitHub data below verified via `gh api` on **2026-08-16**. This is the
highest-trust document in this package. Where something was relayed rather
than verified, it says so explicitly.

## The architectural conclusion (all researchers converged)

> The component that never dies must be a **program**. It starts a **fresh
> agent** on one tightly-scoped unit of work, persists progress to files /
> git / an issue graph, verifies with something outside the model's mouth,
> then repeats.

Two named anti-patterns:
- **One immortal chat + auto-compact.** Context rot arrives before the hard
  window does.
- **A supervisor LLM above an orchestrator LLM.** This is the operator's
  infinite regress.

Corollary (Grok's, and it is right): **do not adopt one mega-product, adopt a
stack.** Nothing well-maintained does loop + quota + multi-repo + independent
verification at once.

Named sources for the pattern:
- Geoffrey Huntley's Ralph Wiggum technique — https://github.com/ghuntley/how-to-ralph-wiggum
  (method essay; last push Jan 2026 — read it, do not "install" it)
- Anthropic, "Effective harnesses for long-running agents" — initializer
  agent + coding agent + artifacts (`feature_list.json`,
  `claude-progress.txt`, `init.sh`, git history). Released reference code:
  https://github.com/anthropics/claude-quickstarts/tree/main/autonomous-coding
  — **the loop driver is a Python script, not an agent.**
- Anthropic, "Harness design for long-running application development" —
  planner/generator/evaluator; notes newer models let them drop explicit
  context resets in favour of SDK autocompaction. That is a
  model-generation claim, not a licence to run one session for days across
  mixed vendors with rolling caps.
- OpenAI Symphony — the issue tracker as a **finite state machine**; every
  ticket has a status and the orchestrator cares about nothing else.

## Maturity table

Test used: default-branch last commit (`repos/X/commits?per_page=1`) +
contributor distribution (`repos/X/contributors`) + 4-week commit volume
(`repos/X/stats/participation`). **`pushed_at` was deliberately NOT used** —
it fires on tags and side branches and overstates liveness.

| Project | ★ | last default-branch commit | commits/4wk | top vs 2nd human | verdict |
|---|---|---|---|---|---|
| `gastownhall/beads` | 26.4k | Aug 15 | 795 | 4794 / 772 / 616 / 244 | ✅ real distributed community |
| `OpenHands/OpenHands` | 84.2k | Aug 15 | 197 | 100+ contributors | ✅ |
| `paperclipai/paperclip` | 78.5k | Aug 16 | 500 | 2429 / 355 / 148 / 32 | ✅ small real team, company-backed |
| `omnigent-ai/omnigent` | 8.9k | Aug 16 | 1057 | 621 / 347 / 321 / 148 | ✅ genuinely distributed, but **alpha** + interactive |
| `github/gh-aw` | 4.9k | Aug 16 | 1517 | Copilot 11580, then dsyme 1104 / pelikhan 792 | ✅ GitHub-maintained |
| `RunMaestro/Maestro` | 3.3k | Aug 16 | — | 4348 / 649 / 465 / 145 | ✅ small real team. **AGPL-3.0** |
| `mikeyobrien/ralph-orchestrator` | 3.1k | Aug 16 | — | 457 / **16** / 10 / 6 | ⚠️ effectively solo |
| `earendil-works/pi` | 91.4k | Aug 16 | — | — | ✅ (a **worker**, not an orchestrator) |
| `anomalyco/opencode` | 198k | Aug 16 | — | — | ✅ (a **worker**, not an orchestrator) |
| `openai/symphony` | 26.7k | Aug 12 | 13 | 9 contributors | ⚠️ reference spec; OpenAI says it will not maintain it as a product |
| `gastownhall/gastown` | 17.6k | **Jul 23** | 22 | — | ⚠️ decelerating |
| `SWE-agent/SWE-agent` | 20k | **Jul 16** | 0 | — | ⚠️ quiet |
| `frankbria/ralph-claude-code` | 9.6k | **Jul 10** | 0 | 27 contributors | ⚠️ stalled |
| `sipyourdrink-ltd/bernstein` | 907 | Aug 16 | 690 | 3570 / **37** | ⚠️ effectively solo (README admits it) |
| `razzant/claudexor` | 412 | Aug 16 | 894 | 1373 / **7** | ⚠️ effectively solo |
| `smtg-ai/claude-squad` | 8.3k | Jul 30 | — | ~19 contributors | ⚠️ AGPL; does not solve context |
| `langchain-ai/open-swe` | 10.6k | Aug 16 | 169 | 41 contributors | ⚠️ active but cloud-sandboxed, not local-first |
| `Aider-AI/aider` | 48k | **May 22** | — | — | ❌ stale (pair tool, not a factory) |
| `subsy/ralph-tui` | 2.4k | **May 13** | — | 30 contributors | ❌ ~95 days stale |
| `snarktank/ralph` | 21.5k | **Feb 2** | — | — | ❌ technique, not a product |
| `BloopAI/vibe-kanban` | **27.8k** | **Apr 24** | 0 | — | ❌ **dead** — Bloop shut down 10 Apr 2026 |
| `RooCodeInc/Roo-Code` | 24.3k | May 15 | 0 | — | ❌ **archived** |

**The headline method finding: two 24k+-star projects are corpses, and three
high-velocity projects are one human plus bots.** Star count is
anti-correlated with nothing useful here.

Not independently verified (relayed from Grok, flagged as such):
`herdrdev/herdr` at ~29.7k stars / 76 contributors / v0.8.0 on 3 Aug 2026.

Also surfaced but NOT verified enough to recommend:
`the-open-engine/zeroshot` (1.7k, active, planner/implementer/independent
validator), `aeonfun/aeon` (665, runs unattended on GitHub Actions),
`getpaseo/paseo` (13.9k, daemon, very active, 855 open issues),
`Untrivial-ai/agent-orchestrator` (markets an LLM orchestrator — the
regress), `thrashr888/AllBeads` (multi-repo beads, early),
`jedarden/NEEDLE` (right architecture, 16 stars).

## The panel

Five AI researchers attempted the same brief (`panel/research-brief.md`).

| | Outcome |
|---|---|
| Claude Opus 5 (prior session) | Own search + GitHub API verification |
| **Grok** | 22KB. Most current and most skeptical. Best single answer. |
| **Cursor** | 20KB. Converged independently with Grok. |
| Gemini | Completed, but stale numbers and a central false claim (below) |
| **Codex** | **Died: "You've hit your usage limit… try again Aug 20th"** |

**Grok and Cursor never saw each other's work and produced the same top three
in the same order:**

1. `mikeyobrien/ralph-orchestrator` — the never-dying program. Rust, MIT,
   fresh context per iteration, multi-CLI backends, and **backpressure gates
   that reject work failing tests/lint/typecheck**.
2. `gastownhall/beads` — durable state. The layer supervisor-LLMs were trying
   to be. A dependency graph the next amnesiac agent reads via
   `bd ready` / `bd show`, without inheriting a poisoned transcript.
3. `gastownhall/gastown` — only if the job is genuinely many agents × many
   repos for days, and **only the program half**. Both independently warned
   that its "Mayor" is an LLM with a tmux session; let the daemon/scheduler/
   refinery be immortal and treat the Mayor as cheap to kill.

Herdr was recommended by both as the *host* for the loop — infrastructure,
not the orchestrator. Installing only Herdr leaves you with a nicer tmux and
the same manual restart ritual.

## Corrections made during the session (all of these superseded something)

1. **Anthropic's own `ralph-wiggum` plugin for Claude Code is NOT Ralph.**
   Both Grok and Cursor independently found it loops inside the *current*
   session via a Stop hook — same context window. That is the failure mode,
   packaged. An earlier claim in the session that Ralph "was formalized as a
   plugin in Claude Code" was retracted on this basis.
2. **`gastown` was recommended first at one point and then withdrawn.** 17.6k
   stars but last default-branch commit Jul 23 and 22 commits/4wk. It is
   decelerating, and its marketed UX re-imports the regress.
3. **`ralph-tui` was leaned on early and should not have been.** It is not
   just stale, it is the stalest thing in its own category.
4. **Gemini's central claim is false.** It said flatly that no OSS tool
   orchestrates consumer CLI subscriptions with quota rotation and that "you
   would absolutely have to write your own custom daemon." Counter-examples
   exist (below). Gemini was also working from stale figures throughout
   (called OpenHands "~35k stars"; it is 84k) and called Aider "extremely
   active daily maintenance" when it had not shipped since May.
5. **But the quota claim splits, and an earlier over-correction needs its own
   correction.** The precise position:
   - *Claude-only subscription-window waiting exists.* `RunMaestro/Maestro`
     has Auto-Resume on Limit and reads real Claude plan usage.
     `frankbria/ralph-claude-code` has three-layer 5-hour detection with an
     unattended auto-wait. Both verified from docs; **neither tested**.
   - *Cross-vendor rolling-window pacing with account rotation does not exist
     in adoptable form.* `razzant/claudexor` does Claude + Codex via
     `oauth/usage` endpoints with credential profiles and a "continuation
     packet" for cross-context handoff — and is one person (1373 commits vs.
     the next human at 7). It clears the capability bar and fails the
     maintenance bar. Grok and Cursor both concluded independently that
     nobody owns "Claude account 2 is in the 5h hole, fail over to Codex,
     then Grok."
6. **An earlier praise of `orc_watchdog.py` was made without reading it.**
   On reading, it has at least two defects that would make it silently do the
   wrong thing. See `01-requirements-and-local-context.md`.

## What nobody has shipped (consensus across Grok and Cursor)

1. **A quota brain for subscription windows** across vendors.
2. **Multi-account rotation as a first-class scheduler.**
3. **Independent verification that does not trust the agent** — the judge
   that reconciles tracker + git range + test log and is willing to call the
   orchestrator's `COMPLETED` a lie.
4. **Simple multi-repo Ralph.** beads is per-repo (federation exists, it is
   not simple); gastown is multi-repo and is a lifestyle.
5. **Loop persistence across machine reboot** as a boring guarantee. Herdr
   persists panes; Maestro documents that its Auto Run *controller* dies on
   restart.
