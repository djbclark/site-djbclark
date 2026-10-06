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


def make_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "init"],
                   cwd=path, check=True)
    return path


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo")


@pytest.fixture
def state(tmp_path):
    s = tmp_path / "state"
    s.mkdir()
    return s


def payload(repo_dir, repo="repo", task="main", **kw):
    base = dict(session_id="s1", writer="claude-code", chain=["x-1"],
                latest_handoff="none", active_work="test work",
                blockers=[], next_steps=["run: echo hi"],
                history_bullets=["did a thing"],
                workspaces=[{"repo": repo, "task": task, "dir": str(repo_dir)}])
    base.update(kw)
    return json.dumps(base)


def head(repo):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()


def pointer_dir(state, repo="repo", task="main"):
    return state / repo / task


def canonical_path(state, chain="x-1"):
    return state / "chains" / chain / "SESSION_LOG.md"


def test_read_missing_is_not_error(state, repo):
    d = pointer_dir(state)
    d.mkdir(parents=True)
    p = run(["read", "--state-root", str(state), "--dir", str(d)])
    assert p.returncode == 0
    assert json.loads(p.stdout)["exists"] is False


def test_write_then_read_roundtrip(state, repo):
    p = run(["write", "--state-root", str(state)], stdin=payload(repo))
    assert p.returncode == 0, p.stderr
    log = canonical_path(state)
    assert log.exists()
    text = log.read_text()
    assert "schema_version: 2" in text
    assert head(repo) in text
    ptr = pointer_dir(state) / "SESSION_LOG.md"
    assert ptr.exists()
    assert "redirect: chains/x-1/SESSION_LOG.md" in ptr.read_text()
    out = json.loads(run(["read", "--state-root", str(state),
                          "--dir", str(pointer_dir(state))]).stdout)
    assert out["exists"] and out["stale"] is False
    assert out["workspaces"][0]["repo"] == "repo"


def test_staleness_flips_after_new_commit(state, repo):
    run(["write", "--state-root", str(state)], stdin=payload(repo))
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "move"],
                   cwd=repo, check=True)
    out = json.loads(run(["read", "--state-root", str(state),
                          "--dir", str(pointer_dir(state))]).stdout)
    assert out["stale"] is True
    assert out["workspaces"][0]["actual_head"] == head(repo)


def test_two_workspaces_one_chain(state, tmp_path):
    worktree_repo = make_repo(tmp_path / "wt" / "repo")
    ops_repo = make_repo(tmp_path / "ops" / "repo")
    combined = json.dumps(dict(
        session_id="s1", writer="claude-code", chain=["x-1"],
        latest_handoff="none", active_work="spanning both",
        blockers=[], next_steps=["run: echo hi"], history_bullets=["touched both"],
        workspaces=[
            {"repo": "repo", "task": "sometask", "dir": str(worktree_repo)},
            {"repo": "repo", "task": "ops", "dir": str(ops_repo)},
        ],
    ))
    p = run(["write", "--state-root", str(state)], stdin=combined)
    assert p.returncode == 0, p.stderr
    # One canonical file...
    text = canonical_path(state).read_text()
    assert head(worktree_repo) in text and head(ops_repo) in text
    # ...and both directories get pointers to the same chain.
    for task in ("sometask", "ops"):
        ptr = (state / "repo" / task / "SESSION_LOG.md").read_text()
        assert "redirect: chains/x-1/SESSION_LOG.md" in ptr
    # Reading from either pointer reports staleness for both workspaces.
    out = json.loads(run(["read", "--state-root", str(state),
                          "--dir", str(state / "repo" / "ops")]).stdout)
    assert len(out["workspaces"]) == 2
    assert out["stale"] is False


def test_history_cap_10_entries(state, repo):
    for i in range(13):
        run(["write", "--state-root", str(state)],
            stdin=payload(repo, history_bullets=[f"entry {i}"]))
    text = canonical_path(state).read_text()
    assert text.count("### ") == 10
    assert "entry 12" in text and "entry 2" not in text


