#!/usr/bin/env python3
"""Rescue Crush per-project SQLite evidence into S1.

Crush keeps ``.crush/crush.db`` inside each project listed by one of the
``~/.local/share/crush*/projects.json`` registries. Only that exact database
path (and the one global ``~/.config/crush/.crush/crush.db``) is considered;
registry configuration, provider credentials, and neighboring project files
are never opened. The source DB is opened read-only without ``immutable=1`` so
committed WAL rows remain visible.

The current reviewed schema allow-list is ``sessions``, ``messages``,
``files``, ``read_files``, ``goose_db_version``, ``mcp_enabled_servers`` and
``mcp_disabled_servers``. Every selected row is encoded as a typed-JSON
envelope, and its locator includes the database-path identity, project path,
primary key and canonical-row SHA-256. Updates therefore add immutable events;
they never overwrite or delete prior evidence. Per-database/per-table content
fingerprints make unchanged passes idempotent. Missing and unreadable sources
record deduplicated gaps without treating absence as deletion.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s1_evidence import EvidenceStore, SourceMutated, now_iso

PRODUCER = "crush"
ADAPTER_VERSION = "crush-sqlite-1"
REGISTRY_ROOT = Path.home() / ".local" / "share"
GLOBAL_DB = Path.home() / ".config" / "crush" / ".crush" / "crush.db"
ALLOWED_TABLES = frozenset(
    {
        "sessions",
        "messages",
        "files",
        "read_files",
        "goose_db_version",
        "mcp_enabled_servers",
        "mcp_disabled_servers",
    }
)
REQUIRED_TABLES = frozenset({"sessions", "messages"})
SENSITIVE_WORDS = ("key", "token", "auth", "oauth", "secret", "credential", "password")
NONSECRET_TOKEN_COUNTS = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
    }
)
MAX_PROJECTION_CHARS = 12_000
MAX_JSON_DEPTH = 8
MAX_JSON_NODES = 4096


@dataclass(frozen=True)
class Source:
    project_path: Path
    db_path: Path
    global_store: bool = False

    @property
    def source_uri(self) -> str:
        return source_uri(self.db_path)


def source_uri(db_path: Path) -> str:
    """Stable source ID derived from the resolved allowed database path."""
    identity = str(db_path.expanduser().resolve(strict=False))
    return f"crush://db/{hashlib.sha256(identity.encode()).hexdigest()}"


def _registry_paths(registry_root: Path = REGISTRY_ROOT) -> list[Path]:
    """Read only direct projects.json children of every Crush registry dir."""
    if not registry_root.is_dir():
        return []
    return sorted(
        path
        for path in registry_root.glob("crush*/projects.json")
        if path.parent.name.startswith("crush") and not path.is_symlink()
    )


def discover_sources(
    *, registry_paths: list[Path] | None = None, global_db: Path | None = GLOBAL_DB
) -> tuple[list[Source], list[Path]]:
    """Return unique present DBs and missing registry project paths.

    Registry entries contribute only their ``path`` field. ``data_dir`` and all
    other Crush config files are ignored. A project symlink is resolved once;
    the adapter then permits only its direct ``.crush/crush.db`` child.
    """
    registries = _registry_paths() if registry_paths is None else registry_paths
    candidates: dict[str, Source] = {}
    missing: dict[str, Path] = {}
    for registry in registries:
        try:
            document = json.loads(registry.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            # Registry failure is represented as a missing candidate under its
            # exact registry path; it cannot be used to guess project files.
            missing[str(registry.resolve(strict=False))] = registry
            continue
        projects = document.get("projects", []) if isinstance(document, dict) else []
        if not isinstance(projects, list):
            continue
        for item in projects:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            registered = Path(item["path"]).expanduser()
            try:
                project = registered.resolve(strict=False)
            except (OSError, RuntimeError):
                project = registered.absolute()
            if not registered.exists():
                missing[str(project)] = project
                continue
            if not project.is_dir():
                missing[str(project)] = project
                continue
            crush_dir = project / ".crush"
            db_path = crush_dir / "crush.db"
            if crush_dir.is_symlink() or db_path.is_symlink():
                # Do not follow a planted data-directory or database symlink.
                candidates.setdefault(
                    str(db_path.resolve(strict=False)), Source(project, db_path)
                )
                continue
            if not db_path.is_file():
                # Most registered projects have never opened Crush. Missing DBs
                # become gaps later only if this exact source was checkpointed.
                continue
            resolved_db = db_path.resolve(strict=False)
            candidates.setdefault(str(resolved_db), Source(project, db_path))

    sources = list(candidates.values())
    if global_db is not None:
        global_path = global_db.expanduser()
        if global_path.is_file() or global_path.is_symlink():
            global_resolved = str(global_path.resolve(strict=False))
            if global_resolved not in candidates:
                global_project = global_path.parent.parent.resolve(strict=False)
                sources.append(Source(global_project, global_path, global_store=True))
    sources.sort(
        key=lambda source: (
            str(source.db_path.resolve(strict=False)),
            source.global_store,
        )
    )
    return sources, list(missing.values())


def _safe_source(source: Source) -> bool:
    project = source.project_path
    database = source.db_path
    if source.global_store:
        if database != project / ".crush" / "crush.db":
            return False
    else:
        if database.parent != project / ".crush" or database.name != "crush.db":
            return False
        if (project / ".crush").is_symlink():
            return False
    if database.is_symlink() or not database.is_file():
        return False
    for suffix in ("-wal", "-shm", "-journal"):
        if database.with_name(database.name + suffix).is_symlink():
            return False
    return True


def open_source(source: Source) -> sqlite3.Connection:
    """Open exactly the allowed SQLite source read-only and WAL-aware."""
    if not _safe_source(source):
        raise PermissionError("database path is outside the Crush allow-list")
    connection = sqlite3.connect(
        source.db_path.resolve(strict=True).as_uri() + "?mode=ro",
        uri=True,
        timeout=2,
    )
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
    except sqlite3.Error:
        connection.close()
        raise
    return connection


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def table_info(connection: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return list(connection.execute(f"PRAGMA table_info({_quote_identifier(table)})"))


def _tag_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bytes):
        return {
            "type": "blob",
            "base64": base64.b64encode(value).decode("ascii"),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    if isinstance(value, bool):
        return {"type": "integer", "value": int(value)}
    if isinstance(value, int):
        return {"type": "integer", "value": value}
    if isinstance(value, float):
        return {"type": "real", "value": value.hex()}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    raise TypeError(f"unsupported SQLite value type: {type(value).__name__}")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()


def canonical_row_bytes(table: str, columns: list[str], row: sqlite3.Row) -> bytes:
    """Hash identity over all typed source values, including BLOB bytes."""
    return _canonical_json(
        {
            "format": "s1-sqlite-row-v1",
            "table": table,
            "columns": [[name, _tag_value(row[name])] for name in columns],
        }
    )


def _walk_json(node: Any, output: list[str], budget: list[int], depth: int = 0) -> None:
    if (
        depth > MAX_JSON_DEPTH
        or budget[0] <= 0
        or sum(map(len, output)) >= MAX_PROJECTION_CHARS
    ):
        return
    budget[0] -= 1
    if isinstance(node, dict):
        for value in node.values():
            _walk_json(value, output, budget, depth + 1)
            if budget[0] <= 0:
                break
    elif isinstance(node, list):
        for value in node:
            _walk_json(value, output, budget, depth + 1)
            if budget[0] <= 0:
                break
    elif isinstance(node, str):
        if node:
            output.append(node[:MAX_PROJECTION_CHARS])
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        output.append(str(node))


def search_text(table: str, columns: list[str], row: sqlite3.Row) -> tuple[str, bool]:
    """Extract bounded searchable text without indexing typed/base64 noise."""
    values: list[str] = []
    unparsed = False
    for name in columns:
        value = row[name]
        if not isinstance(value, str) or not value:
            continue
        if name in {"parts", "todos", "content"}:
            try:
                decoded = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                if name == "parts" and value.lstrip().startswith(("{", "[")):
                    unparsed = True
                values.append(value)
            else:
                _walk_json(decoded, values, [MAX_JSON_NODES])
        elif name not in {
            "id",
            "session_id",
            "parent_session_id",
            "summary_message_id",
        }:
            values.append(value)
        if sum(map(len, values)) >= MAX_PROJECTION_CHARS:
            break
    return "\n".join(values)[:MAX_PROJECTION_CHARS], unparsed


def encode_row(
    table: str, columns: list[str], row: sqlite3.Row, projection: str
) -> bytes:
    """Lossless typed envelope, with the S1 indexer's projection hook first."""
    return _canonical_json(
        {
            "format": "s1-sqlite-row-v1",
            "table": table,
            "row": [[name, _tag_value(row[name])] for name in columns],
            "_s1_search_text": projection[:MAX_PROJECTION_CHARS],
        }
    )


