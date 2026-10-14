# SIPB LLMs: how it is wired into this machine

Base URL `https://llms-dev-1.mit.edu/api` (OpenAI-compatible Open WebUI). Endpoint map and
gotchas: [api.md](api.md). Project background and the index of related material:
[README.md](README.md). Measurements: [REPORT.md](REPORT.md). Rewritten 2026-10-12 (the
2026-08-19 version covered only opencode and Hermes).

## Credential

One managed secret, `MIT_SIPB_API_KEY`, in sudo-secretspec (profile `site-private`):

```bash
sudo-secretspec add MIT_SIPB_API_KEY --description "MIT SIPB API key" --reason "save new MIT SIPB API token"
sudo-secretspec set  MIT_SIPB_API_KEY --reason "save new MIT SIPB API token"
```

Value: `sk-` + 32 hex chars (35 chars), from the Open WebUI UI (profile icon, Settings,
Account, API keys). Store it verbatim with no trailing newline ([api.md](api.md) gotcha).
Consumers read it with `sudo-secretspec run -- <cmd>` and expand `$MIT_SIPB_API_KEY`
inside the child. Exception, left as is by the owner: `~/.config/crush/crushrc` holds the
key in plain text (mode 600).

## The local proxy (Crush, Hermes and opencode all go through it)

`tools/sipb-llms-proxy` in site-djbclark, launchd `land.charm.sipb-llms-proxy`,
`127.0.0.1:8890`, upstream `https://llms-dev-1.mit.edu`. It rewrites the wrong
`finish_reason`, turns the `null` reply into a 400, serializes requests per model, retries
502/503/504 and empty streams, and logs latency to
`~/.local/state/sipb-llms-proxy/requests.jsonl`. LaunchAgent with `RunAtLoad` and
`KeepAlive`: starts at login and restarts when killed. Restart:
`launchctl kickstart -k gui/$(id -u)/land.charm.sipb-llms-proxy`.

## Crush (and `acp-run crush`)

1. Provider and models in `~/.config/crush/crushrc` (`provider add sipb-llms`, base URL
   `http://127.0.0.1:8890/api`). Default model `sipb-llms/qwen3.6:35b-a3b-q4_K_M` with
   `--think` (large and small are the same, so only one model is ever loaded for us);
   `qwen3.5:35b` is the fallback. Chosen from the 2026-10-12 benchmark ([REPORT.md](REPORT.md)).
2. Lean profile: about 150 `option disable-skill` lines and a `permissions deny` list
   (todo, web, lsp, MCP-resource tools). With the default tool set the prompt was ~28k tokens
   of the 32k window and a turn took ~34 s; lean turns take ~5 s.
3. `option request-timeout 600`: Crush's default 2-minute idle timeout aborted turns while the
   shared server was queueing.
4. `~/.config/crush/CRUSH.md` (copy: `bench/rules.md`): seven short rules for small models
   (no todo tools, one write per file with a relative path, chain shell commands, act instead of
   describing, finish before stopping, `web-digest` before digging, skills on demand through
   `skill-get`). `web-digest` and `skill-get` are for
   small-context models only.
4a. No permission prompts (2026-10-14): `~/.bashrc`'s `crush()` adds `--yolo` to the stock Homebrew
   Crush (v0.98.1; the fork is not used for the TUI), and crushrc ends with a `PreToolUse` hook:
   `hook add PreToolUse --name auto-allow --command ~/.config/crush/hooks/auto-allow.sh` (copy: `bench/auto-allow.sh`; it prints `{"decision":"allow"}` unconditionally). acp-run runs every agent yolo (operator, 2026-10-14): `--perm scoped:` and `ask` are deprecated, warn once and run as
   `all`; `--perm deny` still works for crush (tools off, hook stripped). The hook
   pre-approves every tool call (upstream `docs/hooks/README.md`), so bare launches (Orca, herdr, zsh)
   and tools added upstream later do not prompt either. Verified in the real TUI under tmux: `bash`,
   `view`, a `write` outside the project and the `agent` tool all ran silently ("Hook auto-allow -> OK"
   in the transcript). `permissions allow <tool>` is NOT the way: it matches exact tool names only, so a
   new tool prompts (the control run without the hook showed "Permission Required"). `ctrl+y` toggles
   Yolo in the TUI. Skills: press `/` (opens the palette), type `skill`, Enter, fill SKILL and TASK.
   Do NOT use `permissions yolo` in crushrc: it is a fork-only verb; brew crush v0.98.1 aborts config
   load with `unknown subcommand "yolo"` (hit and reverted 2026-10-14).
