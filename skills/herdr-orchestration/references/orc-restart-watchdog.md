# Proactive orc restart on context bloat

The self-closure recovery flow in [SKILL.md](../SKILL.md#orchestrator-tab-identity-and-self-closure-defense) handles orc *dying*. It doesn't cover orc's context
window quietly filling up over a long session — quality degrades and
per-turn burn rate climbs well before any crash (see the tokenmax reference
memory `reference_token_self_check` in site-private memory). Per
`feedback_primary_orchestrator_role`, hitting an actual quota cap is a full,
unrecoverable-from-inside stop — nothing inside orc's own session can fix it
after the fact — so the only workable fix is external: something outside
orc watches and restarts it *before* that happens.

**Two different problems, two different fixes — don't conflate them:**

- **Context bloat** (a big cache-read-token count) → fixed by a genuinely
  cold session (no `--resume`) re-briefed from orc's own plan/roster file.
  This sheds context and resets the burn rate.
- **Quota exhaustion** (an account's 5-hour or weekly window running out) →
  a fresh session does **not** fix this, the account is still capped. The
  only real fixes are `cswap` to a different account or waiting for reset.
  Never restart orc's process in response to a quota alert — it accomplishes
  nothing and just discards its live context for free.

**`/baton` is the wrong resume mechanism for orc itself.** Tier 1
(`SESSION_LOG.md`) is scoped to a single git task workspace under
`~/src/ops-worktrees/` — it doesn't cover a cross-repo orchestrator juggling
multiple herdr panes. orc's actual durable state is the plan/roster file it
already maintains per ["Workflow per unit"](../SKILL.md#workflow-per-unit) step 11. A restart briefs
the fresh session from that file plus a live `herdr agent list`/`pane list`
query, not from `/baton`.

## The watchdog

`~/.claude/hooks/orc-watchdog/orc_watchdog.py` (untracked local tooling, not
part of any of the three repos — same convention as this skill and the base
`herdr` skill, which are also loose files under `~/.claude`). It polls,
external to orc's own process, so it keeps working even if orc is already
capped or unresponsive:

- **Context size**: last `cache_read_input_tokens` from orc's session
  transcript JSONL (auto-discovers the most recently modified transcript
  under `~/.claude/projects/*/*.jsonl`, or pin one with `--session-id`).
  Default hard threshold 350,000 tokens (well past the
  `context_size_nudge.py` hook, which asks the operator from +70k growth or
  150k total and pages at +130k or 250k).
- **Quota**: `aiuse --json`, looking for a `kind: "burn"` alert on the
  `claude` provider, or the active `cswap` account's 5-hour window dropping
  under 25% (the primary-orchestrator floor). This only logs/alerts — see
  above for why it never triggers a restart.

orc is located by **Herdr tab label**, not agent name — `herdr agent list`
on this account carries no per-agent `name` field unless one was explicitly
set with `agent rename`, so the watchdog looks up the tab labeled `orc`
(the same naming convention from ["Orchestrator tab identity"](../SKILL.md#orchestrator-tab-identity-and-self-closure-defense) in SKILL.md) via
`herdr tab list` → `herdr pane list`, then targets that pane by ID for every
subsequent `herdr agent ...` call. Verify with:

```bash
python3 ~/.claude/hooks/orc-watchdog/orc_watchdog.py check
```

Run it as a poll loop, dry-run by default (logs what it *would* do without
touching orc):

```bash
python3 ~/.claude/hooks/orc-watchdog/orc_watchdog.py watch \
  --plan-file /absolute/path/to/the/roster.md
```

Add `--act` only once you've watched a few dry-run cycles and are confident
in the plan-file path and threshold — this is the flag that actually sends
`/quit` to orc's pane and restarts it. `--tab-label` overrides `orc` if a
given setup names it differently. Restarts only fire when orc is `idle` or
`done` (never interrupts live work) and are rate-limited to once per 20
minutes.

**Restart sequence**, once triggered with `--act`: send literal `/quit` text
to orc's pane (this types into the CLI and exits its process — distinct
from `herdr pane close`/`tab close`, so the self-closure wrapper's guard
does not apply and does not need to be bypassed) → wait for the pane to
lose its agent identity → `herdr agent start orc --kind claude --pane
<id>` → send a bootstrap prompt naming the plan-file path and instructing
the fresh session to reconcile against live `herdr agent list`/`pane list`
before continuing → send a final `continue`.

**Who runs the watchdog.** It's a plain script, not an LLM agent — no
Claude quota cost either way, so it doesn't need to run on a separate
vendor account the way a judgment-making "meta" agent would (per
`feedback_agent_spawn_token_pacing` and `feedback_primary_orchestrator_role`
— an agent meta watcher sharing orc's own Claude pool would go down with
orc). If a more capable "meta" is ever built on top of this to make broader
judgment calls (which sub-agents to reassign, when a restart is worth
interrupting idle-but-not-done work, etc.), keep that layer on a separate
account/vendor from orc for the same reason, and have it call this script
(or its functions) for the mechanical parts rather than re-deriving the
polling/threshold/herdr-targeting logic inline.

**Always name that watcher's own Herdr tab `orc-meta`** — whether it's this
plain script running in a pane, or a live judgment-making agent. Distinct
from the ad hoc `meta` label used for a one-off crash-recovery session
in SKILL.md: `orc-meta` is the standing, always-there watcher tab, so it needs a
name that's unambiguous at a glance alongside `orc` itself and stable
enough to script against (e.g. as this watchdog's own `--tab-label`
default, should it ever need to identify itself rather than just orc).
