#!/usr/bin/env python3
"""Maintain the durable handoff log for a session, spanning every workspace
it touches (e.g. a worktree task and the matching ~/ops deploy checkout at
once).

The canonical log lives at ``<state-root>/chains/<chain-key>/SESSION_LOG.md``
and carries a `workspaces` list, one entry per touched (repo, task) location
with its own git anchor for staleness checking. Every touched location also
gets a small pointer file at the conventional
``<state-root>/<repo>/<task>/SESSION_LOG.md`` path that just redirects to the
canonical file — that's what preserves the existing "ls the repo directory,
read whatever's there" discovery behavior.

The program deliberately has no hook-style error suppression: a failed git
command, malformed input, or unwritable state directory is an invocation
error and must be visible to its caller.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml


LOG_NAME = "SESSION_LOG.md"
HISTORY_HEADING = "## Recent History"
CURRENT_HEADING = "## Current State"
POINTER_NOTE = (
    "This is a pointer file — the durable log lives at the path in "
    "`redirect` above. See site-private docs/session-handoff-compaction-spec.md §3.\n"
)


@dataclass
class HistoryEntry:
    timestamp: str
    writer: str
    lines: list[str]


def now_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value))
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "root"


def run_git(repo_dir: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo_dir, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def repository_state(repo_dir: Path) -> tuple[str, str, bool]:
    head = run_git(repo_dir, "rev-parse", "HEAD")
    try:
        branch = run_git(repo_dir, "symbolic-ref", "--short", "HEAD")
    except subprocess.CalledProcessError:
        branch = "HEAD"
    dirty = bool(run_git(repo_dir, "status", "--porcelain"))
    return branch, head, dirty


def split_document(text: str) -> tuple[dict[str, Any], str]:
    """Return YAML frontmatter and the markdown following it."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    raw = text[4:end]
    parsed = yaml.safe_load(raw) or {}
    if not isinstance(parsed, dict):
        raise ValueError("frontmatter must be a mapping")
    return parsed, text[end + 5 :]


def parse_history(body: str) -> list[HistoryEntry]:
    if HISTORY_HEADING not in body:
        return []
    history = body.split(HISTORY_HEADING, 1)[1]
    entries: list[HistoryEntry] = []
    current: HistoryEntry | None = None
    for line in history.splitlines():
        if line.startswith("### ") and " — " in line:
            stamp, writer = line[4:].split(" — ", 1)
            current = HistoryEntry(stamp.strip(), writer.strip(), [])
            entries.append(current)
        elif current is not None:
            current.lines.append(line)
    # Trailing blank lines are formatting, not entry content.
    for entry in entries:
        while entry.lines and not entry.lines[-1].strip():
            entry.lines.pop()
    return entries


def parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None


def retain(entries: list[HistoryEntry]) -> list[HistoryEntry]:
    cutoff = datetime.now().astimezone() - timedelta(days=30)
    kept: list[HistoryEntry] = []
    for entry in entries:
        stamp = parse_timestamp(entry.timestamp)
        # An unparseable legacy timestamp is retained; silently deleting it is
        # worse than allowing a human to repair it.
        if stamp is not None:
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=cutoff.tzinfo)
            if stamp < cutoff:
                continue
        kept.append(entry)
        if len(kept) == 10:
            break
    return kept


def list_sidecars(state_dir: Path) -> list[Path]:
    return sorted(state_dir.glob("precompact-*.md"), key=lambda p: p.name)


def sidecar_entries(state_dir: Path) -> tuple[list[HistoryEntry], list[Path]]:
    """Make one history record per compaction, and list all files to remove."""
    files = list_sidecars(state_dir)
    by_name = {p.name: p for p in files}
    consumed: set[str] = set()
    entries: list[HistoryEntry] = []
    to_delete: list[Path] = []
    for path in files:
        if path.name in consumed:
            continue
        enriched_suffix = "-enriched.md"
        if path.name.endswith(enriched_suffix):
            base_name = path.name[: -len(enriched_suffix)] + ".md"
            if base_name in by_name:
                # The ordinary sidecar produces the record and points at this.
                continue
        companion = by_name.get(path.stem + "-enriched.md")
        frontmatter, body = split_document(path.read_text())
        timestamp = str(frontmatter.get("updated_at") or now_stamp())
        trigger = str(frontmatter.get("trigger") or "unknown")
        lines = [f"- unplanned compaction ({trigger})."]
        summary = " ".join(line.strip() for line in body.splitlines() if line.strip())
        if summary:
            lines.append(f"- Sidecar summary: {summary}")
        if companion is not None:
            lines.append(f"- Enriched sidecar summary: {companion.read_text().strip()}")
            consumed.add(companion.name)
            to_delete.append(companion)
        entries.append(HistoryEntry(timestamp, "compaction", lines))
        consumed.add(path.name)
        to_delete.append(path)
    return entries, to_delete