4b. `web-digest` shown as text (2026-10-14): twice in the real TUI Qwen answered a search request by typing
   `web-digest "..."` (once inside `<tool_use>...</tool_use>`) as its reply instead of calling bash, so
   nothing ran. Rewording rule 6 did not stop it (the second failure came after), and 11 single-turn
   trials had not reproduced it, so the model evidently treats `web-digest` as a tool of its own.
   Fix: `web-digest-mcp` (djbclark-ade `bin/`, stdlib stdio MCP server, one tool) registered in
   crushrc with `mcp add web --type stdio --command ~/.local/bin/web-digest-mcp`; the model now calls
   `mcp_web_web_search` (4 of 4 TUI trials, sidebar shows `web 1 tools`). Small-context models only.
   Third failure (`[mcp_web_web_search(query="hyades.mit.edu")]` as text, wrong argument name) led to the
   proxy fix: `sipb-llms-proxy` now converts that form, `<tool_use>NAME "arg"</tool_use>` and a bare
   `web-digest "q"` reply into native calls for tools the request offered, and writes every converted,
   unmatched or suspect message to `~/.local/state/sipb-llms-proxy/toolcall-capture.jsonl` (0600) so the
   converter can be tuned. Details: `tools/sipb-llms-proxy/README.md`; prior art and the LLMLingua test:
   `prior-art-small-context.md`.
5. `acp-run crush -C <dir> -p '...' [--verify 'python3 -m unittest discover']` runs the PR #2450
   build `crush-acp` with `--yolo`. Run it without `--model`. The entry sets
   `CRUSH_GLOBAL_DATA=~/.local/share/crush-acp` because the shared data dir
   (`~/.local/share/crush/crush.json`, written by the interactive TUI) overrides `crushrc`: a Charm
   Hyper login there sent every turn to Hyper on 2026-10-12.
6. The build recipe for `crush-acp` is in `djbclark-ade/docs/apply-toolchain-prompt.md`.

## Hermes

Provider `sipb-llms` in `~/.hermes/config.yaml`: `base_url: http://127.0.0.1:8890/api` (since
2026-10-12; the proxy gives it the finish_reason fix, retries and the log), `api_key_env`
`MIT_SIPB_API_KEY` (in `~/.hermes/.env`), `api_mode: chat_completions`, `discover_models: false`,
39 models listed (the same 39 chat models the server lists, including `qwen3.6:35b-a3b-q4_K_M` and
`gemma4:26b`; checked 2026-10-12). Not Hermes' default and
not in its fallback chain. Verify with the real CLI (a bare resolver call returns the literal
`${MIT_SIPB_API_KEY}` placeholder and a 401):

```bash
hermes -z "Reply with exactly: PONG" --provider sipb-llms -m qwen3.5:4b
```

Verified 2026-10-12: `PONG`, and the request appears in the proxy log. Note that Hermes' own
system prompt is ~110k characters (~28k tokens) per request, close to the 32k context.

## opencode

Provider `sipb` in `~/.config/opencode/opencode.json` (npm `@ai-sdk/openai-compatible`), 19-model
subset, key in `~/.local/share/opencode/auth.json` under `sipb`. `baseURL` is
`http://127.0.0.1:8890/api` (the proxy) since 2026-10-12 (backup of the old file:
`~/backups/opencode.json.pre-sipb-proxy-2026-10-12`). Config is read at start-up. opencode's own
system prompt is ~105k characters (~26k tokens), so a first call after a model swap can take minutes
and a second request for the same model queues behind it in the proxy (`queue_wait_s` in the log).

## Verification status (2026-10-12)

1. `acp-run crush` on a small bug-fix task with `--verify`: pass, 38 s, provider `sipb-llms`.
2. Hermes through the proxy: `PONG`.
3. Proxy: tool-call stream raw `stop` sent as `tool_calls`, logged; reload from the plist and
   restart after `kill -9` both checked.
