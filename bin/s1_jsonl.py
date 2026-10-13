#!/usr/bin/env python3
"""Shared append-only JSONL tailing helpers for S1 adapters (Phase B).

These are the exact primitives `s1_claude.py` proved out, lifted so the
JSONL-family adapters (codex, acp-run, copilot, grok, ...) share one
implementation instead of drifting copies:

- `iter_records` yields complete lines only — a record without its terminating
  newline is still being written and is picked up on the next pass, so a
  half-flushed line never gets hashed as if it were final;
- `parse_locator` reads the committed byte offset back out of a checkpoint's
  `<begin>:<end>#<n>` locator;
- `fingerprint_prefix` hashes the already-consumed prefix (capped) so a
  rewritten or truncated source is detected instead of silently re-read.

Adapters still own their own record mapping, source-uri derivation and
allow-lists; only the byte mechanics live here.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator

FINGERPRINT_BYTES = 4096


def iter_records(path: Path, start: int) -> Iterator[tuple[int, int, bytes]]:
    """Yield (start_offset, end_offset, raw_line) for complete records only.

    A line without a trailing newline is still being written; we stop there and
    pick it up on the next pass rather than ingesting a half record.
    """
    with path.open("rb") as handle:
        handle.seek(start)
        offset = start
        while True:
            line = handle.readline()
            if not line:
                return
            if not line.endswith(b"\n"):
                return  # incomplete tail; do not commit
            end = offset + len(line)
            stripped = line.strip()
            if stripped:
                yield offset, end, line
            offset = end


def parse_locator(locator: str | None) -> int:
    """Byte offset just past the last committed record, or 0."""
    if not locator:
        return 0
    try:
        span = locator.split("#", 1)[0]
        return int(span.split(":", 1)[1])
    except (IndexError, ValueError):
        return 0


def fingerprint_prefix(path: Path, upto: int) -> str:
    """Hash of the prefix we have already consumed, capped for cost.

    The invariant this protects is precise: *the bytes we already ingested must
    not have changed*. Hashing a fixed-size window instead would be wrong on a
    short file, where a normal append rewrites the window and every append
    would look like a truncation.

    `upto` is the committed byte offset, so verification recomputes over
    exactly the same span that produced the stored value. Once the file is
    longer than the cap the value stops moving and stays a cheap constant.
    """
    window = min(upto, FINGERPRINT_BYTES)
    if window <= 0:
        return ""
    with path.open("rb") as handle:
        return hashlib.sha256(handle.read(window)).hexdigest()
