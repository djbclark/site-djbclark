#!/usr/bin/env python3
"""Backfill the Hindsight corpus into S1.

Hindsight's banks hold records that exist nowhere else — LLM-extracted facts,
curated uploads, corrections — and until they are copied into S1 the memory
plan's own words apply: *"Hindsight is not yet rebuildable: existing records
may be unique. Export and backfill them to S1 before … considering
retirement."* This closes that. Once every bank is in S1, Hindsight becomes a
rebuildable projection rather than an irreplaceable store, and the choice to
keep or replace it is a free one.

What is stored: one S1 event per Hindsight document, with the document's own
text and its metadata as the raw payload. Facts derived from a document are
deliberately *not* stored separately — they are the LLM's reading of the text,
which is exactly the kind of derived state S1 should be able to rebuild rather
than archive.

**Pagination is not optional.** The documents endpoint defaults to
`limit=100`; a naive listing silently truncates, which is how the bank
migration missed 14 documents on 2026-08-23. This pages explicitly.

Usage:
    hindsight_s1_banks.py backfill              # every bank, resuming
    hindsight_s1_banks.py backfill --bank hermes-shared
    hindsight_s1_banks.py backfill --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hindsight_s1 import EvidenceStore, SourceMutated, now_iso  # noqa: E402

API = "http://127.0.0.1:8888/v1/default/banks"
PRODUCER = "hindsight"
ADAPTER_VERSION = "hindsight-banks-1"
PAGE = 100


def _get(url: str, timeout: int = 120) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as fh:
        return json.load(fh)


def banks() -> list[str]:
    payload = _get(API)
    items = payload if isinstance(payload, list) else (
        payload.get("banks") or payload.get("items") or [])
    return sorted(str(b.get("id") or b.get("bank_id")) for b in items if b)


def documents(bank: str) -> Iterator[dict[str, Any]]:
    """Page through every document. Never trust a single unpaginated call."""
    quoted = urllib.parse.quote(bank, safe="")
    offset = 0
    while True:
        payload = _get(f"{API}/{quoted}/documents?limit={PAGE}&offset={offset}")
        items = payload if isinstance(payload, list) else (
            payload.get("documents") or payload.get("items") or [])
        if not items:
            return
        yield from items
        if len(items) < PAGE:
            return
        offset += len(items)


def document_payload(bank: str, doc_id: str) -> dict[str, Any] | None:
    url = f"{API}/{urllib.parse.quote(bank, safe='')}/documents/{urllib.parse.quote(doc_id, safe='')}"
    try:
        return _get(url)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None


def raw_bytes(doc: dict[str, Any]) -> bytes:
    """Canonical JSON of the document's durable content.

    Volatile counters (`memory_unit_count`, `nodes_by_fact_type`) are excluded:
    they change as consolidation re-derives facts, and including them would
    make an unchanged document look mutated on every re-run.
    """
    keep = {k: v for k, v in doc.items()
            if k not in ("memory_unit_count", "nodes_by_fact_type", "updated_at",
                         "observation_scopes")}
    return json.dumps(keep, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def backfill_bank(store: EvidenceStore, bank: str, *, batch: str,
                  dry_run: bool = False) -> dict[str, Any]:
    uri = f"hindsight://{bank}"
    created = seen = skipped = failed = 0
    for stub in documents(bank):
        doc_id = str(stub.get("id") or stub.get("document_id") or "")
        if not doc_id:
            continue
        seen += 1
        if dry_run:
            continue
        full = document_payload(bank, doc_id)
        if full is None:
            failed += 1
            continue
        raw = raw_bytes(full)
        ts = str(full.get("created_at") or "")
        ts_utc = (ts.replace("+00:00", "Z") if ts else now_iso())
        if not ts_utc.endswith("Z"):
            ts_utc = ts_utc.split(".")[0] + "Z"
        try:
            event_id, was_created = store.put_event(
                producer=PRODUCER,
                source_uri=uri,
                source_locator=f"documents/{doc_id}",
                raw=raw,
                ts_utc=ts_utc,
                ts_source="producer" if ts else "ingest",
                role="system",
                origin="derived",
                event_type="hindsight.document",
                producer_session_id=bank,
                scope=bank,
                ingest_batch=batch,
                media_type="application/json",
            )
        except SourceMutated:
            store.record_gap(PRODUCER, uri, "document content changed after ingest",
                             from_locator=f"documents/{doc_id}")
            skipped += 1
            continue
        created += was_created
        store.assign_conversation(event_id, f"{PRODUCER}:{bank}",
                                  assigned_by=ADAPTER_VERSION, confidence=1.0)

    if not dry_run and seen:
        store.set_checkpoint(PRODUCER, uri, source_fingerprint=f"documents={seen}",
                             committed_locator=f"documents={seen}",
                             adapter_version=ADAPTER_VERSION)
    return {"bank": bank, "seen": seen, "created": created,
            "skipped": skipped, "failed": failed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill Hindsight banks into S1")
    parser.add_argument("--db", default=None)
    parser.add_argument("--cas", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--bank", default=None, help="one bank instead of all")
    b.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    kwargs: dict[str, Any] = {}
    if args.db:
        kwargs["db_path"] = args.db
    if args.cas:
        kwargs["cas_root"] = args.cas
    store = EvidenceStore(**kwargs)

    targets = [args.bank] if args.bank else banks()
    batch = f"hindsight-banks:{now_iso()}"
    totals = {"banks": 0, "seen": 0, "created": 0, "skipped": 0, "failed": 0}
    for bank in targets:
        r = backfill_bank(store, bank, batch=batch, dry_run=args.dry_run)
        totals["banks"] += 1
        for k in ("seen", "created", "skipped", "failed"):
            totals[k] += r[k]
        print(f"  {r['bank'][:44]:44} seen={r['seen']:4} new={r['created']:4} "
              f"skipped={r['skipped']} failed={r['failed']}")
    print(json.dumps({"dry_run": args.dry_run, **totals}, indent=2))
    store.close()
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
