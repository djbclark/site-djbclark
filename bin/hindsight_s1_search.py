#!/usr/bin/env python3
"""Retrieval over the S1 evidence store.

S1 shipped with exact substring search that scans every CAS object. That is
ground truth and stays — it is what a restore drill uses to prove the bytes
are really there — but at 448k events it is far too slow to actually use.

This adds three indexed modes on top:

- **fts** — word and phrase search (FTS5, unicode61). The everyday mode.
- **trigram** — substring and typo-tolerant search (FTS5 trigram), for when
  you half-remember a symbol or a path.
- **neighbours** — given a hit, the events around it in the same
  conversation. Retrieval that returns a single message out of a 200-turn
  session is usually useless; the surrounding turns are the answer.

**Indexed text is a bounded projection, not the whole payload.** Only the
first `PROJECTION_CHARS` of each event is indexed. A trigram index over 2.1GB
of raw bytes would cost several GB and index mostly JSON punctuation. The
projection keeps the index small and covers the searchable head of an event;
`exact` still scans the full bytes when completeness matters. This is a
deliberate trade, and the reason both modes exist.

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

from hindsight_s1 import EvidenceStore, now_iso  # noqa: E402

PROJECTION_CHARS = 8192
INDEX_VERSION = 1


def project(payload: bytes) -> str:
    """The searchable head of an event, as text.

    JSON payloads are flattened to their scalar values: indexing raw JSON
    means indexing keys and punctuation, which pollutes every query with
    structural noise. Non-JSON falls back to decoded text.
    """
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
        self._migrate()

    def _migrate(self) -> None:
        self.db.executescript(
            """
        CREATE VIRTUAL TABLE IF NOT EXISTS event_fts
          USING fts5(event_id UNINDEXED, body, tokenize='unicode61');
        CREATE VIRTUAL TABLE IF NOT EXISTS event_trigram
          USING fts5(event_id UNINDEXED, body, tokenize='trigram');
        CREATE TABLE IF NOT EXISTS search_indexed (
          event_id   TEXT PRIMARY KEY REFERENCES event(event_id) ON DELETE CASCADE,
          indexed_at TEXT NOT NULL,
          version    INTEGER NOT NULL
        );
        """
        )
        self.db.commit()

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
            body = project(payload)
            self.db.execute("INSERT INTO event_fts (event_id, body) VALUES (?,?)",
                            (row["event_id"], body))
            self.db.execute("INSERT INTO event_trigram (event_id, body) VALUES (?,?)",
                            (row["event_id"], body))
            self.db.execute(
                "INSERT OR REPLACE INTO search_indexed (event_id, indexed_at, version)"
                " VALUES (?,?,?)", (row["event_id"], now_iso(), INDEX_VERSION))
            done += 1
            if done % progress == 0:
                self.db.commit()
                print(f"  indexed {done}/{len(rows)}", flush=True)
        self.db.commit()
        return {"indexed": done, "cas_missing": missing, "remaining": self.pending()}

    # -- querying ---------------------------------------------------------

    def _hits(self, table: str, query: str, limit: int) -> list[sqlite3.Row]:
        return self.db.execute(
            f"SELECT e.*, snippet({table}, 1, '[', ']', '…', 12) AS snip"
            f" FROM {table} JOIN event e ON e.event_id = {table}.event_id"
            f" WHERE {table} MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()

    def search(self, query: str, *, mode: str = "fts", limit: int = 20) -> list[sqlite3.Row]:
        """fts = words/phrases; trigram = substrings; exact = full-byte scan."""
        if mode == "fts":
            return self._hits("event_fts", query, limit)
        if mode == "trigram":
            # Trigram MATCH wants a literal; quote it so punctuation in a path
            # or symbol name is not read as FTS syntax.
            return self._hits("event_trigram", '"' + query.replace('"', '""') + '"', limit)
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

    def stats(self) -> dict[str, Any]:
        return {
            "events": self.db.execute("SELECT COUNT(*) FROM event").fetchone()[0],
            "indexed": self.db.execute("SELECT COUNT(*) FROM search_indexed").fetchone()[0],
            "pending": self.pending(),
            "projection_chars": PROJECTION_CHARS,
            "index_version": INDEX_VERSION,
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
    sub.add_parser("stats")

    args = parser.parse_args(argv)
    kwargs: dict[str, Any] = {}
    if args.db:
        kwargs["db_path"] = args.db
    if args.cas:
        kwargs["cas_root"] = args.cas
    index = SearchIndex(EvidenceStore(**kwargs))

    if args.command == "index":
        print(json.dumps(index.build(limit=args.limit), indent=2))
    elif args.command == "search":
        _print(index.search(args.query, mode=args.mode, limit=args.limit))
    elif args.command == "neighbours":
        _print(index.neighbours(args.event_id, window=args.window))
    elif args.command == "stats":
        print(json.dumps(index.stats(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