4. opencode through the proxy: `opencode run --model sipb/qwen3.5:9b "Reply with exactly: OK"` printed `OK` and
   appears in the proxy log (2026-10-12).

## Base-prompt measurement and trims (2026-10-14)

Captured a real Crush request (fake local upstream on :8899, `crush run` in an empty dir, config copy with the
base URL swapped): **39,877 chars, ~10k tokens, before any project `AGENTS.md`** (the aiuse sessions started
at 16k with a 16.5 KB one). System prompt 23.9k chars (Crush's built-in template: critical_rules, editing_files,
decision_making, workflow ...; not editable), 10 tool schemas 14.7k chars (`bash` alone 8.5k: its git/PR guidance).
Trims, now 35,382 chars (-11%, about 1.1k tokens), 8 tools, no skills section:
1. `permissions deny agent multiedit` (sub-agent and multiedit schemas, 1.4k chars).
2. `option disable-skill crush-config`, `crush-hooks` (the builtin skills) and `forgejo-ci` (a new skill had
   leaked into every request: the old lean profile disabled skills by name, so each new skill cost context).
3. `~/.bashrc` `crush()` sets `CRUSH_SKILLS_DIR=~/.config/crush/skills-none` (an empty dir): no global skill is
   listed, whatever is added later; the disable lines remain the fallback for launches that skip the wrapper
   (Orca, herdr, bare binary). Skills load through `skill-get` and the `/` palette.
Not trimmed (not ours or not safe): the built-in system template and the `bash` description (upstream text),
the project's `AGENTS.md` (project-specific: keep it short in repos you run Crush in), CRUSH.md (7 rules, ~2.3k chars).
Backups: `~/.bashrc.bak-2026-10-14`, `~/.config/crush/crushrc.bak2-2026-10-14`.


## Context files load twice, and the 32k window summarizes every turn (2026-10-14)

Symptom (aiuse repo): `missing required parameter: pattern` from `grep`, the model wandering into unrelated
files, then an endless loop of "The previous session was interrupted because it got too long, the initial user
request was: `The previous session ...`" (each turn nests one more level).

Cause, measured: Crush loads every default context path (`AGENTS.md`, `CLAUDE.md`, ...) and dedupes by
lower-cased path name, not real path (`internal/agent/prompt/prompt.go` `loadContextFiles`). Every repo here has
`CLAUDE.md -> AGENTS.md`, so the file is sent twice. Test (`crush run` in a temp dir, 10 KB `AGENTS.md`):
45,367 chars / 16,762 tokens without the symlink, 55,639 chars / 19,906 tokens with it. aiuse (16.5 KB
`AGENTS.md`): 72.9k chars, about 27k tokens, above Crush's auto-summarize trigger for a 32,768 window
(`smallContextWindowRatio` 0.2: summarize when under 6,553 tokens remain, i.e. above ~26.2k used). So every
turn is followed by a summarize call, whose output re-enters as the next "initial request". Default context
paths are appended to, never replaced, so `context_paths` cannot exclude `CLAUDE.md`.

Not proven: that the missing `pattern` argument comes from the full window (the failing calls were at 69-72k
chars, but one call at 72.6k chars did carry `pattern`).

Update 2026-10-14: the dedupe bug is upstream issue #4018 with fix PR #4022 (open, CLA unsigned); the missing
ask/opt-out is filed as charmbracelet/crush#4070. Local stopgap: `~/src/djbclark-ade/bin/crush-context-check`, called by
the `crush()` shell function before the TUI starts: lists the files Crush will load (sizes, token estimate against the
summarize trigger, symlink pairs shown as sent twice) and asks y / always-for-this-directory / N. `CRUSH_CONTEXT_OK=1
crush` skips it. Free workaround: start Crush from a subdirectory with none of these files (verified: 34,960 chars,
the base prompt only). The only global paths are `~/.config/crush/CRUSH.md` and `~/.config/AGENTS.md`.

Options: (a) upstream patch, dedupe context files by `filepath.EvalSymlinks`; (b) keep each project's
`AGENTS.md` under ~6 KB where Crush runs; (c) `disable_auto_summarize` only hides the loop (the prompt still
overflows).
