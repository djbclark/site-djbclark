# S1 archive: per-source zstd JSONL files searched with ugrep (design, 2026-10-31)

Status: implementation in progress (branch `s1-archive-ugrep`). Decided by djbclark on
2026-10-31 after the size study in this session: replace the two SQLite files of the S1
evidence store (`~/.local/share/s1-evidence/`, 16.4 GB) with plain compressed files,
searched by `ugrep -z` (+ `ugrep-indexer -z`). Sampled compression of today's source logs
predicts about 2 GB for the same data. On 2026-11-06 a new desktop box arrives and a
PostgreSQL S1 may then be built there with this Mac as feeder and search consumer
(`s1-postgres-migration-notes.md`); this layout is designed so that move stays cheap
(section 9).

## 1. Goals and non-goals

Goals: far less disk; no data loss; every existing adapter keeps working; search keeps
working for `verify_facts.py`, `mine_sessions.py`, `fleet-watch` and the skills that quote
`s1_search.py`; nothing is ever decompressed to disk.

Non-goals: SQL, ranking, FTS5 phrase/NEAR semantics, cross-source dedup. Search is
grep-style (literal or regex), newest files first.

## 2. Layout

Root `~/.local/share/s1-archive/` (override: `S1_ARCHIVE_ROOT`; tests pass a temp dir).

    sessions/<producer>/<h2>/<slug>-<h12>.jsonl.zst   one file per (producer, source_uri)
    state/checkpoints.jsonl                           last line per (producer, source_uri) wins
    state/gaps.jsonl                                  ingest_gap records
    state/heads.json                                  per producer: newest ts, count, last ingest
    ingest.lock  maintenance.lock  cycle.log          unchanged semantics from s1_cycle.py
    **/._UG#_Store                                    ugrep-indexer index files (disposable)

`h = sha256(f"{producer}\0{source_uri}")` hex; `<h2>` = first 2 chars, `<h12>` = first 12;
`<slug>` = the source_uri basename reduced to `[A-Za-z0-9._-]`, at most 48 chars, never empty
(`session` if nothing is left). A source_uri never contributes a path separator: nothing
derived from log content may escape the root (checked by test).

## 3. Record format

One JSON object per line, UTF-8, `ensure_ascii=False`, `separators=(",", ":")`, keys sorted
as written below. Lines never contain a raw newline (JSON escapes it).

Event: `{"v":1,"t":"ev","id":<event_id>,"producer":..,"source_uri":..,"source_locator":..,
"ts":<ts_utc>,"role":..,"event_type":..,"origin":..,"account_id":..,"scope":..,
"sensitivity":..,"ingest_batch":..,"ts_source":..,"content_encoding":..,
"producer_version":..|null,"producer_session_id":..|null,"source_seq":..|null,
"tool_name":..|null,"tool_call_id":..|null,"media_type":..|null,"sha256":<hex of raw>,
"size":<len(raw)>,"ingested":<ISO UTC>,"raw":<text>}`

`raw` holds the exact bytes: as a JSON string when the bytes are valid UTF-8 and round-trip
(`raw.decode("utf-8").encode("utf-8") == raw`), else the key is `raw_b64` (standard base64)
instead. `sha256` is always of the bytes, so a reader verifies losslessness itself.
`event_id` is still `derive_event_id(producer, source_uri, source_locator, sha256)`
(copy the function; do not import the SQLite module).

Conversation membership: `{"v":1,"t":"conv","id":<event_id>,"conversation_id":..,
"assigned_by":..,"confidence":..|null,"at":<ISO UTC>}`. Last record per (id, conversation_id)
wins. Stored in the same file as the event.

State records (`state/*.jsonl`, uncompressed, small): checkpoints
`{"producer","source_uri","fingerprint","committed_locator","adapter_version","at"}`; gaps
`{"producer","source_uri","reason","from_locator","to_locator","at"}`.

## 4. Writing: append a zstd frame

A zstd file may be a concatenation of frames; `compression.zstd.decompress`, `zstd -d`,
`ugrep -z` and `ugrep-indexer -z` all read it as one stream (checked 2026-10-31 with
ugrep 7.8.5 / ugrep-indexer 7.5.0). So a cycle appends one frame per touched file:

1. Build the frame in memory (level 3), `os.open(path, O_WRONLY|O_APPEND|O_CREAT, 0o600)`, one
   `os.write`, `os.fsync`, close. Create parent dirs 0o700.
2. Only after the frame is durable write the checkpoint (append to `state/checkpoints.jsonl`,
   fsync). A crash between the two re-ingests the same events, which dedup (section 5).
