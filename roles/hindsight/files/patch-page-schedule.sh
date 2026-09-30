#!/usr/bin/env bash
# Re-apply after any `npx @vectorize-io/hindsight-coding-agents install|update` — those
# overwrite dist/ and drop this patch. Idempotent; safe to run any time. Installed by
# site-djbclark roles/hindsight and re-run by its hindsight-plugin-patch LaunchAgent.
#
# Why: the plugin creates knowledge pages and initiative pages with
# refresh_after_consolidation: true, so every consolidation re-runs a 1-5 minute reflect per
# page (~90 refreshes in 8.5 h on 2026-09-30). New pages start on a 6-hourly cron instead;
# bin/hindsight_page_schedule.py (same LaunchAgent) re-staggers each bank's pages within the
# hour. Also adds exclude_mental_models: true to the initiative-page trigger, which lacked it
# (the blank-page bug patch-page-trigger.sh fixes for the standard pages).
set -euo pipefail
cd "${HINDSIGHT_PLUGIN_DIR:-$HOME/.hindsight/coding-agents}/dist"
python3 - <<'PY'
import glob
marker = "/* local patch: page schedule */"
std_old = "  refresh_after_consolidation: true,\n"
std_new = '  refresh_after_consolidation: false, ' + marker + '\n  refresh_cron: "0 */6 * * *",\n'
ini_old = '          fact_types: ["world", "experience", "observation"],\n          refresh_after_consolidation: true\n        }'
ini_new = ('          fact_types: ["world", "experience", "observation"],\n'
           '          refresh_after_consolidation: false, ' + marker + '\n'
           '          refresh_cron: "0 */6 * * *",\n          exclude_mental_models: true\n        }')
done = skipped = bad = 0
for f in sorted(glob.glob('*.js')):
    s = open(f).read()
    if 'var PAGE_TRIGGER = {' not in s:
        continue
    if marker in s:
        skipped += 1
        continue
    if s.count(std_old) != 1 or s.count(ini_old) != 1:
        bad += 1
        print(f"NOT PATCHED: trigger shape changed in {f}", flush=True)
        continue
    open(f, 'w').write(s.replace(std_old, std_new).replace(ini_old, ini_new))
    done += 1
print(f"page-schedule: patched={done} already={skipped} not-matching={bad}")
raise SystemExit(1 if bad else 0)
PY
