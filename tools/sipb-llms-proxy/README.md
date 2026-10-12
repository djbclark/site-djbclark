# sipb-llms-proxy

Loopback proxy (127.0.0.1:8890) between Crush and the SIPB LLMs server
(Open WebUI at llms-dev-1.mit.edu). It fixes two server quirks; see the
docstring in `sipb-llms-proxy`:

1. an over-long prompt returns HTTP 200 with a bare `null` body: the proxy turns
   it into a readable HTTP 400;
2. a tool-calling stream ends with `finish_reason: "stop"`: the proxy rewrites it
   to `tool_calls`, without which Crush ends the turn after one tool call.

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
