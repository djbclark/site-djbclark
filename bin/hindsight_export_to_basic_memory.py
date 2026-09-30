#!/usr/bin/env python3
"""One-shot export of a Hindsight archive into Basic Memory markdown notes.

Written for the 2026-09-30 Hindsight retirement. Reads the JSONL table dumps
(`memory_units`, `mental_models`, `directives`; one `row_to_json` per line,
gzipped) and writes plain markdown under an output root that a Basic Memory
project indexes:

    <out>/<bank>/pages/<name>.md        one note per mental model / knowledge page
    <out>/<bank>/facts/<YYYY-MM>-NN.md  facts as `- [fact_type] text` observations
    <out>/<bank>/directives.md          bank directives, when any

Facts whose source still exists elsewhere are skipped, because re-importing a
paraphrase of a canonical source creates a second copy of the same fact:
`source:git` / `source:git-log` (git history) and `source:site-private-memory`
(the memory files themselves). They stay in the archive.

Usage: hindsight_export_to_basic_memory.py <archive-dir> <out-dir>
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SKIP_TAGS = {"source:git", "source:git-log", "source:site-private-memory"}
FACTS_PER_NOTE = 100
DATE_FIELDS = ("occurred_start", "event_date", "mentioned_at", "created_at")


def rows(archive: Path, table: str):
    with gzip.open(archive / f"{table}.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def bank_slug(bank_id: str) -> str:
    return slug(bank_id.split("::", 1)[-1])


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "unnamed"


def one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fact_date(row: dict) -> str:
    for field in DATE_FIELDS:
        if row.get(field):
            return row[field][:10]
    return "0000-00-00"


def frontmatter(title: str, tags: list[str], **extra: str) -> str:
    lines = ["---", f"title: {json.dumps(title)}", "type: note"]
    lines.append("tags: [" + ", ".join(tags) + "]")
    lines += [f"{key}: {json.dumps(value)}" for key, value in extra.items()]
    return "\n".join(lines + ["---", ""])


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    archive, out = Path(sys.argv[1]), Path(sys.argv[2])
    counts: dict[str, Counter] = defaultdict(Counter)

    for row in rows(archive, "mental_models"):
        bank = bank_slug(row["bank_id"])
        title = f"{bank} — {row['name']}"
        body = frontmatter(
            title,
            ["hindsight", "hindsight-page", bank],
            hindsight_bank=row["bank_id"],
            hindsight_id=row["id"],
            last_refreshed=row.get("last_refreshed_at") or "",
        )
        body += f"\n# {title}\n\n{(row.get('content') or '').strip()}\n"
        write(out / bank / "pages" / f"{slug(row['name'])}.md", body)
        counts[bank]["pages"] += 1

    directives: dict[str, list[dict]] = defaultdict(list)
    for row in rows(archive, "directives"):
        directives[row["bank_id"]].append(row)
    for bank_id, items in directives.items():
        bank = bank_slug(bank_id)
        title = f"{bank} — Hindsight directives"
        body = frontmatter(title, ["hindsight", bank], hindsight_bank=bank_id)
        body += f"\n# {title}\n\n"
        for item in items:
            body += f"## {item.get('name') or item['id']}\n\n{(item.get('content') or '').strip()}\n\n"
        write(out / bank / "directives.md", body)
        counts[bank]["directives"] += len(items)

    facts: dict[tuple[str, str], list[dict]] = defaultdict(list)
    bank_ids: dict[str, str] = {}
    for row in rows(archive, "memory_units"):
        bank = bank_slug(row["bank_id"])
        bank_ids[bank] = row["bank_id"]
        if SKIP_TAGS & set(row.get("tags") or []):
            counts[bank]["skipped"] += 1
            continue
        facts[(bank, fact_date(row)[:7])].append(row)

    for (bank, month), items in sorted(facts.items()):
        items.sort(key=lambda r: (fact_date(r), r["id"]))
        for part, start in enumerate(range(0, len(items), FACTS_PER_NOTE), 1):
            chunk = items[start : start + FACTS_PER_NOTE]
            title = f"{bank} — Hindsight facts {month} part {part:02d}"
            body = frontmatter(
                title, ["hindsight", "hindsight-facts", bank], hindsight_bank=bank_ids[bank]
            )
            body += f"\n# {title}\n\n"
            for row in chunk:
                body += f"- [{row['fact_type']}] {one_line(row['text'])} ({fact_date(row)})\n"
            write(out / bank / "facts" / f"{month}-{part:02d}.md", body)
            counts[bank]["facts"] += len(chunk)

    total = Counter()
    for bank in sorted(counts):
        total.update(counts[bank])
        print(bank, dict(counts[bank]))
    print("TOTAL", dict(total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
