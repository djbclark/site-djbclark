# S1 evidence store: moving from SQLite to PostgreSQL (design note, not a plan of record)

Status: **notes only**. Nothing here is scheduled. SQLite stays the store until
a concrete need appears (several concurrent writers, network clients, a store
too large for one machine). Written 2026-10-13 after search layout 3 (per-row
zstd `event_text`) shrank `candidates.sqlite3` to about 6.1 GiB; the CAS pack
(`cas-pack/pack.sqlite3`) is about 2.3 GiB. Size and effort figures below are
**estimates, not measurements**.

## 0. If the only goal is "a copy on another server"

Replicate SQLite instead of migrating (Litestream-style WAL shipping, or a
periodic `VACUUM INTO` plus rsync). That needs no code change and gives a
read-only copy. Choose Postgres only for concurrent writers or network
clients. Caveat: a layout-3 copy can only be searched through `s1_search.py`
(the `event_text` view calls the Python SQL function `s1_unzstd`); plain
`sqlite3` fails on snippets and the view, so a replica host needs this repo's
code, Python and libzstd.

## 1. Where the code touches the store

1. `bin/s1_evidence.py` (`EvidenceStore`): schema, `put_bytes`/`get_bytes`,
   ledger writes, checkpoints, gaps, integrity checks, CAS pack. The adapters
   write only through this class (`s1_<adapter>.py` import `EvidenceStore`,
   2 to 9 references each).
2. `bin/s1_search.py` (`SearchIndex`): the derived index (FTS5, trigram,
   layout 3 view). About 900 lines; the only other place that speaks to the
   store's SQL.
3. `bin/s1_cycle.py`: scheduler; uses lock files and subprocess steps, not SQL.
4. SQLite appearing elsewhere in `bin/s1_*.py` (agy, crush, opencode, Cursor,
   Hermes, cline) is the **source** databases those adapters read. It stays
   SQLite whatever happens to the store.

## 2. Evidence tables: straightforward

Tables: `event`, `conversation_member`, `raw_object`, `attachment`,
`ingest_checkpoint`, `ingest_gap`, `s1_meta`, plus the pack's `obj`,
`dictionary`, `pack_meta`.

1. `event.ingest_lsn INTEGER UNIQUE` becomes a Postgres sequence (or
   `GENERATED ALWAYS AS IDENTITY`); keep the same values on import so
   checkpoints (`committed_lsn`) stay valid.
2. `UNIQUE(producer, source_uri, source_locator)` and the
   `ON CONFLICT (...) DO UPDATE` upserts port as they are. `INSERT OR IGNORE`
   becomes `ON CONFLICT DO NOTHING`; `INSERT OR REPLACE` becomes an explicit
   upsert. Placeholders change from `?` to `%s`/`$n`.
3. CHECK constraints and `ON DELETE CASCADE` foreign keys are valid Postgres.
4. Timestamps are ISO strings today; keep them as `text` for a lossless first
   port, convert to `timestamptz` later if wanted.
5. CAS: `obj(sha, raw_size, data, codec, dict_id)` becomes a table with
   `data bytea`. The bytes are already zstd-compressed by the application, so
   set `STORAGE EXTERNAL` on that column to stop Postgres trying to compress
   them again. The application keeps doing the zstd (dictionary included), so
   stored bytes stay identical and verification is a straight hash compare.
6. `PRAGMA journal_mode/busy_timeout/integrity_check/foreign_key_check` have
   no direct equivalent: replace with connection settings and a verification
   pass (row counts, `raw_sha256` of every object, FK check by query).

## 3. The search layer: the real work

| Today (SQLite) | Postgres |
|---|---|
| FTS5 `event_fts`, external content | `tsvector` column or expression + GIN index |
| trigram: `body LIKE` + `s1_contains` recheck, `detail=none` | `pg_trgm` GIN index; `LIKE`/`ILIKE` use it, and queries under 3 chars still work (slower) |
| `snippet()` | `ts_headline()` |
| bm25 `rank` ordering | `ts_rank`/`ts_rank_cd`; **ordering will differ**, accept "equivalent", not identical |
| layout 3 compressed `event_text` + `s1_unzstd` view | not needed; TOAST compresses `text` (pglz or lz4) |

1. The index is derived state: rebuild it from the evidence on the new server,
   no data migration needed.
2. Test with the same method used for layout 3: pick hundreds of generic
   queries, compare hit sets on events present in both stores (new events make
   raw hit sets differ), compare snippets per event, report any difference.
3. Do not read the SQLite store with `immutable=1` while the scheduler writes
   (gave "database disk image is malformed" in a check script on 2026-10-13).

## 4. Operations that change

1. Scheduler and lock model: SQLite is one writer at a time, enforced by
   `ingest.lock` and `maintenance.lock`. Postgres allows concurrent writers;
   keep the lock files for maintenance, but the "database is locked" failure
   mode (a long write blocking cycle steps) disappears.
2. The adapters read local transcripts on this Mac, so ingest stays local and
   writes over the network. Handle a dropped connection mid-scan with retry;
   checkpoints already make scans resumable.
3. Backup moves to `pg_dump`/WAL archiving; the "APFS clone then swap files"
   migration trick used for layouts 2 and 3 no longer applies.
4. Secrets: the connection string goes through the normal secret tooling,
   never into the repo.

## 5. Rough effort (estimates)

1. Evidence and CAS port plus verification: one to two days of agent time.
2. Search layer rewrite plus equivalence testing: about a week.
3. Cutover under the maintenance lock: about an hour once the new store is
   loaded and verified; keep the SQLite files until a clean week of cycles.

## 6. Keep it portable meanwhile

1. Keep SQL inside `EvidenceStore` and `SearchIndex`; adapters call methods,
   never raw SQL on the store.
2. Prefer standard SQL (`ON CONFLICT` upserts) over SQLite-only forms in new
   code.
3. Keep the CAS bytes application-compressed so they move unchanged.
