---
name: resume
description: Start-of-session shortcut for resuming a task workspace from its Tier 1 pointer file. Use when the operator types /resume, or says "resume", "pick up where we left off", "continue this task" at the start of a session.
---

# Resume — shortcut into the session-handoff reader protocol

This is a thin entry point, not a separate protocol. Follow the
`session-handoff` skill's **Reader protocol** section exactly (read
`SESSION_LOG.md` if present, check sidecars newer than `updated_at`, run
the staleness check against real `HEAD`, state a resume plan before
touching anything, bootstrap a minimal log if none exists — never ask
the operator for information the file already answers).

If the operator invoked this with no argument, resolve the current
directory against the Tier 1 path convention in `session-handoff` (or,
if you were handed an explicit path in the prompt, use that instead of
resolving from cwd). If cwd doesn't resolve (e.g. running in the bare
home directory), that is NOT a dead end — go straight to
`session-handoff`'s **Chain discovery fallback** (step 0 of its Reader
protocol) instead of asking the operator to supply a path.

Do not duplicate the reader protocol's steps here — if they ever change,
they change in exactly one place (`session-handoff`'s SKILL.md), not two.
