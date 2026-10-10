# Session Handoff v0.1-build — Implementation & Test Plan

**Status (2026-10-09, #137 C2.2):** historical. Built in August 2026; its
`~/src/ops-worktrees/` assumptions were retired 2026-08-23, and the live
protocol is the `session-handoff` skill in `~/src/djbclark-ade`.
**Original status:** approved for implementation. Executes spec v0.3 (both §10
questions ratified by operator 2026-08-03: Tier 2 direct-to-master under
the memory exception; PreCompact hook global with path guard).
**Audience:** implementing agents of any capability. Zero design latitude
is required or offered — every file's exact content is in this plan. If
reality conflicts with this plan, or this plan conflicts with the spec,
**stop and report to the orchestrator; do not improvise.**
**Required reading before any task:** `docs/session-handoff-compaction-spec.md`
(same directory, v0.3).

---

## Ground rules (apply to every task)

1. **Never edit tracked files in `~/ops/`.** The only permitted `~/ops`
   write is the runtime Tier 2 flow itself (memory-only commit under
   `site-private/memory/`, preceded by `just ops-memory-sync` from the
   sibling `site-djbclark` checkout, pushed immediately). All other
   tracked edits happen in task worktrees under `~/src/ops-worktrees/`.
2. **Live-vs-tracked convention:** files under `~/.claude/` (hooks,
   skills, settings) are live and edited in place. Each gets a tracked
   mirror committed in the `session-handoff-compaction-spec/site-private`
   worktree under `claude/` (Task P6.1). Live copy is canonical until a
   release wires symlinks; the mirror is for versioning only.
3. **Commit after every completed task** in the worktree you're editing,
   message prefix `handoff-v01:`. Never commit `~/.claude/settings.json`
   or any file containing tokens/credentials.
4. **Hooks must always exit 0.** A hook that can fail a compaction is
   worse than no hook.
5. **Do not spawn fresh Claude sessions for testing without orchestrator
   sign-off on the batch** (quota pacing policy). Phases P0–P4 tests are
   all mechanical/local and need no sign-off; only P5's E2E matrix does.
6. Timestamps everywhere: `date +%Y-%m-%dT%H:%M:%S%z` (local) or
   `date -u +%Y%m%dT%H%M%SZ` (filenames). Never bare `HH:MM`.
7. **All installed tooling is Python 3 — no shell scripts** (operator
   directive 2026-08-03). Libraries are allowed and live in the
   `handoff-tools` venv (P2b), including `claude-agent-sdk`. ONE
   exception: `precompact_handoff.py` itself must remain stdlib-only
   with no venv dependency — it runs synchronously inside compaction
   and must work even when the venv is broken. Shell one-liners inside
   test steps and git commands are fine.
8. **Enrichment spends model quota** (Haiku via the Agent SDK, riding
   Claude Code auth). It defaults ON; `HANDOFF_ENRICH=0` in the
   environment disables it globally. Do not swap the model or raise
   `max_turns` without operator approval.

---

## Phase P0 — Preflight (blocking; ~5 min)

**P0.1 Verify environment.** All must pass before P1:

```bash
test -d ~/src/ops-worktrees/.store && echo OK-store
test -d ~/ops/site-private/memory && echo OK-memory
command -v git >/dev/null && echo OK-git
test -f ~/.claude/settings.json && echo OK-settings
grep -q "ops-memory-sync" ~/ops/site-djbclark/justfile && echo OK-sync
python3 -c 'import sys; assert sys.version_info >= (3,10)' && echo OK-python
command -v claude >/dev/null && echo OK-claude-cli
```

Acceptance: seven `OK-*` lines. Any failure → stop, report which.

---

## Phase P1 — Path library + state root

**P1.1 Create state root:** `mkdir -p ~/.local/state/handoffs`

**P1.2 Create `~/.claude/hooks/precompact_handoff.py`** — one Python
file serving two modes: `--resolve <dir>` (path resolution, used by the
P1.3 tests and any future tooling) and default hook mode (P2). Exactly
this content:

```python
#!/usr/bin/env python3
"""precompact_handoff.py — PreCompact safety net + workspace resolver.

Hook mode (default): read Claude Code hook JSON on stdin, write a Tier 1
sidecar checkpoint (precompact-<utc-ts>.md). MUST always exit 0 — never
fail or delay a compaction, no matter what.

Resolve mode: `--resolve <dir>` prints "<repo>/<task>" or "REJECT".

Spec: site-private docs/session-handoff-compaction-spec.md §6.
Python 3 stdlib only. No third-party imports.
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE_ROOT = Path.home() / ".local" / "state" / "handoffs"


def resolve_workspace(directory):
    """Return (repo, task) or None outside recognized ops paths."""
    try:
        d = Path(directory).expanduser().resolve()
        home = Path.home()
        try:
            parts = d.relative_to(home / "src" / "ops-worktrees").parts
            if len(parts) >= 2 and parts[0] != ".store":
                return parts[1], parts[0]  # repo, task
            return None
        except ValueError:
            pass
        try:
            parts = d.relative_to(home / "ops").parts
            return (parts[0], "ops") if parts else None
        except ValueError:
            return None
    except Exception:
        return None


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
    if resolved is None:
        return  # path guard: silent no-op outside ops trees
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
        r = resolve_workspace(sys.argv[2])
        print(f"{r[0]}/{r[1]}" if r else "REJECT")
        return
    hook_main()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
```

`chmod +x` it.

**P1.3 Test P1** (mechanical, no agent spawns). Run each; compare output:

| Input dir | Expected |
|---|---|
| `~/src/ops-worktrees/session-handoff-compaction-spec/site-private` | repo=`site-private` task=`session-handoff-compaction-spec` |
| `~/src/ops-worktrees/main/stayturgid` | repo=`stayturgid` task=`main` |
| `~/src/ops-worktrees/main/stayturgid/docs/deep/nested` | same as above |
| `~/ops/site-djbclark` | repo=`site-djbclark` task=`ops` |
| `~/src/ops-worktrees/.store/stayturgid.git` | return 1, vars empty |
| `~/src/ops-worktrees` | return 1 |
| `$HOME` | return 1 |

Test command shape:
`python3 ~/.claude/hooks/precompact_handoff.py --resolve "<dir>"`
(prints `repo/task` or `REJECT`).

Note: `--resolve` output order is `repo/task` — e.g. the first table row
prints `site-private/session-handoff-compaction-spec`.

Acceptance: all seven rows match. Record actual outputs in your report.

---

## Phase P2 — PreCompact hook (depends P1)

**P2.1 Hook script.** Already created in P1.2 — hook mode is the
default (no arguments) mode of
`~/.claude/hooks/precompact_handoff.py`. Nothing new to write here;
verify `python3 -c "import ast; ast.parse(open('$HOME/.claude/hooks/precompact_handoff.py').read())"`
exits 0 (syntax check) and the file is executable.

**P2.2 Register the hook.** Back up `~/.claude/settings.json` to
`~/.claude/settings.json.bak-handoff-v01` first. Then merge (do NOT
clobber existing keys) so the file contains:

```json
"hooks": {
  "PreCompact": [
    { "hooks": [ { "type": "command",
        "command": "\"$HOME\"/.claude/hooks/precompact_handoff.py" } ] }
  ]
}
```

If a `hooks` or `PreCompact` key already exists, append this entry to the
existing array. Validate afterwards: `jq . ~/.claude/settings.json`
must parse. If unsure about the merge, use the `update-config` skill.

**P2.3 Test P2** (all mechanical):

1. **Happy path:** from inside
   `~/src/ops-worktrees/session-handoff-compaction-spec/site-private`:
   ```bash
   echo '{"trigger":"manual","session_id":"test-123","transcript_path":"/tmp/t.jsonl"}' \
     | ~/.claude/hooks/precompact-handoff.sh; echo "exit=$?"
   ```
   Expect `exit=0` and exactly one new
   `~/.local/state/handoffs/site-private/session-handoff-compaction-spec/precompact-*.md`
   containing `trigger: manual`, correct `branch`, non-empty `head_sha`.
2. **Path guard:** same command from `$HOME`. Expect `exit=0` and **no**
   new file anywhere under `~/.local/state/handoffs/`.
3. **Bad input:** `echo 'not json' | <script>` from the workspace.
   Expect `exit=0`, file written with `trigger: unknown`.
4. **No stdin:** `~/.claude/hooks/precompact-handoff.sh < /dev/null`.
   Expect `exit=0`.
5. **Unwritable state dir:** `chmod 555` the repo's state dir, run happy
   path, expect `exit=0` (no file, no error output). Restore `755`.
6. **No temp litter:** after all tests, `ls` the state dir — no
   `.precompact.*.tmp` files remain.

Acceptance: all six pass. Clean up test sidecar files afterwards.

---

## Phase P2b — handoff-tools package (depends P1; parallel with P2/P3)

**P2b.1 Create the package.** Layout:

```
~/.claude/hooks/handoff-tools/
├── pyproject.toml          # name=handoff-tools, requires-python>=3.10
├── session_log.py
├── enrich_checkpoint.py
├── tests/test_session_log.py
└── .venv/                  # python3 -m venv .venv
```

Install deps: `.venv/bin/pip install claude-agent-sdk pyyaml pytest anyio`

**P2b.2 `session_log.py` — Tier 1 mechanics as a CLI.** This moves cap
enforcement, sidecar folding, atomic writes, and staleness checks out of
per-session LLM discipline into tested code. Implement to make the P2b.4
test suite pass (the tests are the contract; where prose and tests
disagree, tests win). CLI:

- `session_log.py read --dir <state-dir> --repo-dir <worktree>` → prints
  JSON to stdout: `{"exists": bool, "frontmatter": {...}, "body": str,
  "stale": bool, "actual_head": str, "sidecars": [paths...]}`. `stale` is
  true iff frontmatter `head_sha` ≠ `git rev-parse HEAD` in `--repo-dir`.
  Missing file → `exists: false`, everything else null/empty, exit 0
  (absence is a state, not an error).
- `session_log.py write --dir <state-dir> --repo-dir <worktree>` with a
  JSON payload on stdin:
  `{"session_id": str, "writer": str, "chain": [str], "latest_handoff":
  str, "active_work": str, "blockers": [str], "next_steps": [str],
  "history_bullets": [str (max 3, error if more)]}`.
  Behavior: computes `branch`/`head_sha`/`dirty` itself from
  `--repo-dir`; folds ALL `precompact-*.md` sidecars into Recent History
  (one entry each, oldest first, marked "unplanned compaction"; enriched
  sidecars keep a pointer line to their content summary) then DELETES
  them; prepends the new history entry; enforces caps (10 entries AND
  drop >30 days AND ≤3 bullets/entry); replaces Current State wholesale;
  writes frontmatter per the spec §3 schema (`schema_version: 1`, ISO
  8601 `updated_at` with offset); writes atomically (tempfile +
  `os.replace` in the same dir). Errors are LOUD (nonzero exit) — this
  is not a hook.
- `session_log.py fold --dir <state-dir> --repo-dir <worktree>` → fold
  sidecars into history only, touch nothing else except `updated_at`.

**P2b.3 `enrich_checkpoint.py`** with exactly this content:

```python
#!/usr/bin/env python3
"""enrich_checkpoint.py — mine a compacting session's transcript into an
enriched checkpoint. Launched detached by precompact_handoff.py.
Best-effort: failures are logged (stderr -> enrich.log) and harmless.

Usage: enrich_checkpoint.py <sidecar.md> <transcript.jsonl>
Writes <sidecar-stem>-enriched.md next to the sidecar.
"""
import json
import sys
from pathlib import Path

import anyio
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions,
                              TextBlock, query)

MAX_CHARS = 150_000  # transcript tail cap fed to the model

PROMPT = """An AI coding session is being context-compacted. Below is \
the tail of its transcript. Extract, as terse markdown bullets under \
these exact headings, only what is actually present (omit empty \
headings). Preserve raw numbers, file paths, and command lines exactly.

## Goal
## Work completed
## Approaches tried (incl. failed, with why)
## Decisions (chosen and rejected)
## Evidence & measurements
## Operator feedback/preferences
## Next steps

Transcript tail:
"""


def transcript_text(path):
    pieces = []
    try:
        for line in Path(path).read_text(errors="replace").splitlines():
            try:
                obj = json.loads(line)
            except Exception:
                continue
            msg = obj.get("message") or {}
            role = msg.get("role") or obj.get("type") or "?"
            content = msg.get("content")
            if isinstance(content, str):
                pieces.append(f"[{role}] {content}")
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "text":
                        pieces.append(f"[{role}] {b.get('text', '')}")
    except Exception:
        return ""
    return "\n".join(pieces)[-MAX_CHARS:]


async def amain(sidecar, transcript):
    text = transcript_text(transcript)
    if not text:
        return
    opts = ClaudeAgentOptions(
        model="claude-haiku-4-5",
        max_turns=1,
        allowed_tools=[],
        system_prompt="You are a terse session archivist.",
    )
    out = []
    async for message in query(prompt=PROMPT + text, options=opts):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    out.append(block.text)
    if not out:
        return
    enriched = sidecar.with_name(sidecar.stem + "-enriched.md")
    tmp = enriched.with_suffix(".tmp")
    tmp.write_text(
        "# Enriched checkpoint (haiku, best-effort)\n\n"
        + "\n".join(out) + "\n")
    tmp.replace(enriched)


def main():
    if len(sys.argv) != 3:
        sys.exit(2)
    anyio.run(amain, Path(sys.argv[1]), Path(sys.argv[2]))


if __name__ == "__main__":
    main()
```

**P2b.4 Test suite** — `tests/test_session_log.py` with exactly this
content (implement `session_log.py` until it passes; do not weaken
tests):

```python
"""Contract tests for session_log.py. Tests ARE the spec where prose
is ambiguous. Run: .venv/bin/python -m pytest tests/ -q"""
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "session_log.py"


def run(args, stdin=None):
    return subprocess.run([sys.executable, str(TOOL), *args],
                          input=stdin, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "init"],
                   cwd=r, check=True)
    return r


@pytest.fixture
def state(tmp_path):
    s = tmp_path / "state"
    s.mkdir()
    return s


def payload(**kw):
    base = dict(session_id="s1", writer="claude-code", chain=["x-1"],
                latest_handoff="none", active_work="test work",
                blockers=[], next_steps=["run: echo hi"],
                history_bullets=["did a thing"])
    base.update(kw)
    return json.dumps(base)


def head(repo):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()


def test_read_missing_is_not_error(state, repo):
    p = run(["read", "--dir", str(state), "--repo-dir", str(repo)])
    assert p.returncode == 0
    assert json.loads(p.stdout)["exists"] is False


def test_write_then_read_roundtrip(state, repo):
    p = run(["write", "--dir", str(state), "--repo-dir", str(repo)],
            stdin=payload())
    assert p.returncode == 0, p.stderr
    log = state / "SESSION_LOG.md"
    assert log.exists()
    text = log.read_text()
    assert "schema_version: 1" in text
    assert head(repo) in text
    out = json.loads(run(["read", "--dir", str(state),
                          "--repo-dir", str(repo)]).stdout)
    assert out["exists"] and out["stale"] is False


def test_staleness_flips_after_new_commit(state, repo):
    run(["write", "--dir", str(state), "--repo-dir", str(repo)],
        stdin=payload())
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "move"],
                   cwd=repo, check=True)
    out = json.loads(run(["read", "--dir", str(state),
                          "--repo-dir", str(repo)]).stdout)
    assert out["stale"] is True
    assert out["actual_head"] == head(repo)


def test_history_cap_10_entries(state, repo):
    for i in range(13):
        run(["write", "--dir", str(state), "--repo-dir", str(repo)],
            stdin=payload(history_bullets=[f"entry {i}"]))
    text = (state / "SESSION_LOG.md").read_text()
    assert text.count("### ") == 10
    assert "entry 12" in text and "entry 2" not in text


def test_max_3_bullets_rejected(state, repo):
    p = run(["write", "--dir", str(state), "--repo-dir", str(repo)],
            stdin=payload(history_bullets=["a", "b", "c", "d"]))
    assert p.returncode != 0


def test_sidecars_folded_and_deleted(state, repo):
    (state / "precompact-20260803T120000Z.md").write_text(
        "---\ncompacted: true\ntrigger: manual\n"
        "updated_at: 2026-08-03T08:00:00-0400\n---\n\nclean\n")
    run(["write", "--dir", str(state), "--repo-dir", str(repo)],
        stdin=payload())
    text = (state / "SESSION_LOG.md").read_text()
    assert "unplanned compaction" in text
    assert not list(state.glob("precompact-*.md"))


def test_current_state_replaced_wholesale(state, repo):
    run(["write", "--dir", str(state), "--repo-dir", str(repo)],
        stdin=payload(active_work="OLD WORK"))
    run(["write", "--dir", str(state), "--repo-dir", str(repo)],
        stdin=payload(active_work="NEW WORK"))
    text = (state / "SESSION_LOG.md").read_text()
    assert "NEW WORK" in text
    # old value survives only in history, never in Current State
    cs = text.split("## Recent History")[0]
    assert "OLD WORK" not in cs


def test_atomic_no_tmp_litter(state, repo):
    run(["write", "--dir", str(state), "--repo-dir", str(repo)],
        stdin=payload())
    assert not [p for p in state.iterdir() if ".tmp" in p.name]


def test_age_cap_30_days(state, repo):
    old = (datetime.now().astimezone() - timedelta(days=45))
    stamp = old.strftime("%Y-%m-%dT%H:%M:%S%z")
    run(["write", "--dir", str(state), "--repo-dir", str(repo)],
        stdin=payload(history_bullets=["ancient"]))
    text = (state / "SESSION_LOG.md").read_text()
    text = text.replace(
        text.split("### ")[1].split(" — ")[0], stamp, 1)
    (state / "SESSION_LOG.md").write_text(text)
    run(["write", "--dir", str(state), "--repo-dir", str(repo)],
        stdin=payload(history_bullets=["fresh"]))
    final = (state / "SESSION_LOG.md").read_text()
    assert "fresh" in final and "ancient" not in final
```

**P2b.5 Tests for the phase:**
1. `.venv/bin/python -m pytest tests/ -q` → all pass, none skipped.
2. Syntax check enricher:
   `.venv/bin/python -c "import ast; ast.parse(open('enrich_checkpoint.py').read())"`.
3. Enrichment kill-switch: from a workspace dir,
   `HANDOFF_ENRICH=0 <happy-path P2.3 test 1>` → sidecar written, no
   `enrich.log` created, no `*-enriched.md`.
4. Do NOT run a live enricher call in this phase — that's P5.7 (needs
   sign-off, spends quota).

