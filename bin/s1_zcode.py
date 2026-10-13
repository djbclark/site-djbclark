#!/usr/bin/env python3
"""S1 adapter for zcode's opencode-shaped SQLite history database.

This deliberately reuses the OpenCode reader and its strict session/message/
part table and column allow-list. Only the source path and stable producer id
differ; credentials/configuration and rollout/artifact siblings are never read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s1_evidence import EvidenceStore  # noqa: E402
from s1_opencode import sink as _sqlite_sink  # noqa: E402

PRODUCER = "zcode"
SOURCE_DB = Path.home() / ".zcode" / "cli" / "db" / "db.sqlite"


def sink(
    store: EvidenceStore, source_db: str | Path = SOURCE_DB, **kwargs: Any
) -> dict[str, int]:
    """Delegate to the shared SQLite reader with zcode's distinct identity."""
    return _sqlite_sink(store, source_db, producer=PRODUCER, **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest zcode SQLite history into S1")
    parser.add_argument("--db", default=None, help="S1 database")
    parser.add_argument("--cas", default=None, help="S1 content-addressed store")
    parser.add_argument(
        "--source-db", default=str(SOURCE_DB), help="zcode history database"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("sink", help="ingest allow-listed history rows, resuming")
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    kwargs: dict[str, Any] = {}
    if args.db:
        kwargs["db_path"] = args.db
    if args.cas:
        kwargs["cas_root"] = args.cas
    store = EvidenceStore(**kwargs)
    try:
        result = sink(
            store, Path(args.source_db), dry_run=args.dry_run, limit=args.limit
        )
        print(json.dumps({"dry_run": args.dry_run, **result}, indent=2))
        return 1 if result["failed"] else 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
