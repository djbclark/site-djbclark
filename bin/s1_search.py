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

**One copy of the text, two indexes over it (layout 2).** The projection is
stored once, in `event_text`; `event_fts` and `event_trigram` are FTS5
*external-content* tables that read it for snippets and match checks. The
trigram index is `detail=none` (no positions): 0.4 GB instead of 2.6 GB.
Without positions FTS5 cannot run a quoted trigram phrase, so trigram mode
asks `body LIKE '%q%'` (index-assisted; it narrows to rows that hold every
trigram) and then re-checks the literal in Python. Hit sets equal the old
phrase query; ranking within them is coarser, because bm25 has no term
frequencies under `detail=none`. Layout 1 (each index with its own internal
copy of the text, trigram at `detail=full`) took 5.4 GB at 448k events;
layout 2 takes 2.3 GB once vacuumed. `migrate` converts a layout-1 store;
`vacuum` then returns the freed pages. The layout is recorded in `s1_meta`
(`search_layout`) and the two are never mixed.

The index is derived state — it can be dropped and rebuilt from the CAS at
any time, and never carries information the evidence does not.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s1_evidence import DEFAULT_DB, EvidenceStore, now_iso  # noqa: E402

PROJECTION_CHARS = 8192
# Version of project(): bump it and build() re-indexes every event.
INDEX_VERSION = 1
# Version of the table layout (module docstring), stored in s1_meta.
SEARCH_LAYOUT = 2
TRIGRAM_MIN_CHARS = 3
INDEX_TABLES = ("event_fts", "event_trigram")
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


def vacuum(store: EvidenceStore, into: str | Path | None = None) -> dict[str, Any]:
    """Return free pages: VACUUM in place, or VACUUM INTO a new file."""
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
        self._migrate()

    def _migrate(self) -> None:
        found = store_layout(self.db)
        if found is not None and found != SEARCH_LAYOUT:
            raise LayoutError(
                f"{self.store.path}: search layout {found}, this code needs {SEARCH_LAYOUT};"
                " run `s1_search.py migrate`, then `s1_search.py vacuum`")
        self.db.executescript(
            "BEGIN;" + _LAYOUT_DDL +
            "INSERT OR IGNORE INTO s1_meta (key, value)"
            f" VALUES ('search_layout', '{SEARCH_LAYOUT}');"
            "COMMIT;")

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
            rowid = self.db.execute("INSERT INTO event_text (event_id, body) VALUES (?,?)",
                                    (event_id, body)).lastrowid
        else:
            rowid = old["id"]
            for table in INDEX_TABLES:
                self.db.execute(f"INSERT INTO {table} ({table}, rowid, event_id, body)"
                                " VALUES ('delete', ?, ?, ?)", (rowid, event_id, old["body"]))
            self.db.execute("UPDATE event_text SET body=? WHERE id=?", (body, rowid))
        for table in INDEX_TABLES:
            self.db.execute(f"INSERT INTO {table} (rowid, event_id, body) VALUES (?,?,?)",
                            (rowid, event_id, body))

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
            result["healthy"] = all(v == "ok" for v in result["integrity_check"].values())
        return result


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
                    help="also run the FTS5 integrity-check on both indexes (slow)")
    m = sub.add_parser("migrate", help="convert a layout-1 index to layout 2 (one-off, idempotent)")
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
        return _run(args, store)
    except (LayoutError, FileExistsError) as exc:
        print(f"{args.command}: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()


def _run(args: argparse.Namespace, store: EvidenceStore) -> int:
    if args.command == "migrate":
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
