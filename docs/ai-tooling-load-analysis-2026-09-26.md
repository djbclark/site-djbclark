# AI tooling load analysis — `mac`, 2026-09-26

> Revised 2026-10-03: the memory service measured here (an LLM-extraction service) was retired 2026-09-30 and removed from the ops repos; its product name is scrubbed from this record on the operator's instruction. Numbers are unchanged.

**Machine:** MacBook, 8 cores (4P + 4E), 16 GB RAM, single built-in 2560×1600 display.
**Method:** every number was measured live during the 2026-09-26 sessions (ps/top/vm_stat/launchctl/lsof, the memory-service and LiteLLM APIs, each service's own logs, and Claude transcripts). Estimates are labelled.
**Revision 3 (evening):** regenerated after the fixes landed. Supersedes the two earlier drafts; §5 lists where those drafts were wrong.
**Author:** Claude (Fable 5.1) at the operator's request.

---

## 0. Where things stand

| | Morning | Now |
|---|---|---|
| Load (1 / 5 / 15 min) | 99.8 / 84 / 70 | **6.4 / 7.4 / 9.9** |
| Swap | 11.0 of 12.3 GB | **7.2 of 8.2 GB** (macOS shrank the swapfile) |
| WindowServer CPU | 25–60 %, peaks 100 % | **8.9 %** |
| Postgres backends (memory service) | 95 (71 idle) | 12–25 (0 idle) |
| memory service "slow DB pool acquire" | ~195 / min | ~1 |
| launchd crash loops | 3 (one spawn every ~4 s, for 1–2 days) | 0 — all at `runs = 1` |
| Log bloat | 1.8 GB + 596 MB + 200 MB + 142 MB | 664 KB + 2.2 MB + 0 + 0, all size-capped |
| memory-service failed ops | 244 | 6 (new, retryable) |
| Knowledge pages with content | 0 of 111 (all blank by defect) | 82 of 111, rest filling |
| basic-memory + hermes MCP per new session | ~313 MB phys footprint | **0** (shared HTTP servers) |

**The diagnosis, one paragraph.** This is a 16 GB laptop running as a server: a Postgres-backed memory engine with local CPU embeddings, an LLM proxy, an always-on agent gateway, an observability stack, ~60 non-Apple daemons, 52 scheduled jobs and 14–15 concurrent Claude sessions each carrying ~7 MCP child processes. RAM is the binding constraint; WindowServer starving on input events is the symptom you feel as dropped keystrokes. Three things made it acutely bad and all three were defects, not load: two port collisions and a launcher under `KeepAlive`, respawning every 10 s for over a day while fourteen watchdogs looked elsewhere. Underneath, the structural pattern is session sprawl and per-session process multiplication.

---

## 1. Findings, with the corrected measurements

### 1.1 Memory: RSS lied by 7×

`ps rss` reported the MCP child processes at ~785 MB total. `top`'s MEM column (phys footprint, which counts compressed and swapped pages) reports **5,631 MB**:

| Process | Copies | Footprint each | Total |
|---|---|---|---|
| `basic-memory mcp` (python3.13) | 13 | 198 MB | 2,576 MB |
| `hermes mcp serve` (python3.11) | 13 | 115 MB | 1,489 MB |
| `node` (memory-service `mcp-server.js`, graft) | 29 | 35 MB | 1,018 MB |
| `maestro … mcp` (JVM, scoped to `~`) | 2 | 192 MB | 384 MB |
| cua-driver / ghost-os / cow | 14 each | 2–6 MB | 159 MB |

Idle processes live almost entirely in the compressor, which RSS does not count. **Measure with `top -l 1 -pid <pid> -stats mem`, never `ps rss`, on this machine.** The earlier drafts' RAM estimates were all low for this reason.

### 1.2 Three crash loops (all fixed)

| Job | Runs | Real cause | Fix |
|---|---|---|---|
| `com.djbclark.superbrain` | 9,082 (16,626 failures logged) | **macOS AirPlay Receiver owns `*:5000` and `*:7000`**; `api.py:2782` hardcoded 5000. The 8443 funnel path was delivering YouTube WebSub pushes to AirPlay's 403. | `PORT=5001`; `api.py` honours `PORT` (superbrain `bc3661f`); funnel path, landing and registry repointed; 142 MB log truncated |
| `com.djbclark.caddy` | 6,909 this load / **42,927** starts | **Tailscale `serve` route `:443 → 127.0.0.1:8787`** — the macsys `tailscaled` binds the tailnet IP:443 inside a root system extension (invisible to user `lsof`), and on macOS that makes caddy's wildcard `*:443` fail. Continuous for ~44 h while awake; whoever won each post-wake race held the port. | `tailscale serve --https=443 off` (caddy is the registered 443 owner); `ThrottleInterval=60`; 200 MB log truncated |
| `homebrew.mxcl.container` | **11,687** | `container system start` is a *launcher* that exits 0 after starting the apiserver; brew's plist ships `KeepAlive: true`. | `KeepAlive: {SuccessfulExit: false}`; apiserver unaffected |

Evidence that ruled out the other caddy theories: only 42 SIGTERM lines in the whole log, none in the loop window; the 4,426 "server running" lines in the window were partial starts (`:80`/`:8080` up, `:443` failing in the same instant).

### 1.3 Session sprawl

15 Claude sessions; 12 idle 5–6 hours, seven of them batch-spawned in the same second by an orchestrator and never reaped. Each carries ~7 MCP children. Sessions started before this evening's change still hold a stdio basic-memory (198 MB) and hermes (115 MB) copy each; those are released as sessions restart. **You chose to handle these yourself** — the list is in §8.

### 1.4 Hooks: ~6 spawns / ~0.6 s per ordinary tool call

Measured: `node` startup 0.09 s, `python3` 0.10 s, `bash` 0.07 s; `graft-hooks.cjs post-edit` 0.35 s, `tool-savings` 0.17 s, `graft_grep_nudge.py` 0.19 s. A Bash call runs orca + graft-nudge before and openusage + superset + orca + graft-savings after. `moshi-hook` fires only on `AskUserQuestion`/`ExitPlanMode` (matcher-scoped, not duplicated — an earlier draft got this wrong). The notable ratio: graft's hooks run on every Bash/Read/Grep/Glob/Edit in every session, while `mcp__graft__*` had 26 calls in 14 days.

Per prompt, until this evening: a 40 s memory-service `reflect` (LLM call) — **now off** (`autoReflect=false`), along with the session-start `deepen` (`autoSeed=false`).

### 1.5 Memory service (LLM-extraction memory, retired 2026-09-30)

1. **Tuned this morning** (`d1fa8b3`, `c240b0e`): pools 100/100 → 16/8, `LLM_MAX_CONCURRENT` 32 → 4, worker slots 10 → 6, refresh concurrency 8 → 2, recall 32 → 8; four empty banks deleted. Root cause upstream #4754 (pool max 100 collides with embedded pg `max_connections` 100) plus asyncpg never shrinking a grown pool.
2. **Knowledge pages were blank by defect, and the defect regenerates.** The HTTP API defaults `exclude_mental_models=false` whenever a trigger object is passed (`http.py:990`); only the no-trigger path gets the document default `true`. The plugin always passes a trigger (`PAGE_TRIGGER`) that omits the key — in 0.3.4 (installed) *and* 0.7.0 (latest, 2026-09-24). Proven both ways by API test: omit → `False`; include → `True`. Fixes: all 111 pages PATCHed (parallel session); all 28 plugin bundles patched; a re-apply script (since removed) re-applied after any plugin update, and the existing hook-patch watchdog cron in Hermes (6 h) now alerts on both a lost bundle patch and any live page with `exclude_mental_models=false`. Not yet filed upstream.
3. The 169 mental-model refreshes/day are **consolidation-triggered** (`refresh_after_consolidation: true`), not tick-driven — the tick only serves cron-type triggers (`maintenance.py`). The lever is retain volume; 0.9.2 added "minimum interval between automatic refreshes", which 0.9.0 lacks.
4. Backfill cost: grok 20 % → 62 % of its window over the day (resets Oct 1 06:41 UTC). 82 of 111 pages now have content; 29 fill on their banks' next consolidation.
5. `coding-agent::orca` holds 13,098 facts — 43 % of all facts across 28 banks.

### 1.6 Scheduler and daemons

52 scheduled jobs (30 Hermes cron, 22 launchd intervals). Trimmed today: `adb-reconnect` ×4 60 → 300 s (stayturgid `8bc98e0`), `aiuse` 15 → 60 min, `hermes-heartbeat` 1 → 5 min. Still running: three 5-minute jobs. ~60 non-Apple daemons; three cloud-sync clients (Dropbox 141 + Google Drive 111 + OneDrive 14 MB); comms ~930 MB; fourteen window-management/overlay tools that hook WindowServer.

### 1.7 The meta-pattern

Fourteen watchdogs, none watching launchd itself. **Fixed:** `check-launchd-loops.sh` (Hermes cron, every 6 h) compares run counts against the previous check and alerts on deltas the schedule can't explain. Self-tested.

---

## 2. Everything done today, by commit

| Area | Change | Where |
|---|---|---|
| LiteLLM | rpm caps, `allowed_fails`/`cooldown_time` (single-deployment cooldown bug), fallbacks reordered off ClinePass | site-djbclark `d098968` |
| Routing | memory-service retain/reflect, goose, Hermes aux/MoA/fallbacks → grok-sub (ClinePass spent until 2026-10-16) | `e5e55ff`, `03cd731`, `~/.hermes/config.yaml` |
| Memory service | pool caps; concurrency; 4 banks pruned; 244 failed ops re-queued to 0 | `d1fa8b3`, `c240b0e` |
| Memory-service pages | 111 triggers PATCHed; plugin patched; re-apply script | plugin dir (since removed) |
| Plugin config | `autoReflect=false`, `autoSeed=false` | plugin config (since removed) |
| superbrain | port 5001, `PORT` honoured, funnel/landing/registry repointed | superbrain `bc3661f`, site-djbclark `1628762` |
| caddy | serve :443 route removed, throttle, log rotated | `~/Library/LaunchAgents`, tailscale |
| container | KeepAlive → SuccessfulExit:false | `~/Library/LaunchAgents` |
| Scheduler | adb ×4, aiuse, heartbeat intervals | stayturgid `8bc98e0`, plists, hermes cron |
| Logs | litellm/memory-service/superbrain/caddy rotated and capped | `dac2066`, `e44b74b`, truncations |
| **Shared MCP** | basic-memory as one HTTP server (18796, new role); hermes via existing bridge (18790); `~/.claude.json` + crushrc repointed | site-djbclark `7af4281`, `e1cbfd4` |
| Registry | 18796 allocated; 1879x bridge block registered; superbrain 5001 | `e1cbfd4`, `1628762` |
| Watchdog | launchd crash-loop watchdog, Hermes cron every 6 h | `~/.hermes/scripts/check-launchd-loops.sh` |
| Memory | 8 notes: AirPlay :5000, Tailscale serve :443, page trigger, run-count sweep, container loop, MCP-per-session, gemini 20/day, shared MCP + rollback | site-private `bd2ca5e`, `00c2c26`, `696854d` |

Every config edit has a dated `.bak-2026-09-26-*` sibling next to it.

---

## 3. Shared MCP servers — what changed and how it was verified

**Before:** every Claude session spawned its own `basic-memory mcp` (198 MB) and `hermes mcp serve` (115 MB).
**After:** `~/.claude.json` and `~/.config/crush/crushrc` point `basic-memory` at `http://127.0.0.1:18796/mcp` (new `roles/basic_memory_mcp`, native streamable-HTTP, logpipe-supervised) and `hermes` at `http://127.0.0.1:18790/mcp` (the existing `hermes-mcp-bridge`; no new label, gateway untouched).

**Why sharing is safe:** basic-memory's state is its project DB, tools take a `project` argument; Hermes's event tools are client-cursor based (`events_poll(after_cursor)`), and the bridge already multiplexed remote clients through one child.

**Stay per-session, by design:** memory-service `mcp-server.js` (bank from `process.cwd()`), graft (per-repo index), cua-driver `mcp` (thin client to the already-shared daemon), ghost-os, cow.

**Verification:** two fresh `claude -p` sessions. Their process subtrees contained **no basic-memory and no hermes** (only node/ghost/cua-driver/cow); 1-second sampling saw **6 connections to :18796 and 4 to :18790 from those PIDs**; both answered `ok main / 93`. `claude mcp list` shows both ✔ Connected. Shared basic-memory server: one process, 207 MB.

**Other clients:** Codex, Claude desktop and Hermes-as-client had nothing to repoint.

**Rollback:** `memory/project_shared_mcp_servers_http.md`.

---

## 4. Loose ends that are not mine (2026-09-26 snapshot)

> **Update 2026-10-04:** The memory service was retired on 2026-09-30 and replaced by Basic Memory. Its failed operations, empty knowledge pages, and service-specific follow-up are obsolete, not current action items. The quota figures below are also a dated snapshot, not current usage.

1. **Obsolete — 6 memory-service ops failed since the last re-queue** — three in `orca` ("exceeded max recovery attempts"), two in `crush` (sub-batch), one in `site-private`. Do not retry against the retired service.
2. **Obsolete — 29 knowledge pages still empty**, waiting on their banks' next consolidation (`ops` 5/5, `orca` 3/6, `home-ops`, `site-private`, `superbrain`, `hermes-worktrees` 3/5). This consolidation path is retired.
3. **Historical quota snapshot:** Grok at 62 % with 4.4 days to reset; ClinePass's monthly reset was expected 2026-10-16; `gemini-free` was 20 requests/day. Recheck live quota before using these figures.

---

## 5. Corrections to the earlier drafts

1. **RSS vs footprint** (§1.1): MCP children were 5.6 GB, not 0.8 GB. Every RAM figure in the earlier drafts was low.
2. **`moshi-hook` is not registered twice**; the two entries are matcher-scoped. A3 withdrawn; the hook tax is ~6 spawns / 0.6 s, not 11 / 1.2 s.
3. **Caddy was not a Tailscale boot race**; it was a continuous port collision with a root-side Tailscale serve listener.
4. **"The memory service contributed nothing"** measured a broken system — the pages were blank by defect.
5. **The refresh tick is not a lever** for these pages (cron-only).
6. **The memory service was never crash-looping** during the morning; `HTTP 000` readings were transient unresponsiveness under swap.
7. **No SIPB misconfiguration existed**; that was a misread of two disjoint `sed` ranges.

---

## 6. Decisions you made today

1. Idle sessions: **you handle them** (§8).
2. `cua-driver`, `cow`, `basic-memory` global MCP: **keep all three** (evidence: 0 calls in 233 transcripts / 14 days; basic-memory is now HTTP so its per-session cost is gone anyway).
3. `autoReflect` / `autoSeed`: **both off**.
4. Superbrain: kept, moved to 5001.

---

## 7. Remaining recommendations

### 7.1 Cheap, no tradeoff
1. **Obsolete:** retry the 6 failed ops once grok has headroom; the service is retired.
2. **Obsolete:** file the `exclude_mental_models` bug upstream (the retired service's coding-agents repo, `PAGE_TRIGGER`/`buildPageTrigger`).
3. Scope the `maestro` JVM MCP to the mobile repo instead of `~` (192 MB per session started in the home dir).

### 7.2 Configuration, small tradeoffs
1. **Obsolete:** upgrade the memory service 0.9.0 → 0.10.1. The service is retired.
2. **Obsolete:** upgrade the plugin 0.3.4 → 0.7.0 and run `patch-page-trigger.sh`. The service and its plugin are retired.
3. Per-repo `.mcp.json` for graft and ghost-os; graft's hooks run everywhere for 26 calls/fortnight.
4. **Obsolete:** memory-service second pass: decide `orca` (13 k facts); prune `probe-orca-dispatch` (348), `deepseek-harness` (281), `unattributed-2026-08` (218), `cowexp-3` (64), the three untouched since August; move embeddings off-CPU; revisit `pg0 work_mem=64MB`.
5. Remaining 5-minute jobs; one cloud-sync client at a time; thin the fourteen overlay tools.

### 7.3 Structural
1. **Evaluate moving the still-active server-class services off the laptop** (LiteLLM, observability, Hermes gateway, superbrain, caddy); the memory service and its pg0 were retired. The litellm role is already multi-host (`mac-mini-intel` in the justfile). The BeagleBone is a fine Tailscale subnet router and far too weak for this.
2. **RAM.** 16 GB is the root constraint; today's work reduced demand, it did not add supply.
3. **Obsolete:** decide the memory service's future after the pages have been populated; the service was retired before this could be a current decision.

---

## 8. Sessions holding stdio MCP copies (yours to reap)

Each still holds a 198 MB basic-memory and a 115 MB hermes copy until restarted; `claude --resume` brings any of them back.

| PID | cwd | idle |
|---|---|---|
| 41292, 41294, 41296, 41299 | `~/src/hermes-worktrees` | ~6 h (batch, same second) |
| 33883 | `~/src/hermes-worktrees` | ~6 h |
| 8410, 9486 | `~` | ~6 h (batch) |
| 8411 | `~/src/tendcf` | ~6 h |
| 41300 | `~/src/mobile` | ~6 h |
| 25498 | `~/src/crush` | ~6 h |
| 62799 | `~/src/aiuse` | ~3.5 h |
| 18536 | `~/src/crush` | ~1.5 h |
| 22707, 91171 | `~/orca/projects/djbclark-ade` | recent |

---

## Appendix — durable facts now in `site-private/memory`

- `reference_macos_airplay_owns_port_5000` · `reference_tailscale_serve_443_vs_caddy_collision` · `reference_hindsight_page_trigger_exclude_mental_models` · `reference_launchd_run_count_crash_loop_check` · `reference_brew_container_launcher_keepalive_loop` · `reference_claude_mcp_servers_spawn_per_session` · `reference_gemini_free_tier_20_rpd` · `project_shared_mcp_servers_http` (rollback) · `project_clinepass_capped_until_2026-10-16` (revert checklist).
