# sipb-llms-proxy

Loopback proxy (127.0.0.1:8890) between Crush and the SIPB LLMs server
(Open WebUI at llms-dev-1.mit.edu). It fixes two server quirks; see the
docstring in `sipb-llms-proxy`:

1. an over-long prompt returns HTTP 200 with a bare `null` body: the proxy turns
   it into a readable HTTP 400;
2. a tool-calling stream ends with `finish_reason: "stop"`: the proxy rewrites it
   to `tool_calls`, without which Crush ends the turn after one tool call.

No secrets: the API key travels in the client's `Authorization` header and is
forwarded untouched.

Deployed as launchd `land.charm.sipb-llms-proxy` (`land.charm.sipb-llms-proxy.plist`
here is a copy of `~/Library/LaunchAgents/`); the plist runs
`/usr/bin/python3 ~/.local/bin/sipb-llms-proxy`, which is a symlink to this file.
After editing: `launchctl kickstart -k gui/$(id -u)/land.charm.sipb-llms-proxy`;
the port takes about 30 s to open when the machine is heavily loaded.
Port 8890 is not in `registry/ports.yml` (adding it would make the landing-health
pager watch it).
