---
name: model-routing
description: >-
  Route AI work by vendor × model × effort across every service on this
  machine: map aiuse --json lines to their TUIs, know which pools are
  monthly subscription vs prepaid vs free, spot chronically-unused quota
  worth burning, and pick the right AI for the kind of work. Use when
  choosing which agent/model/service should run a task, before big
  multi-agent runs, when a quota window is tight, or when asked "which AI
  should do X", "what models do we have", or about aiuse output.
---

# Model routing on this machine

Canonical source of this skill: `skills/model-routing/SKILL.md` in the
djbclark-ade repo (github.com/djbclark/djbclark-ade); the copy at
`~/.claude/skills/model-routing/` is the deployed live copy — keep them
identical.

The canonical, dated matrix lives at
`~/orca/projects/djbclark-ade/docs/model-routing.md` (repo
djbclark/djbclark-ade). Read it first; this skill carries the stable
method, not the volatile numbers.

## Probes (prefer these over a hand-kept snapshot; aiuse's own cache is fine while fresh)

- **`aiuse --available`** (aiuse 3.1.4+, github.com/djbclark/aiuse) — the routing
  shortlist: only usable pools, one line per vendor AND model family, sorted by
  headroom, every window as "X% used / Y% left". Reads the snapshot cache (<1 s,
  age on the first line); `--live` forces a ~30-60 s collect; `--json` is the
  machine form. Exit 0 = pools exist, **3 = nothing usable**, 1 = error. The
  cache (`~/.cache/aiuse/snapshots/latest.json`) stays fresh because the operator
  often runs `aiuse watch` and a launchd job snapshots hourly; treat it as good
  while it says `fresh`, and still preflight each target (item 5 below), since no
  snapshot sees a pool drained in the last few minutes. `aiuse serve` defaults to
  port 28787 and is not running here.
- `aiuse --json -q` — everything, including exhausted pools. Schema 1.1 is
  self-describing: per window `state` (`exhausted` <=1% left, `tight` <15%, `ok`,
  `unknown`), `headroom_percent`, and `pool_family` + `models_hint` on split
  vendors; per account `usable_now`, `binding_window`, `available_at`,
  `age_seconds`; top level `summary_lines`, `semantics`, `agent_notes`, `fresh`.
  Ignore its `kind:"conserve"` pace alerts for go/no-go calls.
- `aiuse note-exhausted <provider> [--family F] --resets-in 4h53m [--reason T]` —
  after a 429 you actually saw, record it so the next agent skips that pool until
  its reset (advisory, expires, shown as `source: agent-reported`).
  `~/ops/site-private/bin/aiuse-pools` is a thin wrapper around `--available`.
- `cswap list` — Claude accounts + 5h/weekly/Fable windows.
- `codex login status`; `opencode models`; `bl quota list`;
  `curl -s localhost:4000/v1/models` (LiteLLM/ClinePass);
  `agy --version`; `devin --version`; `copilot --version`.
- Orca's agent roster + per-agent launch flags:
  `~/Library/Application Support/orca/profiles/local-default/orca-data.json`
  → `settings.agentDefaultArgs` / `disabledTuiAgents`. Nearly every TUI
  is configured inside Orca; macro-graph dispatch reaches any enabled one.

## Reading quota numbers (a misreading here already cost a dispatch round)

`aiuse --available` / `--json` now bake these rules into their output; use them for
any raw number from another source.

1. **`used_percent` is the share CONSUMED; 100 means empty.** `remaining_percent`
   is the headroom. Decide from `remaining_percent` and never quote a bare
   percentage: write "100% used / 0% left". On 2026-10-03 `Codex 5-hour quota:
   100` was read as "100% free" and a review was sent to an exhausted codex.
2. **An account is usable only if every one of its windows has headroom.** The
   fullest window binds: codex at 100% used on its 5-hour window is unusable for
   ~5 hours even with its weekly window at 35% used.
3. **One TUI can hold several independent pools, one per model family.** agy:
   Gemini and Claude/GPT are separate pools (`agy models`); Claude: ordinary vs
   Fable bucket; Cursor: Auto/included vs "other models". A 429 or
   `RESOURCE_EXHAUSTED` describes the pool the chosen model draws on, not the
   vendor. Retry on a model from the vendor's other pool before declaring the
   vendor spent (agy: a `gemini-*` model when a `claude-*`/`gpt-*` one is
   exhausted, and vice versa), and pick the model by which pool is fresh, not
   only by which is strongest.