def decode_row(raw: bytes) -> tuple[str, dict[str, Any]]:
    """Decode a typed envelope for byte-exact verification and tests."""
    envelope = json.loads(raw.decode("utf-8"))
    if envelope.get("format") != "s1-sqlite-row-v1":
        raise ValueError("unsupported Crush row encoding")
    output: dict[str, Any] = {}
    for name, tagged in envelope["row"]:
        kind = tagged["type"]
        if kind == "null":
            value = None
        elif kind == "integer":
            value = int(tagged["value"])
        elif kind == "real":
            value = float.fromhex(tagged["value"])
        elif kind == "text":
            value = str(tagged["value"])
        elif kind == "blob":
            value = base64.b64decode(tagged["base64"], validate=True)
            if hashlib.sha256(value).hexdigest() != tagged["sha256"]:
                raise ValueError(f"BLOB hash mismatch for {name}")
        else:
            raise ValueError(f"unknown SQLite value tag {kind!r}")
        output[name] = value
    return str(envelope["table"]), output


def _primary_key(row: sqlite3.Row, primary_keys: list[str]) -> str:
    encoded = _canonical_json([[name, _tag_value(row[name])] for name in primary_keys])
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _table_is_sensitive(table: str, columns: list[str]) -> bool:
    table_name = table.casefold()
    if any(word in table_name for word in SENSITIVE_WORDS):
        return True
    for column in columns:
        name = column.casefold()
        if name in NONSECRET_TOKEN_COUNTS:
            continue
        if any(word in name for word in SENSITIVE_WORDS):
            return True
    return False


