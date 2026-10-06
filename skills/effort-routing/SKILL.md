---
name: effort-routing
description: >-
  Match your own reasoning effort to the work in front of you, within a
  single session — drop to a cheaper tier for mechanical stretches, climb
  back for judgment, and say when you switch. Use when starting a long
  stretch of file edits, doc writing, or command running; when a session
  set to high effort is doing rote work; when dispatching subagents; or
  when asked "should we drop the thinking level for this".
---

# Effort routing — your own tier, not other vendors'

Sibling to [model-routing](../model-routing/SKILL.md), which decides *which
vendor* runs work. This one decides *how much thinking* the current session
spends. They are different problems and get confused constantly.

Canonical source: `skills/effort-routing/SKILL.md` in djbclark-ade. Snapshot
**2026-08-23**.

## The honest constraint

`claude --model` and `--effort` set the tier **for a session**, and
`~/.claude/settings.json` holds the default (`effortLevel`). A running session
cannot re-tier itself mid-turn. So "dynamic effort" has exactly two real
mechanisms:

1. **Dispatch.** Subagents take their own `model` and `effort`. Sending a
   mechanical stretch to a cheap subagent is the one fully automatic lever.
2. **Tell the operator.** For the session's own tier, say plainly that the
   next stretch is mechanical and they can `/model` down — then keep working.
   Do not stop and wait.

Anything claiming more than that is describing a feature that does not exist.

## Classifying the stretch

Ask what the *next several actions* look like, not the last one:

| Signal | Tier |
|---|---|
| Applying a decision already made; edits, commits, doc writing, running known commands | **low / haiku** |
| Normal implementation with a clear shape; tests, adapters, refactors | **medium / sonnet** |
| The shape is not clear yet; architecture, adjudication, debugging something that already defeated one attempt, whole-corpus reading | **high / xhigh, Fable** |

Two traps worth naming. A session set high stays high through hours of rote
work because nobody notices — that is the common failure, and it is invisible
because nothing breaks. The rarer, worse one is dropping tier for something
that *looked* mechanical and quietly producing a bad decision; when in doubt
about which side you are on, stay high and say so.

## What to actually do

- **Long mechanical stretch ahead** — say so in one line and keep going;
  offer that `/model sonnet` or `--effort low` would cost less. Do not ask
  permission.
- **Fan-out of rote nodes** — dispatch them at `model: "haiku"`,
  `effort: "low"` rather than doing them inline at session tier.
- **One hard call inside otherwise ordinary work** — do not raise the whole
  session. Dispatch that single question to `fable-deep` and carry on; this is
  what its separate weekly budget is for (see model-routing).
- **Switching** — always name the switch and why. An unexplained tier change
  reads as inconsistency.

## What actually dominates cost: prompt caching

Effort tiering is a real lever, but a smaller one than the thing underneath
it. Verified against
[code.claude.com/docs/en/costs](https://code.claude.com/docs/en/costs):

- **The whole conversation is re-sent on every request**, including each
  batch of tool results. Prompt caching means that history is re-read at the
  cached rate rather than full price — so a one-line question in a session
  that has been open all day still draws usage for the entire conversation.
- **Cache lifetime is one hour on a subscription**, dropping to five minutes
  once you are drawing on usage credits (and five minutes on API keys). The
  first message after a longer break misses the cache and reprocesses
  everything. `ENABLE_PROMPT_CACHING_1H=1` keeps the one-hour lifetime while
  on usage credits.
- **`/clear` costs nothing; `/compact` is itself a large request**, because
  it reads the conversation it summarises. When you want a fresh start rather
  than continuity, clear — do not compact out of habit.
- **Subagents isolate verbose work.** Test runs, log processing and doc
  fetches keep their output in the subagent's context and return only a
  summary. This is why dispatch beats doing rote work inline, independent of
  tier.

Practical consequence for the rules above: the cheapest thing you can do is
usually not a lower tier, it is a **shorter conversation**. Clear between
unrelated tasks; a stale 400k-token context taxes every subsequent message
regardless of model.

One caveat, deliberately flagged: a widely-shared video claims that switching
model, changing effort, toggling fast mode, connecting an MCP server,
installing plugins, denying a tool, or upgrading Claude Code each invalidate
the cache outright. **That list is not in the official docs**, which describe
cache misses only in terms of the time-based lifetime. Treat it as unverified
— if it is true, mid-session switching is more expensive than it looks, so
prefer dispatching a subagent over re-tiering a long session, which is the
better move anyway.

## Related

Vendor choice, quota headroom, and which pools are idle:
[model-routing](../model-routing/SKILL.md) and `bin/route_agent.py`
(`route --kind judgment|code|bulk|research|mechanical|github`). Effort routing
picks the tier; that picks the vendor. Run both.