def render_frontmatter(frontmatter: dict[str, Any]) -> str:
    dumped = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False,
                            allow_unicode=True)
    return "---\n" + dumped + "---\n"


def render(frontmatter: dict[str, Any], active_work: str, blockers: list[str],
           next_steps: list[str], entries: list[HistoryEntry]) -> str:
    values: list[str] = [render_frontmatter(frontmatter).rstrip("\n"), "",
                         CURRENT_HEADING, f"- Active work: {active_work}"]
    values.append("- Blockers: " + ("; ".join(blockers) if blockers else "None"))
    values.append("- Next steps:")
    values.extend(f"  - {step}" for step in next_steps)
    values.extend(["", HISTORY_HEADING])
    for entry in entries:
        values.append(f"### {entry.timestamp} — {entry.writer}")
        values.extend(entry.lines or ["- No details recorded."])
        values.append("")
    return "\n".join(values).rstrip() + "\n"


def render_pointer(frontmatter: dict[str, Any]) -> str:
    return render_frontmatter(frontmatter) + "\n" + POINTER_NOTE


def atomic_write(path: Path, content: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".session_log_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def require_payload(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    required = ("session_id", "writer", "chain", "latest_handoff", "active_work",
                "blockers", "next_steps", "history_bullets", "workspaces")
    if not isinstance(data, dict) or any(key not in data for key in required):
        raise ValueError("payload is missing required fields")
    for key in ("session_id", "writer", "latest_handoff", "active_work"):
        if not isinstance(data[key], str):
            raise ValueError(f"payload {key} must be a string")
    for key in ("chain", "blockers", "next_steps", "history_bullets"):
        if not isinstance(data[key], list) or not all(isinstance(item, str) for item in data[key]):
            raise ValueError(f"payload {key} must be a list of strings")
    if len(data["history_bullets"]) > 3:
        raise ValueError("history_bullets may contain at most 3 items")
    if not data["chain"]:
        raise ValueError("chain must be non-empty — every session belongs to at least one chain")
    workspaces = data["workspaces"]
    if not isinstance(workspaces, list) or not workspaces:
        raise ValueError("workspaces must be a non-empty list of {repo, task, dir}")
    for ws in workspaces:
        if not isinstance(ws, dict) or not all(
            isinstance(ws.get(k), str) and ws.get(k) for k in ("repo", "task", "dir")
        ):
            raise ValueError("each workspace needs non-empty string repo, task, and dir")
    return data


def resolve_canonical(state_root: Path, dir_: Path) -> tuple[Path | None, dict[str, Any], str, bool]:
    """Follow a workspace's pointer file to the canonical log.

    Returns (canonical_path, frontmatter, body, existed). A pointer file
    with no `redirect` key is a pre-migration legacy log — treated as
    already canonical so old logs keep working until migrated.
    """
    pointer_path = dir_ / LOG_NAME
    if not pointer_path.exists():
        return None, {}, "", False
    frontmatter, body = split_document(pointer_path.read_text())
    redirect = frontmatter.get("redirect")
    if not redirect:
        return pointer_path, frontmatter, body, True
    canonical_path = state_root / redirect
    if not canonical_path.exists():
        return canonical_path, {}, "", False
    canonical_frontmatter, canonical_body = split_document(canonical_path.read_text())
    return canonical_path, canonical_frontmatter, canonical_body, True


def read_command(state_root: Path, dir_: Path) -> None:
    canonical_path, frontmatter, body, existed = resolve_canonical(state_root, dir_)
    if not existed:
        print(json.dumps({"exists": False, "frontmatter": None, "body": "",
                          "canonical_path": str(canonical_path) if canonical_path else None,
                          "workspaces": None, "stale": None}))
        return
    workspaces = frontmatter.get("workspaces")
    staleness = None
    if isinstance(workspaces, list):
        staleness = []
        for ws in workspaces:
            try:
                actual_head = run_git(Path(ws["dir"]), "rev-parse", "HEAD")
                stale = actual_head != ws.get("head_sha")
            except Exception:
                actual_head, stale = None, True
            staleness.append({"repo": ws.get("repo"), "task": ws.get("task"),
                              "actual_head": actual_head, "stale": stale})
    overall_stale = any(w["stale"] for w in staleness) if staleness else None
    print(json.dumps({"exists": True, "frontmatter": frontmatter, "body": body,
                      "canonical_path": str(canonical_path), "workspaces": staleness,
                      "stale": overall_stale,
                      "legacy_unmigrated": staleness is None}))