def _record_gap(
    store: EvidenceStore,
    uri: str,
    reason: str,
    *,
    from_locator: str | None = None,
    to_locator: str | None = None,
    dry_run: bool = False,
) -> int:
    if dry_run:
        return 0
    exists = store.db.execute(
        "SELECT 1 FROM ingest_gap WHERE producer=? AND source_uri=? AND reason=? "
        "AND from_locator IS ? AND to_locator IS ? LIMIT 1",
        (PRODUCER, uri, reason, from_locator, to_locator),
    ).fetchone()
    if exists:
        return 0
    store.record_gap(
        PRODUCER, uri, reason, from_locator=from_locator, to_locator=to_locator
    )
    return 1


def _checkpoint_uri(source: Source, table: str) -> str:
    return f"{source.source_uri}#table={table}"


def _event_fields(table: str, row: sqlite3.Row) -> tuple[str, str, str | None]:
    if table == "messages":
        role = str(row["role"] or "unknown") if "role" in set(row.keys()) else "unknown"
        if role == "user":
            return "user", "human", "message.user"
        if role == "assistant":
            return "assistant", "model", "message.assistant"
        if role == "tool":
            return "tool", "tool", "message.tool"
        return "unknown", "system", f"message.{role}"
    return "system", "derived", f"{table}.row"


