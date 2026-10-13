#!/usr/bin/env python3
"""Retrieval over the S1 evidence store.

S1 shipped with exact substring search that scans every CAS object. That is
ground truth and stays — it is what a restore drill uses to prove the bytes
are really there — but at 448k events it is far too slow to actually use.

This adds three indexed modes on top:

- **fts** — word and phrase search (FTS5, unicode61). The everyday mode.
- **trigram** — literal substring search (FTS5 trigram), for when you
  half-remember a symbol or a path. Case-insensitive with Unicode case
  folding; `_` and `%` are literal; queries under 3 characters return
  nothing, because a trigram index cannot match them.
- **neighbours** — given a hit, the events around it in the same
  conversation. Retrieval that returns a single message out of a 200-turn
  session is usually useless; the surrounding turns are the answer.

**Indexed text is a bounded projection, not the whole payload.** Only the
first `PROJECTION_CHARS` of each event is indexed. A trigram index over 2.1GB
of raw bytes would cost several GB and index mostly JSON punctuation. The
projection keeps the index small and covers the searchable head of an event;
`exact` still scans the full bytes when completeness matters. This is a
deliberate trade, and the reason both modes exist.

**One copy of the text, two indexes over it (layouts 2 and 3).** Layout 2
stores the projection once, in `event_text`; `event_fts` and `event_trigram`
are FTS5 *external-content* tables that read it for snippets and match checks.
Layout 3 zstd-compresses each projection into `event_text_data`; a view named
`event_text` calls `s1_unzstd(blob, dict_id)` to expose the same content to the
unchanged FTS tables. This preserves their existing index data: before the
atomic table-to-view swap, migration fully verifies every decompressed row;
afterward `stats --check` runs rank=1 FTS integrity checks through the view.
The trigram index is `detail=none` (no positions): 0.4 GB instead of 2.6 GB.
Without positions FTS5 cannot run a quoted trigram phrase, so trigram mode
asks `body LIKE '%q%'` (index-assisted; it narrows to rows that hold every
trigram) and then re-checks the literal in Python. Hit sets equal the old
phrase query; ranking within them is coarser, because bm25 has no term
frequencies under `detail=none`. Layout 1 (each index with its own internal
copy of the text, trigram at `detail=full`) took 5.4 GB at 448k events;
layout 2 takes 2.3 GB once vacuumed. `migrate` converts a layout-1 store;
`vacuum` then returns the freed pages. The layout is recorded in `s1_meta`
(`search_layout`) and the two are never mixed.

`migrate --to-layout 3` explicitly starts/resumes layout 2 → 3. It trains a
dictionary from a random sample and copies in committed batches while layout 2
remains usable; a full verification precedes the final switch. `vacuum` remains
a separate step. Layout 2 remains the default for new stores, so deploying this
code against the live layout-2 store does not change its format. The view calls
a Python SQL function: every `s1_search.py` connection registers it. An ad-hoc
SQLite connection without it fails when a snippet, view read, rebuild, or
rank=1 integrity-check needs content. A direct view read reports
`no such function: s1_unzstd`; FTS5 may mask that detail as `SQL logic error`
(observed on SQLite 3.54.0), but it does not return an empty/wrong snippet.
Use `s1_search.py` to open layout-3 stores. The function and store codec are
implemented with the same stdlib-only libzstd binding used by `s1_evidence.py`
(the active Python 3.13 runtime has no `compression.zstd` module).

The index is derived state — it can be dropped and rebuilt from the CAS at
any time, and never carries information the evidence does not.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s1_evidence import DEFAULT_DB, EvidenceStore, _Zstd, now_iso  # noqa: E402

PROJECTION_CHARS = 8192
# Version of project(): bump it and build() re-indexes every event.
INDEX_VERSION = 1
# Version of the table layout (module docstring), stored in s1_meta.
SEARCH_LAYOUT = 2
COMPRESSED_LAYOUT = 3
TRIGRAM_MIN_CHARS = 3
INDEX_TABLES = ("event_fts", "event_trigram")
_TEXT_SIZE_BYTES = 4
_TEXT_COPY_BATCH = 5000
_TEXT_SAMPLE_ROWS = 1000
# SQLite up to 3.53 decodes the noncharacters U+FFFE and U+FFFF as U+FFFD;
# 3.54.0 (2026-10-09) keeps them. The same text then tokenizes differently
# under the two, and an FTS5 integrity-check written by one fails under the
# other. Indexed text stores them as U+FFFD, the way the older builds read it.
_NONCHARACTERS = str.maketrans({0xFFFE: 0xFFFD, 0xFFFF: 0xFFFD})

_LAYOUT_DDL = """
CREATE TABLE IF NOT EXISTS event_text (
  id       INTEGER PRIMARY KEY,
  event_id TEXT NOT NULL,
  body     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS event_text_event_idx ON event_text(event_id);
CREATE VIRTUAL TABLE IF NOT EXISTS event_fts
  USING fts5(event_id UNINDEXED, body, tokenize='unicode61',
             content='event_text', content_rowid='id');
CREATE VIRTUAL TABLE IF NOT EXISTS event_trigram
  USING fts5(event_id UNINDEXED, body, tokenize='trigram',
             content='event_text', content_rowid='id', detail=none);
CREATE TABLE IF NOT EXISTS search_indexed (
  event_id   TEXT PRIMARY KEY REFERENCES event(event_id) ON DELETE CASCADE,
  indexed_at TEXT NOT NULL,
  version    INTEGER NOT NULL
);
"""


class LayoutError(RuntimeError):
    """The store's search tables are not in a layout this code may touch."""


def store_layout(db: sqlite3.Connection) -> int | None:
    """The search layout of an open store: None when it has no index yet."""
    row = db.execute("SELECT value FROM s1_meta WHERE key='search_layout'").fetchone()
    if row is not None:
        return int(row[0])
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='event_fts'").fetchone():
        return 1
    return None


def _unpack_text(blob: bytes, dict_id: int, dictionary: bytes | None,
                 codec: _Zstd) -> str:
    if dict_id == 0:
        raw = bytes(blob)
    else:
        data = bytes(blob)
        if len(data) < _TEXT_SIZE_BYTES:
            raise ValueError("s1_search.py: truncated compressed event_text body")
        size = int.from_bytes(data[:_TEXT_SIZE_BYTES], "big")
        raw = codec.decompress(data[_TEXT_SIZE_BYTES:], size, dict_id, dictionary)
    return raw.decode("utf-8")


def _pack_text(body: str, dict_id: int, dictionary: bytes | None,
               codec: _Zstd) -> tuple[bytes, int]:
    raw = body.encode("utf-8")
    if len(raw) < 64:
        return raw, 0
    compressed = codec.compress(raw, dict_id, dictionary)
    if len(compressed) + _TEXT_SIZE_BYTES >= len(raw):
        return raw, 0
    return len(raw).to_bytes(_TEXT_SIZE_BYTES, "big") + compressed, dict_id


def _register_unzstd(db: sqlite3.Connection) -> tuple[Callable[[], _Zstd], Any]:
    """Register the layout-3 view function and return this connection's codec."""
    codec: list[_Zstd | None] = [None]
    dictionaries: dict[int, bytes | None] = {}

    def get_codec() -> _Zstd:
        if codec[0] is None:
            codec[0] = _Zstd()
        return codec[0]

    def dictionary_for(dict_id: int) -> bytes | None:
        if dict_id not in dictionaries:
            row = db.execute("SELECT dict FROM s1_text_dict WHERE id=?", (dict_id,)).fetchone()
            if row is None:
                raise ValueError(f"s1_search.py: missing event_text dictionary {dict_id}")
            dictionaries[dict_id] = bytes(row[0]) or None
        return dictionaries[dict_id]

    def unzstd(blob: bytes | None, dict_id: int | None) -> str | None:
        if blob is None or dict_id is None:
            return None
        value = int(dict_id)
        return _unpack_text(bytes(blob), value,
                            dictionary_for(value) if value else None, get_codec())

    db.create_function("s1_unzstd", 2, unzstd, deterministic=True)
    return get_codec, dictionary_for


def other_writer_files(db_path: str | Path) -> list[Path]:
    """Journal files beside a database that no connection of ours has opened.

    A clean close removes `-wal` and `-shm`, and a committed rollback journal
    is deleted, so any of them before we open the file means another
    connection is live or one crashed mid-write.
    """
    return [p for p in (Path(f"{db_path}{s}") for s in ("-wal", "-shm", "-journal"))
            if p.exists()]


# PRAGMA quick_check rows that blame only the two layout-1 indexes, which
# migrate_layout() drops and rebuilds from their content table. The wording
# varies across SQLite versions (3.53.1 and 3.54.0 seen).
_OLD_INDEX_ERROR = re.compile(
    r'fts5: checksum mismatch for table "(event_fts|event_trigram)"'
    r'|(malformed inside|malformed inverted index for|unable to validate the inverted index for)'
    r' FTS5 table main\.(event_fts|event_trigram)(: .*)?')


def migrate_layout(db: sqlite3.Connection, *,
                   ignore_old_index_errors: bool = False) -> dict[str, Any]:
    """Convert a layout-1 store to layout 2 in one transaction. Idempotent.

    The text comes from layout 1's `event_fts_content`, which holds the same
    projection build() wrote, so nothing is re-read from the CAS and
    `search_indexed` stays valid. Freed pages stay in the file until `vacuum`.

    Refuses when PRAGMA quick_check reports anything. With
    `ignore_old_index_errors`, it proceeds when every reported problem is in
    the old event_fts/event_trigram indexes, which it is about to discard.
    On the live store (2026-10-12) SQLite 3.54.0 flagged both, because two
    rows hold U+FFFF and the older build that wrote them read it as U+FFFD
    (see _NONCHARACTERS); SQLite 3.53.1 and Apple's build passed them.
    """
    found = store_layout(db)
    if found == SEARCH_LAYOUT:
        return {"migrated": False, "layout": SEARCH_LAYOUT}
    if found == COMPRESSED_LAYOUT:
        return {"migrated": False, "layout": COMPRESSED_LAYOUT,
                "note": "already migrated; layout 3 is not downgraded"}
    if found is not None and found != 1:
        raise LayoutError(f"unknown search layout {found}")
    problems = [r[0] for r in db.execute("PRAGMA quick_check(100)")]
    report: dict[str, Any] = {"migrated": True, "from_layout": found, "layout": SEARCH_LAYOUT}
    if problems != ["ok"]:
        tolerable = found == 1 and all(_OLD_INDEX_ERROR.fullmatch(p) for p in problems)
        if not (ignore_old_index_errors and tolerable):
            hint = " (all in the old indexes: --ignore-old-index-errors)" if tolerable else ""
            raise LayoutError(f"PRAGMA quick_check failed, not migrating{hint}: {problems}")
        report["ignored_old_index_errors"] = problems
    db.execute("BEGIN IMMEDIATE")
    try:
        if found == 1:
            db.execute("CREATE TABLE event_text (id INTEGER PRIMARY KEY,"
                       " event_id TEXT NOT NULL, body TEXT NOT NULL)")
            # One row per event; a duplicate (never seen) keeps its newest text.
            db.execute(
                "INSERT INTO event_text (id, event_id, body)"
                " SELECT id, c0, c1 FROM event_fts_content WHERE id IN"
                " (SELECT MAX(id) FROM event_fts_content"
                "  WHERE c0 IS NOT NULL AND c1 IS NOT NULL GROUP BY c0)"
                " ORDER BY id")
            report["noncharacters_replaced"] = db.execute(
                "UPDATE event_text SET body = replace(replace(body,"
                " char(65534), char(65533)), char(65535), char(65533))"
                " WHERE instr(body, char(65534)) > 0 OR instr(body, char(65535)) > 0").rowcount
            db.execute("DROP TABLE event_fts")
            db.execute("DROP TABLE event_trigram")
        for stmt in _LAYOUT_DDL.split(";"):
            if stmt.strip():
                db.execute(stmt)
        for table in INDEX_TABLES:
            db.execute(f"INSERT INTO {table} ({table}) VALUES ('rebuild')")
            db.execute(f"INSERT INTO {table} ({table}) VALUES ('optimize')")
        # An event marked indexed whose text did not carry over is re-indexed.
        report["reset_indexed"] = db.execute(
            "DELETE FROM search_indexed WHERE event_id NOT IN"
            " (SELECT event_id FROM event_text)").rowcount
        db.execute("INSERT OR REPLACE INTO s1_meta (key, value) VALUES ('search_layout', ?)",
                   (str(SEARCH_LAYOUT),))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    report["text_rows"] = db.execute("SELECT COUNT(*) FROM event_text").fetchone()[0]
    return report


def migrate_layout3(db: sqlite3.Connection, *, batch_size: int = _TEXT_COPY_BATCH,
                    max_batches: int | None = None) -> dict[str, Any]:
    """Resumably convert layout 2 to per-row zstd layout 3.

    The layout-2 table remains authoritative throughout the batched shadow
    copy. A final full identity pass and FTS5 rank=1 checks happen in the same
    write transaction as the table-to-view swap. The FTS virtual tables keep
    their existing `content='event_text'` declaration and index data.

    `max_batches` is a test/recovery aid: it commits that many copy batches
    and returns with layout 2 intact so a later call can resume.
    """
    found = store_layout(db)
    if found == COMPRESSED_LAYOUT:
        return {"migrated": False, "layout": COMPRESSED_LAYOUT}
    if found != SEARCH_LAYOUT:
        raise LayoutError(
            f"layout 3 migration requires layout 2, found {found}; "
            "run `s1_search.py migrate` first if this is a layout-1 store"
        )
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    db.executescript(
        "CREATE TABLE IF NOT EXISTS s1_text_dict ("
        " id INTEGER PRIMARY KEY, dict BLOB NOT NULL);"
        "CREATE TABLE IF NOT EXISTS event_text_zstage ("
        " id INTEGER PRIMARY KEY, event_id TEXT NOT NULL,"
        " zbody BLOB NOT NULL, dict_id INTEGER NOT NULL);"
        "CREATE UNIQUE INDEX IF NOT EXISTS event_text_zstage_event_idx"
        " ON event_text_zstage(event_id);"
        "CREATE TABLE IF NOT EXISTS s1_text_migration ("
        " id INTEGER PRIMARY KEY CHECK(id=1), dict_id INTEGER NOT NULL,"
        " last_id INTEGER NOT NULL DEFAULT 0);")

    get_codec, dictionary_for = _register_unzstd(db)
    codec = get_codec()
    timings = {"dictionary_seconds": 0.0, "copy_seconds": 0.0,
               "verify_seconds": 0.0, "switch_seconds": 0.0}
    state = db.execute(
        "SELECT dict_id,last_id FROM s1_text_migration WHERE id=1"
    ).fetchone()
    if state is None:
        started = time.perf_counter()
        samples = [str(r[0]).encode("utf-8") for r in db.execute(
            "SELECT body FROM event_text ORDER BY random() LIMIT ?",
            (_TEXT_SAMPLE_ROWS,),
        )]
        dictionary = b""
        if len(samples) >= 100:
            try:
                dictionary = codec.train(samples)
            except ValueError:
                # Small/low-entropy fixtures and unusual corpora still migrate
                # safely; they use zstd without a trained dictionary.
                dictionary = b""
        dict_id = db.execute(
            "SELECT COALESCE(MAX(id),0)+1 FROM s1_text_dict"
        ).fetchone()[0]
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO s1_text_dict(id,dict) VALUES(?,?)",
                   (dict_id, dictionary))
        db.execute("INSERT INTO s1_text_migration(id,dict_id,last_id) VALUES(1,?,0)",
                   (dict_id,))
        db.commit()
        timings["dictionary_seconds"] = time.perf_counter() - started
        state = (dict_id, 0)
    dict_id, last_id = int(state[0]), int(state[1])
    dictionary = dictionary_for(dict_id)

    batches = 0
    copied_rows = 0
    started = time.perf_counter()
    while True:
        rows = db.execute(
            "SELECT id,event_id,body FROM event_text WHERE id>? ORDER BY id LIMIT ?",
            (last_id, batch_size),
        ).fetchall()
        if not rows:
            break
        packed = []
        for row in rows:
            zbody, used_dict = _pack_text(row[2], dict_id, dictionary, codec)
            packed.append((row[0], row[1], zbody, used_dict))
        db.execute("BEGIN IMMEDIATE")
        db.executemany(
            "INSERT OR REPLACE INTO event_text_zstage(id,event_id,zbody,dict_id)"
            " VALUES(?,?,?,?)", packed,
        )
        last_id = int(rows[-1][0])
        db.execute("UPDATE s1_text_migration SET last_id=? WHERE id=1", (last_id,))
        db.commit()
        copied_rows += len(rows)
        batches += 1
        if max_batches is not None and batches >= max_batches:
            timings["copy_seconds"] = time.perf_counter() - started
            return {"migrated": False, "resumable": True, "layout": SEARCH_LAYOUT,
                    "copy_batches": batches, "copied_rows": copied_rows,
                    "last_id": last_id, "dict_id": dict_id, **timings}
    timings["copy_seconds"] = time.perf_counter() - started

    # Reconcile any rows changed while a resumable copy was paused. Layout 2
    # remains queryable until this entire pass and the final locked pass finish.
    started = time.perf_counter()
    repaired_rows = 0
    cursor = db.execute("SELECT id,event_id,body FROM event_text ORDER BY id")
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        ids = [int(r[0]) for r in rows]
        marks = ",".join("?" for _ in ids)
        staged = {int(r[0]): r for r in db.execute(
            f"SELECT id,event_id,zbody,dict_id FROM event_text_zstage WHERE id IN ({marks})",
            ids,
        )}
        repairs = []
        for source in rows:
            old = staged.get(int(source[0]))
            same = False
            if old is not None and old[1] == source[1]:
                try:
                    same = _unpack_text(old[2], int(old[3]),
                                        dictionary_for(int(old[3])) if old[3] else None,
                                        codec) == source[2]
                except (ValueError, UnicodeError):
                    same = False
            if not same:
                zbody, used_dict = _pack_text(source[2], dict_id, dictionary, codec)
                repairs.append((source[0], source[1], zbody, used_dict))
        if repairs:
            db.execute("BEGIN IMMEDIATE")
            db.executemany(
                "INSERT OR REPLACE INTO event_text_zstage(id,event_id,zbody,dict_id)"
                " VALUES(?,?,?,?)", repairs,
            )
            db.commit()
            repaired_rows += len(repairs)
    db.execute(
        "DELETE FROM event_text_zstage WHERE NOT EXISTS"
        " (SELECT 1 FROM event_text WHERE event_text.id=event_text_zstage.id)"
    )
    db.commit()
    timings["verify_seconds"] = time.perf_counter() - started

    # Full strict verification and publication are serialized with all SQLite
    # writers. A failed check rolls the DDL back and leaves the staged copy for
    # a subsequent resumable invocation.
    started = time.perf_counter()
    db.execute("BEGIN IMMEDIATE")
    try:
        source_count = db.execute("SELECT COUNT(*) FROM event_text").fetchone()[0]
        stage_count = db.execute("SELECT COUNT(*) FROM event_text_zstage").fetchone()[0]
        mismatches = abs(source_count - stage_count)
        cursor = db.execute("SELECT id,event_id,body FROM event_text ORDER BY id")
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            ids = [int(r[0]) for r in rows]
            marks = ",".join("?" for _ in ids)
            staged = {int(r[0]): r for r in db.execute(
                f"SELECT id,event_id,zbody,dict_id FROM event_text_zstage WHERE id IN ({marks})",
                ids,
            )}
            for source in rows:
                stored = staged.get(int(source[0]))
                if stored is None or stored[1] != source[1]:
                    mismatches += 1
                    continue
                try:
                    body = _unpack_text(
                        stored[2], int(stored[3]),
                        dictionary_for(int(stored[3])) if stored[3] else None, codec,
                    )
                except (ValueError, UnicodeError):
                    mismatches += 1
                    continue
                if body != source[2]:
                    mismatches += 1
        if mismatches:
            raise LayoutError(
                f"layout 3 final verification found {mismatches} row mismatch(es); "
                "migration remains resumable; rerun `migrate --to-layout 3`"
            )

        db.execute("DROP TABLE event_text")
        db.execute("ALTER TABLE event_text_zstage RENAME TO event_text_data")
        db.execute("DROP INDEX event_text_zstage_event_idx")
        db.execute("CREATE UNIQUE INDEX event_text_event_idx ON event_text_data(event_id)")
        db.execute(
            "CREATE VIEW event_text AS SELECT id,event_id,"
            "s1_unzstd(zbody,dict_id) AS body FROM event_text_data"
        )
        db.execute(
            "INSERT OR REPLACE INTO s1_meta(key,value) VALUES('search_layout',?)",
            (str(COMPRESSED_LAYOUT),),
        )
        db.execute(
            "INSERT OR REPLACE INTO s1_meta(key,value) VALUES('search_dict_id',?)",
            (str(dict_id),),
        )
        db.execute("DROP TABLE s1_text_migration")
        for table in INDEX_TABLES:
            db.execute(f"INSERT INTO {table} ({table},rank) VALUES ('integrity-check',1)")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    timings["switch_seconds"] = time.perf_counter() - started
    return {"migrated": True, "from_layout": SEARCH_LAYOUT,
            "layout": COMPRESSED_LAYOUT, "dict_id": dict_id,
            "dictionary_bytes": len(dictionary or b""), "text_rows": source_count,
            "copied_rows": copied_rows, "repaired_rows": repaired_rows,
            "verified_rows": source_count, "verification_mismatches": 0,
            "fts_indexes_preserved": True, "copy_batches": batches, **timings}