4. **State moves within a session.** agy's Claude/GPT 5-hour window read 0% used
   at probe time and was exhausted ~35 minutes later (weekly 0% to ~51%), around
   the time one Opus-high review ran on it; other sessions use agy too, so the
   cause is inferred. Re-probe before each batch.
5. **Preflight** each target with one trivial call through the exact invocation
   and model about to be used (`"Reply with exactly: OK"`); `usage limit`,
   `RESOURCE_EXHAUSTED` or 429 means that pool is spent. Note the reset time the
   error prints.

### agy has a burst limit that `aiuse` cannot see (incident 2026-10-03)

**`aiuse` headroom does not mean agy can generate, and agy's two clients fail
independently.** From 15:42 local on 2026-10-03 every `agy` **CLI** generation
request (Gemini 3.8/3.7 Flash, 3.1 Pro, Claude Sonnet 5.5) got an instant
`RESOURCE_EXHAUSTED (code 429)`, while `agy -p /usage` and `aiuse --json` showed
Gemini 5h 100% left / weekly 71% left and Claude+GPT 5h 100% left / weekly 49%
left. At 22:54, on the same account, `acp-run agy --model gemini-3.8-flash-medium`
answered in 6.5 s. The CLI login (`~/.gemini/antigravity-cli`) was locked out,
not the account; the ACP server (`agy_acp_server` 1.3.0, shadow GEMINI_HOME
`~/.local/share/agy-acp-home`) is a separate client. A probe at 23:50 still got
`attempt 1..5 failed (RESOURCE_EXHAUSTED` in 60 s, then `--print-timeout` cut it.

**Update 2026-10-04: the CLI lockout persisted 18+ hours and re-login cannot
clear it.** The throttle keys on persistent client state
(`~/.gemini/antigravity-cli/installation_id` survives logout/login), and it held
while a working quota probe showed Gemini 5h **1% used**. `acp-run agy` answered
in 15.8 s the same minute the CLI 429'd a flash model. So the CLI surface can be
dead for a day with a full quota and nothing an agent does locally will revive
it — route around it, don't retry it.

**Likely cause (inferred, not published by Google): a per-client burst limit.**
Between 12:00 and 14:59 the agy CLI made about **304 generation requests**; the
busiest earlier hour had 68. One bigteam `claude-opus-5-5-high` review alone was
47 requests, and two sessions looped skill-detection `agy -p` probes. Count
**requests, not calls**: a tool-using agy turn is many requests. Treat roughly
**60 requests/hour per CLI login** as the budget, i.e. about one review an hour.
`aiuse`/CodexBar launching `agy -p /usage` every few minutes adds CLI launches
but no generation requests.

Rules for any agent that dispatches to agy:

1. **Cap the calls.** No probe loops, no per-skill or per-TUI "do you see X"
   loops. One probe, then reuse the answer. Sequential `agy -p` calls count the
   same as concurrent ones against the hourly budget.
2. **Always pass `--print-timeout`** (for example `--print-timeout 120s`). agy
   retries a 429 in-process 8 times with backoff (~2m20s), so an exhausted CLI
   looks like a hang. A log line `Run: attempt N failed (RESOURCE_EXHAUSTED` in
   `~/.gemini/antigravity-cli/log/cli-*.log` is a **fast fail**: stop, do not
   wait out the retries or retry the call.
3. **Delegate only via `acp-run agy` — never `agy -p`** (standing rule
   2026-10-04). The CLI surface throttles independently of quota and of the ACP
   client, and its lockouts are client-keyed and survive re-login, so a CLI
   dispatch can silently hit a dead client for hours. `agy -p` is not a
   fallback; the interactive TUI is for the operator. If a CLI call is truly
   unavoidable (e.g. probing CLI-local state the ACP shadow home cannot see),
   run exactly one with `--print-timeout`. When one client returns 429 while
   `aiuse` shows headroom, **try the other client** before moving the slice to
   another vendor. Preflight the exact client you will use.

   **`acp-run claude` handshake flake:** `session/new` can hang after a successful
   `initialize` (claude-agent-acp `newSession` awaits `providerUpdate` with no
   timeout). `acp-run` retries handshake twice (40s each) then falls back to
   `claude -p --model … --dangerously-skip-permissions` unless `--no-fallback`.
   Do not wait out a hung ACP process.
4. **Send Opus-high work to agy sparingly.** The Claude/GPT pool is small (5h
   window, ~35 minutes to drain on 2026-10-03). Prefer a `gemini-*` model for bulk
   work, and spend `claude-*` on agy only where nothing else fits.
