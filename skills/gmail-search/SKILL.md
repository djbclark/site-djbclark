---
name: gmail-search
description: >-
  High-speed local Gmail search: the Hermes-built FTS5 index of the
  operator's complete mailbox (~192k messages), queryable in ~100ms from
  any session via a plain CLI — no API round-trip, no MCP. Use whenever a
  task needs to find or read the operator's email: "search my email",
  "find that message/thread from X", "when did I get...", or any lookup
  the claude.ai Gmail connector would do slower. Read-only; a Hermes cron
  job keeps the index fresh every 5 minutes.
---

# High-speed local Gmail search

Canonical source: `skills/gmail-search/SKILL.md` in the djbclark-ade repo;
deployed live copy at `~/.claude/skills/gmail-search/`. Snapshot facts dated
**2026-08-23** — re-probe with the `stats` command below.

Hermes built and maintains a complete local Gmail index at
`~/.hermes/gmail_index_v2.db` (SQLite + FTS5, ~904MB, 191,980 messages /
94,375 threads at snapshot). Search it directly:

```bash
python3 ~/.hermes/gmail_search_engine.py search --query "<terms>" --limit 5
```

- Returns a JSON array: `id`, `thread_id`, `date`, `sender`, `recipient`,
  `subject`, `snippet`, full `body`, and a BM25 `score` (results arrive
  best-first). Bodies can be long — use `--limit` small and widen only if
  needed.
- `--query` accepts FTS5 syntax: `"exact phrase"`, `term1 AND term2`,
  `term*` prefix matching.
- ~100ms per query (verified 83ms). Prefer this over the claude.ai Gmail
  connector for *finding* mail; use the connector when you need to act on
  mail (send, label, thread state) or need messages newer than the last
  incremental sync (≤5 min old).
- Freshness/stats: `python3 ~/.hermes/gmail_search_engine.py stats` →
  message/thread counts + Gmail `history_id`.

## Rules

- **Search only.** Never run `sync` or `full-sync` — a Hermes cron job
  ("Gmail index incremental sync", every 5m, plus a twice-daily summary)
  owns writes under a single-writer lock (`gmail_index_v2.db.sync.lock`).
  A manual full-sync repaginates the entire mailbox for no benefit.
- **Results are the operator's private email.** Quote only what the task
  needs; never commit, publish, or paste results into anything
  outward-facing (repos, artifacts, messages) without being asked.
- The engine is `~/.hermes/gmail_index_v2.py` (docstring: Gmail API
  pagination → SQLite → FTS5; no local AI); `gmail_search_engine.py` is
  the stable compatibility entry point — call that, not the v2 module.
- Not exposed via the `hermes` MCP server (that bridge carries messaging
  conversations + approvals only) — the CLI above is the access path.
