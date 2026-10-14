# PreToolUse hook: pre-approve every tool call (no permission prompts in the TUI).
# Silent under acp-run (ACP_RUN_CRUSH=1) so its --perm scoped:/deny policies still get asked.
[ -n "$ACP_RUN_CRUSH" ] || echo '{"decision":"allow"}'
