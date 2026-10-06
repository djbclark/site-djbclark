# Pane layout convention

Operator preference, set 2026-07-28.

- Never close a pane/tab. Minimize/shrink instead. The
  `~/.herdr-wrapper/bin/herdr` wrapper (see "Orchestrator tab identity and
  self-closure defense" in [SKILL.md](../SKILL.md#orchestrator-tab-identity-and-self-closure-defense))
  refuses self-closure as a backstop, but it is not a reason to get sloppy
  about closing *other* panes/tabs either — minimize/shrink remains the
  default.
- 2 panes (you + newest agent): side by side.
- 3 panes: you = top-left quarter, newest agent = full right half, older
  agent = bottom-left quarter (under you).
- 4 panes: you stay top-left quarter, newest/current agent goes under you
  (bottom-left), the other 2 older agents share the right half.
- 5+ panes: you stay in place, current agent under you, all older agents
  stack in order on the right, shrinking as more accumulate.
- **Within the right-side stack, size by activity, not just recency**:
  agents that are `idle`/`done` get minimal space; agents still `working`
  get more room. Re-check `herdr agent get` for each right-side pane whenever
  you rearrange it and use `herdr pane resize` so active work is legible and
  finished panes are just a status strip. This can mean an older agent
  that's still working stays bigger than a more recently finished one —
  activity state wins over recency for sizing.
- **`pane resize --direction` semantics are inconsistent/counterintuitive
  across a nested split tree** — the same direction argument shrank one
  pane but no-op'd or grew a different one at another boundary, with no
  obvious rule tied to upper/lower position in the split. Don't assume a
  direction based on one earlier result. If a resize call returns
  `"changed": false` or grows the wrong pane, try the same direction/amount
  on the *other* pane sharing that boundary instead of guessing more
  directions on the same pane — that flip is what worked in practice. Treat
  this as "converge on a good-enough layout by trying a couple of calls and
  checking the resulting rect", not something to get exactly right
  analytically.
- Use `herdr pane swap --source-pane <id> --target-pane <id>` to reposition
  without closing/recreating panes when a new agent needs to become "the
  newest" in the layout.
- **Once a pane shrinks to a handful of rows (5+ agents), `agent read` may
  only return 1-2 lines even at `--lines 150`** — the terminal's actual
  rendered viewport is too small to hold much scrollback. Check
  `herdr pane get <id>` — if `viewport_rows` is small (single digits), use
  `herdr pane zoom <id> --on` to temporarily maximize it, read normally, then
  `herdr pane zoom <id> --off` to restore the layout. Don't leave it zoomed.
- Dedicated full-screen tabs for "always show me" / "always show the active
  agent" were requested once but explicitly *not* implemented — the only way
  to put the orchestrator's own pane in a different tab is `pane move` on
  your own live pane, which risks disconnecting your own control channel
  mid-session. Don't attempt this without the operator explicitly asking you
  to try it, watching, accepting the risk.