def write_command(state_root: Path, raw: str) -> None:
    payload = require_payload(raw)
    chain = payload["chain"]
    chain_key = safe_slug(chain[0])
    canonical_dir = state_root / "chains" / chain_key
    canonical_dir.mkdir(parents=True, exist_ok=True)
    canonical_path = canonical_dir / LOG_NAME

    workspace_records: list[dict[str, Any]] = []
    folded_entries: list[HistoryEntry] = []
    sidecar_deletions: list[Path] = []
    for ws in payload["workspaces"]:
        repo_dir = Path(ws["dir"]).expanduser()
        branch, head_sha, dirty = repository_state(repo_dir)
        workspace_records.append({
            "repo": ws["repo"], "task": ws["task"], "dir": str(repo_dir),
            "branch": branch, "head_sha": head_sha, "dirty": dirty,
        })
        ws_state_dir = state_root / ws["repo"] / ws["task"]
        ws_state_dir.mkdir(parents=True, exist_ok=True)
        entries, deletions = sidecar_entries(ws_state_dir)
        folded_entries.extend(entries)
        sidecar_deletions.extend(deletions)

    _, old_body = split_document(canonical_path.read_text()) if canonical_path.exists() else ({}, "")
    frontmatter = {
        "schema_version": 2, "updated_at": now_stamp(),
        "session_id": payload["session_id"], "writer": payload["writer"],
        "chain": chain, "latest_handoff": payload["latest_handoff"],
        "workspaces": workspace_records,
    }
    # Keep the history heading independently timestamped.  Besides describing
    # the event more precisely, this avoids conflating a document update with
    # its entry when an operator edits a historical heading by hand.
    entry_stamp = (datetime.now().astimezone() + timedelta(seconds=1)).strftime(
        "%Y-%m-%dT%H:%M:%S%z")
    new_entry = HistoryEntry(entry_stamp, payload["writer"],
                             [f"- {line}" for line in payload["history_bullets"]])
    folded_entries.sort(key=lambda e: e.timestamp)
    entries = retain([new_entry, *folded_entries, *parse_history(old_body)])
    atomic_write(canonical_path, render(frontmatter, payload["active_work"], payload["blockers"],
                                        payload["next_steps"], entries))
    for sidecar in sidecar_deletions:
        sidecar.unlink()

    for ws in workspace_records:
        pointer_dir = state_root / ws["repo"] / ws["task"]
        pointer_dir.mkdir(parents=True, exist_ok=True)
        pointer_frontmatter = {
            "schema_version": 2, "updated_at": now_stamp(),
            "chain": chain, "redirect": f"chains/{chain_key}/{LOG_NAME}",
        }
        atomic_write(pointer_dir / LOG_NAME, render_pointer(pointer_frontmatter))


def fold_command(state_root: Path, dir_: Path) -> None:
    canonical_path, frontmatter, body, existed = resolve_canonical(state_root, dir_)
    if not existed or canonical_path is None:
        raise FileNotFoundError(f"cannot fold sidecars: no session log found via {dir_}")
    folded, deletions = sidecar_entries(dir_)
    frontmatter["updated_at"] = now_stamp()
    # Current State is retained verbatim in fold mode.
    current = body.split(HISTORY_HEADING, 1)[0]
    entries = retain([*folded, *parse_history(body)])
    history_lines = [HISTORY_HEADING]
    for entry in entries:
        history_lines.extend([f"### {entry.timestamp} — {entry.writer}", *entry.lines, ""])
    content = (render_frontmatter(frontmatter) + "\n" + current.lstrip("\n") + "\n"
              + "\n".join(history_lines).rstrip() + "\n")
    atomic_write(canonical_path, content)
    for sidecar in deletions:
        sidecar.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("read", "write", "fold"))
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--dir", type=Path,
                        help="workspace pointer directory (<state-root>/<repo>/<task>); "
                             "required for read/fold, unused for write")
    args = parser.parse_args()
    state_root = args.state_root.expanduser()
    if args.command == "write":
        write_command(state_root, sys.stdin.read())
        return 0
    if args.dir is None:
        raise ValueError(f"--dir is required for {args.command}")
    dir_ = args.dir.expanduser()
    if not dir_.is_dir():
        raise NotADirectoryError(dir_)
    if args.command == "read":
        read_command(state_root, dir_)
    else:
        fold_command(state_root, dir_)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"session_log.py: {error}", file=sys.stderr)
        raise SystemExit(1)
