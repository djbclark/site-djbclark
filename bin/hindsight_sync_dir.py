#!/usr/bin/env python3
"""Mirror a directory of Markdown files into a Hindsight bank, one document per file.

The files stay canonical; the bank is a search index over them. Each file is
retained with document_id "<prefix><filename>", so Hindsight's default
update_mode "replace" swaps the old copy out when a file changes. Files that
disappear are deleted from the bank. Only changed files are sent: a state file
records the sha256 of what the bank last accepted.

Files matching the secret patterns in hindsight_memory_candidates.py are
skipped and reported, never sent (the 2026-08-23 bank purge was a key leak).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hindsight_memory_candidates import SECRET_PATTERNS  # noqa: E402

BATCH = 10
# Documented non-secrets that look like keys (the LiteLLM loopback placeholder).
PLACEHOLDERS = ("sk-litellm-local",)


def call(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Mirror a directory of Markdown files into a Hindsight bank.")
    ap.add_argument("--api", default="http://127.0.0.1:8888")
    ap.add_argument("--bank", required=True)
    ap.add_argument("--dir", required=True, type=Path)
    ap.add_argument("--glob", action="append", required=True, help="repeatable, e.g. 'reference_*.md'")
    ap.add_argument("--prefix", required=True, help="document_id prefix, e.g. 'site-private-memory/'")
    ap.add_argument("--tag", action="append", default=[], help="repeatable tag for every retained file")
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    bank = f"{a.api}/v1/default/banks/{urllib.parse.quote(a.bank, safe='')}"
    state: dict[str, str] = json.loads(a.state.read_text()) if a.state.exists() else {}
    files = sorted({p for g in a.glob for p in a.dir.glob(g) if p.is_file()})

    changed, skipped = [], []
    current: dict[str, str] = {}
    for p in files:
        text = p.read_text(errors="replace")
        scan = text
        for ph in PLACEHOLDERS:
            scan = scan.replace(ph, "")
        if any(rx.search(scan) for rx in SECRET_PATTERNS):
            skipped.append(p.name)
            continue
        digest = hashlib.sha256(text.encode()).hexdigest()
        current[p.name] = digest
        if state.get(p.name) != digest:
            changed.append((p, text))
    removed = [n for n in state if n not in current and n not in skipped]

    print(f"{a.bank}: {len(files)} files, {len(changed)} changed, {len(removed)} removed, {len(skipped)} skipped")
    for n in skipped:
        print(f"  SKIPPED (secret-shaped content): {n}")
    if a.dry_run:
        for p, _ in changed:
            print(f"  would retain {p.name}")
        for n in removed:
            print(f"  would delete {n}")
        return 0

    for i in range(0, len(changed), BATCH):
        chunk = changed[i:i + BATCH]
        items = [{
            "content": f"Source file: {p}\n\n{text}",
            "document_id": a.prefix + p.name,
            "context": f"memory file {p.name}",
            "tags": a.tag,
            "timestamp": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
        } for p, text in chunk]
        call("POST", f"{bank}/memories", {"items": items, "async": True})
        for p, _ in chunk:
            state[p.name] = current[p.name]
        a.state.write_text(json.dumps(state, indent=1, sort_keys=True))
    for n in removed:
        try:
            call("DELETE", f"{bank}/documents/{urllib.parse.quote(a.prefix + n, safe='')}")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        del state[n]
        a.state.write_text(json.dumps(state, indent=1, sort_keys=True))
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