def _put_event(
    store: EvidenceStore,
    source: Source,
    table: str,
    locator: str,
    raw: bytes,
    row: sqlite3.Row,
    *,
    batch: str,
    dry_run: bool,
) -> bool:
    if dry_run:
        return False
    role, origin, event_type = _event_fields(table, row)
    columns = set(row.keys())
    session_id = None
    if "session_id" in columns and row["session_id"] is not None:
        session_id = str(row["session_id"])
    elif table == "sessions" and "id" in columns:
        session_id = str(row["id"])
    seq = row["created_at"] if "created_at" in columns else None
    if not isinstance(seq, int):
        seq = None
    event_id, created = store.put_event(
        producer=PRODUCER,
        source_uri=source.source_uri,
        source_locator=locator,
        raw=raw,
        ts_utc=now_iso(),
        ts_source="ingest",
        role=role,
        origin=origin,
        event_type=event_type,
        producer_session_id=session_id,
        source_seq=seq,
        scope=PRODUCER,
        ingest_batch=batch,
        content_encoding="utf-8",
        media_type="application/json",
        sensitivity="sensitive",
    )
    conversation = session_id
    if table == "messages" and conversation:
        conversation = f"{source.source_uri}:{conversation}"
    if conversation:
        store.assign_conversation(
            event_id,
            f"{PRODUCER}:{conversation}",
            assigned_by=ADAPTER_VERSION,
            confidence=1.0,
        )
    return created


