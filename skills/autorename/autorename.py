#!/usr/bin/env python3
"""Rename the current Claude Code session, the way /rename does.

A skill cannot invoke the built-in /rename, so this writes what /rename writes:
a `custom-title` record appended to the session transcript (the running
process watches the transcript for these) plus the `custom-title.json` sidecar.

    autorename.py "Title words here"            # always rename
    autorename.py --auto "Title words here"     # skip if the operator renamed it by hand
    autorename.py --show                        # print the current title

Exit 0 = renamed or deliberately skipped (stdout says which); 2 = cannot run.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

MARK = '"type":"custom-title"'
MAX_LEN = 80


def clean(title: str) -> str:
    title = re.sub(r"[\x00-\x1f\x7f]+", " ", title)
    title = re.sub(r"\s+", " ", title.replace('"', "")).strip().strip("'`")
    return title[:MAX_LEN].rstrip()


def find_transcript(sid: str) -> Path | None:
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"
    hits = sorted(root.glob(f"*/{sid}.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def current_title(transcript: Path) -> str | None:
    last = None
    with transcript.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if MARK in line:
                try:
                    last = json.loads(line).get("customTitle")
                except ValueError:
                    pass
    return last or None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("title", nargs="?")
    ap.add_argument("--auto", action="store_true", help="do not overwrite a title the operator set")
    ap.add_argument("--show", action="store_true", help="print the current title and exit")
    ap.add_argument("--session-id", default=os.environ.get("CLAUDE_CODE_SESSION_ID"))
    args = ap.parse_args()

    if not args.session_id:
        print("autorename: no CLAUDE_CODE_SESSION_ID (not a Claude Code session); nothing renamed", file=sys.stderr)
        return 2
    transcript = find_transcript(args.session_id)
    if transcript is None:
        print(f"autorename: no transcript for session {args.session_id}", file=sys.stderr)
        return 2

    current = current_title(transcript)
    if args.show:
        print(current or "(no custom title)")
        return 0
    if not args.title or not (title := clean(args.title)):
        ap.error("a non-empty title is required")

    state = Path.home() / ".local/state/autorename" / f"{args.session_id}.txt"
    last_written = state.read_text(encoding="utf-8").strip() if state.exists() else None

    if current == title:
        print(f"unchanged: {title}")
        return 0
    if args.auto and current is not None and current != last_written:
        print(f"skipped: operator-set title kept ({current!r})")
        return 0

    record = json.dumps(
        {"type": "custom-title", "customTitle": title, "sessionId": args.session_id},
        ensure_ascii=False, separators=(",", ":"),
    )
    with transcript.open("a", encoding="utf-8") as fh:
        fh.write(record + "\n")

    sidecar_dir = transcript.parent / args.session_id
    sidecar_dir.mkdir(mode=0o700, exist_ok=True)
    (sidecar_dir / "custom-title.json").write_text(
        json.dumps({"customTitle": title}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(title + "\n", encoding="utf-8")
    print(f"renamed: {title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