Acceptance: 1–3 pass; deviation list empty.

---

## Phase P3 — Claude Code skills (depends P1 + P2b)

**P3.1 Create `~/.claude/skills/session-handoff/SKILL.md`** (Tier 1
protocol) with exactly:

```markdown
---
name: session-handoff
description: Read/write the out-of-tree Tier 1 session pointer file (SESSION_LOG.md) for ops worktree sessions. Use at session start in any ops workspace, before handing off to another agent/session, and at session end. Triggers on: resume session, session log, tier 1, read the session log, update session log.
---

# Session Handoff — Tier 1 pointer file

Spec: `~/ops/site-private/docs/session-handoff-compaction-spec.md` (v0.3).
State root: `~/.local/state/handoffs/<repo>/<task>/SESSION_LOG.md`, where
`<task>` is the task-workspace dir name under `~/src/ops-worktrees/`
(`main` for reference checkouts, `ops` for `~/ops` sessions).

## Ownership

One writer per task workspace: the session that owns it. Sub-agents
NEVER write Tier 1 or Tier 2 — they return completion reports; the owner
writes. Any agent may read.

## Reader protocol (session start, or when handed a Tier 1 path)

1. Read `SESSION_LOG.md` if present. Also glob `precompact-*.md` in the
   same dir — sidecars newer than `updated_at` are unplanned-compaction
   checkpoints that supersede the log's recency.
2. Staleness check: compare frontmatter `head_sha` to actual
   `git rev-parse HEAD` in the worktree. Mismatch (or dirty-state drift)
   demotes the file from briefing to lead: verify its claims against the
   repo before trusting any of them.
3. State a resume plan to the operator BEFORE touching anything.
4. Never ask the operator for information the file already answers.
5. File missing or unparseable: not an error. Bootstrap a minimal one
   from `git status` / `git log -1` / current branch with Active work:
   "no prior context found", then proceed.

## Writer protocol (before handoff, at session end, after major state changes)

Use the helper — it owns caps, sidecar folding, atomicity, and git
anchoring so you don't have to get them right by hand:

    ~/.claude/hooks/handoff-tools/.venv/bin/python \
      ~/.claude/hooks/handoff-tools/session_log.py write \
      --dir <state-dir> --repo-dir <worktree>

with the JSON payload on stdin (`session_id`, `writer`, `chain`,
`latest_handoff`, `active_work`, `blockers`, `next_steps`,
`history_bullets` — max 3). `read` and `fold` subcommands exist too;
`read` returns the staleness verdict pre-computed. Only edit the file by
hand if the helper is broken, and then follow the same rules it
enforces (replace Current State wholesale; 10-entry/30-day/3-bullet
caps; temp-file + rename).

Composition rule regardless of path: every Next-steps item must be a
path, a runnable command, or an ID resolvable from cold start. Never
"as discussed above"; never a bare reference to tool-backed state (task
lists, memory) without the exact tool call that retrieves it.

## File format

    ---
    schema_version: 1
    updated_at: 2026-08-03T14:22:17-0400
    session_id: <herdr pane id, or session uuid, or "solo">
    writer: claude-code
    workspace: <task dir name>
    repo: <repo name>
    branch: <branch>
    head_sha: <full sha>
    dirty: true|false
    chain: [<bead/epic ids or standalone-hex>]
    latest_handoff: <site-private-relative path, or "none">
    ---

    ## Current State
    - Active work: <bead ID + description, or free text>
    - Blockers: <list or "None">
    - Next steps: <bullets per writer-protocol rule 6>

    ## Recent History
    ### 2026-08-03T14:22:17-0400 — claude-code
    - <max 3 bullets>

## Guards

- Only operate under `~/src/ops-worktrees/` or `~/ops/`. Elsewhere: this
  skill does not apply; say so and stop.
- Deep recovery (12-item mining, chain docs) is the separate `handoff`
  skill (Tier 2). This skill is the cheap pointer only.
```

