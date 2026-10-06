---
name: skill-everywhere
description: >-
  Make a local skill available to every agent TUI on this machine (Claude Code,
  Codex, Copilot, Cursor, opencode, zcode, Grok, Qwen, crush, Devin, Cline,
  Muse, Antigravity and Hermes) by symlinking it from site-private/skills into each
  one's skills dir with bin/skill-everywhere, then proving each TUI actually
  loads it. Use when the operator asks to add, install, share, publish or
  "make available" a skill for all agents/TUIs, or when a new local skill is
  created that other agents should have too.
---

# skill-everywhere — one skill, every local TUI

The skill lives once, in `~/ops/site-private/skills/<name>/`. Every TUI gets a
**symlink** to it, so editing the git copy updates every agent. Never copy: a
copy drifts silently. `~/.agents/skills/handoff` is a symlink to the git
copy. The stale copy is `~/.agents/skills/.trash/`. Grok walks that tree
and can advertise the trash skill under the live name. Hide it with
`[skills] ignore` in `~/.grok/config.toml`, and link Grok's own
`~/.grok/skills` at the git copy too.

## 1. Link it

```sh
~/ops/site-private/bin/skill-everywhere <name>...          # link, idempotent
~/ops/site-private/bin/skill-everywhere --check <name>...  # status only
~/ops/site-private/bin/skill-everywhere --remove <name>... # undo
```

If the skill is not in `site-private/skills/` yet, move it there first; see
`skills/README.md`. The script skips TUIs that aren't installed. If a path
already exists and isn't our link, the script leaves it alone and exits non-zero.
Report that rather than overwriting it.

## 2. Where each TUI looks (verified 2026-10-03)

| TUI (binary) | How it gets the skill |
|---|---|
| Claude Code (`claude`) | `~/.claude/skills` |
| Codex (`codex`) | `~/.agents/skills` |
| Copilot (`copilot`) | `~/.copilot/skills` |
| opencode (`opencode`) | `~/.config/opencode/skills` |
| Qwen Code (`qwen`) | `~/.qwen/skills` |
| crush (`crush`) | `~/.config/crush/skills` |
| Devin (`devin`) | `~/.config/devin/skills` |
| Cline (`cline`) | `~/.cline/skills` |
| Hermes (`hermes`) | `~/.local/share/skill-everywhere/skills`, which Hermes put in its own `skills.external_dirs` |
| Cursor (`cursor-agent`), Muse (`muse`) | already read `~/.claude/skills`; no extra link |
| Grok (`grok`, including Grok Build) | `~/.grok/skills`. It also scans `~/.claude/skills` and `~/.agents/skills` and dedups by name. Verified 2026-10-04: a same-named `SKILL.md` under `~/.agents/skills/.trash` was the copy this session was offered, so `~/.grok/config.toml` ignores that trash dir and this script links the live skill here. |
| zcode (`zcode`) | already reads `~/.agents/skills`; an extra link listed it twice. **Loaded ≠ slash-invocable (2026-10-05):** zcode exposes only built-ins and plugin commands as bare `/<name>`; a user skill is invoked with the built-in `/skill <name>`, and a bare `/<name>` needs a command wrapper — `skills: <name>` frontmatter auto-mounts it — in `~/.zcode/commands/` (editable copies: `site-private/zcode/commands/`, symlinked like `claude/commands/`; first wrapper: `steps`). |
| Antigravity (`agy`) | `~/.gemini/antigravity-cli/skills` (agy CLI 1.2.16; links are followed). Verified with `/skills` in interactive agy. Headless `agy -p` answers never mention user skills, not even the installer's bailian ones, so check agy interactively. `~/.gemini/config/skills` and `~/.gemini/antigravity/skills` are not read by the CLI |

`aiuse --json` providers with no TUI of their own (alibaba, deepseek,
openrouter, litellm, opencode-zen, clinepass, grok) are API pools behind the
TUIs above, so they need nothing.

**Hermes owns `~/.hermes/`; never edit it yourself.** If the script warns that
the external dir has gone, ask Hermes to re-add it:
`hermes chat -Q -q "<request>" </dev/null`, and have it read the config back.

## 3. Prove it loaded

Configured is not the same as working. After linking a skill, or after changing
the table, ask each TUI from an empty scratch dir with stdin closed:

> Do not use any tools or read any files. If a skill named exactly '<name>' is
> available to you, reply with the first eight words of its description,
> verbatim; otherwise reply NOSKILL.

Use the recipes in `memory/feedback_headless_tui_invocation.md`. On 2026-10-03,
`cursor-agent` needed `--trust` and `devin` needed
`--respect-workspace-trust false` in a scratch dir. Offline checks:
`muse skills list` and `hermes skills list`; for agy, `/skills` in an interactive session. A NOSKILL from a model can be
wrong. When in doubt, ask it to list every skill name it has: that is how Cursor
turned out to be fine.

Codex was verified the same day: `codex exec -s read-only` quoted the
`steps` description verbatim from `~/.agents/skills`.

**agy: probe it at most once, never in a loop (2026-10-03).** Every headless
`agy -p` is at least one generation request, and the agy CLI has a burst limit
(roughly 60 requests an hour per login) that `aiuse` cannot see. Two sessions
looping "is a skill named 'steps' available" probes contributed to a CLI lockout
that returned `RESOURCE_EXHAUSTED (code 429)` on every model from 15:42 until
past 23:50, while `acp-run agy` still worked. So for agy: **a)** the offline
proof is `skill-everywhere --check <name>` (the link exists) plus one interactive
`/skills`, which makes no generation request; **b)** if a headless probe is
unavoidable, run exactly one with `--print-timeout 60s`, batch all the skill
names into that one prompt ("list every skill name you have"), and reuse the
answer for every skill in the batch; **c)** a log line
`attempt N failed (RESOURCE_EXHAUSTED` in `~/.gemini/antigravity-cli/log/cli-*.log`
means stop, not retry. See `model-routing` ("agy has a burst limit").
Actual delegated WORK never goes through `agy -p` at all — **`acp-run agy`
only** (standing rule 2026-10-04; the CLI throttle is client-keyed and survives
re-login). The one-probe CLI exception above exists only because the ACP
server's shadow GEMINI_HOME (`~/.local/share/agy-acp-home`) reads different
skill directories than the CLI, so an ACP answer cannot prove what the CLI sees.

A check can fail for reasons that have nothing to do with where the skill was
put: a usage limit, an expired login, or no provider configured. Report those
TUIs as unverified, not as broken, and re-check once the account works.

Hermes Telegram `/name` is a **slash command**, not a skill lookup. Linking
via this tool puts the skill in `skills.external_dirs`; it does **not**
register `/steps`. That lives in `~/.hermes/plugins/skill-slash` (`/steps`,
`/skill <name>`). Enable `skill-slash` in `plugins.enabled` and restart the
gateway from Terminal. Claude Code slash wrappers live in
`site-private/claude/commands/` (symlink into `~/.claude/commands/`).

## 4. When the table is wrong

Fix `bin/skill-everywhere` and the table above together, then re-run step 3
for the TUIs you changed. When a new TUI shows up in `aiuse --json` or under
`~/.local/bin`, find its skills dir from its docs or its binary, add a row, and
verify it.