def test_max_3_bullets_rejected(state, repo):
    p = run(["write", "--state-root", str(state)],
            stdin=payload(repo, history_bullets=["a", "b", "c", "d"]))
    assert p.returncode != 0


def test_workspaces_required(state, repo):
    bad = json.loads(payload(repo))
    bad["workspaces"] = []
    p = run(["write", "--state-root", str(state)], stdin=json.dumps(bad))
    assert p.returncode != 0


def test_chain_required(state, repo):
    bad = json.loads(payload(repo))
    bad["chain"] = []
    p = run(["write", "--state-root", str(state)], stdin=json.dumps(bad))
    assert p.returncode != 0


def test_sidecars_folded_and_deleted(state, repo):
    d = pointer_dir(state)
    d.mkdir(parents=True)
    (d / "precompact-20260803T120000Z.md").write_text(
        "---\ncompacted: true\ntrigger: manual\n"
        "updated_at: 2026-08-03T08:00:00-0400\n---\n\nclean\n")
    run(["write", "--state-root", str(state)], stdin=payload(repo))
    text = canonical_path(state).read_text()
    assert "unplanned compaction" in text
    assert not list(d.glob("precompact-*.md"))


def test_current_state_replaced_wholesale(state, repo):
    run(["write", "--state-root", str(state)], stdin=payload(repo, active_work="OLD WORK"))
    run(["write", "--state-root", str(state)], stdin=payload(repo, active_work="NEW WORK"))
    text = canonical_path(state).read_text()
    assert "NEW WORK" in text
    # old value survives only in history, never in Current State
    cs = text.split("## Recent History")[0]
    assert "OLD WORK" not in cs


def test_atomic_no_tmp_litter(state, repo):
    run(["write", "--state-root", str(state)], stdin=payload(repo))
    for d in (canonical_path(state).parent, pointer_dir(state)):
        assert not [p for p in d.iterdir() if ".tmp" in p.name]


def test_age_cap_30_days(state, repo):
    old = (datetime.now().astimezone() - timedelta(days=45))
    stamp = old.strftime("%Y-%m-%dT%H:%M:%S%z")
    run(["write", "--state-root", str(state)], stdin=payload(repo, history_bullets=["ancient"]))
    log = canonical_path(state)
    text = log.read_text()
    text = text.replace(
        text.split("### ")[1].split(" — ")[0], stamp, 1)
    log.write_text(text)
    run(["write", "--state-root", str(state)], stdin=payload(repo, history_bullets=["fresh"]))
    final = log.read_text()
    assert "fresh" in final and "ancient" not in final


def test_legacy_log_still_readable(state, repo):
    """A pre-migration full log (no `redirect`) is treated as already canonical."""
    d = pointer_dir(state)
    d.mkdir(parents=True)
    (d / "SESSION_LOG.md").write_text(
        "---\nschema_version: 1\nupdated_at: 2026-08-01T00:00:00-0400\n"
        "session_id: solo\nwriter: claude-code\nrepo: repo\nbranch: master\n"
        f"head_sha: {head(repo)}\ndirty: false\nchain: [x-1]\n"
        "latest_handoff: none\n---\n\n## Current State\n- Active work: legacy\n"
        "- Blockers: None\n- Next steps:\n  - do a thing\n\n## Recent History\n")
    out = json.loads(run(["read", "--state-root", str(state), "--dir", str(d)]).stdout)
    assert out["exists"] is True
    assert out["legacy_unmigrated"] is True


def test_fold_folds_into_canonical_not_pointer(state, repo):
    run(["write", "--state-root", str(state)], stdin=payload(repo))
    d = pointer_dir(state)
    (d / "precompact-20260803T130000Z.md").write_text(
        "---\ncompacted: true\ntrigger: manual\n"
        "updated_at: 2026-08-03T09:00:00-0400\n---\n\ndirty\n")
    p = run(["fold", "--state-root", str(state), "--dir", str(d)])
    assert p.returncode == 0, p.stderr
    assert "unplanned compaction" in canonical_path(state).read_text()
    assert not list(d.glob("precompact-*.md"))
    # Pointer file itself is untouched by fold.
    assert "redirect:" in (d / "SESSION_LOG.md").read_text()
