# acp-run

Run one prompt through a coding agent over the
[Agent Client Protocol](https://agentclientprotocol.com) (ACP), headless, and get
the agent's final message on stdout. It is how one agent on this machine hands a
self-contained task to another vendor's agent: Claude Code, Codex, Copilot,
opencode, Cursor, Qwen Code, Devin, Cline, Hermes, Antigravity (`agy`) and Grok.

A single-file [uv script](https://docs.astral.sh/uv/guides/scripts/) on the
official Python SDK (`agent-client-protocol`); no daemon, no state beyond its
logs. MIT licensed.

```sh
acp-run --list                                  # agents and the command each runs
acp-run claude --info                           # modes, config options, auth methods
acp-run codex -C ~/src/repo -p 'Reply with exactly: OK' --model gpt-6-astra
acp-run copilot -C ~/src/repo -f brief.md --perm deny --timeout 1200 > report.md
```

## What it adds over a bare ACP client

1. **A per-agent table**: the launch command for each agent, per-agent default
   config options (`DEFAULT_SET`), each agent's own auto-approve mode (`YOLO_SET`),
   and environment set-up where an agent needs it.
2. **A permission policy** answering every `session/request_permission`:
   - `all` (default): allow everything.
   - `deny`: refuse everything (read-only review).
   - `scoped:P1,P2`: allow reads, searches, fetches, thinking and commands; allow
     edit/delete/move only when every path the tool call names is under one of
     the listed paths (relative to `-C`). This is an approval policy, not a
     sandbox: an allowed shell command can still write anywhere.
3. **`--model`, `--mode` and `--set ID=VALUE`** for any config option `--info`
   lists.
4. **An audit trail**: every ACP event is logged as JSONL (default
   `~/.local/state/acp-run/`), and one summary line goes to stderr: stop reason,
   seconds, tool calls, permissions allowed/denied, tokens, cost, log path.
5. **Timeouts that cancel the turn** (`session/cancel`), and a bounded handshake
   with retries (`--handshake-tries`), falling back to `claude -p` for the
   `claude` agent when its ACP session never starts (`--no-fallback` to disable).
6. **Exit codes**: 0 = `end_turn` with some output; 1 = another stop reason, an
   agent error or an empty reply; 2 = usage; 124 = timeout.

Run `acp-run --help` for every flag.

## Install

Needs [uv](https://docs.astral.sh/uv/) and the agents' own CLIs/adapters.

```sh
curl -fsSLo ~/.local/bin/acp-run \
  https://raw.githubusercontent.com/djbclark/site-djbclark/master/tools/acp-run/acp-run
chmod +x ~/.local/bin/acp-run
acp-run --list
```

The agent table reflects the machine it was written on (for example Cline is
pinned to the `cline-pass` provider, and `agy` runs Google's first-party ACP
server from `~/.local/share/agy-acp-server/`); edit `AGENTS`, `DEFAULT_SET` and
`YOLO_SET` at the top of the script for yours.

## Why not acpx?

[acpx](https://github.com/openclaw/acpx) is the maintained general-purpose ACP CLI
and is the better choice for most people. On 2026-10-05 it lacked two things this
script exists for: permission rules scoped to file paths, and per-agent
environment and default config options. If acpx gains those, a thin wrapper over
it would replace this script.
