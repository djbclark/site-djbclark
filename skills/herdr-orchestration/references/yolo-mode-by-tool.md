# Yolo-mode setup by tool

Flags last checked 2026-07-28; re-check each tool's `--help` before relying on them.

| Kind | Mechanism | Flag/setting |
| --- | --- | --- |
| `claude` | `~/.claude/settings.json` | `"permissions": {"defaultMode": "bypassPermissions"}` |
| `agy` (Antigravity) | shell alias (`.bashrc`) | `--dangerously-skip-permissions` |
| `codex` | shell alias | `--dangerously-bypass-approvals-and-sandbox` |
| `cursor-agent` | shell alias | `--yolo` (alias for `--force`) |
| `opencode` | shell alias | `--auto` |
| `copilot` | shell alias | `--allow-all` |
| `grok` | shell alias | `--always-approve` |
| `hermes` | shell alias | `--yolo` |

**`gemini` is not the same tool as `agy`, and `gemini` is broken as of
2026-08 — use `agy` for Gemini/Antigravity work.** Herdr lists `gemini` and
`agy` as separate kinds; `--kind gemini` launches the standalone Gemini CLI,
which now dead-ends at sign-in with "This client is no longer supported for
Gemini Code Assist for individuals. To continue using Gemini, please
migrate to the Antigravity suite of products." `--kind agy` launches the
Antigravity CLI, which is the actual working, authenticated Gemini agent on
this machine. Don't start `gemini` expecting it to work; go straight to
`agy`.

Shell aliases only expand in interactive shells — verify with `bash -ic "type
<cmd>"` after adding one, not `bash -c` (aliases silently don't apply there
and you'll wrongly conclude the alias failed). Check which rc file the
environment's default shell actually sources (this session's default shell
was bash → `.bashrc`, not `.zshrc`) before assuming an alias is live.

When a new agent kind shows up that isn't in this table, check its
`--help` output for `permission|skip|dangerous|yolo|auto|approv|sandbox`
before assuming there's no equivalent — every kind checked so far had one.

**This is a deliberate scope trade-off, not a default to copy blindly.**
Uniform full-bypass for every sub-agent is the opposite of the
capability-narrowing pattern most multi-agent write-ups recommend (a
child's permissions should be a *subset* of the parent's, narrower for
riskier work) — it's justified here because every agent in this chain is
trusted, on the operator's own machine, working against the operator's own
accounts, and running unattended for exactly the reason full bypass
removes: routine tool-permission friction. It stops being justified the
moment a unit's task genuinely involves something higher-stakes than that
— touching production credentials/secrets, an irreversible external action
(force-push, a real financial transaction, deleting something with no
backup), or a task from a source you haven't vetted. For those, don't
blanket-yolo the pane: scope the prompt to the specific action needed and
either leave that one tool gated (so it stops for a real approval) or do
the sensitive step yourself instead of delegating it.

**For a one-shot unit, an ACP call gives the narrower option for free.**
Over ACP the agent sends its permission requests to the client, so
`acp-run --perm scoped:<owned paths>` allows edits only inside the unit's own
files and `--perm deny` makes a review read-only, with no alias or bypass flag
at all. That only binds agents that ask (copilot and cline do; claude, cursor
and opencode mostly follow their own settings, so pick a stricter `--mode`).
The aliases above are for interactive Herdr panes. See SKILL.md, "Herdr pane
or ACP call?".

**Detect a genuinely stalled sub-agent, not just a slow one.** A `timeout`
from `agent prompt --wait` is expected on long tasks and is not itself a
problem (see ["Workflow per unit"](../SKILL.md#workflow-per-unit) step 5). It becomes one when `herdr agent get <name>`'s
`state_change_seq` hasn't moved across several consecutive checks spaced
minutes apart while the pane is still nominally `working` — that's the
"still thinking vs. actually stuck" distinction, and treating every
timeout as "just wait more" forever means a truly wedged pane never gets
noticed. If `state_change_seq` is flat for longer than the task's own
prompt would plausibly take, treat it as stalled: read the pane directly
(`herdr agent read <name> --source visible`) to see what it's actually
doing before deciding whether to nudge it (e.g. the `[Pasted text #1]`
case in [SKILL.md](../SKILL.md#workflow-per-unit) step 5), restart it, or reassign the unit.
