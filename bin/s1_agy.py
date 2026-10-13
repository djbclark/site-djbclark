#!/usr/bin/env python3
"""Read-only Google Antigravity conversation adapter for S1.

Only direct ``conversations/<uuid>.db`` and ``conversations/<uuid>.meta``
children of the four configured stores are considered, plus allow-listed files
under the matching ``brain/<uuid>/`` directory. No directory-wide discovery is
performed outside those paths, and credentials are never opened.

SQLite is opened with ``mode=ro`` (never ``immutable=1``), so current WAL rows
remain visible without checkpointing or writing to the source. Every row in
the seven allow-listed tables becomes a revisioned event. Its raw bytes are a
deterministic UTF-8 JSON envelope: each source column is represented by a
type-tagged value, BLOB values use base64 plus their SHA-256, and
``_s1_search_text`` is a derived protobuf-string projection. Decoding the
``row`` member recovers all selected SQLite values exactly, including BLOB
bytes. Event locators include the SHA-256 of the canonical typed row, so an
in-place edit creates a new event and leaves the prior event intact.

The protobuf reader understands varint, length-delimited, fixed64 and fixed32
wire fields, with bounded depth, bytes, and field count. It is deliberately
schema-agnostic; extraction failures never block raw capture and are counted
as ``unparsed``. The S1 search index recognizes the explicit projection field
so base64 encodings and hashes are not indexed as conversation text.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s1_evidence import EvidenceStore, SourceMutated, now_iso

PRODUCER = "agy"
ADAPTER_VERSION = "agy-sqlite-1"
STORE_ROOTS = {
    "cli": Path.home() / ".gemini" / "antigravity-cli" / "conversations",
    "acp": Path.home() / ".gemini" / "antigravity-acp" / "conversations",
    "plain": Path.home() / ".gemini" / "antigravity" / "conversations",
    "ide": Path.home() / ".gemini" / "antigravity-ide" / "conversations",
}
SESSION_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
TABLES = (
    "steps",
    "gen_metadata",
    "executor_metadata",
    "parent_references",
    "trajectory_meta",
    "trajectory_metadata_blob",
    "battle_mode_infos",
)
ALLOWED_BRAIN_EXTENSIONS = frozenset(
    {".md", ".json", ".txt", ".py", ".toml", ".yaml", ".yml", ".sh"}
)
MAX_BRAIN_FILE_BYTES = 4 * 1024 * 1024
MAX_PROTO_BYTES_PER_ROW = 1024 * 1024
MAX_PROTO_DEPTH = 6
MAX_PROTO_FIELDS = 10_000
MAX_PROJECTION_CHARS = 12_000
_NOISE_HEX = re.compile(r"^[0-9a-fA-F]{32,}$")
_NOISE_B64 = re.compile(r"^[A-Za-z0-9_+/=-]{40,}$")


@dataclass(frozen=True)
class Session:
    store_name: str
    session_id: str
    root: Path
    db_path: Path | None
    meta_path: Path | None

    @property
    def source_uri(self) -> str:
        return f"agy://{self.store_name}/{self.session_id}"

    @property
    def brain_root(self) -> Path:
        return self.root.parent / "brain" / self.session_id


def source_uri(store_name: str, session_id: str) -> str:
    """Stable source identity; identical UUIDs in separate stores stay distinct."""
    return f"agy://{store_name}/{session_id}"


def discover_sessions(roots: dict[str, Path] | None = None) -> list[Session]:
    """Discover only direct UUID-named DB/meta children in configured roots."""
    roots = STORE_ROOTS if roots is None else roots
    found: dict[tuple[str, str], dict[str, Path]] = {}
    for store_name, root in roots.items():
        if root.is_symlink() or not root.is_dir():
            continue
        for suffix in (".db", ".meta"):
            for path in sorted(root.glob(f"*{suffix}")):
                session_id = path.name[: -len(suffix)]
                if (
                    not SESSION_RE.fullmatch(session_id)
                    or path.is_symlink()
                    or not path.is_file()
                ):
                    continue
                fields = found.setdefault((store_name, session_id), {})
                fields[suffix] = path
    return [
        Session(
            store_name,
            session_id,
            roots[store_name],
            files.get(".db"),
            files.get(".meta"),
        )
        for (store_name, session_id), files in sorted(found.items())
    ]


def _readonly_connection(path: Path) -> sqlite3.Connection:
    """Open a source database read-only while honoring its live WAL."""
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    con.row_factory = sqlite3.Row
    try:
        # Force SQLite to inspect the db/WAL now, before the caller starts a scan.
        con.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
    except sqlite3.Error:
        con.close()
        raise
    return con


def open_store_readonly(session: Session) -> sqlite3.Connection:
    path = session.db_path
    if (
        path is None
        or session.root.is_symlink()
        or path.parent != session.root
        or path.name != f"{session.session_id}.db"
        or path.is_symlink()
        or not path.is_file()
    ):
        raise PermissionError("database path is outside the Antigravity allow-list")
    try:
        path.resolve(strict=True).relative_to(session.root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise PermissionError(
            "database resolved outside the Antigravity allow-list"
        ) from exc
    for suffix in ("-wal", "-shm"):
        if path.with_name(path.name + suffix).is_symlink():
            raise PermissionError("SQLite sidecar is a symlink")
    return _readonly_connection(path)


def _column_names(con: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")')]


def _pk_names(con: sqlite3.Connection, table: str) -> list[str]:
    rows = list(con.execute(f'PRAGMA table_info("{table}")'))
    return [str(row[1]) for row in sorted(rows, key=lambda row: int(row[5])) if row[5]]


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
    # sqlite3.Row normally produces only the above Python scalar types.
    raise TypeError(f"unsupported SQLite value type: {type(value).__name__}")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_row_bytes(table: str, columns: list[str], row: sqlite3.Row) -> bytes:
    """Stable typed representation used to hash the source row."""
    return _json_bytes(
        {
            "format": "s1-agy-row-v1",
            "table": table,
            "columns": [[name, _tag_value(row[name])] for name in columns],
        }
    )


def encode_row(
    table: str,
    columns: list[str],
    row: sqlite3.Row,
    search_text: str,
) -> bytes:
    """Encode every source column plus a rebuildable, explicitly marked projection."""
    return _json_bytes(
        {
            "format": "s1-agy-row-v1",
            "table": table,
            "row": [[name, _tag_value(row[name])] for name in columns],
            "_s1_search_text": search_text[:MAX_PROJECTION_CHARS],
        }
    )


def decode_row(raw: bytes) -> tuple[str, dict[str, Any]]:
    """Decode the row values from an adapter envelope (used for verification)."""
    envelope = json.loads(raw.decode("utf-8"))
    if envelope.get("format") != "s1-agy-row-v1":
        raise ValueError("unsupported agy row encoding")
    decoded: dict[str, Any] = {}
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
        decoded[name] = value
    return str(envelope["table"]), decoded


def _read_varint(raw: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(10):
        if offset >= len(raw):
            raise ValueError("truncated protobuf varint")
        byte = raw[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    raise ValueError("oversized protobuf varint")


def _useful_text(payload: bytes) -> str | None:
    if len(payload) < 3:
        return None
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None
    visible = sum(char.isprintable() or char in "\r\n\t" for char in text)
    if not text or visible / len(text) < 0.9:
        return None
    stripped = text.strip()
    if len(stripped) < 3 or _NOISE_HEX.fullmatch(stripped):
        return None
    if _NOISE_B64.fullmatch(stripped) and (
        any(c.isdigit() for c in stripped) or "+" in stripped or "/" in stripped
    ):
        return None
    return stripped


def _parse_message(
    raw: bytes, *, depth: int, field_budget: list[int]
) -> tuple[bool, list[str]]:
    if depth > MAX_PROTO_DEPTH or not raw:
        return False, []
    strings: list[str] = []
    offset = 0
    parsed_fields = 0
    try:
        while offset < len(raw):
            field_budget[0] -= 1
            parsed_fields += 1
            if field_budget[0] < 0 or parsed_fields > MAX_PROTO_FIELDS:
                return False, strings
            tag, offset = _read_varint(raw, offset)
            field_number, wire_type = tag >> 3, tag & 7
            if field_number == 0:
                return False, strings
            if wire_type == 0:
                _, offset = _read_varint(raw, offset)
            elif wire_type == 1:
                offset += 8
            elif wire_type == 2:
                length, offset = _read_varint(raw, offset)
                end = offset + length
                if end > len(raw):
                    return False, strings
                child = raw[offset:end]
                offset = end
                candidate = _useful_text(child)
                if candidate:
                    strings.append(candidate)
                if depth < MAX_PROTO_DEPTH and child:
                    nested_ok, nested_text = _parse_message(
                        child, depth=depth + 1, field_budget=field_budget
                    )
                    if nested_ok:
                        strings.extend(nested_text)
            elif wire_type == 5:
                offset += 4
            else:
                return False, strings
            if offset > len(raw):
                return False, strings
        return offset == len(raw) and parsed_fields > 0, strings
    except (IndexError, OverflowError, ValueError):
        return False, strings


def extract_protobuf_text(raw: bytes) -> tuple[bool, list[str]]:
    """Return (wire message parsed, useful UTF-8 fields); never raises."""
    try:
        if len(raw) > MAX_PROTO_BYTES_PER_ROW:
            return False, []
        return _parse_message(
            raw,
            depth=0,
            field_budget=[MAX_PROTO_FIELDS],
        )
    except Exception:  # noqa: BLE001 - extraction must never prevent raw capture
        return False, []


def looks_like_protobuf(raw: bytes) -> bool:
    return extract_protobuf_text(raw)[0]


def _row_projection(row: sqlite3.Row, columns: list[str]) -> tuple[str, bool, bool]:
    parts: list[str] = []
    parsed_any = False
    saw_blob = False
    for name in columns:
        value = row[name]
        if not isinstance(value, bytes) or not value:
            continue
        saw_blob = True
        parsed, strings = extract_protobuf_text(value)
        parsed_any = parsed_any or parsed
        for text in strings:
            if text not in parts:
                parts.append(text)
            if sum(map(len, parts)) >= MAX_PROJECTION_CHARS:
                break
        if sum(map(len, parts)) >= MAX_PROJECTION_CHARS:
            break
    return "\n".join(parts)[:MAX_PROJECTION_CHARS], parsed_any, saw_blob


def _primary_key(row: sqlite3.Row, pk_columns: list[str]) -> str:
    raw = _json_bytes([[name, _tag_value(row[name])] for name in pk_columns])
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _table_checkpoint_uri(session: Session, table: str) -> str:
    return f"{session.source_uri}#table={table}"


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
    found = store.db.execute(
        "SELECT 1 FROM ingest_gap WHERE producer=? AND source_uri=? AND reason=? "
        "AND from_locator IS ? AND to_locator IS ? LIMIT 1",
        (PRODUCER, uri, reason, from_locator, to_locator),
    ).fetchone()
    if found:
        return 0
    store.record_gap(
        PRODUCER, uri, reason, from_locator=from_locator, to_locator=to_locator
    )
    return 1


def _put_event(
    store: EvidenceStore,
    session: Session,
    locator: str,
    raw: bytes,
    *,
    event_type: str,
    batch: str,
    dry_run: bool,
    source_seq: int | None = None,
    media_type: str = "application/json",
    content_encoding: str = "utf-8",
) -> bool:
    if dry_run:
        return False
    event_id, created = store.put_event(
        producer=PRODUCER,
        source_uri=session.source_uri,
        source_locator=locator,
        raw=raw,
        ts_utc=now_iso(),
        ts_source="ingest",
        role="system",
        event_type=event_type,
        origin="derived",
        producer_session_id=session.session_id,
        source_seq=source_seq,
        scope=PRODUCER,
        ingest_batch=batch,
        content_encoding=content_encoding,
        media_type=media_type,
        sensitivity="sensitive",
    )
    store.assign_conversation(
        event_id,
        f"agy:{session.store_name}:{session.session_id}",
        assigned_by=ADAPTER_VERSION,
        confidence=1.0,
    )
    return created


def _ingest_metadata(
    store: EvidenceStore, session: Session, *, batch: str, dry_run: bool
) -> dict[str, int]:
    result = {"files_read": 0, "created": 0, "skipped": 0, "gaps": 0}
    path = session.meta_path
    if path is None:
        return result
    if (
        path.parent != session.root
        or path.name != f"{session.session_id}.meta"
        or path.is_symlink()
    ):
        result["gaps"] += _record_gap(
            store,
            session.source_uri,
            "allow-listed session metadata unavailable",
            dry_run=dry_run,
        )
        return result
    try:
        raw = path.read_bytes()
    except OSError:
        result["gaps"] += _record_gap(
            store,
            session.source_uri,
            "allow-listed session metadata unavailable",
            dry_run=dry_run,
        )
        return result
    result["files_read"] = 1
    digest = hashlib.sha256(raw).hexdigest()
    if _put_event(
        store,
        session,
        f"meta:{digest}",
        raw,
        event_type="session_meta",
        batch=batch,
        dry_run=dry_run,
    ):
        result["created"] += 1
    elif not dry_run:
        result["skipped"] += 1
    return result


def _sensitive_name(path: Path) -> bool:
    for part in path.parts:
        folded = part.casefold()
        if any(term in folded for term in ("token", "cred", "auth")):
            return True
        if folded in {"installation_id", "google_accounts.json"}:
            return True
    return False


def _brain_files(session: Session) -> list[Path]:
    root = session.brain_root
    if root.is_symlink() or not root.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if (
            _sensitive_name(relative)
            or path.suffix.lower() not in ALLOWED_BRAIN_EXTENSIONS
        ):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        parent = root
        has_symlink_parent = False
        for part in relative.parts[:-1]:
            parent = parent / part
            if parent.is_symlink():
                has_symlink_parent = True
                break
        if has_symlink_parent:
            continue
        try:
            path.resolve(strict=True).relative_to(root.resolve(strict=True))
        except (OSError, ValueError):
            continue
        out.append(path)
    return out


def _ingest_brain(
    store: EvidenceStore, session: Session, *, batch: str, dry_run: bool
) -> dict[str, int]:
    result = {"brain_files": 0, "created": 0, "skipped": 0, "gaps": 0}
    for path in _brain_files(session):
        try:
            size = path.stat().st_size
        except OSError:
            result["gaps"] += _record_gap(
                store,
                session.source_uri,
                "allow-listed brain artifact unavailable",
                dry_run=dry_run,
            )
            continue
        if size > MAX_BRAIN_FILE_BYTES:
            result["gaps"] += _record_gap(
                store,
                session.source_uri,
                "allow-listed brain artifact exceeds size cap",
                from_locator=path.relative_to(session.brain_root).as_posix(),
                dry_run=dry_run,
            )
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            result["gaps"] += _record_gap(
                store,
                session.source_uri,
                "allow-listed brain artifact unavailable",
                dry_run=dry_run,
            )
            continue
        result["brain_files"] += 1
        digest = hashlib.sha256(raw).hexdigest()
        relative = path.relative_to(session.brain_root).as_posix()
        locator = f"brain:{quote(relative, safe='/')}:{digest}"
        if _put_event(
            store,
            session,
            locator,
            raw,
            event_type=f"brain_artifact{path.suffix.lower()}",
            batch=batch,
            dry_run=dry_run,
            media_type="text/plain",
        ):
            result["created"] += 1
        elif not dry_run:
            result["skipped"] += 1
    return result


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def scan_session(
    store: EvidenceStore,
    session: Session,
    *,
    batch: str,
    dry_run: bool = False,
) -> dict[str, int]:
    result = {
        "sessions": 1,
        "rows_read": 0,
        "files_read": 0,
        "brain_files": 0,
        "created": 0,
        "skipped": 0,
        "unparsed": 0,
        "protobuf_parsed": 0,
        "gaps": 0,
        "failed": 0,
    }
    for key, value in _ingest_metadata(
        store, session, batch=batch, dry_run=dry_run
    ).items():
        result[key] = result.get(key, 0) + value

    if session.db_path is None:
        # ACP metadata-only sessions are legitimate unless this URI had prior rows.
        prior = store.db.execute(
            "SELECT 1 FROM ingest_checkpoint WHERE producer=? AND source_uri LIKE ? LIMIT 1",
            (PRODUCER, session.source_uri + "#table=%"),
        ).fetchone()
        if prior:
            result["gaps"] += _record_gap(
                store,
                session.source_uri,
                "previously checkpointed conversation database is missing",
                dry_run=dry_run,
            )
            result["failed"] = 1
    else:
        con: sqlite3.Connection | None = None
        try:
            con = open_store_readonly(session)
            present = {
                str(row[0])
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            missing = [table for table in TABLES if table not in present]
            if missing:
                raise sqlite3.DatabaseError("required Antigravity tables absent")
            source_events = {
                str(row[0])
                for row in store.db.execute(
                    "SELECT source_locator FROM event WHERE producer=? AND source_uri=?",
                    (PRODUCER, session.source_uri),
                )
            }
            for table in TABLES:
                columns = _column_names(con, table)
                pk_columns = _pk_names(con, table)
                if not columns or not pk_columns:
                    raise sqlite3.DatabaseError(f"unsupported {table} identity schema")
                checkpoint_uri = _table_checkpoint_uri(session, table)
                checkpoint = (
                    None if dry_run else store.checkpoint(PRODUCER, checkpoint_uri)
                )
                previous: dict[str, Any] = {}
                if checkpoint is not None:
                    try:
                        previous = json.loads(checkpoint["source_fingerprint"])
                    except (TypeError, ValueError):
                        previous = {}
                digest = hashlib.sha256()
                count = 0
                max_key = ""
                quoted_columns = ",".join(
                    '"' + name.replace('"', '""') + '"' for name in columns
                )
                ordering = ",".join(
                    '"' + name.replace('"', '""') + '"' for name in pk_columns
                )
                cursor = con.execute(
                    f'SELECT {quoted_columns} FROM "{table}" ORDER BY {ordering}'
                )
                for row in cursor:
                    count += 1
                    result["rows_read"] += 1
                    row_bytes = canonical_row_bytes(table, columns, row)
                    row_hash = hashlib.sha256(row_bytes).hexdigest()
                    digest.update(bytes.fromhex(row_hash))
                    primary_key = _primary_key(row, pk_columns)
                    max_key = primary_key
                    locator = f"{table}:row:{primary_key}:sha256:{row_hash}"
                    if locator in source_events:
                        result["skipped"] += 1
                        continue
                    try:
                        projection, parsed, saw_blob = _row_projection(row, columns)
                    except Exception:  # noqa: BLE001 - retain the unparsed raw row
                        projection, parsed, saw_blob = "", False, True
                    result["protobuf_parsed"] += int(parsed)
                    result["unparsed"] += int(saw_blob and not parsed)
                    raw = encode_row(table, columns, row, projection)
                    sequence = (
                        _as_int(row[pk_columns[0]])
                        if isinstance(row[pk_columns[0]], int)
                        else None
                    )
                    try:
                        created = _put_event(
                            store,
                            session,
                            locator,
                            raw,
                            event_type=f"{table}.row",
                            batch=batch,
                            dry_run=dry_run,
                            source_seq=sequence,
                        )
                    except SourceMutated:
                        result["gaps"] += _record_gap(
                            store,
                            session.source_uri,
                            f"{table} event identity collision",
                            from_locator=locator,
                            dry_run=dry_run,
                        )
                        result["failed"] = 1
                        continue
                    if created:
                        result["created"] += 1
                    elif not dry_run:
                        result["skipped"] += 1

                old_count = _as_int(previous.get("count"))
                if previous and (count < old_count or (old_count and not max_key)):
                    result["gaps"] += _record_gap(
                        store,
                        session.source_uri,
                        f"{table} rows shrank or were removed; retained events are not deleted",
                        from_locator=f"count={old_count};max={previous.get('max_key', '')}",
                        to_locator=f"count={count};max={max_key}",
                        dry_run=dry_run,
                    )
                if not dry_run:
                    fingerprint = json.dumps(
                        {
                            "count": count,
                            "max_key": max_key,
                            "sha256": digest.hexdigest(),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    if (
                        checkpoint is None
                        or checkpoint["source_fingerprint"] != fingerprint
                    ):
                        store.set_checkpoint(
                            PRODUCER,
                            checkpoint_uri,
                            source_fingerprint=fingerprint,
                            committed_locator=f"count={count};max={max_key}",
                            adapter_version=ADAPTER_VERSION,
                        )
            if not session.db_path.is_file():
                raise sqlite3.OperationalError(
                    "conversation database vanished mid-scan"
                )
        except (sqlite3.Error, OSError, PermissionError):
            result["gaps"] += _record_gap(
                store,
                session.source_uri,
                "conversation database unavailable, corrupt, or schema-incompatible; retry next scan",
                dry_run=dry_run,
            )
            result["failed"] = 1
        finally:
            if con is not None:
                con.close()

    for key, value in _ingest_brain(
        store, session, batch=batch, dry_run=dry_run
    ).items():
        result[key] = result.get(key, 0) + value
    return result


def scan(
    store: EvidenceStore,
    *,
    roots: dict[str, Path] | None = None,
    store_filter: str | None = None,
    batch: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    """Scan all or one allow-listed store; rows are hashed on each pass."""
    totals = {
        "sessions": 0,
        "rows_read": 0,
        "blobs_read": 0,
        "files_read": 0,
        "brain_files": 0,
        "created": 0,
        "skipped": 0,
        "unparsed": 0,
        "protobuf_parsed": 0,
        "graph_raw": 0,
        "json_parsed": 0,
        "gaps": 0,
        "failed": 0,
    }
    configured = STORE_ROOTS if roots is None else roots
    if store_filter is not None and store_filter not in configured:
        totals["failed"] = 1
        totals["gaps"] += _record_gap(
            store,
            f"{PRODUCER}://{store_filter}/unknown",
            "requested store is outside the allow-list",
            dry_run=dry_run,
        )
        return totals
    selected = (
        {name: path for name, path in configured.items() if name == store_filter}
        if store_filter
        else configured
    )
    sessions = discover_sessions(selected)
    if limit is not None:
        sessions = sessions[: max(0, limit)]
    batch = batch or f"{PRODUCER}:{now_iso()}"
    for session in sessions:
        current = scan_session(store, session, batch=batch, dry_run=dry_run)
        for key in totals:
            totals[key] += current.get(key, 0)
    totals["blobs_read"] = totals["rows_read"]
    totals["graph_raw"] = totals["protobuf_parsed"]
    if limit is None and not dry_run:
        present_sources = {session.source_uri for session in sessions}
        prefixes = tuple(f"agy://{name}/" for name in selected)
        checkpoints = store.db.execute(
            "SELECT DISTINCT source_uri FROM ingest_checkpoint WHERE producer=?",
            (PRODUCER,),
        ).fetchall()
        checked_missing: set[str] = set()
        for row in checkpoints:
            checkpoint_uri = str(row["source_uri"])
            base_uri = checkpoint_uri.split("#table=", 1)[0]
            if not base_uri.startswith(prefixes) or base_uri in present_sources:
                continue
            if base_uri in checked_missing:
                continue
            checked_missing.add(base_uri)
            totals["gaps"] += _record_gap(
                store,
                base_uri,
                "previously checkpointed conversation database is no longer present",
            )
            totals["failed"] = 1
    return totals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest Antigravity conversation evidence into S1"
    )
    parser.add_argument("--db", default=None, help="S1 control database")
    parser.add_argument("--cas", default=None, help="S1 CAS root")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("scan", help="ingest allow-listed Antigravity stores")
    command.add_argument("--dry-run", action="store_true")
    command.add_argument(
        "--limit", type=int, default=None, help="limit conversation UUIDs"
    )
    command.add_argument("--store", choices=tuple(STORE_ROOTS), default=None)
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
            store_filter=args.store,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        # The cycle runner extracts numeric JSON values and logs them as key=value.
        print(json.dumps({"dry_run": int(args.dry_run), **result}, sort_keys=True))
        return 1 if result["failed"] else 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
