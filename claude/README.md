# Tracked mirrors of `~/.claude/` session-handoff artifacts

Live copies under `~/.claude/hooks/` are canonical — this directory only
versions them. **`claude/skills/{handoff,session-handoff}` are symlinks to
`~/src/djbclark-ade/skills/<name>`** (the canonical skills; edit them there),
and `claude/skills/resume` points at `djbclark-ade/skills/baton`, which `resume`
was folded into on 2026-10-08. They replaced diverged copies on 2026-10-13
(#137 C2.1); the canonical skills were already a superset of them.

## model-routing skill lives elsewhere

`~/.claude/skills/model-routing/` is NOT mirrored here: its canonical
source is `skills/model-routing/SKILL.md` in the djbclark-ade repo
(github.com/djbclark/djbclark-ade), which owns all ADE/agent-graph
content. Tracked here briefly on 2026-08-23 (#101), moved same day.

## graft nudge hook (2026-09-26)

`hooks/graft_grep_nudge.py` is registered in `~/.claude/settings.json` (not
tracked) as a `PreToolUse` hook:
`{"matcher": "Grep|Glob|Bash", "hooks": [{"type": "command",
"command": "python3 \"$HOME/.claude/hooks/graft_grep_nudge.py\"", "timeout": 5}]}`.
Once per session, in a repo with `graft/INDEX.md`, it reminds the model to try
graft before grep/glob (Bash only when the command is grep/rg/ag/ack/find/fd).

## graft alwaysLoad guard (2026-09-26)

`hooks/graft_mcp_alwaysload.py` is registered under `hooks.SessionStart` in
`~/.claude/settings.json` (no matcher):
`{"hooks":[{"type":"command","command":"python3 \"$HOME/.claude/hooks/graft_mcp_alwaysload.py\"","timeout":5}]}`.
If the cwd's `.mcp.json` has a `mcpServers.graft` entry without
`"alwaysLoad": true` (graft's own SessionStart reconcile rewrites the entry to
its stock shape on every version upgrade, trailhq/Graft#118), it re-adds the
flag and says so in additionalContext; otherwise it is silent and touches
nothing. The Hermes watchdog `check-graft-wiring-invariants.sh` checks that it
is registered and matches this mirror.

## Custom commands and subagents (2026-09-30)

`claude/agents/fable-deep.md` is the canonical copy; `~/.claude/commands/*.md`
and `~/.claude/agents/*.md` are symlinks to the files here (same
distribute-and-symlink pattern as `skills/`). The orchestration command
wrappers in `claude/commands/` (`helm-all`, `herdr-tidy`, `resume`,
`session-finder-all`) are themselves symlinks into
`~/src/djbclark-ade/claude/commands/` since 2026-10-08; edit them there.

## Prompt-hook deadlines: nudge hooks run under `hook-deadline` (2026-10-10)

`hooks/context_size_nudge.py` and `skills/autorename/autorename_nudge.py` are
registered under `hooks.UserPromptSubmit` in `~/.claude/settings.json` (not
tracked) as
`"$HOME"/ops/site-private/bin/hook-deadline 4 "$HOME"/.claude/hooks/context_size_nudge.py`
and
`"$HOME"/ops/site-private/bin/hook-deadline 4 python3 "$HOME"/ops/site-djbclark/skills/autorename/autorename_nudge.py`,
each with `"timeout": 20` as the backstop. Both scripts arm a 2 s
`signal.alarm` of their own, but that only starts once the interpreter is up:
on 2026-10-10 (load average 32-40, six Claude sessions plus a `claude -p` turn
with a 31k-word prompt) python start-up alone exceeded the old 5 s / 10 s
timeouts and Claude Code printed "hook timed out, output discarded" on every
prompt. The wrapper (perl, ~10 ms start) cuts the whole process group at 4 s
and exits 0 silently, so a starved hook costs at most 4 s and no noise; the
nudge simply fires on the next prompt. After any settings rewrite, check the
two entries still carry the `hook-deadline 4` prefix.