def vacuum(store: EvidenceStore, into: str | Path | None = None) -> dict[str, Any]:
    """Return free pages: VACUUM in place, or VACUUM INTO a new file."""
    _register_unzstd(store.db)
    before = store.path.stat().st_size
    if into is None:
        store.db.execute("VACUUM")
        target = store.path
    else:
        target = Path(into).expanduser()
        if target.exists():
            raise FileExistsError(target)
        store.db.execute("VACUUM INTO ?", (str(target),))
    return {"file": str(target), "bytes_before": before, "bytes_after": target.stat().st_size}


def _contains(body: str | None, query: str | None) -> bool:
    return body is not None and query is not None and query.casefold() in body.casefold()


def _like_pattern(query: str) -> str:
    """A LIKE pattern that matches every row containing `query`, and maybe more.

    LIKE folds ASCII case only, so a non-ASCII character with case variants
    becomes `_` (any one character). `_` and `%` in the query stay wildcards:
    escaping them with ESCAPE turns off the trigram index. Either way the
    pattern can only over-match, and s1_contains() then checks the literal.
    """
    return "%" + "".join(
        "_" if ord(c) > 127 and (c.lower() != c or c.upper() != c or c.casefold() != c) else c
        for c in query) + "%"


def project(payload: bytes) -> str:
    """The searchable head of an event, as text.

    JSON payloads are flattened to their scalar values: indexing raw JSON
    means indexing keys and punctuation, which pollutes every query with
    structural noise. Non-JSON falls back to decoded text.
    """
    return _project(payload).translate(_NONCHARACTERS)