**P3.2 Create `~/.claude/skills/handoff/SKILL.md`** (Tier 2) with exactly:

```markdown
---
name: handoff
description: Create a deep Tier 2 handoff document in site-private/memory/handoffs/ — chain-tagged, DAG-linked, mined from the full conversation. Use when pausing substantial work, before ending a long session, or when the operator says "do a handoff", "create a handoff", "save session context".
---

# Handoff — Tier 2 deep recovery document

Spec: `~/ops/site-private/docs/session-handoff-compaction-spec.md` (v0.3).
Output: `~/ops/site-private/memory/handoffs/<target-repo>/` — committed
DIRECTLY TO MASTER under the memory-data exception, pushed immediately.

## Guards

- Only the workspace-owning session runs this. Sub-agents never do.
- Never generate handoff-like documents freeform outside this skill.
- Only when the operator (or owning orchestrator) explicitly wants a
  handoff created now. If ambiguous, ask.
- Not in plan mode.

## Step 1 — Gather external state (parallel Bash, never agents)

`git log --oneline -15`, `git diff --stat`, `git status -s | head -30`,
`git branch --show-current`, `git rev-parse HEAD`; Beads state if
available (`bd list --status=in_progress` in ops-djbclark context);
`ls ~/ops/site-private/memory/handoffs/<repo>/ 2>/dev/null`.

## Step 2 — Chain tag and lineage

Chain tag, first match: (1) Beads epic ID; (2) 1–4 bead IDs (list);
(3) `standalone-{4-hex}` (`python3 -c "import secrets;print(secrets.token_hex(2))"`).

Lineage is an explicit DAG:
- `handoff_id`: fresh 4-hex id.
- `parent_handoff_ids`: if this session started from a resume prompt
  naming a parent handoff file, that file's id (deterministic — primary).
  Else grep `~/ops/site-private/memory/handoffs/<repo>/` for the chain
  tag as RECOVERY ONLY: a shared bead is a candidate, not proof — read
  the candidate's "Where We're Going"; only clear continuation makes it
  a parent, and the new doc must say `lineage: inferred`. Doubt → ask
  the operator. No parent → `[]`.

## Step 3 — Mine the conversation

Announce pass choice: Quick (<100K context) / Deep (100K–500K) /
Chunked map-reduce (500K+). Extract, in chronological order where it
matters: goals; work completed (files, functions, specifics); approaches
tried; FAILED approaches + why (most expensive to rediscover — never
skip); test results with raw numbers; data files created; decisions +
rejected alternatives; discoveries/gotchas; code analysis (signatures,
constants); operator preferences expressed; open questions; dependencies.

## Step 4 — Write the file

Path: `~/ops/site-private/memory/handoffs/<repo>/HANDOFF_{chain}_{slug}_{YYYY-MM-DD}_{handoff_id}.md`
(slug: 2–4 kebab words; multi-bead chains use the primary bead in the
filename). `mkdir -p` the repo dir if needed.

    ---
    schema_version: 1
    handoff_id: <4 hex>
    parent_handoff_ids: []
    lineage: deterministic|inferred|none
    chain: [<ids>]
    repo: <target repo>
    workspace: <task dir name>
    branch: <branch>
    head_sha: <sha>
    created_at: <ISO 8601 with offset>
    writer: claude-code
    ---
    # Handoff — <title>
    ## The Goal
    ## Where We Are
    ## What We Tried            <- failed approaches, chronological, with why
    ## Key Decisions            <- chosen AND rejected
    ## Evidence & Data          <- real numbers, file paths
    ## Operator Feedback
    ## Where We're Going        <- ordered; item 1 is THE next action
    ## Quick Start              <- exact commands for the next session

## Step 5 — Validation gate (all required; line count is NOT the gate)

- [ ] Objective stated
- [ ] Exact git state (branch, head_sha, dirty list)
- [ ] Files changed this session
- [ ] Tests run + results (or explicit "none run")
- [ ] Decisions + rejected alternatives
- [ ] Failed approaches + why
- [ ] Blockers / open questions
- [ ] ONE explicit next action at the top of Where We're Going
- [ ] Parent linkage (ids, or explicit none)
- [ ] Redaction: no credentials, tokens, .env values, key material,
      anywhere in the doc

Any unchecked box: fix before proceeding. Thin sections: expand from the
conversation, don't pad.

## Step 6 — Commit (memory exception flow, EXACTLY this)

1. `cd ~/ops/site-djbclark && just ops-memory-sync`
2. `cd ~/ops/site-private && git add memory/handoffs/ && git commit -m "memory: handoff <repo>/<filename>"`
   — memory-only commit; NOTHING else staged.
3. `git push` immediately. Leave the tree clean.

## Step 7 — Update Tier 1

Via the `session-handoff` skill's writer protocol: set `latest_handoff`
to the new site-private-relative path, refresh Current State, add a
history entry. Then report to the operator: file path, chain + lineage,
validation outcome, the next action.
```