5. A `--print-timeout` cut prints `[agy] print timeout ... returning partial
   output` and **exits 0**; exit 0 is not success, read the output and the log.

## Billing classes (2026-08-23 shape; membership drifts)

- **Monthly subscription windows**: claude (5h/weekly/+Fable bucket),
  codex (ChatGPT Plus weekly), antigravity/agy (Google AI Pro — also
  exposes Claude/GPT windows), copilot (premium requests), cursor Pro,
  grok (SuperGrok; reserve for GrokBot; **excluded from delegation since 2026-10-06**, see bigteam's *Current exclusions*), zai GLM lite (via the zcode TUI), clinepass (Cline windows, also the crush TUI; feeds
  hermes via LiteLLM :4000; reserve, never run out), devin (disabled in Orca on
  purpose).
- **Free**: opencode-go bundled models; sipb (MIT-hosted, `opencode`
  provider `sipb`).
- **Prepaid real money, gated**: opencode-zen, openrouter, deepseek —
  only via the `opencode-ralph-tui-*` gate scripts, never by default.

## Headless invocation (one-shot prompts to other TUIs)

### First choice: `acp-run` for every agent that speaks ACP

For a one-shot or headless call to an agent with an
[Agent Client Protocol](https://agentclientprotocol.com/) mode, use
`~/ops/site-private/bin/acp-run` instead of the per-CLI forms below. It
speaks ACP to the agent over stdio, so permission requests come back to the
caller, tool calls arrive typed, and usage is reported, instead of scraping
text and passing `--yolo`-style flags.

```
acp-run <agent> -C <dir> (-p PROMPT | -f FILE | stdin) --model M \
        [--mode M] [--perm all|deny|scoped:P1,P2] [--timeout S] [--log PATH] [--json]
acp-run --list              # agents and the command each runs
acp-run <agent> --info      # its models, modes and auth methods
```

- **Agents** (`--list`): claude (via the `claude-agent-acp` adapter), codex
  (via `codex-acp`), copilot, opencode, cursor, qwen, devin, cline,
  hermes, grok (`grok agent stdio`; **excluded since 2026-10-06** — bigteam's *Current exclusions*), agy
  (Google's signed `agy_acp_server.par`; verified 2026-10-03 22:54, 6.5 s; fails
  independently of the `agy` CLI, see "agy has a burst limit" above).
  Which ones currently work end to end, and what the others need, is
  in `site-private/memory/feedback_prefer_acp_for_delegation.md`; check
  there, not here.
- **Output:** final message on stdout; one summary line on stderr (stop
  reason, seconds, tool calls, permissions allowed/denied, tokens, cost, log
  path); full JSONL event log under `~/.local/state/acp-run/` unless
  `--log` names one. Exit 0 = end_turn, 1 = error/other stop reason,
  124 = timeout (it sends `session/cancel` first).
- **Always pass `--model`.** Without it the agent uses its own default; for
  the claude adapter that is the settings model, which cost about 6× a
  `--model sonnet` run on the same task. `--info` lists valid values.
- **`--perm`:** `scoped:<paths>` allows reads, searches and commands, and
  allows edits only under the listed paths (relative to `-C`); `deny` refuses
  every request (read-only review). Only agents that ask are bound by it:
  copilot and cline ask; claude, cursor and opencode follow their own
  settings and mostly auto-allow, so pick a stricter `--mode` (see `--info`)
  when that matters, and check the diff afterwards.
- **Exit 0 is still not success.** An agent can end its turn normally with a
  provider error as its reply. Verify the outcome (tests, diff, a real
  review in the output) exactly as for the headless forms.
- cline's ACP mode defaults to its paid `cline` provider and ignores the
  TUI's ClinePass setting, so acp-run always sets `provider=cline-pass`
  (generic form: `--set <config-id>=<value>`, ids from `--info`).
- cline bills ClinePass and claude bills the orchestrator's own pool: see
  *Reserve pools* below before sending either bulk work.

### Knowing when a delegated call finished

Run each delegation (`acp-run ...` or a per-CLI form below) as a **foreground
command in its own Bash call with `run_in_background: true`**, with no trailing
`&`. The harness then re-invokes you when it exits. A shell-`&` job is not
tracked and finishes silently (tested 2026-10-03); a wait loop built on
`pgrep -f '<pattern>'` matches itself and never ends. ACP does not change this:
`acp-run` is an ordinary command, and ACP only makes its exit code (0, 1, 124)
and stop reason reliable. Full recipe: `bigteam` Step 4.

### Per-CLI headless forms (no ACP mode, or fallback)

zcode, crush and muse have no usable ACP route yet, so they keep these forms.
The rows for ACP-capable CLIs stay as a fallback for when an ACP route is
broken. **agy:** prefer `acp-run agy`; the `agy -p` form below is the fallback and
is subject to the burst budget in "agy has a burst limit" above.

**Default permission mode: yolo or its equivalent, for every agent however launched** (standing rule 2026-10-03, `home-agents.md`). Gate only for a review-only slice or bigteam's `--perm scoped:` check, and say so. Use `-s read-only` on codex only for review-only calls; work slices use `--dangerously-bypass-approvals-and-sandbox`.

**Authority for launch flags:** Orca's roster,
`~/Library/Application Support/orca/profiles/local-default/orca-data.json`
→ `settings.agentDefaultArgs`. That map is what actually works on this
machine for every enabled TUI (codex `--dangerously-bypass-approvals-and-sandbox`,
antigravity `--dangerously-skip-permissions`, copilot/cursor/crush `--yolo`,
grok `--permission-mode bypassPermissions`, …). Read it instead of guessing
flags. Standing rule (frontier-ai-review-stack memory): prefer a TUI's
official headless mode, or a maintained orchestrator (Orca
`worker-start --agent <name>`, see the `orchestration` skill), over a
hand-rolled subprocess wrapper.

When a direct one-shot call is still the right tool (a single review of a
diff), these forms are verified 2026-09-20. Every one runs with **stdin
closed** (`< /dev/null`) and output redirected to a file; backgrounding a
TUI with `&` inherits the harness's stdin and codex blocks on it forever.

| TUI | Verified headless form | Failure mode seen |
| --- | --- | --- |
| codex (GPT-6 Astra default) | `codex exec -s read-only -C <dir> "<prompt>" < /dev/null > out 2>&1` | without `< /dev/null`: prints `Reading additional input from stdin...` and hangs with no timeout. |
| agy (Antigravity) | `agy --dangerously-skip-permissions --print-timeout 120s -p='<prompt>' < /dev/null > out 2>&1` — **attach the prompt with `-p=`**, which is order-independent and cannot be confused with a flag. `-p`/`--print`/`--prompt` is a *required-value string flag*, not a boolean. | `agy -p` with no value: exits 2, `flag needs an argument: -p`. `agy -p --effort high` (value-less `-p` before another flag): **since 1.1.18 this is a clean exit 2** naming the mistake — *"-p took \"--effort\" as its prompt…"* — and before 1.1.18 it silently ran with `--effort` as the prompt. Verified on 1.2.16, 2026-10-03. Headless still needs `--dangerously-skip-permissions` or tool permissions auto-deny (by design, hardened in 1.2.15). **`RESOURCE_EXHAUSTED (code 429)` with `aiuse` showing headroom** (2026-10-03: every CLI model, 15:42 to 23:50+, while ACP worked): a CLI burst lockout, not an empty pool; the CLI retries 8 times (~2m20s) so it looks like a hang, and `--print-timeout` cuts it with exit 0 and partial output. Check `grep 'attempt [0-9]* failed' ~/.gemini/antigravity-cli/log/cli-*.log` and switch to `acp-run agy`. |
| copilot | `copilot -p "<prompt>" --model auto --allow-all-tools --allow-all-paths --silent < /dev/null > out 2>&1` | fine as-is. **Do not add `--reasoning-effort` with `--model auto`**: exits 1, `Model "auto" does not support reasoning effort configuration` (2026-09-26). Name a concrete model if you want an effort level. |
| opencode (free Go bundle) | `opencode run -m opencode-go/<model> "<prompt>" < /dev/null > out 2>&1` — e.g. `opencode-go/deepseek-v4-pro`, `opencode-go/gpt-6-luna`, `opencode-go/kimi-k3` (all answered 2026-09-26; `opencode models \| grep ^opencode-go/` lists 33). | **`opencode/<model>` is the prepaid Zen catalogue, not Go**: every `opencode/*` model except `big-pickle` fails with `Upstream request failed: Insufficient account funds`. `big-pickle` answers but on a review prompt spent its run trying to install pytest and returned nothing — steer it with "do not run tests or install anything". **Side effect:** every `opencode run` rewrites `./opencode.json` in the cwd (adds a `$schema` key) — `git checkout -- opencode.json` afterwards in repos that track it. |
| cursor-agent | `cursor-agent -p --yolo --output-format text "<prompt>" < /dev/null > out 2>&1` | without `--trust` (or `--yolo`/`-f`) in a directory Cursor hasn't trusted: exits 1 with a "Workspace Trust Required" prompt and no review. |
| zai (zcode) | `zcode -p "<prompt>" < /dev/null > out 2>&1` — `-p` already defaults to `--mode yolo`; `--attach <file>` works (verified 2026-09-30). Inlining the file into the prompt is equally fine. | **Never pass `--mode build` (or `--mode edit`) headless**: it gates every tool behind an approval no one can give, so the run hangs indefinitely — process alive, ~0 CPU, no `zcode-cli` worker doing work, zero output — until it's killed (seen 2026-09-30, `--mode build --attach`). The default yolo mode auto-approves. The `ZCode Built-in skipped (not-due)` lines on stderr are a benign memory-heartbeat, not an error. |

Where DeepSeek lives on this machine (probed 2026-09-26): free —
`opencode-go/deepseek-v4-pro` / `-v4-flash` / `-v4.1-flash` (Go bundle)
and `sipb/deepseek-r1:{8b,14b,32b}` (MIT-hosted); paid —
`opencode/deepseek-*` (Zen prepaid), `clinepass-deepseek`
via LiteLLM :4000 (ClinePass, a reserve pool), and the `deepseek`
prepaid account. Check `aiuse` for what is left in each. z.ai serves GLM, not DeepSeek.

Rules that fall out of this:

- Exit 0 is not success. Append `echo "<tool> exit=$?"` to each output
  file and treat a file holding only a preamble line as a failed run.
- Prefer the read-only sandbox where one exists (codex `-s read-only`).
  Where it does not (agy), check `git status --porcelain` afterwards;
  agy left an empty `graft/` directory in the repo on one run.
- One background Bash call per batch with a long timeout, never chained
  `sleep`s; read each output file when the batch notification arrives.
- A reviewer that returns exit 0 with no findings is a failed run, not a
  clean bill: check the file has an actual review before counting it.
- Run reviewers against a stable tree: don't edit the file under review
  while they read it. For a second round after fixes, tell them what the
  first round found and fixed, so they verify rather than repeat.

Herdr-hosted TUIs (driving agents in Herdr panes; verified 2026-09-26):

- `herdr workspace create` returns before the pane's shell is up;
  `herdr agent start` a moment later fails `agent_pane_busy: … is not an
  available shell`. Poll `herdr pane read <pane>` for a shell prompt (`$`)
  first — ~2 s.
- Key names are `ctrl+c`, `enter`, `esc` (`ctrl-c` → `invalid_key`).
- `herdr pane read` prints plain text; every other command prints one JSON
  envelope, `{"error":…}` **with exit 0** on failure — parse the envelope.
- `herdr agent prompt <target> "/exit"` cleanly ends a Claude session and
  returns the pane to its shell; `bin/herdr-sleeper` in djbclark-ade
  builds on this (see docs/agent-sleep.md).

## Routing method

1. Free and chronically-unused subscription pools first for bulk work —
   aiuse's history section names them (historically: antigravity,
   opencode-go, copilot, cursor).
2. Claude/codex for judgment and agentic work; tier inside them (haiku/
   low for mechanical, fable/xhigh for hardest adjudication — Fable has
   its own weekly bucket).
3. **Reserve pools: never run them out.** clinepass (Hermes runs on it
   via LiteLLM :4000), used carefully, and the `grok` TUI's SuperGrok pool
   (GrokBot runs on it), which is **excluded for now** (operator, 2026-10-06:
   no `grok` TUI, `acp-run grok` or LiteLLM `grok-sub`; see bigteam's *Current
   exclusions*). Grok *models* through another TUI bill that TUI's pool
   instead and stay allowed. Claude gets the same care:
   use it, but orchestration runs from it, so an empty Claude window stops
   every other agent too. Detail: the `bigteam` skill's *Reserve pools*.
   **Copilot** is a lighter case: it shares a subscription with GitHub-side
   Copilot features (code review on `master`), so spend it modestly, small
   slices, GitHub-shaped work only; much less caution than clinepass.
   Never prepaid without an explicit fresh operator decision.
4. Levers: `acp-run <agent> --model <m> [--mode <m>]` for one-shot calls
   to ACP-capable agents (`--info` lists the values); Claude workflows
   `agent(..., {model, effort})`; Orca
   `worker-start --agent <any enabled TUI> --model --effort`; codex
   `model_reasoning_effort`; the per-CLI flags in the headless table for
   non-ACP CLIs.

Standing orders that pair with this: continuous operation over handoff
rituals; flag best-practice deviations to the operator (site-private
memory).
