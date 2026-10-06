# Gmail Index: Implementation Guide, Proposal, and Operating Reminder

## Purpose

Hermes maintains a local, token-efficient search index of Gmail so an AI agent can retrieve a small, relevant evidence set instead of loading the mailbox into model context.

The live implementation is outside this repository at:

```text
~/.hermes/gmail_index_v2.py
~/.hermes/gmail_index_v2.db
```

This document is the durable private design and operating reference for that system.

## Current implementation

The indexer:

- Uses the authenticated Gmail API directly.
- Performs a complete paginated initial import.
- Stores message metadata, thread IDs, headers, labels, snippets, and extracted plain-text bodies.
- Falls back to cleaned HTML text when a plain-text MIME part is unavailable.
- Uses SQLite WAL mode and FTS5 for local BM25-ranked search.
- Uses Gmail `historyId` for incremental synchronization.
- Marks messages deleted when Gmail history reports a deletion or a message can no longer be fetched.
- Uses bounded Gmail batch requests with retry/backoff for rate limits.
- Has a non-blocking OS-level single-writer lock at:

```text
~/.hermes/gmail_index_v2.db.sync.lock
```

Only one `sync` or `full-sync` may run for a database at a time. A concurrent invocation exits with status 2 instead of waiting or racing. Read-only `search` and `stats` commands remain usable during synchronization.

The initial import completed successfully with 190,636 messages and 93,153 threads. The Gmail history cursor is persisted in the database metadata.

## AI-facing usage

The command-line interface is intended primarily for AI tooling, not manual human operation.

Search:

```bash
~/.hermes/skills/productivity/google-workspace/.venv/bin/python \
  ~/.hermes/gmail_index_v2.py search \
  --query '"project timeline" client' \
  --limit 20
```

Statistics:

```bash
~/.hermes/skills/productivity/google-workspace/.venv/bin/python \
  ~/.hermes/gmail_index_v2.py stats
```

Incremental update:

```bash
~/.hermes/skills/productivity/google-workspace/.venv/bin/python \
  ~/.hermes/gmail_index_v2.py sync
```

Full import or recovery:

```bash
~/.hermes/skills/productivity/google-workspace/.venv/bin/python \
  ~/.hermes/gmail_index_v2.py full-sync
```

The AI should search narrowly first, inspect returned subjects/senders/dates/snippets, then retrieve or request more evidence only when needed. Search terms are combined as AND terms; quoted phrases are preserved.

## Recommended polling cadence

### Recommendation: every 5 minutes while the machine is active

A five-minute interval is a good default for this mailbox because:

- `history.list` is inexpensive when there are no changes.
- The expensive `messages.get` calls occur only for changed message IDs.
- Five minutes gives near-current search results without causing continuous API traffic.
- The single-writer lock prevents overlap if one update takes longer than expected.
- A quiet wrapper can suppress notifications when there are zero changes.

A one-minute schedule would reduce latency but creates more frequent authentication/API activity for little practical benefit. Fifteen minutes is reasonable for lower-power or overnight operation. The job should not run more frequently than every minute.

The recommended first deployment is therefore a five-minute Hermes scheduled job. It should:

1. Run the dedicated Python interpreter.
2. Call `gmail_index_v2.py sync`.
3. Emit nothing when there are zero changes.
4. Emit a concise update when messages change.
5. Emit an error alert on authentication, quota, or database failure.
6. Rely on the indexer's lock rather than implementing a second lock in the scheduler.

## Push/webhook proposal — not currently enabled

Gmail supports server push through `users.watch` and Google Cloud Pub/Sub:

```text
Gmail users.watch
  -> Cloud Pub/Sub topic
  -> webhook or pull subscriber
  -> history.list(startHistoryId)
  -> existing incremental index update
```

The notification contains a new mailbox `historyId`, not the message body. The existing incremental sync logic remains the source of truth for fetching and applying changes.

Google documents these constraints:

- Watches expire after at most seven days and should be renewed at least daily.
- Notifications are normally delivered within seconds but may be delayed or dropped.
- Notifications over one event per second for a watched user may be dropped.
- A periodic fallback call to `history.list` is still required.
- Setup requires a Google Cloud Pub/Sub topic, Gmail publish permission, a subscription, and a durable receiver.

Push would be worthwhile only if sub-minute freshness becomes important enough to justify a continuously available receiver. It would be more operationally complex than five-minute local polling. No topic, subscription, watch, webhook, or permanent receiver has been created.

Preferred future push design, if needed:

```text
Cloud Run HTTPS endpoint
  -> authenticated Pub/Sub push subscription
  -> durable queue/idempotency check
  -> incremental Gmail sync worker
  -> local or hosted index update
```

The five-minute polling job should remain as a reliability fallback even after push is introduced.

## Future improvements

Prioritized improvements:

1. Keep the scheduled incremental sync and observe real-world API/quota behavior.
2. Add structured output mode for AI callers so only selected fields are returned.
3. Add thread-oriented retrieval and optional conversation reconstruction.
4. Add attachment metadata and opt-in text extraction for supported formats.
5. Add remote-only semantic embeddings if a provider and privacy/cost policy are chosen; do not add local AI implicitly.
6. Consider Gmail Pub/Sub push only after polling latency becomes a demonstrated problem.
7. If the index becomes a major shared capability, expose it as a short-lived stdio MCP tool rather than requiring AI agents to know the CLI path.

## Operational reminders

- Never run two synchronizations concurrently.
- Do not delete the `.sync.lock` file while a sync is running; it is harmless when no process holds it.
- Use the Google Workspace Python 3.11 environment, not system Python.
- Use the Python SQLite build with FTS5; the system `sqlite3` CLI may not have FTS5 enabled.
- Keep OAuth credentials and tokens out of this repository and out of logs.
- Do not start a full sync for routine updates.
- If the history cursor becomes invalid, the indexer should fall back to a full sync; monitor the resulting API duration before repeating it.
- Search and stats are safe read-only operations while a sync is active.

## References

- [Gmail API push notifications](https://developers.google.com/workspace/gmail/api/guides/push)
- [Gmail API synchronization](https://developers.google.com/workspace/gmail/api/guides/sync)
- [Gmail `users.watch`](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/watch)
- [Gmail `users.history.list`](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/history/list)
- [Gmail API quotas](https://developers.google.com/workspace/gmail/api/reference/quota)
- [SQLite FTS5](https://sqlite.org/fts5.html)
