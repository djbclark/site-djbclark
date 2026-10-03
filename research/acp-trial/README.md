# ACP trial — driving agent CLIs over the Agent Client Protocol

2026-10-03. Question: should headless delegation to other agent CLIs use the
[Agent Client Protocol](https://agentclientprotocol.com/) instead of each
CLI's own `-p`/`run` mode plus output scraping?

**Verdict: yes, as the transport for ACP-capable agents.** All three agents
tried did the task correctly over ACP. Over ACP they also reported what they
did: structured tool calls, every permission request, and token usage with
cost. Headless mode for two of them returned only the word `DONE`. Speed and
cost were about the same. ACP does not replace an orchestrator (worktrees,
supervision, panes a human can watch). It is the channel between the
orchestrator and one agent.

## Method

- **Task.** Fix a one-character bug in `fixture/calc.py` so that
  `python3 test_calc.py` prints `OK`, without editing the test, and finish with
  `DONE` or `FAILED`.
- **Isolation.** Each run got a fresh copy of `fixture/`. All six ran in
  parallel.
- **ACP side.** `trial_client.py` is a ~90-line client on the official
  [Python SDK](https://github.com/agentclientprotocol/python-sdk)
  (`agent-client-protocol`). It spawns the agent over stdio, sends one prompt,
  approves any permission request with the agent's `allow_once` or
  `allow_always` option (and logs it), and records every `session/update`. It
  advertises no client fs or terminal capabilities, so the agents use their
  own tools.
- **Headless side.** Each CLI's usual one-shot mode, with the permission flags
  we normally need.
- **Check.** Afterwards we run the test ourselves and byte-compare the test file
  against the original (`run_trial.sh`).

| Agent | ACP command | Headless command |
|---|---|---|
| opencode | `opencode acp` | `opencode run "<p>"` |
| Copilot CLI | `copilot --acp` | `copilot -p "<p>" --allow-all-tools --allow-all-paths --silent` |
| Claude Code (Sonnet 5.5) | `npx -y @agentclientprotocol/claude-agent-acp` | `claude -p "<p>" --permission-mode bypassPermissions --output-format json` |

## Results

| Agent | Mode | Test passes, test file untouched | Wall time | What the caller learns |
|---|---|---|---|---|
| opencode | ACP | ✅ | 33.7 s | 6 tool calls, 13 tool updates, 7 thought chunks; 248k tokens (210k cached), cost $0 |
| opencode | headless | ✅ | 36.9 s | the text `DONE` (12 bytes) |
| Copilot | ACP | ✅ | 43.1 s | 8 tool calls, **5 permission requests** routed to the client, 380 thought chunks; 231k tokens (201k cached) |
| Copilot | headless | ✅ | 45.9 s | the text `DONE` |
| Claude | ACP | ✅ | 43.3 s | 3 tool calls, 10 tool updates; 167k tokens; cost $0.21 |
| Claude | headless | ✅ | 19.8 s | final text plus usage and cost in `--output-format json` ($0.27) |

Raw data: `results/` (per-run summaries, wall clock, verification). The full
per-event JSONL logs (19–222 KB each) were kept out of the repo.

## Findings

1. **Reliability: same.** 6/6 runs succeeded. One trivial task can't separate
   the two modes on reliability. The known headless failure modes (output cut
   off, a hang on an approval nobody can answer, exit 0 with no output) would
   need longer tasks to trigger.
2. **Observability: ACP is far better.** For opencode and Copilot, headless
   mode tells the caller nothing beyond the final word. Over ACP every tool call
   arrives as a typed event with a title and status, and all three agents
   reported token usage. Copilot's usage is otherwise invisible.
3. **Permissions move to the orchestrator.** Over ACP Copilot needed none of its
   `--allow-all-*` flags. It sent five `session/request_permission` calls, with
   titles such as "Update file" and "Run calculator tests", and the client
   decided each one. A real orchestrator could allow edits only inside a slice's
   owned files and refuse the rest. That is a per-call version of bigteam's
   file-ownership rule. opencode and the Claude adapter sent no requests: both
   followed their own local permission settings and auto-allowed. So
   per-call control depends on each agent's mode settings.
4. **Cost: same.** Claude cost $0.21 over ACP vs $0.27 headless; the difference
   is cache variance, not the protocol.
5. **Startup cost for adapters.** The Claude adapter's 43 s vs 20 s headless is
   mostly `npx -y` fetching and starting the adapter. Installing it globally
   would remove most of that.
6. **Side effects come with the agent, not the protocol.** Copilot built a
   graft index in its run directory, because the global instructions tell
   agents to. The same happens headless.

## Not tested

These are the next questions, in order:

1. Cancelling and timeouts (`session/cancel`) on a long task.
2. Agents with native ACP that were not tried: qwen (its token had expired),
   devin, cline (needs re-login), goose (no provider set up), hermes, and Codex
   via `@agentclientprotocol/codex-acp`.
3. Long multi-file tasks, where headless output scraping actually breaks.
4. Restricting permissions in the client instead of auto-allowing.

## Recommendation

1. Turn `trial_client.py` into a small `acp-run <agent> <dir> <prompt>`
   wrapper. It would write the full event log to a file, return the final text
   plus a usage line, and take a permission policy (allow everything, allow
   edits only under listed paths, or deny). Use it in bigteam/model-routing
   instead of the per-CLI `-p` recipes wherever the agent speaks ACP.
2. Keep the per-CLI headless recipes for agy, zcode, crush and muse, which
   have no ACP mode.
3. Keep Orca/Herdr for supervision and visible panes. ACP would sit under
   them, not replace them.

## Follow-up: `acp-run` (same day)

The recommendation above was built: `site-private/bin/acp-run` is a uv
inline-script client on the official SDK. It wraps 10 agents and has
permission policies, `--model` (via ACP session config options), `--mode`, a
timeout that sends `session/cancel` (exit 124), and a JSONL log per run. The
same bug-fix task, run through it:

| Agent | Result |
|---|---|
| claude (adapter, npm -g), copilot, cursor (`cursor-agent acp`, needs `authenticate` with `cursor_login`), devin, cline, opencode | ✅ fixed, test passes |
| hermes | ❌ transport fine and `end_turn`, but the reply was a provider error from its ACP default model. **Exit 0 is not success.** |
| qwen | ❌ 401, expired token (needs re-login) |
| goose | ❌ no provider configured |
| codex (`codex-acp` adapter) | not run (usage limit) |

Also verified:

1. **`--perm scoped:calc.py`**: Copilot sent 6 permission requests, all inside
   scope, so all were allowed, and the fix landed.
2. **`--perm deny`**: Copilot's edit was refused and the test still failed, as
   intended.
3. **`--timeout 4`** on a long task: `session/cancel` was sent, the agent
   stopped with `cancelled`, exit 124.
4. **`--model` matters.** The claude adapter defaults to the user's settings
   model (Fable here): $1.33 for this task, versus $0.22 with `--model sonnet`.

