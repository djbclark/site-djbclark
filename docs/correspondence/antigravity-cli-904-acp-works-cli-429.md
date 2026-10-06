# Draft comment for google-antigravity/antigravity-cli#904 — NOT POSTED

Status: unsent draft, 2026-10-03. Shown to djbclark for approval before posting.
Searched existing issues first (open and closed: "RESOURCE_EXHAUSTED ACP",
"429 Resource has been exhausted", "rate limit burst"): nothing duplicates it,
so this is a comment on #904, not a new issue. Related: #1018 (headless runs
retry an exhausted quota until `--print-timeout`), #1152 (our ACP hook-runner
report, a different bug).

Differences from #904 as filed, stated in the comment so it is not read as a
"me too": our error text is `Resource has been exhausted (e.g. check quota)`,
not `Individual quota reached`, and `/usage` shows full headroom rather than a
"Starter" tier. We do not know it is the same defect.

---

Possibly related, with one data point that may help narrow it: on the same
account, the CLI gets `RESOURCE_EXHAUSTED (code 429)` on every generation
request while the ACP server works, with full quota shown.

- **CLI:** agy 1.2.16, macOS 27.0.1. From 15:42 local on 2026-10-03, every model
  (Gemini 3.8 Flash, 3.7 Flash, 3.1 Pro, Claude Sonnet 5.5) fails instantly:
  `Run: attempt 1 failed (RESOURCE_EXHAUSTED (code 429): Resource has been
  exhausted (e.g. check quota).), retrying in 4s`, through attempt 8, about 2m20s
  in all. Still failing at 23:50.
- **Quota as the CLI itself reports it:** `agy -p /usage` shows Gemini 5h 100%
  left / weekly 71% left, Claude+GPT 5h 100% left / weekly 49% left.
- **ACP, same account, same hour:** `agy_acp_server` 1.3.0 (its own shadow
  `GEMINI_HOME`, sharing the same `oauth_creds.json`) answered a one-line prompt
  with `gemini-3.8-flash-medium` in 6.5 s at 22:54.

So the account and the pool are fine and the lockout follows the CLI client. Our
guess, unverified: a per-client burst limit. The CLI made about 304 generation
requests between 12:00 and 14:59 (the busiest earlier hour was 68), most of them
from scripted `agy -p` calls, and the 429s started shortly after. If a
per-client rate limit exists, it would help to have it documented, and to have
the CLI report it as a rate limit with a reset time rather than as an exhausted
quota, because the current message sends users to check a quota that is full.

Happy to attach the CLI log (`attempt N failed` lines) if useful.

**Update 2026-10-04 (posted version includes this):** the lockout persisted
18+ hours and survived several logout/login cycles, so whatever keys the
throttle survives re-login (persistent client state, not the session). On
2026-10-04 08:12 local a usage probe still showed Gemini 5h ~1% used, and at
08:04 the CLI 429'd `gemini-3.8-flash-low` in the same minute that the ACP
server answered `gemini-3.1-pro-low` in 15.8 s. We also eliminated local
background callers as a cause: a quota sampler had been launching the CLI
(logged out, no generation requests) every 3 minutes; disabling it did not
clear the 429. Example Error ID from an interactive 429:
`4e24f4cf-4c89-431c-8883-8ead6462e871-9`.

Posted 2026-10-04 (operator approved via /loose step): see issue comment.