def _project(payload: bytes) -> str:
    # Lossless row envelopes may be much larger than the projection window.
    # Their canonical JSON puts this key first, so decode just its JSON string
    # instead of parsing a deliberately truncated document or indexing base64.
    projection_prefix = b'{"_s1_search_text":'
    if payload.startswith(projection_prefix):
        try:
            projected, _ = json.JSONDecoder().raw_decode(
                payload[len(projection_prefix) :].decode("utf-8")
            )
        except (UnicodeDecodeError, ValueError):
            projected = None
        if isinstance(projected, str):
            return projected[:PROJECTION_CHARS]

    head = payload[: PROJECTION_CHARS * 2]
    try:
        obj = json.loads(head.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        return head.decode("utf-8", errors="replace")[:PROJECTION_CHARS]

    parts: list[str] = []

    def walk(node: Any) -> None:
        if len(" ".join(parts)) > PROJECTION_CHARS:
            return
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            parts.append(node)
        elif node is not None:
            parts.append(str(node))

    walk(obj)
    return " ".join(parts)[:PROJECTION_CHARS]


class SearchIndex:
    def __init__(self, store: EvidenceStore):
        self.store = store
        self.db = store.db
        self.db.create_function("s1_contains", 2, _contains, deterministic=True)
        self._text_codec, self._text_dictionary = _register_unzstd(self.db)
        self._migrate()

    def _migrate(self) -> None:
        found = store_layout(self.db)
        if found not in (None, SEARCH_LAYOUT, COMPRESSED_LAYOUT):
            raise LayoutError(
                f"{self.store.path}: search layout {found}, this code needs {SEARCH_LAYOUT};"
                " run `s1_search.py migrate`, then `s1_search.py vacuum`")
        if found != COMPRESSED_LAYOUT:
            self.db.executescript(
                "BEGIN;" + _LAYOUT_DDL +
                "INSERT OR IGNORE INTO s1_meta (key, value)"
                f" VALUES ('search_layout', '{SEARCH_LAYOUT}');"
                "COMMIT;")
        self.layout = store_layout(self.db)

    # -- indexing ---------------------------------------------------------

    def pending(self) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM event e LEFT JOIN search_indexed s"
            " ON s.event_id = e.event_id AND s.version = ?"
            " WHERE s.event_id IS NULL", (INDEX_VERSION,)
        ).fetchone()[0]

    def build(self, *, limit: int | None = None, progress: int = 20000) -> dict[str, Any]:
        """Index events that have no current-version entry. Resumable by design."""
        query = ("SELECT e.event_id, e.raw_sha256 FROM event e"
                 " LEFT JOIN search_indexed s ON s.event_id = e.event_id AND s.version = ?"
                 " WHERE s.event_id IS NULL ORDER BY e.ingest_lsn")
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = self.db.execute(query, (INDEX_VERSION,)).fetchall()

        done = missing = 0
        for row in rows:
            try:
                payload = self.store.get_bytes(row["raw_sha256"])
            except FileNotFoundError:
                missing += 1
                continue
            self._put_text(row["event_id"], project(payload))
            self.db.execute(
                "INSERT OR REPLACE INTO search_indexed (event_id, indexed_at, version)"
                " VALUES (?,?,?)", (row["event_id"], now_iso(), INDEX_VERSION))
            done += 1
            if done % progress == 0:
                self.db.commit()
                print(f"  indexed {done}/{len(rows)}", flush=True)
        self.db.commit()
        return {"indexed": done, "cas_missing": missing, "remaining": self.pending()}

    def _put_text(self, event_id: str, body: str) -> None:
        """Write one event's text to event_text and both indexes, in step.

        External-content FTS5 never reads event_text on a write. Replacing a
        row therefore needs the FTS5 'delete' command with the *old* text
        first, or the old tokens stay in the index pointing at the new body.
        """
        old = self.db.execute("SELECT id, body FROM event_text WHERE event_id=?",
                              (event_id,)).fetchone()
        if old is None:
            if self.layout == COMPRESSED_LAYOUT:
                rowid = self._put_compressed_row(event_id, body)
            else:
                rowid = self.db.execute(
                    "INSERT INTO event_text (event_id, body) VALUES (?,?)",
                    (event_id, body),
                ).lastrowid
        else:
            rowid = old["id"]
            for table in INDEX_TABLES:
                self.db.execute(f"INSERT INTO {table} ({table}, rowid, event_id, body)"
                                " VALUES ('delete', ?, ?, ?)", (rowid, event_id, old["body"]))
            if self.layout == COMPRESSED_LAYOUT:
                self._update_compressed_row(rowid, body)
            else:
                self.db.execute("UPDATE event_text SET body=? WHERE id=?", (body, rowid))
        for table in INDEX_TABLES:
            self.db.execute(f"INSERT INTO {table} (rowid, event_id, body) VALUES (?,?,?)",
                            (rowid, event_id, body))

    def _put_compressed_row(self, event_id: str, body: str) -> int:
        dict_id = int(self.db.execute(
            "SELECT value FROM s1_meta WHERE key='search_dict_id'"
        ).fetchone()[0])
        dictionary = self._text_dictionary(dict_id)
        zbody, used_dict = _pack_text(body, dict_id, dictionary, self._text_codec())
        cursor = self.db.execute(
            "INSERT INTO event_text_data(event_id,zbody,dict_id) VALUES(?,?,?)",
            (event_id, zbody, used_dict),
        )
        return int(cursor.lastrowid)

    def _update_compressed_row(self, rowid: int, body: str) -> None:
        dict_id = int(self.db.execute(
            "SELECT value FROM s1_meta WHERE key='search_dict_id'"
        ).fetchone()[0])
        dictionary = self._text_dictionary(dict_id)
        zbody, used_dict = _pack_text(body, dict_id, dictionary, self._text_codec())
        self.db.execute(
            "UPDATE event_text_data SET zbody=?,dict_id=? WHERE id=?",
            (zbody, used_dict, rowid),
        )

    def _delete_text(self, event_id: str) -> bool:
        """Remove one projection and both FTS entries using the exact old body."""
        old = self.db.execute(
            "SELECT id,body FROM event_text WHERE event_id=?", (event_id,)
        ).fetchone()
        if old is None:
            return False
        for table in INDEX_TABLES:
            self.db.execute(
                f"INSERT INTO {table} ({table},rowid,event_id,body)"
                " VALUES ('delete',?,?,?)",
                (old["id"], event_id, old["body"]),
            )
        if self.layout == COMPRESSED_LAYOUT:
            self.db.execute("DELETE FROM event_text_data WHERE id=?", (old["id"],))
        else:
            self.db.execute("DELETE FROM event_text WHERE id=?", (old["id"],))
        self.db.execute("DELETE FROM search_indexed WHERE event_id=?", (event_id,))
        return True

    # -- querying ---------------------------------------------------------

    def _hits(self, table: str, where: str, params: tuple, limit: int) -> list[sqlite3.Row]:
        return self.db.execute(
            f"SELECT e.*, snippet({table}, 1, '[', ']', '…', 12) AS snip"
            f" FROM {table} JOIN event e ON e.event_id = {table}.event_id"
            f" WHERE {where} ORDER BY rank LIMIT ?",
            (*params, limit),
        ).fetchall()

    def search(self, query: str, *, mode: str = "fts", limit: int = 20) -> list[sqlite3.Row]:
        """fts = words/phrases; trigram = substrings; exact = full-byte scan."""
        if mode == "fts":
            return self._hits("event_fts", "event_fts MATCH ?", (query,), limit)
        if mode == "trigram":
            # The trigram index cannot match under 3 characters, and a LIKE
            # would turn into a full scan, so short queries find nothing.
            if len(query) < TRIGRAM_MIN_CHARS:
                return []
            return self._hits(
                "event_trigram",
                "event_trigram.body LIKE ? AND s1_contains(event_trigram.body, ?)",
                (_like_pattern(query), query), limit)
        if mode == "exact":
            return self.store.search(query, limit=limit)
        raise ValueError("mode must be one of: fts, trigram, exact")

    def neighbours(self, event_id: str, *, window: int = 3) -> list[sqlite3.Row]:
        """The events immediately around this one in its conversation.

        Falls back to the producer session when the event was never assigned
        to a conversation, so this still returns useful context rather than
        nothing.
        """
        row = self.store.get_event(event_id)
        if row is None:
            raise KeyError(event_id)
        member = self.db.execute(
            "SELECT conversation_id FROM conversation_member WHERE event_id=?",
            (event_id,)).fetchone()
        if member:
            scope_sql = ("SELECT e.* FROM event e JOIN conversation_member m"
                         " ON m.event_id = e.event_id WHERE m.conversation_id = ?")
            params: tuple = (member["conversation_id"],)
        else:
            scope_sql = "SELECT e.* FROM event e WHERE e.producer=? AND e.producer_session_id IS ?"
            params = (row["producer"], row["producer_session_id"])
        ordered = self.db.execute(
            scope_sql + " ORDER BY e.ts_utc, e.source_seq, e.ingest_lsn", params).fetchall()
        ids = [r["event_id"] for r in ordered]
        if event_id not in ids:
            return [row]
        i = ids.index(event_id)
        return ordered[max(0, i - window): i + window + 1]

    def check(self) -> dict[str, str]:
        """FTS5 integrity-check of each index, including against event_text."""
        result = {}
        for table in INDEX_TABLES:
            try:
                self.db.execute(f"INSERT INTO {table} ({table}, rank) VALUES ('integrity-check', 1)")
                result[table] = "ok"
            except sqlite3.DatabaseError as exc:
                result[table] = str(exc)
        self.db.commit()  # the INSERT opened a transaction; the check writes nothing
        return result

    def stats(self, *, check: bool = False) -> dict[str, Any]:
        result = {
            "events": self.db.execute("SELECT COUNT(*) FROM event").fetchone()[0],
            "indexed": self.db.execute("SELECT COUNT(*) FROM search_indexed").fetchone()[0],
            "text_rows": self.db.execute("SELECT COUNT(*) FROM event_text").fetchone()[0],
            "pending": self.pending(),
            "projection_chars": PROJECTION_CHARS,
            "index_version": INDEX_VERSION,
            "search_layout": store_layout(self.db),
        }
        if check:
            result["integrity_check"] = self.check()
            text_check = self._check_text() if self.layout == COMPRESSED_LAYOUT else "ok"
            result["text_check"] = text_check
            result["healthy"] = (
                all(v == "ok" for v in result["integrity_check"].values())
                and (text_check == "ok" or text_check.get("healthy", False))
            )
        return result

    def _check_text(self) -> dict[str, Any]:
        """Check layout-3 row counts and force decompression on a bounded sample."""
        try:
            view_rows = self.db.execute("SELECT COUNT(*) FROM event_text").fetchone()[0]
            data_rows = self.db.execute("SELECT COUNT(*) FROM event_text_data").fetchone()[0]
            indexed_rows = self.db.execute("SELECT COUNT(*) FROM search_indexed").fetchone()[0]
            sample = self.db.execute(
                "SELECT id,event_id,body FROM event_text ORDER BY random() LIMIT 32"
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            return {"healthy": False, "error": str(exc)}
        valid_sample = all(isinstance(row["body"], str) for row in sample)
        counts_match = view_rows == data_rows == indexed_rows
        return {
            "healthy": counts_match and valid_sample,
            "view_rows": view_rows,
            "compressed_rows": data_rows,
            "indexed_rows": indexed_rows,
            "decompression_sample_rows": len(sample),
            "row_counts_match": counts_match,
            "sample_ok": valid_sample,
        }


def _print(rows: list[sqlite3.Row]) -> None:
    for r in rows:
        snip = re.sub(r"\s+", " ", (r["snip"] if "snip" in r.keys() else "") or "")[:110]
        print(f"{r['event_id'][:14]}  {r['ts_utc'][:19]}  {r['producer'][:12]:12} "
              f"{(r['scope'] or '')[:16]:16} {snip}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Search the S1 evidence store")
    parser.add_argument("--db", default=None)
    parser.add_argument("--cas", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("index", help="build/extend the search index (resumable)")
    b.add_argument("--limit", type=int, default=None)
    q = sub.add_parser("search")
    q.add_argument("query")
    q.add_argument("--mode", choices=("fts", "trigram", "exact"), default="fts")
    q.add_argument("--limit", type=int, default=20)
    n = sub.add_parser("neighbours")
    n.add_argument("event_id")
    n.add_argument("--window", type=int, default=3)
    st = sub.add_parser("stats")
    st.add_argument("--check", action="store_true",
                    help="also run the FTS5 integrity-check on both indexes (slow; it is a write, so it holds the write lock for minutes: on the live store run it under maintenance.lock)")
    m = sub.add_parser("migrate", help="convert a search index to an explicitly selected layout")
    m.add_argument("--to-layout", choices=("2", "3"), default="2",
                   help="target layout (default: 2); use 3 to stage/resume zstd compression")
    m.add_argument("--ignore-old-index-errors", action="store_true",
                   help="proceed when quick_check blames only the indexes being replaced")
    v = sub.add_parser("vacuum", help="return free pages after migrate (explicit, slow)")
    v.add_argument("--into", default=None, help="write a compacted copy here instead")

    args = parser.parse_args(argv)
    kwargs: dict[str, Any] = {}
    if args.db:
        kwargs["db_path"] = args.db
    if args.cas:
        kwargs["cas_root"] = args.cas
    if args.command in ("migrate", "vacuum"):
        busy = other_writer_files(Path(args.db or DEFAULT_DB).expanduser())
        if busy:
            print(f"refusing to {args.command}: another writer may be live: "
                  + ", ".join(map(str, busy)), file=sys.stderr)
            return 2
    store = EvidenceStore(**kwargs)
    try:
        _register_unzstd(store.db)
        return _run(args, store)
    except (LayoutError, FileExistsError) as exc:
        print(f"{args.command}: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()


def _run(args: argparse.Namespace, store: EvidenceStore) -> int:
    if args.command == "migrate":
        if args.to_layout == "3":
            print(json.dumps(migrate_layout3(store.db), indent=2))
        else:
            print(json.dumps(migrate_layout(
                store.db, ignore_old_index_errors=args.ignore_old_index_errors), indent=2))
        return 0
    if args.command == "vacuum":
        print(json.dumps(vacuum(store, args.into), indent=2))
        return 0
    index = SearchIndex(store)
    if args.command == "index":
        print(json.dumps(index.build(limit=args.limit), indent=2))
    elif args.command == "search":
        _print(index.search(args.query, mode=args.mode, limit=args.limit))
    elif args.command == "neighbours":
        _print(index.neighbours(args.event_id, window=args.window))
    elif args.command == "stats":
        result = index.stats(check=args.check)
        print(json.dumps(result, indent=2))
        return 0 if result.get("healthy", True) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