def _scan_database(
    store: EvidenceStore,
    source: Source,
    *,
    batch: str,
    dry_run: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "files": 0,
        "tables": 0,
        "read": 0,
        "created": 0,
        "skipped": 0,
        "gaps": 0,
        "unparsed": 0,
        "tables_skipped": 0,
        "skipped_table_names": [],
        "event_kinds": {},
        "failed": 0,
    }
    try:
        connection = open_source(source)
    except (sqlite3.Error, OSError, PermissionError):
        result["gaps"] += _record_gap(
            store,
            source.source_uri,
            "Crush database missing, locked, corrupt, or outside the path allow-list; retry next scan",
            dry_run=dry_run,
        )
        return result

    result["files"] = 1
    try:
        present = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        absent = sorted(REQUIRED_TABLES - present)
        if absent:
            result["gaps"] += _record_gap(
                store,
                source.source_uri,
                "required Crush history tables absent; schema may be unsupported",
                from_locator=",".join(absent),
                dry_run=dry_run,
            )
        for table in sorted(present):
            info = table_info(connection, table)
            columns = [str(row[1]) for row in info]
            if table not in ALLOWED_TABLES or _table_is_sensitive(table, columns):
                result["tables_skipped"] += 1
                result["skipped_table_names"].append(table)
                continue
            primary_keys = [
                str(row[1])
                for row in sorted(info, key=lambda row: int(row[5]))
                if row[5]
            ]
            if not columns or not primary_keys:
                result["tables_skipped"] += 1
                result["skipped_table_names"].append(table)
                result["gaps"] += _record_gap(
                    store,
                    source.source_uri,
                    f"allow-listed table {table} has no stable primary key",
                    dry_run=dry_run,
                )
                continue

            result["tables"] += 1
            previous = (
                None
                if dry_run
                else store.checkpoint(PRODUCER, _checkpoint_uri(source, table))
            )
            old_fingerprint: dict[str, Any] = {}
            if previous is not None:
                try:
                    old_fingerprint = json.loads(previous["source_fingerprint"])
                except (TypeError, ValueError):
                    old_fingerprint = {}
            quoted = ",".join(_quote_identifier(name) for name in columns)
            ordering = ",".join(_quote_identifier(name) for name in primary_keys)
            statement = (
                f"SELECT {quoted} FROM {_quote_identifier(table)} ORDER BY {ordering}"
            )
            digest = hashlib.sha256()
            count = 0
            rows: list[tuple[str, bytes]] = []
            for row in connection.execute(statement):
                count += 1
                result["read"] += 1
                canonical = canonical_row_bytes(table, columns, row)
                row_hash = hashlib.sha256(canonical).hexdigest()
                digest.update(bytes.fromhex(row_hash))
                rows.append((_primary_key(row, primary_keys), canonical))

            fingerprint = {
                "count": count,
                "sha256": digest.hexdigest(),
            }
            unchanged = old_fingerprint == fingerprint
            if unchanged:
                result["skipped"] += count
                continue

            if old_fingerprint and count < int(old_fingerprint.get("count", 0)):
                result["gaps"] += _record_gap(
                    store,
                    source.source_uri,
                    f"{table} rows shrank or were removed; prior evidence is retained",
                    from_locator=f"count={old_fingerprint.get('count', 0)}",
                    to_locator=f"count={count}",
                    dry_run=dry_run,
                )

            # The first pass hashes every row cheaply into the table fingerprint.
            # Only a changed table needs row payloads for envelope emission.
            for primary_key, canonical in rows:
                row_hash = hashlib.sha256(canonical).hexdigest()
                locator = (
                    f"project:{quote(str(source.project_path), safe='/')}"
                    f"/table:{quote(table, safe='')}/key:{primary_key}/sha256:{row_hash}"
                )
                found = store.db.execute(
                    "SELECT 1 FROM event WHERE producer=? AND source_uri=? AND source_locator=? LIMIT 1",
                    (PRODUCER, source.source_uri, locator),
                ).fetchone()
                if found:
                    result["skipped"] += 1
                    continue
                # Re-read just this primary key to keep row values typed by sqlite3
                # rather than decoding the typed hash form into a second envelope.
                where = " AND ".join(
                    f"{_quote_identifier(name)}=?" for name in primary_keys
                )
                key_values = json.loads(
                    base64.urlsafe_b64decode(
                        primary_key + "=" * (-len(primary_key) % 4)
                    )
                )
                decoded_keys = {
                    name: _decode_tag(tagged) for name, tagged in key_values
                }
                params = tuple(decoded_keys[name] for name in primary_keys)
                live_row = connection.execute(
                    f"SELECT {quoted} FROM {_quote_identifier(table)} WHERE {where}",
                    params,
                ).fetchone()
                if live_row is None:
                    result["gaps"] += _record_gap(
                        store,
                        source.source_uri,
                        f"{table} row vanished during scan; retry next pass",
                        from_locator=locator,
                        dry_run=dry_run,
                    )
                    continue
                current = canonical_row_bytes(table, columns, live_row)
                if current != canonical:
                    result["gaps"] += _record_gap(
                        store,
                        source.source_uri,
                        f"{table} row changed while being read; retry next pass",
                        from_locator=locator,
                        dry_run=dry_run,
                    )
                    continue
                projection, unparsed = search_text(table, columns, live_row)
                result["unparsed"] += int(unparsed)
                raw = encode_row(table, columns, live_row, projection)
                try:
                    created = _put_event(
                        store,
                        source,
                        table,
                        locator,
                        raw,
                        live_row,
                        batch=batch,
                        dry_run=dry_run,
                    )
                except SourceMutated:
                    result["gaps"] += _record_gap(
                        store,
                        source.source_uri,
                        f"{table} event identity collision; retained evidence is unchanged",
                        from_locator=locator,
                        dry_run=dry_run,
                    )
                    continue
                result["created"] += int(created)
                result["skipped"] += int(not created and not dry_run)
                if created:
                    _, _, kind = _event_fields(table, live_row)
                    result["event_kinds"][kind] = result["event_kinds"].get(kind, 0) + 1

            if not dry_run:
                store.set_checkpoint(
                    PRODUCER,
                    _checkpoint_uri(source, table),
                    source_fingerprint=json.dumps(
                        fingerprint, sort_keys=True, separators=(",", ":")
                    ),
                    committed_locator=f"count={count}",
                    adapter_version=ADAPTER_VERSION,
                )
        if not source.db_path.is_file():
            result["gaps"] += _record_gap(
                store,
                source.source_uri,
                "Crush database vanished during scan; captured rows are retained",
                dry_run=dry_run,
            )
    except (sqlite3.Error, OSError, PermissionError, ValueError, TypeError):
        result["gaps"] += _record_gap(
            store,
            source.source_uri,
            "Crush database read interrupted or schema incompatible; retry next scan",
            dry_run=dry_run,
        )
    finally:
        connection.close()
    return result


