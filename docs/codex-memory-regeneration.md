# What regenerates `memory/codex/{memory_summary,raw_memories}.md`

**Status:** confirmed, from live evidence on this machine.
**Author:** Claude Code, 2026-08-03, investigating
[djbclark/site-private#4](https://github.com/djbclark/site-private/issues/4).

## Answer

**Codex CLI itself** — a built-in, automatic background feature called
`memories` (feature flag `memories`, stage `stable`, enabled). Nothing in this
repo, no cron/launchd job, and no Hermes automation writes these files. Codex
generates them locally as a side effect of normal use; a human/agent session
is still the one that `git commit`s and pushes the result (see
[Concurrency story](#concurrency-story-and-why-it-conflicted) below).

### The mechanism, end to end

1. **Config.** `~/.codex/config.toml` (this machine) has:
   ```toml
   [features]
   memories = true

   [memories]
   generate_memories = true
   use_memories = true
   ```
   The full `MemoriesToml` schema (recovered from the `codex` binary's
   symbol/string table) also supports `extract_model`, `consolidation_model`,
   `max_raw_memories_for_consolidation`, `max_unused_days`,
   `max_rollout_age_days`, `max_rollouts_per_startup`,
   `min_rollout_idle_hours`, `min_rate_limit_remaining_percent`, and
   `dedicated_tools` — none of which are overridden here, so Codex is running
   this feature on its built-in defaults.

2. **Two background job kinds**, tracked in a local SQLite job queue at
   `~/.codex/memories_1.sqlite` (on this machine that path is a symlink to
   `${OPS_ROOT:-~/ops}/site-private/.codex-runtime/memories_1.sqlite` — an
   ignored, machine-local runtime file, *not* something this repo tracks):
   - **`memory_stage1`** — one job per conversation thread/session
     (`job_key` = thread UUID). Runs after a session has been idle for
     `min_rollout_idle_hours`, up to `max_rollouts_per_startup` per Codex
     startup. Extracts a raw-memory note + a rollout summary from that
     session's rollout log and stores them in a `stage1_outputs` table
     (columns: `thread_id`, `raw_memory`, `rollout_summary`, `rollout_slug`,
     `selected_for_phase2`, …). Verified 30 `done` rows in the live db on
     this machine, one per processed session.
   - **`memory_consolidate_global`** — a single global job
     (`job_key = "global"`, exactly one row, lease/`worker_id`/
     `ownership_token`-guarded so only one worker runs it at a time on a
     given machine). Triggered once enough new `stage1_outputs` accumulate
     (tracked via `input_watermark`/`last_success_watermark` columns).
     Verified one `done` row, ~100s runtime — consistent with an LLM call
     using the configured `consolidation_model`.

3. **The writer is an internal LLM agent, not a template.** The `codex`
   binary embeds a full prompt for this job (crate `codex_memories_write`,
   `memories/write/src/prompts.rs`, entry point
   `## Memory Writing Agent: Phase 2 (Consolidation)`). Recovered instructions
   from the binary's string table confirm the exact behavior this repo's
   `AGENTS.md`/`home-agents.md` had only inferred:
   - `raw_memories.md` is treated as *"the routing layer, not always the
     final authority for detail"* and is rebuilt by *"mechanical merge of
     selected raw_memories from Phase 1; ordered by stable ascending thread
     id"* — matches the live file's actual header, `Merged stage-1 raw
     memories (stable ascending thread-id order)`.
   - `memory_summary.md` is explicitly meant to be rewritten wholesale:
     *"freely restructuring memory_summary.md so it reflects the current
     memory set"*, *"write memory_summary.md last (highest-signal file)"*,
     and it must start with the literal line `v1` (confirmed: it does).
   - `MEMORY.md` is the durable "searchable registry" consolidated first;
     `memory_summary.md` is refreshed after it as a compact routing layer.

4. **The sanctioned hand-edit path exists and is *not* the two summary
   files.** `memory/codex/extensions/ad_hoc/` is a real, designed extension
   point (see `memory/codex/extensions/ad_hoc/instructions.md`, itself
   embedded verbatim in the binary's prompt as
   `## Memory Writing Agent: Phase 2 (Consolidation)` input): drop a dated
   note file there, and the next consolidation run is required to fold it in
   (*"Every note must be consolidated in the memory structure"*, *"Never
   delete a note file"*). Hand-editing `memory_summary.md` or
   `raw_memories.md` directly works against a process designed to overwrite
   them wholesale on its own schedule.

### Concurrency story, and why it conflicted

The job queue is single-owner **per machine** (one lease-guarded
`memory_consolidate_global` job in one local SQLite db). That protects against
two Codex processes on the *same* machine racing each other. It does nothing
for the actual hazard this repo's memory policy exists to manage: **multiple
independent Codex-CLI instances (different machines, or the same machine at
different times with divergent local session history) each regenerate a full
local copy of `memory_summary.md`/`raw_memories.md` from their own local
`stage1_outputs`, then a human/agent session commits and pushes whatever Codex
produced locally.** Two such whole-file rewrites, based on different local
raw material, do not merge at the git level — which is exactly what happened
in the 2026-07-26 `site-private` PR #3 merge referenced in
[`home-agents.md`](../home-agents.md).

There is no distributed coordination for this job across machines, and none
is planned by Codex itself — the queue's job is local dedup/single-flight, not
cross-repo consistency. The get-out is git itself: last write wins per the
existing narrow memory-exception workflow (`just ops-memory-sync` before
writing, commit only `memory/`, push immediately), same as any other
concurrently-hand-edited file in that exception — these two just conflict more
often because Codex rewrites their entire contents on every consolidation run
instead of appending.

## What this settles from issue #4

- **Which process regenerates them?** Codex CLI's own built-in `memories`
  feature — background jobs `memory_stage1` (per session) and
  `memory_consolidate_global` (global, single-flight per machine), backed by
  an internal LLM "Memory Writing Agent." Not a cron/launchd job, not a
  script in this repo, not Hermes (Hermes's own, differently-named
  "hygiene suite" memory consolidation on 2026-08-03 is a separate, unrelated
  mechanism that happened to land in a similar-looking commit).
- **Are they meant to be hand-edited?** No. The sanctioned edit path is
  dropping a note under `memory/codex/extensions/ad_hoc/`; the consolidation
  agent is contractually required (per its own embedded prompt) to fold new
  notes in on its next run and never delete a note file.
- **Concurrency story?** Single-owner *per machine*, enforced by a local
  SQLite job lease — not a cross-machine/cross-repo guarantee. Conflicts are
  resolved the same way as any other memory-exception commit: sync right
  before writing, commit only `memory/`, push immediately, treat a conflict
  as expected and resolve it manually rather than a sign something is broken.

## Evidence trail (how this was confirmed)

- `codex features list` → `memories  stable  true`.
- `~/.codex/config.toml` → `[memories]` section present in this machine's
  live, ignored config.
- `strings` on the installed `codex` binary
  (`/opt/homebrew/Caskroom/codex/0.146.0/bin/codex`) surfaced the
  `codex_memories_write` crate path, its Phase 2 consolidation prompt
  (verbatim instructions matching the live files' actual structure), the
  `MemoriesToml` config schema, and the `memory_stage1`/
  `memory_consolidate_global` job-kind strings.
- `sqlite3 ~/.codex/memories_1.sqlite` (resolves to
  `.codex-runtime/memories_1.sqlite` in this repo) → `jobs` and
  `stage1_outputs` tables with real, `done` rows: 30 `memory_stage1` rows (one
  per processed session) and exactly one `memory_consolidate_global` row
  (`job_key = "global"`).
- `git log --follow -- memory/codex/memory_summary.md` /
  `raw_memories.md` → history of periodic "sync consolidated summaries"
  commits, consistent with a human/agent committing Codex's local output
  rather than authoring it by hand.
- Live file contents match the recovered prompt's contract exactly:
  `memory_summary.md` starts with the literal line `v1`; `raw_memories.md`
  opens with `Merged stage-1 raw memories (stable ascending thread-id
  order)` and is organized in per-thread blocks keyed by thread ID with
  `rollout_path`/`rollout_summary_file` fields.

No open questions remain from the original issue.
