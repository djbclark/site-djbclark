# firecrawl-router live suite (2026-10-18)

Isolated router instances on ports 19101-19108 (commercial key blanked), reading the
service keys from the LaunchAgent plist with plistlib; nothing is printed.

1. `python3 -I suite.py OUTDIR` : 67 cases, about 45 min, `OUTDIR/summary.md`, `OUTDIR/leakscan.txt`.
2. `mkdir -p run3 && python3 -I suite_scripts_and_code.py` : 14 cases (Japanese, Korean, Russian, Chinese,
   Arabic, C source, deadline, directQuote abstain).

Both hit SIPB LLMs and the free LiteLLM pool; run when nobody else is using them.
Last result: 67/67 after the router fixes in ade 6aabe2b. The second round was 13/14 on the first run; its one
miss was a wrong expectation (an unreachable host comes back as success:false from the primary, passed through
by design), now relaxed in the script.
