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

## The local proxy (everything except opencode goes through it)

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
4. `~/.config/crush/CRUSH.md` (copy: `bench/rules.md`): five short rules for small models
   (no todo tools, one write per file, chain shell commands, act instead of describing, finish
   before stopping).
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
39 models listed (the server had 39 chat models on 2026-10-12, but newer ones such as
`qwen3.6:35b-a3b-q4_K_M` and `gemma4:26b` are not in Hermes' list yet). Not Hermes' default and
not in its fallback chain. Verify with the real CLI (a bare resolver call returns the literal
`${MIT_SIPB_API_KEY}` placeholder and a 401):

```bash
hermes -z "Reply with exactly: PONG" --provider sipb-llms -m qwen3.5:4b
```

Verified 2026-10-12: `PONG`, and the request appears in the proxy log. Note that Hermes' own
system prompt is ~110k characters (~28k tokens) per request, close to the 32k context.

## opencode

Provider `sipb` in `~/.config/opencode/opencode.json` (npm `@ai-sdk/openai-compatible`), 19-model
subset, key in `~/.local/share/opencode/auth.json` under `sipb`. Still points straight at
`https://llms-dev-1.mit.edu/api`, not the proxy. If opencode stops after one tool call on a SIPB
model, point its `baseURL` at `http://127.0.0.1:8890/api` (untested). Config is read at start-up.

## Verification status (2026-10-12)

1. `acp-run crush` on a small bug-fix task with `--verify`: pass, 38 s, provider `sipb-llms`.
2. Hermes through the proxy: `PONG`.
3. Proxy: tool-call stream raw `stop` sent as `tool_calls`, logged; reload from the plist and
   restart after `kill -9` both checked.
4. opencode: last checked 2026-08-19 (`opencode run --model sipb/qwen3.5:9b` printed `OK`).
