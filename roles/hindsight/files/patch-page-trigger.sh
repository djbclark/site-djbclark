#!/usr/bin/env bash
# Re-apply after any `npx @vectorize-io/hindsight-coding-agents install|update` — those
# overwrite dist/ and drop this patch. Installed by site-djbclark roles/hindsight, which also
# runs it from the hindsight-plugin-patch LaunchAgent whenever dist/ changes. Idempotent;
# safe to run any time.
#
# Why: the Hindsight HTTP API defaults trigger.exclude_mental_models to FALSE whenever a
# trigger object is passed (only the no-trigger path gets the document default of true), and
# every plugin release through 0.7.0 passes a trigger that omits the key. With false, the
# refresh agent searches the empty sibling pages first and never reaches observations, so
# every seeded knowledge page stays blank while still costing a full LLM refresh per cycle.
# Proven 2026-09-26 by API test on hindsight-api 0.9.0.
set -euo pipefail
cd "${HINDSIGHT_PLUGIN_DIR:-$HOME/.hindsight/coding-agents}/dist"
python3 - <<'PY'
import re, glob
pat = re.compile(r'(var PAGE_TRIGGER = \{\n  fact_types: \["world", "experience", "observation"\],\n  refresh_after_consolidation: true)\n\};')
rep = r'\1,\n  exclude_mental_models: true // local patch, see ../patch-page-trigger.sh\n};'
done = skipped = 0; bad = 0
for f in sorted(glob.glob('*.js')):
    s = open(f).read()
    if 'var PAGE_TRIGGER = {' not in s: continue
    if 'exclude_mental_models: true' in s: skipped += 1; continue
    s2, k = pat.subn(rep, s)
    if k: open(f, 'w').write(s2); done += 1
    else: bad += 1; print(f"NOT PATCHED: PAGE_TRIGGER shape changed in {f}", flush=True)
print(f"page-trigger: patched={done} already={skipped} not-matching={bad}")
raise SystemExit(1 if bad else 0)
PY