def scan(
    store: EvidenceStore,
    *,
    registry_paths: list[Path] | None = None,
    global_db: Path | None = GLOBAL_DB,
    batch: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Capture rows from registered per-project DBs and the optional global DB."""
    totals: dict[str, Any] = {
        "files": 0,
        "tables": 0,
        "read": 0,
        "created": 0,
        "skipped": 0,
        "gaps": 0,
        "unparsed": 0,
        "tables_skipped": 0,
        "skipped_table_names": [],
        "event_kinds": {},
        "failed": 0,
    }
    sources, missing = discover_sources(
        registry_paths=registry_paths, global_db=global_db
    )
    if limit is not None:
        sources = sources[: max(0, limit)]
    batch = batch or f"{PRODUCER}:{now_iso()}"
    for source in sources:
        current = _scan_database(store, source, batch=batch, dry_run=dry_run)
        for key in (
            "files",
            "tables",
            "read",
            "created",
            "skipped",
            "gaps",
            "unparsed",
            "tables_skipped",
        ):
            totals[key] += current[key]
        totals["skipped_table_names"] = sorted(
            set(totals["skipped_table_names"]) | set(current["skipped_table_names"])
        )
        for kind, count in current["event_kinds"].items():
            totals["event_kinds"][kind] = totals["event_kinds"].get(kind, 0) + count
        totals["failed"] += current["failed"]

    if limit is None:
        for project in missing:
            uri = source_uri(project / ".crush" / "crush.db")
            totals["gaps"] += _record_gap(
                store,
                uri,
                "registry project path no longer exists; prior evidence may be incomplete",
                from_locator=str(project),
                dry_run=dry_run,
            )
        if not dry_run:
            live_uris = {source.source_uri for source in sources}
            checkpoints = store.db.execute(
                "SELECT DISTINCT source_uri FROM ingest_checkpoint WHERE producer=?",
                (PRODUCER,),
            ).fetchall()
            missing_reported = {
                source_uri(project / ".crush" / "crush.db") for project in missing
            }
            for row in checkpoints:
                checkpoint_uri = str(row["source_uri"])
                base_uri = checkpoint_uri.split("#table=", 1)[0]
                if (
                    not base_uri.startswith("crush://db/")
                    or base_uri in live_uris
                    or base_uri in missing_reported
                ):
                    continue
                missing_reported.add(base_uri)
                totals["gaps"] += _record_gap(
                    store,
                    base_uri,
                    "previously checkpointed Crush database is no longer registered or present",
                )
    return totals


def _decode_tag(tagged: dict[str, Any]) -> Any:
    kind = tagged["type"]
    if kind == "null":
        return None
    if kind == "integer":
        return int(tagged["value"])
    if kind == "real":
        return float.fromhex(tagged["value"])
    if kind == "text":
        return str(tagged["value"])
    if kind == "blob":
        return base64.b64decode(tagged["base64"], validate=True)
    raise ValueError(f"unknown SQLite value tag {kind!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rescue Crush SQLite history into S1")
    parser.add_argument("--db", default=None, help="S1 control database")
    parser.add_argument("--cas", default=None, help="S1 CAS root")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("scan", help="scan Crush project and global history DBs")
    command.add_argument("--dry-run", action="store_true")
    command.add_argument(
        "--limit", type=int, default=None, help="maximum source databases"
    )
    command.add_argument(
        "--registry", action="append", default=None, help="projects.json (repeatable)"
    )
    command.add_argument(
        "--no-global", action="store_true", help="skip the global Crush DB"
    )
    args = parser.parse_args(argv)
    kwargs: dict[str, Any] = {}
    if args.db:
        kwargs["db_path"] = args.db
    if args.cas:
        kwargs["cas_root"] = args.cas
    store = EvidenceStore(**kwargs)
    try:
        result = scan(
            store,
            registry_paths=[Path(path).expanduser() for path in args.registry]
            if args.registry
            else None,
            global_db=None if args.no_global else GLOBAL_DB,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        print(json.dumps({"dry_run": int(args.dry_run), **result}, sort_keys=True))
        return 1 if result["failed"] else 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
