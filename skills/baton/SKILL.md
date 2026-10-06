---
name: baton
description: Alias for /resume — start-of-session shortcut for resuming a task workspace from its Tier 1 pointer file. Use when the operator types /baton, or says "baton", "pick up the baton", "resume" at the start of a session.
---

# Baton — alias for resume

This is a naming alias, not a separate protocol. Follow the `resume`
skill exactly (which is itself a thin entry point into `session-handoff`'s
**Reader protocol** section) — same behavior, same steps, just invokable
under a second name.

Do not duplicate `resume`'s or `session-handoff`'s steps here — if they
ever change, they change in exactly those two places, not three.
