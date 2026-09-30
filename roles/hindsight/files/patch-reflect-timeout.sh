#!/usr/bin/env bash
# Re-apply after any `npx @vectorize-io/hindsight-coding-agents install|update` — those
# overwrite dist/ and drop this patch. Idempotent; safe to run any time. Installed by
# site-djbclark roles/hindsight and re-run by its hindsight-plugin-patch LaunchAgent.
#
# Why: the hindsight_reflect MCP tool calls client.reflect(query, { budget: "high" }) with no
# timeoutMs, so it always aborts at the client default of 120 s and ignores reflectTimeoutMs in
# coding-agent.json (only the hooks' auto-reflect path reads that key). On the OpenCode Go pool
# a budget-high reflect took 90-270 s on 2026-09-30 under host load. The patch makes the tool read
# reflectTimeoutMs from the config on every call, so a config change needs no MCP restart.
# Found 2026-09-30 in plugin 0.3.4.
set -euo pipefail
cd "${HINDSIGHT_PLUGIN_DIR:-$HOME/.hindsight/coding-agents}/dist"
python3 - <<'PY'
import glob
old = 'client.reflect(query, { budget: "high" })'
new = 'client.reflect(query, { budget: "high", timeoutMs: loadConfig().reflectTimeoutMs }) /* local patch, see patch-reflect-timeout.sh */'
done = skipped = 0
for f in sorted(glob.glob('*.js')):
    s = open(f).read()
    if new in s: skipped += 1; continue
    if old not in s: continue
    if 'function loadConfig(opts = {})' not in s:
        print(f"NOT PATCHED: no loadConfig in {f}"); raise SystemExit(1)
    open(f, 'w').write(s.replace(old, new)); done += 1
print(f"reflect-timeout: patched={done} already={skipped}")
raise SystemExit(0 if done + skipped else 1)
PY