**P3.3 Test P3** (static): both files parse as skills — restart check:
`ls ~/.claude/skills/` shows both; frontmatter has `name` and
`description`; no line exceeds reasonable length; paths in the bodies
exist (`~/ops/site-private/memory/`, state root). No agent spawns.

Acceptance: both skills present and internally consistent with spec v0.3
§3–§4. Note: `docs/session-handoff-compaction-spec.md` referenced by both
skills only exists in `~/ops/site-private/` after this task's PR merges
and a release lands it there — until then the reference is
forward-looking. Do not "fix" it by pointing at the worktree.

---

## Phase P4 — herdr-orchestration amendment + vendor pointers (depends P3)

**P4.1 Amend `~/.claude/skills/herdr-orchestration/SKILL.md`.** Locate
the section headed `## Session-to-session handoffs: prefer live
orchestration over clipboard relay (added 2026-08-01)`. Immediately
after that section's existing content, insert:

```markdown
### Durable file backing (added 2026-08-03 — Tier 1/Tier 2 system)

Live orchestration now rides on the session-handoff file system (spec:
site-private `docs/session-handoff-compaction-spec.md`):

- BEFORE spawning or prompting the next session, the owning session
  updates Tier 1 (`session-handoff` skill) — and writes a Tier 2 doc
  (`handoff` skill) if the work is substantial enough to deserve deep
  recovery.
- The spawn prompt is a **bootstrap packet**, not a context dump:
  1. repo + absolute workspace path
  2. one-line objective
  3. absolute Tier 1 path
     (`~/.local/state/handoffs/<repo>/<task>/SESSION_LOG.md`)
  4. instruction: "Report whether that file exists and whether its
     head_sha matches `git rev-parse HEAD` before doing anything else."
  5. a 2–3 line critical-fallback summary in case the path is wrong.
- Sub-agents never write Tier 1/Tier 2; they end by returning a
  completion report (what changed, commands run, blockers) and the
  owner folds it into Tier 1.
```