3. A torn tail frame (crash mid-write) is detected when a file is loaded for a write:
   find the end of the last complete frame, truncate the file to it, log it. A file that
   fails earlier than its tail is never "repaired": raise `ArchiveCorrupt` and name the file.

Files are created 0o600 (the content is private chat logs).

Compaction (`s1_archive.py compact`, a cycle step under the ingest lock): a file with more
than one frame and `mtime` older than 6 h is rewritten as one frame at level 12 to a temp file
beside it, verified (decoded record count and every `sha256` equal the original), then
`os.replace`d. Never touch a file newer than 6 h or while `maintenance.lock` exists.

## 5. Idempotency without a database

`put_event` loads the source's file once per process (cached): the set of `(source_locator ->
(event_id, sha256))`. Same locator and same sha: return `(event_id, False)`. Same locator,
different sha: raise `SourceMutated` (same contract as the SQLite store). New: append.
Writes are buffered per file and flushed by `flush()` / `close()` / when a buffer reaches
4 MiB; `set_checkpoint` calls `flush()` for that source first, so a checkpoint never
outruns its events.

## 6. Search

`bin/s1_search.py` becomes a thin ugrep driver (argv lists, `shell=True` never, a pattern
always after `--`/`-e`):

    ugrep -z -I --index -F -i? -o? ... -- PATTERN ROOT/sessions

Subcommands keep their names: `search PHRASE [--mode fts|trigram] [--producer P] [--limit N]
[--json]` (mode `trigram` = `-F` literal; `fts` = word-ish: each whitespace word as a `-e`
with `--and`... see the slice brief), `neighbours EVENT_ID [--window N]` (finds the file via
`ugrep -F -l EVENT_ID`, loads it, prints the window around it in file order), `index`
(runs `ugrep-indexer -z -I -v <root>/sessions` with the chosen accuracy, then `compact`),
`stats`, `check`. Result rows keep the old columns: `event_id producer ts role
source_uri snippet`; a snippet is cut around the match from the decoded `raw`, at most
240 chars. Exit codes: 0 hits, 1 no hits, 2 usage, 3 ugrep missing or failed.

Known ugrep-indexer behaviour (tested 2026-10-31): a file modified after indexing is always
searched (correct); modified within the same second as the index run, it can be missed until
the next run. Cycle order: append, then index, so a miss needs an append within one second
after the index pass; documented, accepted.

## 7. What replaces what

    EvidenceStore (s1_evidence.py)  ->  ArchiveStore (s1_archive.py), same method names
    SearchIndex  (s1_search.py)     ->  ugrep driver (same CLI)
    candidates.sqlite3, pack.sqlite3 ->  sessions/**.jsonl.zst + state/*.jsonl
    s1_cycle.py STEPS "search-index" ->  "archive-index" (ugrep-indexer) + "archive-compact"

`s1_evidence.py` stays in the tree, unchanged, until djbclark approves deleting the old
store; the backfill exporter (`s1_export.py`) is its only remaining user.

## 8. Backfill and cutover

1. `s1_export.py export` reads the live SQLite store read-only (`mode=ro`, never `immutable=1`),
   nice'd, per source in `ingest_lsn` order, and writes through `ArchiveStore` (events,
   conversation_member, ingest_checkpoint, ingest_gap, producer heads). Resumable: re-running
   skips what already dedups.
2. `s1_export.py verify` compares per-producer counts, every event_id present, a random
   sample of 20,000 events byte-for-byte (sha256 old vs new) and prints PASS/FAIL.
3. Cutover: pause `com.djbclark.s1-ingest`, final export delta, verify, point the cycle at
   the archive, re-enable. The old `~/.local/share/s1-evidence/` is NOT deleted by any code
   here: that reclaim (about 16 GB) waits for djbclark's explicit yes.

## 9. Keeping the PostgreSQL move cheap (2026-11-06 box)

The archive is the canonical, loss-free interchange form: one self-describing JSON line per
event, with `sha256` and ids stable across stores. A later loader maps each `ev` line to the
`event` table and `raw` to the blob table without touching adapters; the ArchiveStore
method set is the same interface a `PostgresStore` would implement, and the Mac stays a
feeder (append) and search consumer. Tracked in a GitHub issue (see the PR).

## 10. Security notes

Log content is untrusted: it only ever becomes JSON string values, file contents and
ugrep patterns passed after `--`/`-e` as argv. No path component or command comes from it.
Archive files and dirs are owner-only. Index files hold hashed n-grams of private logs, so
they live under the same 0o700 root.
