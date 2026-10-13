# sipb-llms-proxy

Loopback proxy (127.0.0.1:8890) between Crush and the SIPB LLMs server
(Open WebUI at llms-dev-1.mit.edu). It fixes three server quirks; see the
docstring in `sipb-llms-proxy`:

1. an over-long prompt returns HTTP 200 with a bare `null` body: the proxy turns
   it into a readable HTTP 400;
2. a tool-calling stream ends with `finish_reason: "stop"`: the proxy rewrites it
   to `tool_calls`, without which Crush ends the turn after one tool call;
3. a tool call the model wrote as *text* (the server did not translate it) is
   rewritten into a native `tool_calls` delta, without which Crush treats the
   turn as a plain answer and runs nothing. See "Text-form tool calls" below.

Since 2026-10-12 it also (all via env vars, defaults in the docstring):

3. serializes requests per model (`SIPB_MAX_CONCURRENCY`, default 1; the server
   loads one model at a time and is shared), with a queue timeout;
4. retries a POST on connection errors, HTTP 502/503/504 and an empty stream
   (`SIPB_RETRIES`, default 2), only before any byte reached the client;
5. appends one JSON line per POST to `~/.local/state/sipb-llms-proxy/requests.jsonl`
   (model, prompt chars, queue wait, time to first token, total, status, raw and
   sent finish_reason, retries; never content or the key): the evidence for
   reports to the SIPB sysadmins;
6. can prepend a rules file (`~/.config/sipb-llms-proxy/rules.md`, off unless the
   file exists; `X-Sipb-Rules: off` skips it) to the first system message of every
   chat request. NOT installed: the rules we use (`~/.config/crush/CRUSH.md`) are
   Crush-specific and would be wrong for Hermes or opencode.

Tests: `python3 tools/sipb-llms-proxy/test_proxy.py` (fake upstream, no network).

## Text-form tool calls (added 2026-10-13)

On some turns the SIPB server does not return a `tool_calls` delta at all: the
model puts its tool call in the message **content**, in a harness-specific
pseudo-syntax, and the server passes it through as text. Crush runs a tool only
when the delta carries `tool_calls`, so the turn silently does nothing. Observed
forms (2026-10-13), one per model:

| model | text-form call |
| --- | --- |
| qwen3.6:35b-a3b | `<tool_calls><invoke name="bash"><parameter name="command">…`, `<tool_use name="view"><crush_path>…`, `<file path=…>` |
| qwen3-coder:30b | `<function=ls><parameter=path>…</function>` |
| qwen3.5:35b | `<view><location>…</location></view>`, bare ```` ```bash ```` fences |
| deepseek-r1:32b | no syntax at all — a fabricated "[file created]" line |

The proxy recognises the **explicit** XML encodings and re-emits them as a native
`tool_calls` delta (`text_toolcalls()`), mid-stream: it holds the stream from the
first marker and, at end of stream, replaces the held text with the tool call.
Prose before the marker has already streamed. It deliberately does **not** touch a
bare ```` ```bash ```` fence — a model often prints a command just to show it, and
turning that into an executed command would be unsafe. So models that only emit a
fence (deepseek-r1:32b) are *not* rescued by this and should be dropped
(`crushrc`, REPORT.md section 4.7). Disable the whole feature with
`SIPB_NORMALIZE_TOOLCALLS=0` (default on).

Tests for it: the `test_normalize_*` cases in `test_proxy.py`.

No secrets: the API key travels in the client's `Authorization` header and is
forwarded untouched.

Deployed as launchd `land.charm.sipb-llms-proxy` (`land.charm.sipb-llms-proxy.plist`
here is a copy of `~/Library/LaunchAgents/`); the plist runs
`/usr/bin/python3 ~/.local/bin/sipb-llms-proxy`, which is a symlink to this file.
After editing: `launchctl kickstart -k gui/$(id -u)/land.charm.sipb-llms-proxy`;
the port takes about 30 s to open when the machine is heavily loaded.
Port 8890 is not in `registry/ports.yml` (adding it would make the landing-health
pager watch it).

Clients (2026-10-12): Crush (`~/.config/crush/crushrc`) and Hermes (provider `sipb-llms`
in `~/.hermes/config.yaml`, `base_url: http://127.0.0.1:8890/api`) both go through it;
opencode's `sipb` provider still goes direct. Reboots: it is a LaunchAgent with
`RunAtLoad` and `KeepAlive`, so it starts at login and restarts if killed (checked
2026-10-12 by bootout/bootstrap and `kill -9`); it needs no network to start. Like the
other agents on this machine it does not run before anyone has logged in.