**P4.2 Vendor pointer in the shared agents file.** In THIS worktree
(`session-handoff-compaction-spec/site-private`), edit `home-agents.md`:
append this section before any trailing content:

```markdown
## Session logs (Tier 1 handoff pointers)

Every ops worktree session should start by checking
`~/.local/state/handoffs/<repo>/<task>/SESSION_LOG.md` (task = workspace
dir name under `~/src/ops-worktrees/`; `main` / `ops` for the reference
and deploy checkouts). Read it, compare its `head_sha` to actual `HEAD`,
and state a resume plan before acting. Full protocol:
[docs/session-handoff-compaction-spec.md](docs/session-handoff-compaction-spec.md).
Only the workspace-owning session writes it; sub-agents report back
instead. Missing file = fresh start, not an error.
```

Commit in the worktree. Other vendor rules files (`GEMINI.md`,
`.cursorrules`): create nothing new; only add an equivalent pointer to
files that already exist (check; currently none expected).

**P4.3 Public-skills sync check** (policy:
`[[feedback_skill_update_sync_external]]`). Check whether
`djbclark/claude-orchestration-skills` contains `herdr-orchestration`:
`gh api repos/djbclark/claude-orchestration-skills/contents/ --jq '.[].name'`.
If present, apply the P4.1 amendment there too (branch + PR, or direct
push if that repo's convention allows), after confirming the inserted
text contains nothing private (it doesn't — paths are generic). If
absent, record "not published there" in your report.

**P4.4 Test P4:** grep checks — amendment text present in the live
skill; `home-agents.md` section present and committed;
P4.3 outcome recorded.

---

## Phase P5 — End-to-end acceptance (depends P2+P2b+P3+P4;
**orchestrator sign-off required before spawning sessions or SDK
calls**)

**P5.0 Unit gate (mechanical, no sign-off):** re-run the P2b pytest
suite green, and P1.3/P2.3 spot checks, on the day of E2E — not stale
results from the build day.

Seed fixture first (mechanical): from
`~/src/ops-worktrees/session-handoff-compaction-spec/site-private`, write
a realistic Tier 1 file by hand following P3.1's format — Active work:
"handoff v0.1 E2E fixture", one fake-but-plausible history entry, correct
real `head_sha`.

**P5.1 Cold-start resume (the core acceptance test).** Spawn ONE fresh
Claude Code session (via herdr if live, else `claude -p`) with only:

> Read `~/.local/state/handoffs/site-private/session-handoff-compaction-spec/SESSION_LOG.md`
> and resume work per its protocol.

PASS iff the fresh session: (a) reads the file; (b) runs the staleness
check against real HEAD and reports the result; (c) states a resume plan
before any mutation; (d) asks nothing the file already answers.
FAIL on any miss — capture the transcript for the orchestrator.

**P5.2 Staleness detection.** Make one trivial commit in the fixture
worktree (e.g. whitespace in a scratch file) so HEAD moves. Repeat P5.1.
PASS iff the session flags the mismatch and demotes the file to a lead
(verifies claims) rather than trusting it.

**P5.3 Bootstrap-on-missing.** Delete the fixture Tier 1 file. Repeat
P5.1. PASS iff the session treats absence as fresh-start, synthesizes a
minimal log per protocol, and does NOT error or ask "where is the file".

**P5.4 Real compaction hook firing.** Operator-in-the-loop (flag for
scheduling): in a live interactive session inside any ops workspace, run
`/compact`. PASS iff a `precompact-*.md` sidecar appears in the right
state dir with `trigger: manual` and compaction itself is undisturbed.
Then verify sidecar folding: run the `session-handoff` skill's writer
protocol in that session; PASS iff the sidecar's content lands as a
Recent History entry and the sidecar file is deleted.

**P5.5 Tier 2 full flow.** In a session with real accumulated work (this
spec task itself qualifies), run the `handoff` skill end-to-end. PASS
iff: file lands in `~/ops/site-private/memory/handoffs/site-private/`
with all frontmatter fields; every validation-gate box checkable;
`ops-memory-sync` ran first; commit is memory-only; pushed; Tier 1
`latest_handoff` updated to the site-private-relative path.

**P5.6 Cross-vendor read (stretch — attempt once, don't loop on
failure).** Via herdr, spawn one available non-Claude agent (per device/
vendor availability; check with orchestrator) with the P4.1 bootstrap
packet pointing at the fixture. PASS iff it reads the file and reports
found/sha-match status. If no vendor is available, mark SKIPPED with
reason — this is a build-step-2 guarantee, not a v0.1 blocker.

**P5.7 Enricher E2E (one Haiku call — included in the sign-off
batch).** Build a fixture transcript: 30–50 JSONL lines shaped like real
Claude Code transcript entries (`{"type":"user","message":{"role":"user",
"content":"..."}}` / assistant equivalents) telling a coherent
mini-story: a goal, one failed approach with a reason, one decision, one
measurement, a next step. Run:
`.venv/bin/python enrich_checkpoint.py <fixture-sidecar.md> <fixture.jsonl>`.
PASS iff a `*-enriched.md` appears containing the failed approach AND
the measurement (the two highest-value extraction classes); the run
completes in under 2 minutes; and nothing else in the state dir was
touched. Then verify folding: `session_log.py write` on that dir folds
BOTH sidecar and enriched file into history and deletes them.

Acceptance for the phase: P5.0–P5.3, P5.5, and P5.7 PASS; P5.4 PASS or
scheduled with operator; P5.6 PASS or SKIPPED-with-reason.

---

## Phase P6 — Mirrors, docs, migration (depends P5 green)

**P6.1 Tracked mirrors.** In this worktree, create `claude/hooks/` and
`claude/skills/` containing byte-identical copies of:
`precompact_handoff.py`, the `handoff-tools/` package (`session_log.py`,
`enrich_checkpoint.py`, `pyproject.toml`, `tests/` — NEVER `.venv/`),
both P3 SKILL.md files (under `claude/skills/session-handoff/` and
`claude/skills/handoff/`), and a `claude/README.md` (3–5 lines) stating:
live copies under `~/.claude/` are canonical; these are versioned
mirrors; update both together (same rule as the root CLAUDE.md
distribute-and-symlink convention).

**P6.2 Migration note.** New worktree for stayturgid in THIS task
workspace:
`git -C ~/src/ops-worktrees/.store/stayturgid.git worktree add -b feature/session-handoff-compaction-spec ~/src/ops-worktrees/session-handoff-compaction-spec/stayturgid master`.
Add to `docs/operations/sessions/` a `README.md` (create; the dir has
none): "Frozen archive as of 2026-08-03. New handoffs live in
site-private `memory/handoffs/` — see site-private
`docs/session-handoff-compaction-spec.md`." Commit on the branch.

**P6.3 Teardown-procedure update.** Edit the untracked
`~/src/ops-worktrees/README.md` "Remove a task workspace" section: add
`rm -rf ~/.local/state/handoffs/*/"$TASK"` after the worktree-remove
loop, with the note "write a final Tier 2 doc first if the work is being
abandoned". Apply the same edit to the tracked mirror
`docs/ops-worktrees-layout.md` in a new ops-djbclark worktree (same
pattern as P6.2; ops-djbclark has no release process — normal PR).

**P6.4 PRs.** Open PRs for: site-private branch (spec + plan +
home-agents.md + mirrors), stayturgid branch (migration README),
ops-djbclark branch (layout doc). Bodies link the spec file and end with
the standard generated-with footer. Do NOT merge — operator reviews.

---

## Final report format (implementing agent → orchestrator)

Per phase: task IDs with PASS/FAIL/SKIPPED, actual command outputs for
every acceptance table, transcript paths for P5 spawned sessions, PR
URLs, and an explicit list of anything done that deviates from this plan
(target: empty).

## Rollback

Remove the `PreCompact` entry from `~/.claude/settings.json` (restore
`.bak-handoff-v01`); `rm -rf ~/.claude/skills/session-handoff
~/.claude/skills/handoff ~/.claude/hooks/precompact_handoff.py
~/.claude/hooks/handoff-tools ~/.local/state/handoffs`; revert the P4.1
skill section; close the PRs unmerged. (`HANDOFF_ENRICH=0` in the
environment is the soft kill-switch for enrichment alone, no uninstall
needed.) Nothing in this plan touches `~/ops` tracked files, Hermes
config, or existing skills beyond the P4.1 insertion, so rollback is
complete with the above.
