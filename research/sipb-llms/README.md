# SIPB LLMs

MIT's **Student Information Processing Board** runs self-hosted, open-weight language models
for the MIT community. This directory is the one place for everything about using them from
this machine: the project background, a refreshed copy of SIPB's own docs, how it is wired
here, the benchmark and report for the SIPB admins, and an index of the code in other repos.
(Before 2026-10-12 the background and reference docs lived in `~/src/SIPB/docs/llms`; that
path is now a symlink to this directory.)

- Production instance: <https://llms-dev-1.mit.edu> (Open WebUI 0.6.30 in front of Ollama 0.32.13)
- Official project page and FAQ: <https://llms.mit.edu>, <https://llms.mit.edu/docs/faq>
- Sibling best-effort instance: <https://llms-dev-0.mit.edu> (not guaranteed online)
- Access: Touchstone login, often MITnet or VPN only (it was MITnet-only during maintenance on
  2026-08-15); the page returns 503 when it is down, overloaded or you are on the wrong network.
- Contact: `sipb-llms@mit.edu`, Matrix `almonds` on `matrix.mit.edu`, announcements list
  [`sipb-llms-users`](https://mailman.mit.edu/mailman/listinfo/sipb-llms-users). Project lead: Madison Landry.
- Stack facts and limits (one model on the GPU at a time, ~32768-token context, Friday 4-5 pm
  front-end updates, no fine-tuning, logs may be read for debugging): see [faq.md](faq.md) and
  [REPORT.md](REPORT.md).

## Files here

| file | what |
| --- | --- |
| [faq.md](faq.md) | SIPB's official FAQ, mirrored and re-checked 2026-10-12 |
| [api.md](api.md) | endpoint map, key format, behaviour not in the spec |
| [openapi.json](openapi.json) | the Open WebUI OpenAPI spec served at `/openapi.json` (refreshed 2026-10-12) |
| [setup.md](setup.md) | how Crush, Hermes, opencode and the proxy are wired on this machine |
| [REPORT.md](REPORT.md) | measurements, problems and suggestions for the SIPB admins (2026-10-12) |
| [skills/sipb-llm-bench](https://github.com/djbclark/djbclark-ade/tree/master/skills/sipb-llm-bench) | the same harness packaged as a reusable skill (any model, one at a time, plus how to update the report); `bench/` below is the exact copy the report's numbers came from |
| [bench/](bench/) | raw benchmark rows (`results.jsonl`), the harness (`bench.py`), the tool-call conformance check (`toolcall_conformance.py`), the agent rules file (`rules.md`), the Crush config without the key (`crushrc.example`) |

## Related material in other repositories

Public (GitHub, owner `djbclark`):

1. **site-djbclark**: [`tools/sipb-llms-proxy/`](https://github.com/djbclark/site-djbclark/tree/master/tools/sipb-llms-proxy)
   (the loopback proxy, its README, tests and launchd plist) and this directory,
   [`research/sipb-llms/`](https://github.com/djbclark/site-djbclark/tree/master/research/sipb-llms).
2. **aiuse**: [`docs/sipb-quota.md`](https://github.com/djbclark/aiuse/blob/main/docs/sipb-quota.md),
   the collector [`src/aiuse/collectors/sipb.py`](https://github.com/djbclark/aiuse/blob/main/src/aiuse/collectors/sipb.py),
   [`tests/test_sipb.py`](https://github.com/djbclark/aiuse/blob/main/tests/test_sipb.py), the
   `[collectors.sipb]` block in [`config/config.example.toml`](https://github.com/djbclark/aiuse/blob/main/config/config.example.toml),
   and the [collector handoff](https://github.com/djbclark/aiuse/blob/main/docs/handoffs/HANDOFF_aiuse-1gy_sipb-collector_2026-10-10_fb72.md).
3. **djbclark-ade**: the `crush` entry and the `--verify` option in
   [`tools/acp-run/acp-run`](https://github.com/djbclark/djbclark-ade/blob/master/tools/acp-run/acp-run)
   ([README](https://github.com/djbclark/djbclark-ade/blob/master/tools/acp-run/README.md)), and the temporary
   "Crush over ACP" build recipe in
   [`docs/apply-toolchain-prompt.md`](https://github.com/djbclark/djbclark-ade/blob/master/docs/apply-toolchain-prompt.md).
4. **crush** (fork of charmbracelet/crush): the `--yolo` work in
   [PR #3909](https://github.com/charmbracelet/crush/pull/3909); the ACP server it runs on is the
   unmerged upstream [PR #2450](https://github.com/charmbracelet/crush/pull/2450).

Private (`site-private`, visible to the author only): `memory/basic-memory/hermes/sipb-llms-hermes-provider.md`
(how the Hermes provider was added), `memory/project_hermes_value_routing_2026-09-29.md` (the MITnet/VPN
note), `memory/project_crush_removed_2026-10-08.md` (superseded Crush history),
`memory/handoffs/site-djbclark/HANDOFF_standalone-fd48_ai-tooling-load-reduction_2026-09-26_2ae0.md`.

Not in any repository: `~/.config/crush/crushrc` and `CRUSH.md` (the crushrc holds the key),
`~/.hermes/config.yaml` (provider `sipb-llms`), `~/.config/opencode/opencode.json` (provider `sipb`),
`~/Library/LaunchAgents/land.charm.sipb-llms-proxy.plist` (a copy is in the proxy directory).
