# Research: should Kimi K3 be a routable model for Herdr orchestration?

**Date:** 2026-08-03
**Issue:** [djbclark/site-djbclark#36](https://github.com/djbclark/site-djbclark/issues/36)
**Status:** Decision made — trial, don't wire into standing infrastructure yet.

## Question

Should we add Kimi K3 (Moonshot AI, via OpenRouter or a direct Moonshot API
key) as a model Herdr-orchestrated agents can route long-horizon or
large-context tasks to, alongside the existing Claude rotation and the
Repomix+Gemini flat-context audit path from
[#35](https://github.com/djbclark/site-djbclark/issues/35)?

## The argument as originally proposed

> Between the Claude Pro rotation handling smart, chunked iterative coding,
> and Google AI Studio handling massive 1.1M+ token architectural reviews,
> Kimi's consumer tiers are boxed out. But the Kimi K3 API (launched mid-July
> 2026) has two tactical advantages if accessed via OpenRouter/Moonshot API
> key:
>
> 1. The "200k–1M dead zone" — our two smaller repos (`site-djbclark`
>    208,431 tokens + `site-private` 72,283 tokens ≈ 280K combined) are "too
>    big for Claude's 200k cap, small enough for a 1M window." Kimi's prompt
>    caching allegedly brings input cost to $0.30/M, making a combined-repo
>    prompt cost ~8 cents.
> 2. The unsupervised weekend grind — K3 was trained for "long-horizon"
>    agentic work and posted strong scores on the "SWE Marathon" benchmark
>    (multi-hour autonomous terminal tasks). Routing a big herdr-orchestrated
>    refactor grind to Kimi instead of Claude avoids burning Claude usage
>    limits, for a few dollars over 48 hours.
>
> Conclusion: don't buy a Kimi subscription, but keep a small OpenRouter
> balance loaded to route Herdr to `kimi-k3` for 500K+-token tasks as cheap
> insurance.

This doc fact-checks that argument against current, independently verified
sources, then adds the piece the original argument skipped: whether Herdr
can mechanically route a task to Kimi at all.

## Fact-check

### The "200K–1M dead zone" premise does not hold

**Claude does not cap at 200K.** As of 2026-08, Claude Sonnet 5, Opus 4.8,
and Claude Fable 5 all have a **1M-token context window** — 200K only
applies to the smallest tier, Haiku 4.5 (see
[`docs/reference/available-ai-models.md`](available-ai-models.md), rows
10–13). The two smaller repos combined (~280K tokens, per the token counts
already logged in #35) fit comfortably inside Claude's actual context window.
There is no dead zone to fill for this operator's repo sizes. This is the
same correction made against the Gemini/Repomix argument in #35 — worth
flagging that "Claude = 200K" keeps recurring as a stale assumption and
keeps being wrong for the current model lineup.

### Kimi K3's real specs, independently re-verified 2026-08-03

- Released 2026-07-16, model ID `kimi-k3`, 2.8T parameters, Moonshot AI.
- **1,048,576-token context window, matching max output** — no long-context
  pricing surcharge.
- **Pricing: $3.00/M input (cache-miss) / $15.00/M output**, with a
  **$0.30/M cache-hit input rate** (some sources list a shaded $2.90/$14,
  consistent within normal listing variance).

Sources checked this session: [OpenRouter model page](https://openrouter.ai/moonshotai/kimi-k3),
[BenchLM pricing](https://benchlm.ai/moonshot/api-pricing),
[Bifrost cost calculator](https://www.getmaxim.ai/bifrost/llm-cost-calculator/provider/openrouter/model/kimi-k3),
[Trilogy AI writeup](https://trilogyai.substack.com/p/kimi-k3-is-live-pricing-benchmarks).
These corroborate the figures in issue #36's own research pass rather than
contradicting them.

**The pasted argument's "$0.30/M input, ~8 cents per prompt" figure is
cache-hit-only, not a cold-prompt figure.** A cold (first-touch) 280K-token
prompt against the two smaller repos costs ~$0.84 in input alone at the
$3/M cache-miss rate, before any output tokens — roughly 10x the advertised
figure. The 8-cent number only applies once the same prefix is already warm
in cache, i.e. on a second or later call in the same session.

**Cost is not a clear differentiator.** Kimi's $3/$15 sticker price is
identical to Claude Sonnet 5's list price, and Kimi's cache-hit discount
(~0.1x) is roughly the same ratio Anthropic already applies to prompt-cache
reads. On raw price, Kimi is not obviously cheaper than the Claude tier this
work would otherwise route to.

### The genuine advantage: SWE Marathon benchmark performance

This is the part of the original argument that holds up, and it's the
strongest real case for Kimi:

- **SWE Marathon** is a real, current benchmark — 20 long-horizon
  software-engineering tasks in unique executable environments with
  human-written reference solutions and multi-layer verification; logged
  agent attempts average ~27.2M tokens per run
  ([arXiv 2606.07682](https://arxiv.org/pdf/2606.07682)).
- **Kimi K3 leads all checked competitors on it**, independently
  re-confirmed 2026-08-03:

  | Model | SWE Marathon score |
  | --- | --- |
  | **Kimi K3** | **42.0** |
  | Claude Opus 4.8 | 40.0 |
  | GPT-5.6 Sol | 39.0 |
  | Claude Fable 5 | 35.0 |

  Sources: [officechai.com](https://officechai.com/ai/kimi-k3-benchmarks/),
  [Wan 2.7 benchmark roundup](https://wan27.org/blog/kimi-k3-benchmarks),
  [Viddi AI head-to-head](https://viddiai.com/blog/kimi-k3-benchmarks). K3 is
  also independently reported as first-place on Program Bench, BrowseComp,
  Automation Bench, Frontend Code Arena, Terminal-Bench 2.1, and
  OmniDocBench — a consistent pattern of leading specifically on
  sustained/autonomous execution rather than single-shot reasoning.
- K3's coder-subagent tooling (background tasks, todo lists, plan mode,
  skill invocation, nested agents) is built for multi-hour autonomous runs,
  not a large context window bolted onto a chat model. As a public
  demonstration it reportedly designed and verified a chip in a single
  48-hour autonomous run using open-source EDA tools.

So the "long-horizon unsupervised grind" claim is well-supported —
better-supported, in fact, than the token-window/cost argument that
originally led with it.

## The mechanical question: can Herdr actually route to Kimi K3?

The original issue left this open. It's answerable from this repo's own
Herdr docs (`docs/reference/herdr-workstation.md`,
`docs/reference/available-ai-models.md`) without needing to touch the
on-box `~/.config/herdr/config.toml`:

**Herdr does not itself choose models.** It launches and tracks agent CLI
*processes* in panes (`claude`, `codex`, `opencode`, `grok`, `cursor-agent`,
`hermes`, `copilot`, plus the site-side Goose/Aider prototypes), and uses
screen-detection manifests to report `working`/`blocked`/`done` state per
pane. Model selection happens *inside* whichever CLI is running in that
pane, not in Herdr's own config.

That means routing a task to `kimi-k3` is not a Herdr feature request — it's
a question of which already-Herdr-integrated CLI can reach Kimi K3 as a
model backend:

- **OpenCode Go (TUI)** already lists Moonshot's Kimi family as first-class
  model options (`available-ai-models.md` rows 35–36: Kimi K2.7 Code, Kimi
  K2.6) and OpenCode Go has a live Herdr integration
  (`herdr integration status` lists it). Once OpenCode Go's own model
  catalog picks up `kimi-k3` (Moonshot ships new models to existing
  provider integrations regularly — this is an OpenCode Go
  update/config change, not a Herdr change), a Herdr pane running
  `opencode` can target it directly with no Herdr-side work at all.
- **Codex (oauth)** already documents third-party model routing via
  `config.toml`, explicitly naming Kimi as a supported non-OpenAI backend
  (`available-ai-models.md` row 9). That path also requires no Herdr change.
- **OpenRouter (api)** exposes `moonshotai/kimi-k3` directly today. Any
  Herdr-integrated CLI that supports an OpenRouter/BYOK backend (Zed,
  Cursor's API pool, or a raw API-key config) can reach it now.

**Conclusion: the mechanical path already exists and needs no Herdr feature
work.** The correct integration point is the model catalog of an
already-integrated CLI (OpenCode Go being the most natural fit, since it
already treats Kimi as a native provider), not a new Herdr capability.
`docs/reference/available-ai-models.md` is the authoritative catalog for
this operator's model options and is operator-maintained — adding a
confirmed `kimi-k3` row there (once verified live in OpenCode Go's picker)
is the natural follow-up once/if the trial below succeeds, not part of this
research doc.

## Recommendation: trial, don't wire in as standing infrastructure

**Don't buy a Kimi subscription.** No argument for a standing subscription
survives scrutiny, and the original proposal didn't claim otherwise.

**Don't add Kimi K3 as a permanent routing target yet.** The token-window/
cost case is weaker than presented once corrected — there's no 200K–1M dead
zone once Claude's actual 1M window is used, and the headline cost figure
compared a cache-hit rate against a cold-prompt workload. On sticker price
alone, Kimi is not a clear win over the Claude tier already in rotation.

**Do run one real trial.** The SWE Marathon result is real, independently
re-confirmed, and is the only part of the original argument that's an
actual case for Kimi: K3 leads Opus 4.8, GPT-5.6 Sol, and Fable 5 specifically
on long-horizon, high-token, low-supervision agentic work — a different
capability axis than raw reasoning quality or price. That's worth testing
against this operator's actual workload rather than trusting benchmark
transfer:

1. Point one Herdr pane running OpenCode Go at `kimi-k3` (once it appears in
   OpenCode Go's model picker) or at `moonshotai/kimi-k3` via an
   OpenRouter-backed pane.
2. Give it one real multi-hour, low-supervision task of the kind this
   argument is actually about — e.g. a CFEngine or stayturgid refactor
   grind — not a synthetic benchmark.
3. Compare completion quality, actual cost (cold-cache, not the optimistic
   warm-cache number), and how well Herdr's screen-detection tracks its
   pane state, against the same task run through Opus 4.8 or Fable 5.
4. Only after that trial, decide whether Kimi K3 earns a permanent row in
   `available-ai-models.md` and a standing place in the long-horizon-grind
   rotation.

Keeping a small OpenRouter balance loaded to make that trial possible is
reasonable and cheap; committing Kimi K3 into the routing rotation before
running it is not yet justified by the evidence.
