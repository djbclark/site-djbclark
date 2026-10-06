# Herdr CLI gotchas when driving agents headlessly

Last verified 2026-09-26.

- **`herdr workspace create` returns before the new pane's shell is up.**
  A `herdr agent start … --pane <new-pane>` fired immediately fails with
  `agent_pane_busy: agent target pane … is not an available shell`. Poll
  `herdr pane read <pane>` until a shell prompt (`$`) appears — about 2 s —
  then start the agent.
- **Key names are `ctrl+c`, `enter`, `esc`** for `send-keys`; `ctrl-c` is
  rejected with `invalid_key`.
- **`herdr pane read` prints plain text.** Every other command prints one
  JSON envelope, and a failure is `{"error":{"code","message"}}` **with
  exit status 0** — parse the envelope, never trust the exit code.
- `herdr agent prompt <target> "/exit"` cleanly ends a Claude session and
  returns the pane to its shell (~1 s); `herdr agent start <name> --kind
  claude --pane <id> -- --resume <session-id>` brings the same session
  back. `bin/herdr-sleeper` in djbclark-ade automates exactly this for
  idle panes (`herdr-sleeper list` / `log` before assuming a bare-shell
  pane is dead; see djbclark-ade `docs/agent-sleep.md`).
- Do not send a pane `/exit` while its composer holds unsent text — the
  draft is lost with the process.

- **Keys sent before a prompt is on screen land in the agent's input box** (2026-10-06:
  a digit meant for an AskUserQuestion that had not rendered yet sat in the Claude input
  line as type-ahead). Read the screen first (`herdr agent read <pane> --source visible`,
  which prints plain text, not JSON) and send only when the prompt is there.
- **A finished turn in a pane nobody has looked at is `done`, not `idle`** (by design:
  herdr's skill says both mean "ready for input" and differ only by its seen state;
  reproduced three times 2026-10-06, each `herdr agent wait --until idle` timed out while
  `agent get` said `done`). Wait with `--until idle --until done`, or with no `--until`.
  To know a tool call was answered, check the transcript for its result.
