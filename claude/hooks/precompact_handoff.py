#!/usr/bin/env python3
"""precompact_handoff.py — PreCompact safety net + workspace resolver.

Hook mode (default): read Claude Code hook JSON on stdin, write a Tier 1
sidecar checkpoint (precompact-<utc-ts>.md). MUST always exit 0 — never
fail or delay a compaction, no matter what.

Resolve mode: `--resolve <dir>` prints "<repo>/<task>".

Spec: site-private docs/session-handoff-compaction-spec.md §6.
Python 3 stdlib only. No third-party imports.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE_ROOT = Path.home() / ".local" / "state" / "handoffs"


def _safe_slug(value):
    """Return a bounded filesystem-safe path component for *value*."""
    try:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value))
        slug = re.sub(r"-+", "-", slug).strip("-") or "root"
        if len(slug) > 120:
            digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:8]
            slug = f"{slug[:80]}-{digest}"
        return slug
    except Exception:
        return "root"


def _git_root(directory):
    """Best-effort upward search for normal, worktree, or bare git roots."""
    current = directory
    for _ in range(64):
        try:
            dot_git = current / ".git"
            if dot_git.is_dir() or dot_git.is_file():
                return current
            if (current / "HEAD").is_file() and (current / "objects").is_dir():
                return current
            parent = current.parent
            if parent == current:
                break
            current = parent
        except Exception:
            break
    return None


def resolve_workspace(directory):
    """Return a safe ``(repo, task)`` tuple for every directory."""
    try:
        d = Path(directory).expanduser().resolve()
        home = Path.home()
        try:
            parts = d.relative_to(home / "src" / "ops-worktrees").parts
            if len(parts) >= 2 and parts[0] != ".store":
                return parts[1], parts[0]  # repo, task
        except ValueError:
            pass
        try:
            parts = d.relative_to(home / "ops").parts
            if parts:
                return parts[0], "ops"
        except ValueError:
            pass

        root = _git_root(d)
        if root is not None:
            task_path = "root" if d == root else str(d.relative_to(root))
            return _safe_slug(root.name), _safe_slug(task_path)
        return "no-git", _safe_slug(str(d))
    except Exception:
        return "no-git", "root"


def run_git(args, cwd):
    try:
        out = subprocess.run(["git", *args], cwd=cwd,
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def hook_main():
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    resolved = resolve_workspace(os.getcwd())
    repo, task = resolved

    cwd = os.getcwd()
    branch = run_git(["branch", "--show-current"], cwd) or "(not a git tree)"
    head_sha = run_git(["rev-parse", "HEAD"], cwd)
    dirty_lines = run_git(["status", "--porcelain"], cwd).splitlines()[:40]
    dirty = "\n".join(dirty_lines)

    state_dir = STATE_ROOT / repo / task
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    now = datetime.now().astimezone()
    ts_file = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    body = "\n".join([
        "---",
        "schema_version: 1",
        "compacted: true",
        f"trigger: {data.get('trigger', 'unknown')}",
        f"updated_at: {now.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f"session_id: {data.get('session_id', 'unknown')}",
        f"transcript_path: {data.get('transcript_path', '')}",
        f"repo: {repo}",
        f"workspace: {task}",
        f"branch: {branch}",
        f"head_sha: {head_sha}",
        "---",
        "",
        "## Dirty files at compaction",
        "",
        f"```\n{dirty}\n```" if dirty else "clean",
        "",
        "Unplanned checkpoint written by precompact_handoff.py. Fold into",
        "SESSION_LOG.md Recent History on next owned write, then delete me.",
        "",
    ])
    sidecar = state_dir / f"precompact-{ts_file}.md"
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=state_dir,
                                   prefix=".precompact.", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            f.write(body)
        os.replace(tmp, sidecar)
    except Exception:
        if tmp:
            try:
                os.unlink(tmp)
            except Exception:
                pass
        return

    # Best-effort detached enrichment (Agent SDK + Haiku mines the
    # transcript). Single-shot detach; never blocks or fails compaction.
    if os.environ.get("HANDOFF_ENRICH", "1") == "0":
        return
    tools = Path.home() / ".claude" / "hooks" / "handoff-tools"
    venv_py = tools / ".venv" / "bin" / "python"
    enricher = tools / "enrich_checkpoint.py"
    transcript = data.get("transcript_path", "")
    if venv_py.exists() and enricher.exists() and transcript:
        try:
            with open(state_dir / "enrich.log", "a") as log:
                subprocess.Popen(
                    [str(venv_py), str(enricher), str(sidecar), transcript],
                    stdout=log, stderr=log, start_new_session=True)
        except Exception:
            pass


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--resolve":
        repo, task = resolve_workspace(sys.argv[2])
        print(f"{repo}/{task}")
        return
    hook_main()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
