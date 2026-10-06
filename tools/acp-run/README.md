# acp-run

Run one prompt through a coding agent over the
[Agent Client Protocol](https://agentclientprotocol.com) (ACP), headless, and get
the agent's final message on stdout. It is how one agent on this machine hands a
self-contained task to another vendor's agent: Claude Code, Codex, Copilot,
opencode, Cursor, Qwen Code, Devin, Cline, Hermes, Antigravity (`agy`) and Grok.

A single-file [uv script](https://docs.astral.sh/uv/guides/scripts/) on the
official Python SDK (`agent-client-protocol`); no daemon, no state beyond its
logs. MIT licensed. The SDK is pinned below 1.0 until 1.0 is tested.

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
   `~/.local/state/acp-run/`), ending with a `result` record (summary and exit
   code), and one summary line goes to stderr: stop reason, seconds, tool calls,
   permissions allowed/denied, tokens, cost, failure class, log path.
5. **Timeouts that cancel the turn** (`session/cancel`), and a bounded handshake
   with retries (`--handshake-tries`), falling back to `claude -p` for the
   `claude` agent when its ACP session never starts (`--no-fallback` to disable).
   `--handshake-timeout` (env `ACP_RUN_HANDSHAKE_TIMEOUT`) bounds `initialize`
   and `session/new` each: 40 s by default, 90 s for `claude`, whose
   `session/new` takes 13 s on an idle machine and 17-24 s under heavy load.
6. **Safe permission answers**: only an offered `allow_once` or `reject_once`
   option is ever selected. Never an `*_always` option, which an agent may save
   beyond this run (Hermes writes `allow_always` to a permanent allowlist), and
   never `cancelled`, which cancels the whole turn. An allow with no
   `allow_once` offered becomes a `reject_once`; with neither offered the agent
   gets a JSON-RPC error. Under `scoped:`, a tool call with no kind gets one
   inferred from its title (`Edit ...` is an edit, as acpx does); one that cannot
   be inferred needs in-scope paths, like an edit.
7. **Delivery checks.** Agents report some provider failures as a normal answer
   (`end_turn`). acp-run fails such a turn (exit 1, a `FAILED <class>` line on
   stderr, `"failure"` in `--json`) when the whole short reply is a refusal
   (`Upgrade your plan to continue`), or when the reply ends in a provider or
   transport error line (`Error: RetriableError: [unavailable] PING timed out`),
   reported as "reply truncated; edits may be present". ACP errors are classified
   the same way: `quota`, `plan`, `auth` or `transient`. The patterns are a short
   table at the top of the script (`FAILURE_CLASSES`, `REPLY_REFUSALS`,
   `TAIL_ERROR`).
8. **Opt-in prompt retry** (`--prompt-retries N`, default 0): a prompt that fails
   with a transient error before any tool call or permission request is retried
   with backoff (1, 2, 4 s, at most 10 s). Quota, plan and auth failures are not
   retried.
9. **Opt-in machine-load guard** (`--max-load L`, env `ACP_RUN_MAX_LOAD`): refuse
   to start (exit 75) while the 1-minute load average per CPU core is above `L`;
   `--load-wait SECS` (env `ACP_RUN_LOAD_WAIT`) waits up to that long for the
   load to drop first. Off by default.
10. **Clean interrupts**: SIGINT/SIGTERM send `session/cancel`, stop the agent
    and exit 130/143, so a killed run does not leave the agent running.

## Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | `end_turn` with some output |
| 1 | another stop reason, an agent error, an empty reply (no text and no tool calls; or no text under `--perm deny` or after a denied permission), or a delivery-check failure (quota, plan, auth, provider error, truncated reply) |
| 2 | usage error |
| 5 | empty reply and every permission request was denied (the code acpx uses) |
| 75 | refused to start by `--max-load` |
| 124 | timed out (`session/cancel` sent first, then the agent is killed) |
| 130, 143 | interrupted by SIGINT, SIGTERM |

A reply with text exits 0 even when every permission was denied (a `--perm
deny` review can still deliver its report); the summary line then carries a
`warning=`.

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

Several of the ideas above come from acpx (MIT): exit code 5, prompt retries on
transient errors, tool-kind inference from titles, cooperative interrupts.
