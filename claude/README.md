# Tracked mirrors of `~/.claude/` session-handoff artifacts

Live copies under `~/.claude/hooks/` and `~/.claude/skills/` are
canonical — this directory only versions them (spec:
`docs/session-handoff-compaction-spec.md`). Update both together, same
rule as the root CLAUDE.md distribute-and-symlink convention.

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

`claude/commands/{orc,orc-meta}.md` and `claude/agents/fable-deep.md` are the
canonical copies; `~/.claude/commands/*.md` and `~/.claude/agents/*.md` are
symlinks to them (same distribute-and-symlink pattern as `skills/`).
