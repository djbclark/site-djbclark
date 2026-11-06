"""skills/diskfree/scripts/bigteam-prune.py deletes directories: every case here is a checkout that must be KEPT, plus
the clean pushed clone and linked worktree that must go. Hermetic: fixture repos under tmp_path with a bare 'remote'."""
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "skills/diskfree/scripts/bigteam-prune.py"


def _env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return env


def g(cwd, *args, env=None):
    r = subprocess.run(["git", "-c", "protocol.file.allow=always", *args], cwd=cwd, capture_output=True, text=True,
                       env=env or _env())
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def rm(prune, c):
    """prune.remove with the task dir (the checkout's parent) judged eligible right now."""
    task = c.parent
    return prune.remove(c, task, {task: task.stat().st_mtime})


def commit(repo, name, text="x\n", msg=None):
    (Path(repo) / name).write_text(text)
    g(repo, "add", "-A")
    g(repo, "commit", "-q", "-m", msg or f"add {name}")
    return g(repo, "rev-parse", "HEAD")


@pytest.fixture
def prune(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("bigteam_prune", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    for var in m.NET_ENV + ("GIT_SSH", "GIT_SSH_COMMAND"):  # the developer's own proxy settings must not leak in
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(m, "B", tmp_path / "bt")
    monkeypatch.setattr(m, "MIN_AGE", 0)
    (tmp_path / "bt").mkdir()
    return m


@pytest.fixture
def world(tmp_path):
    """A bare remote with one pushed commit on main; returns the remote path."""
    remote = tmp_path / "remote.git"
    g(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    seed = tmp_path / "seed"
    g(tmp_path, "init", "-q", "-b", "main", str(seed))
    commit(seed, "README", "hello\n")
    g(seed, "remote", "add", "origin", str(remote))
    g(seed, "push", "-q", "origin", "main")
    return remote


def make_clone(tmp_path, remote, task="task1", name="clone"):
    d = tmp_path / "bt" / task
    d.mkdir(parents=True, exist_ok=True)
    g(tmp_path, "clone", "-q", str(remote), str(d / name))
    return d / name


def test_clean_pushed_clone_is_removed(prune, tmp_path, world, capsys, monkeypatch):
    c = make_clone(tmp_path, world)
    assert prune.safe(c)[0]
    monkeypatch.setattr(sys, "argv", ["x", "--apply"])
    prune.main()
    assert not c.exists()
    assert "REMOVED" in capsys.readouterr().out


def test_clean_pushed_linked_worktree_is_removed_and_branch_kept(prune, tmp_path, world):
    main = tmp_path / "mainrepo"
    g(tmp_path, "clone", "-q", str(world), str(main))
    d = tmp_path / "bt" / "task1"
    d.mkdir()
    wt = d / "wt"
    g(main, "worktree", "add", "-q", "-b", "worker", str(wt))
    ok, why = prune.safe(wt)
    assert ok, why
    assert rm(prune, wt) == (True, "worktree removed")
    assert not wt.exists()
    assert "worker" in g(main, "branch", "--list", "worker")


def test_detached_head_commit_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    g(c, "checkout", "-q", "--detach")
    commit(c, "secret", "detached work\n")
    ok, why = prune.safe(c)
    assert not ok and "not on a remote" in why
    assert rm(prune, c)[0] is False
    assert c.exists()


def test_tag_only_commit_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    g(c, "checkout", "-q", "--detach")
    commit(c, "t")
    g(c, "tag", "keepme")
    g(c, "checkout", "-q", "main")
    assert not prune.safe(c)[0]


def test_reflog_only_commit_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit(c, "dropped", "lost soon\n")
    g(c, "reset", "-q", "--hard", "origin/main")
    ok, why = prune.safe(c)
    assert not ok and "reflog" in why


def test_unpushed_branch_commit_and_stash_are_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world, name="a")
    commit(c, "new")
    assert not prune.safe(c)[0]
    c2 = make_clone(tmp_path, world, name="b")
    (c2 / "README").write_text("changed\n")
    g(c2, "stash", "-q")
    ok, why = prune.safe(c2)
    assert not ok and "stash" in why


def test_clone_with_external_worktree_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    ext = tmp_path / "elsewhere"
    g(c, "worktree", "add", "-q", "-b", "other", str(ext))
    ok, why = prune.safe(c)
    assert not ok and "worktrees" in why
    assert rm(prune, c)[0] is False
    assert c.exists() and ext.exists()


@pytest.mark.parametrize("fname", ["my report.md", 'qu"ote.json', "caf\u00e9.txt", "out.rc"])
def test_ignored_report_with_odd_name_is_kept(prune, tmp_path, world, fname):
    c = make_clone(tmp_path, world)
    commit(c, ".gitignore", "*\n!.gitignore\n!README\n")
    g(c, "push", "-q", "origin", "HEAD:main")
    (c / fname).write_text("report\n")
    assert g(c, "status", "--porcelain", "--ignored")  # git does list it (quoted); the script must still see it
    ok, why = prune.safe(c)
    assert not ok and "ignored" in why
    assert rm(prune, c)[0] is False
    assert (c / fname).exists()


def test_generated_ignored_dir_does_not_keep_a_clean_clone(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit(c, ".gitignore", "node_modules/\n")
    g(c, "push", "-q", "origin", "HEAD:main")
    (c / "node_modules/pkg").mkdir(parents=True)
    (c / "node_modules/pkg/index.json").write_text("{}\n")
    ok, why = prune.safe(c)
    assert ok, why


def test_generated_dir_with_nested_repo_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit(c, ".gitignore", "node_modules/\n")
    g(c, "push", "-q", "origin", "HEAD:main")
    (c / "node_modules/dep").mkdir(parents=True)
    g(c / "node_modules/dep", "init", "-q")
    assert not prune.safe(c)[0]


def test_untracked_file_seen_despite_show_untracked_no(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    g(c, "config", "status.showUntrackedFiles", "no")
    (c / "notes.txt").write_text("unsaved\n")
    assert g(c, "status", "--porcelain") == ""  # the config really hides it
    ok, why = prune.safe(c)
    assert not ok and "untracked" in why
    assert rm(prune, c)[0] is False


def test_submodule_checkout_is_kept(prune, tmp_path, world):
    sub = tmp_path / "subsrc"
    g(tmp_path, "init", "-q", "-b", "main", str(sub))
    commit(sub, "s")
    c = make_clone(tmp_path, world)
    g(c, "submodule", "add", "-q", str(sub), "vendor/sub")
    g(c, "commit", "-q", "-m", "sub")
    g(c, "push", "-q", "origin", "HEAD:main")
    ok, why = prune.safe(c)
    assert not ok and "submodule" in why


def test_dirty_submodule_is_not_clean_even_if_config_ignores_it(prune, tmp_path, world):
    sub = tmp_path / "subsrc"
    g(tmp_path, "init", "-q", "-b", "main", str(sub))
    commit(sub, "s")
    c = make_clone(tmp_path, world)
    g(c, "submodule", "add", "-q", str(sub), "vendor/sub")
    g(c, "config", "submodule.vendor/sub.ignore", "all")
    (c / "vendor/sub/new.txt").write_text("u\n")
    dirty, _ = prune.scan(c)
    assert dirty


def test_git_env_leak_cannot_redirect_the_checks(prune, tmp_path, world, monkeypatch):
    clean = make_clone(tmp_path, world, name="clean")
    dirty = make_clone(tmp_path, world, name="dirty")
    (dirty / "wip.txt").write_text("wip\n")
    monkeypatch.setenv("GIT_DIR", str(clean / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(clean))
    ok, why = prune.safe(dirty)
    assert not ok and "untracked" in why


def test_rebase_in_progress_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    (c / ".git/rebase-merge").mkdir()
    ok, why = prune.safe(c)
    assert not ok and "rebase-merge" in why


def test_recent_activity_is_kept(prune, tmp_path, world, monkeypatch):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "MIN_AGE", 7 * 86400)
    ok, why = prune.safe(c)
    assert not ok and "7 days" in why


def test_symlinked_task_dir_is_skipped(prune, tmp_path, world, capsys, monkeypatch):
    outside = tmp_path / "outside"
    c = make_clone(tmp_path, world, task="real")
    (tmp_path / "bt" / "real").rename(outside)
    (tmp_path / "bt" / "link").symlink_to(outside)
    assert prune.task_dirs() == []
    monkeypatch.setattr(sys, "argv", ["x", "--apply"])
    prune.main()
    assert (outside / "clone").exists()
    assert "REMOVED" not in capsys.readouterr().out


def test_symlinked_checkout_is_never_followed(prune, tmp_path, world):
    real = tmp_path / "realclone"
    g(tmp_path, "clone", "-q", str(world), str(real))
    d = tmp_path / "bt" / "task1"
    d.mkdir()
    (d / "ln").symlink_to(real)
    assert prune.checkouts(d) == []
    ok, why = prune.safe(d / "ln")
    assert not ok
    assert real.exists()


def test_unfinished_job_record_and_claim_keep_the_dir(prune, tmp_path, world):
    c = make_clone(tmp_path, world, task="a")
    (c.parent / "jobs").mkdir()
    (c.parent / "jobs/j.json").write_text("{}")
    assert not prune.finished_dir(c.parent)
    c2 = make_clone(tmp_path, world, task="b")
    (c2.parent / "CLAIM").write_text("DONE 2026-10-13\n")
    assert not prune.finished_dir(c2.parent)
    c3 = make_clone(tmp_path, world, task="c")
    assert prune.finished_dir(c3.parent)


# ---- round 3 -------------------------------------------------------------------------------------------------------


def make_main_with_worktree(tmp_path, remote, branch=None):
    """A main repository OUTSIDE the bigteam root with a linked worktree inside it; returns (main, worktree)."""
    main = tmp_path / "mainrepo"
    g(tmp_path, "clone", "-q", str(remote), str(main))
    d = tmp_path / "bt" / "task1"
    d.mkdir(parents=True, exist_ok=True)
    wt = d / "wt"
    if branch:
        g(main, "worktree", "add", "-q", "-b", branch, str(wt))
    else:
        g(main, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    return main, wt


def test_linked_worktree_detached_reflog_only_commit_is_kept(prune, tmp_path, world):
    main, wt = make_main_with_worktree(tmp_path, world)
    x = commit(wt, "x", "detached work\n")
    g(wt, "checkout", "-q", "--detach", "origin/main")
    ok, why = prune.safe(wt)
    assert not ok and "reflog" in why
    assert rm(prune, wt)[0] is False
    assert wt.exists()
    assert x  # the commit is only in the worktree's HEAD reflog


def test_linked_worktree_with_per_worktree_ref_is_kept(prune, tmp_path, world):
    main, wt = make_main_with_worktree(tmp_path, world)
    y = commit(wt, "y", "kept on a worktree ref\n")
    g(wt, "update-ref", "refs/worktree/keep", y)
    g(wt, "checkout", "-q", "--detach", "origin/main")
    ok, why = prune.safe(wt)
    assert not ok and "per-worktree refs" in why
    assert rm(prune, wt)[0] is False
    assert wt.exists()


def test_clean_detached_linked_worktree_is_removed_and_says_no_branch(prune, tmp_path, world):
    main, wt = make_main_with_worktree(tmp_path, world)
    ok, why = prune.safe(wt)
    assert ok, why
    assert "detached" in why and "branch kept" not in why
    assert rm(prune, wt) == (True, "worktree removed")


def test_linked_worktree_commit_kept_on_its_branch_is_removed(prune, tmp_path, world):
    main, wt = make_main_with_worktree(tmp_path, world, branch="worker")
    commit(wt, "w", "on a branch, pushed\n")
    g(wt, "push", "-q", "origin", "worker")
    ok, why = prune.safe(wt)
    assert ok, why


def test_siblings_that_are_each_others_remote_are_both_kept(prune, tmp_path, world):
    a = make_clone(tmp_path, world, task="t1", name="a")
    b = make_clone(tmp_path, world, task="t1", name="b")
    commit(a, "z", "only here\n")
    g(b, "remote", "add", "a", str(a))
    g(b, "fetch", "-q", "a")
    g(b, "merge", "-q", "--ff-only", "a/main")
    g(a, "remote", "add", "b", str(b))
    g(a, "fetch", "-q", "b")
    for c in (a, b):
        ok, why = prune.safe(c)
        assert not ok and "local path inside the bigteam root" in why


@pytest.mark.parametrize("style", ["file", "relative"])
def test_local_path_remote_inside_root_is_kept_in_any_spelling(prune, tmp_path, world, style):
    a = make_clone(tmp_path, world, task="t1", name="a")
    b = make_clone(tmp_path, world, task="t1", name="b")
    url = f"file://{a}" if style == "file" else "../a"
    g(b, "remote", "add", "sib", url)
    ok, why = prune.safe(b)
    assert not ok and "local path inside the bigteam root" in why


def test_remote_path_outside_root_still_counts(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    assert prune.local_remote_inside_root(c) is None


def test_ignored_report_under_dot_cache_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit(c, ".gitignore", ".cache/\n")
    g(c, "push", "-q", "origin", "HEAD:main")
    (c / ".cache").mkdir()
    (c / ".cache/adv-report.md").write_text("findings\n")
    ok, why = prune.safe(c)
    assert not ok and "ignored" in why


@pytest.mark.parametrize("what", ["note", "hook", "exclude", "lfs", "config.worktree"])
def test_unusual_git_dir_content_keeps_the_clone(prune, tmp_path, world, what):
    c = make_clone(tmp_path, world)
    gd = c / ".git"
    if what == "note":
        (gd / "NOTES.md").write_text("notes\n")
    elif what == "hook":
        (gd / "hooks/pre-push").write_text("#!/bin/sh\n")
    elif what == "exclude":
        (gd / "info/exclude").write_text("*.secret\n")
    elif what == "lfs":
        (gd / "lfs").mkdir()
    else:
        (gd / "config.worktree").write_text("[core]\n")
    ok, why = prune.safe(c)
    assert not ok and "git dir" in why
    assert rm(prune, c)[0] is False
    assert c.exists()


def test_linked_worktree_git_dir_note_is_kept(prune, tmp_path, world):
    main, wt = make_main_with_worktree(tmp_path, world)
    gd = Path(g(wt, "rev-parse", "--absolute-git-dir"))
    (gd / "NOTES.md").write_text("notes\n")
    ok, why = prune.safe(wt)
    assert not ok and "git dir" in why


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_unreadable_dir_inside_generated_dir_keeps_the_clone(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit(c, ".gitignore", "node_modules/\n")
    g(c, "push", "-q", "origin", "HEAD:main")
    hidden = c / "node_modules/a/hidden"
    hidden.mkdir(parents=True)
    hidden.chmod(0)
    try:
        assert prune.ignored_ok(c, "node_modules/") is False
    finally:
        hidden.chmod(0o755)


def test_failed_rmtree_is_reported_not_counted(prune, tmp_path, world, monkeypatch):
    c = make_clone(tmp_path, world)

    def boom(path):
        raise OSError("disk says no")

    monkeypatch.setattr(prune.shutil, "rmtree", boom)
    ok, msg = rm(prune, c)
    assert ok is False and "half deleted" in msg


def test_second_apply_is_refused_while_the_lock_is_held(prune, tmp_path, world, monkeypatch):
    c = make_clone(tmp_path, world)
    fd = prune.take_lock()
    assert fd is not None
    try:
        monkeypatch.setattr(sys, "argv", ["x", "--apply"])
        with pytest.raises(SystemExit) as e:
            prune.main()
        assert e.value.code == 3
        assert c.exists()
    finally:
        os.close(fd)
    fd = prune.take_lock()
    assert fd is not None  # released: a later run may take it
    os.close(fd)


# ---- round 4 (local Codex review of c7bccd76: three P1s) --------------------------------------------------------


def _siblings_with_remote(prune, tmp_path, world, url_for):
    a = make_clone(tmp_path, world, task="t1", name="a")
    b = make_clone(tmp_path, world, task="t1", name="b")
    commit(a, "z", "only here\n")
    g(b, "remote", "add", "sib", url_for(a))
    return a, b


def test_percent_encoded_file_url_remote_inside_root_is_kept(prune, tmp_path, world):
    a = make_clone(tmp_path, world, task="t1", name="a")
    b = make_clone(tmp_path, world, task="t1", name="b")
    # git decodes %XX in file:// URLs: .../%62t/... is .../bt/... (the encoded spelling does not exist on disk)
    enc = str(a).replace("/bt/", "/%62t/")
    assert enc != str(a)
    g(b, "remote", "add", "sib", f"file://{enc}")
    assert "%62t" in (prune.local_remote_inside_root(b) or "")
    ok, why = prune.safe(b)
    assert not ok and "bigteam root" in why


def test_file_url_with_foreign_host_or_helper_transport_cannot_be_resolved_and_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    for url in ("file://somehost/tmp/x", "ext::sh -c true", "weird://x/y", "hg::file:///tmp/x"):
        g(c, "remote", "add", "odd", url)
        why = prune.local_remote_inside_root(c)
        assert why and "cannot be resolved" in why, url
        g(c, "remote", "remove", "odd")


@pytest.mark.parametrize("url", ["https://github.com/o/r.git", "git@github.com:o/r.git", "ssh://git@github.com/o/r.git"])
def test_ordinary_network_remotes_do_not_keep_a_clone(prune, tmp_path, world, url, monkeypatch):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "ssh_real_host", lambda h, *a, **k: h)
    monkeypatch.setattr(prune, "resolve_addrs", lambda h: [(socket.AF_INET, ("203.0.113.9", 0))])  # TEST-NET-3
    g(c, "remote", "add", "gh", url)
    assert prune.local_remote_inside_root(c) is None


@pytest.mark.parametrize("url", ["ssh://localhost/tmp/x", "me@localhost:tmp/x", "git://127.0.0.1/x", "http://[::1]/x"])
def test_network_urls_to_this_machine_are_kept(prune, tmp_path, world, url, monkeypatch):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "ssh_real_host", lambda h, *a, **k: h)
    g(c, "remote", "add", "loc", url)
    assert prune.local_remote_inside_root(c)


def test_ssh_alias_resolving_to_this_machine_is_kept(prune, tmp_path, world, monkeypatch):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "ssh_real_host", lambda h, *a, **k: "localhost")
    g(c, "remote", "add", "alias", "myalias:work/x")
    assert prune.local_remote_inside_root(c)


def test_bare_repository_inside_generated_dir_keeps_the_checkout(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit(c, ".gitignore", "node_modules/\n")
    g(c, "push", "-q", "origin", "HEAD:main")
    bare = c / "node_modules/cache/scratch.git"
    bare.parent.mkdir(parents=True)
    g(tmp_path, "init", "-q", "--bare", str(bare))
    ok, why = prune.safe(c)
    assert not ok and "ignored" in why
    assert rm(prune, c)[0] is False
    assert bare.exists()


def test_bare_repository_as_the_generated_dir_itself_keeps_the_checkout(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit(c, ".gitignore", "venv/\n")
    g(c, "push", "-q", "origin", "HEAD:main")
    g(tmp_path, "init", "-q", "--bare", str(c / "venv"))
    assert prune.ignored_ok(c, "venv/") is False


def _planned(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    task = c.parent
    baseline = {task: task.stat().st_mtime}
    return c, task, baseline


def test_claim_added_after_planning_stops_the_deletion(prune, tmp_path, world):
    c, task, baseline = _planned(prune, tmp_path, world)
    (task / "CLAIM").write_text("working\n")
    ok, msg = prune.remove(c, task, baseline)
    assert not ok and "no longer eligible" in msg
    assert c.exists()


def test_unfinished_job_added_after_planning_stops_the_deletion(prune, tmp_path, world):
    c, task, baseline = _planned(prune, tmp_path, world)
    (task / "jobs").mkdir()
    (task / "jobs/j.json").write_text("{}")
    ok, msg = prune.remove(c, task, baseline)
    assert not ok and "no longer eligible" in msg
    assert c.exists()


def test_task_dir_touched_after_planning_stops_the_deletion(prune, tmp_path, world):
    c, task, baseline = _planned(prune, tmp_path, world)
    (task / "new-notes.txt").write_text("someone is here\n")
    ok, msg = prune.remove(c, task, baseline)
    assert not ok and "changed since planning" in msg
    assert c.exists()


def test_task_dir_turned_into_a_symlink_after_planning_stops_the_deletion(prune, tmp_path, world):
    c, task, baseline = _planned(prune, tmp_path, world)
    moved = tmp_path / "moved"
    task.rename(moved)
    task.symlink_to(moved)
    ok, msg = prune.remove(c, task, baseline)
    assert not ok and "no longer eligible" in msg
    assert (moved / "clone").exists()


def test_two_checkouts_in_one_task_are_both_removed(prune, tmp_path, world, monkeypatch, capsys):
    a = make_clone(tmp_path, world, task="t1", name="a")
    b = make_clone(tmp_path, world, task="t1", name="b")
    monkeypatch.setattr(sys, "argv", ["x", "--apply"])
    prune.main()
    assert not a.exists() and not b.exists()
    assert capsys.readouterr().out.count("REMOVED") == 2


def test_claim_appearing_between_two_removals_keeps_the_second(prune, tmp_path, world, monkeypatch, capsys):
    a = make_clone(tmp_path, world, task="t1", name="a")
    b = make_clone(tmp_path, world, task="t1", name="b")
    real = prune._remove

    def remove_then_claim(c):
        res = real(c)
        (c.parent / "CLAIM").write_text("a session just started here\n")
        return res

    monkeypatch.setattr(prune, "_remove", remove_then_claim)
    monkeypatch.setattr(sys, "argv", ["x", "--apply"])
    prune.main()
    out = capsys.readouterr().out
    assert out.count("REMOVED") == 1 and "no longer eligible" in out
    assert sum(p.exists() for p in (a, b)) == 1


# ---- round 4b (local Codex review of fffecb8e) -------------------------------------------------------------------


@pytest.mark.parametrize("url", ["ssh://alias/x", "alias:work/x"])
def test_ssh_alias_that_cannot_be_resolved_keeps_the_clone(prune, tmp_path, world, url, monkeypatch):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "ssh_real_host", lambda h, *a, **k: None)  # ssh -G failed, timed out or printed no hostname
    g(c, "remote", "add", "al", url)
    why = prune.local_remote_inside_root(c)
    assert why and "cannot be resolved" in why


def test_ssh_real_host_is_none_when_ssh_fails(prune, monkeypatch):
    class R:
        returncode = 255
        stdout = ""

    monkeypatch.setattr(prune.subprocess, "run", lambda *a, **k: R())
    assert prune.ssh_real_host("x") is None

    def boom(*a, **k):
        raise prune.subprocess.TimeoutExpired("ssh", 10)

    monkeypatch.setattr(prune.subprocess, "run", boom)
    assert prune.ssh_real_host("x") is None


def test_remote_host_with_this_machines_lan_address_is_kept(prune, tmp_path, world, monkeypatch):
    c = make_clone(tmp_path, world)
    lan = (socket.AF_INET, ("192.0.2.77", 0))
    monkeypatch.setattr(prune, "ssh_real_host", lambda h, *a, **k: h)
    monkeypatch.setattr(prune, "resolve_addrs", lambda h: [lan])
    monkeypatch.setattr(prune, "is_local_address", lambda fam, sa: sa[0] == "192.0.2.77")
    g(c, "remote", "add", "ts", "ssh://me@tailnet-host/work/x")
    assert prune.local_remote_inside_root(c)


def test_remote_host_that_does_not_resolve_is_kept(prune, tmp_path, world, monkeypatch):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "resolve_addrs", lambda h, *a, **k: None)
    g(c, "remote", "add", "x", "https://nowhere.invalid/o/r.git")
    assert prune.local_remote_inside_root(c)


def test_is_local_address_uses_the_interfaces(prune):
    assert prune.is_local_address(socket.AF_INET, ("127.0.0.1", 0)) is True
    assert prune.is_local_address(socket.AF_INET, ("0.0.0.0", 0)) is True
    assert prune.is_local_address(socket.AF_INET, ("203.0.113.9", 0)) is False  # TEST-NET-3: not an interface


def _age(prune, c, days=10):
    """Make the checkout and its task dir look `days` old (every activity timestamp the script reads)."""
    old = time.time() - days * 86400
    for name in ("index", "HEAD", "logs/HEAD", "FETCH_HEAD"):
        p = prune.git_path(c, name)
        if p is not None and p.exists():
            os.utime(p, (old, old))
    os.utime(c, (old, old))
    os.utime(c.parent, (old, old))


def test_second_checkout_in_a_task_survives_the_age_rule_after_the_first_removal(prune, tmp_path, world, monkeypatch, capsys):
    monkeypatch.setattr(prune, "MIN_AGE", 7 * 86400)
    a = make_clone(tmp_path, world, task="t1", name="a")
    b = make_clone(tmp_path, world, task="t1", name="b")
    _age(prune, a)
    _age(prune, b)
    assert prune.finished_dir(a.parent)
    monkeypatch.setattr(sys, "argv", ["x", "--apply"])
    prune.main()
    out = capsys.readouterr().out
    assert not a.exists() and not b.exists(), out
    assert out.count("REMOVED") == 2


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_unreadable_jobs_dir_keeps_the_task(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    jobs = c.parent / "jobs"
    jobs.mkdir()
    jobs.chmod(0)
    try:
        assert prune.unclaimed_and_jobs_done(c.parent) is False
        assert prune.finished_dir(c.parent) is False
    finally:
        jobs.chmod(0o755)


# ---- round 4c (local Codex review of 7a1d7c33) ---------------------------------------------------------------------


@pytest.mark.parametrize("url,want", [
    ("git@github.com:o/r.git", ["-l", "git", "--", "github.com"]),
    ("ssh://deploy@example.org:2222/o/r.git", ["-l", "deploy", "-p", "2222", "--", "example.org"]),
    ("example.org:o/r.git", ["--", "example.org"]),
])
def test_ssh_lookup_carries_the_remote_user_and_port(prune, tmp_path, world, url, want, monkeypatch):
    seen = []

    class R:
        returncode = 0
        stdout = "hostname example.org\n"

    monkeypatch.setattr(prune.subprocess, "run", lambda cmd, *a, **k: seen.append(cmd) or R())
    monkeypatch.setattr(prune, "resolve_addrs", lambda h: [(socket.AF_INET, ("203.0.113.9", 0))])
    assert prune.classify_url(url) == ("remote", None)
    cmd = seen[0]
    assert cmd[:2] == ["ssh", "-G"]
    assert cmd[2:] == want


def test_user_routed_ssh_host_that_lands_on_this_machine_is_kept(prune, monkeypatch):
    # `Match user git` + `HostName localhost`: the lookup is only external when the user is not passed through
    def fake(host, user=None, port=None):
        return "localhost" if user == "git" else host

    monkeypatch.setattr(prune, "ssh_real_host", fake)
    monkeypatch.setattr(prune, "resolve_addrs", lambda h: [(socket.AF_INET, ("203.0.113.9", 0))])
    assert prune.classify_url("git@github.com:o/r.git") == ("unknown", None)
    assert prune.classify_url("ssh://git@github.com/o/r.git") == ("unknown", None)
    assert prune.classify_url("github.com:o/r.git") == ("remote", None)


def test_claim_created_during_the_safety_scan_stops_the_deletion(prune, tmp_path, world, monkeypatch):
    c = make_clone(tmp_path, world)
    task = c.parent
    baseline = {task: task.stat().st_mtime}
    real_safe = prune.safe

    def safe_then_claim(x):
        res = real_safe(x)
        (task / "CLAIM").write_text("a session just started here\n")
        return res

    monkeypatch.setattr(prune, "safe", safe_then_claim)
    ok, msg = prune.remove(c, task, baseline)
    assert not ok and "no longer eligible" in msg
    assert c.exists()


# ---- round 5 (local Codex review of ffeb2f64) ---------------------------------------------------------------------


def _expire_reflogs(repo):
    g(repo, "reflog", "expire", "--expire=now", "--expire-unreachable=now", "--all")


def _nested_in_tracked_dir(tmp_path, world, bare=False):
    """A clone whose tracked directory `docs` is also a git repository holding unpushed history of its own: every file
    in it is tracked by the outer clone, so the outer `git status` sees nothing."""
    c = make_clone(tmp_path, world)
    (c / "docs").mkdir()
    commit(c, "docs/page.md", "tracked\n")
    g(c, "push", "-q", "origin", "HEAD:main")
    if bare:
        g(tmp_path, "init", "-q", "--bare", str(c / "docs/store.git"))
        g(c, "add", "-f", "docs/store.git")
        g(c, "commit", "-q", "-m", "track the bare repo")
        g(c, "push", "-q", "origin", "HEAD:main")
    else:
        g(c / "docs", "init", "-q", "-b", "main")
        g(c / "docs", "add", "-A")
        g(c / "docs", "commit", "-q", "-m", "unpushed nested work")
    assert g(c, "status", "--porcelain", "--ignored") == ""  # the outer status really cannot see it
    return c


def test_nested_repo_in_a_tracked_directory_keeps_the_clone(prune, tmp_path, world):
    c = _nested_in_tracked_dir(tmp_path, world)
    ok, why = prune.safe(c)
    assert not ok and "nested git repository" in why
    assert rm(prune, c)[0] is False
    assert (c / "docs/.git").exists()


def test_nested_bare_repo_in_a_tracked_directory_keeps_the_clone(prune, tmp_path, world):
    c = _nested_in_tracked_dir(tmp_path, world, bare=True)
    ok, why = prune.safe(c)
    assert not ok and "nested bare repository" in why


def test_nested_repo_checked_for_linked_worktrees_too(prune, tmp_path, world):
    main, wt = make_main_with_worktree(tmp_path, world)
    (wt / "d").mkdir()
    commit(wt, "d/f", "x\n")
    g(wt, "push", "-q", "origin", "HEAD:refs/heads/pushed")
    g(wt, "fetch", "-q", "origin")
    g(wt / "d", "init", "-q")
    assert g(wt, "status", "--porcelain", "--ignored") == ""
    ok, why = prune.safe(wt)
    assert not ok and "nested" in why


def test_orig_head_only_commit_keeps_the_clone(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    lost = commit(c, "lost", "only ORIG_HEAD will remember this\n")
    g(c, "reset", "-q", "--hard", "origin/main")
    _expire_reflogs(c)
    assert g(c, "rev-parse", "ORIG_HEAD") == lost
    assert g(c, "log", "--oneline", "--all", "--not", "--remotes") == ""  # the older checks really pass
    ok, why = prune.safe(c)
    assert not ok and "pseudo-ref" in why
    assert rm(prune, c)[0] is False


def test_fetch_head_only_commit_keeps_the_clone(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    other = tmp_path / "other"
    g(tmp_path, "clone", "-q", str(world), str(other))
    sha = commit(other, "o", "elsewhere\n")
    g(other, "push", "-q", "origin", "HEAD:refs/heads/side")
    g(c, "fetch", "-q", "origin", "side")  # fills FETCH_HEAD, creates no remote-tracking ref for it
    g(c, "update-ref", "-d", "refs/remotes/origin/side")
    assert sha in (c / ".git/FETCH_HEAD").read_text()
    ok, why = prune.safe(c)
    assert not ok and "pseudo-ref" in why


def test_orig_head_only_commit_keeps_the_linked_worktree(prune, tmp_path, world):
    main, wt = make_main_with_worktree(tmp_path, world)
    lost = commit(wt, "lost", "x\n")
    g(wt, "reset", "-q", "--hard", "origin/main")
    _expire_reflogs(wt)
    gd = Path(g(wt, "rev-parse", "--absolute-git-dir"))
    assert (gd / "ORIG_HEAD").read_text().strip() == lost
    ok, why = prune.safe(wt)
    assert not ok and "pseudo-ref" in why
    assert prune.pseudo_ref_commits(gd) == [lost]


def test_orig_head_on_a_remote_does_not_keep_a_clean_clone(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    g(c, "reset", "-q", "--hard", "origin/main")
    commit_sha = g(c, "rev-parse", "HEAD")
    (c / ".git/ORIG_HEAD").write_text(commit_sha + "\n")
    ok, why = prune.safe(c)
    assert ok, why


# ---- round 6 (local Codex review of 10beb8da) ---------------------------------------------------------------------


def test_linked_worktree_commit_surviving_only_as_an_old_reflog_id_is_kept(prune, tmp_path, world):
    main, wt = make_main_with_worktree(tmp_path, world)
    x = commit(wt, "x", "detached work\n")
    g(wt, "checkout", "-q", "--detach", "origin/main")
    log = prune.git_path(wt, "logs/HEAD")
    lines = log.read_text().splitlines()
    log.write_text(lines[-1] + "\n")  # partial expiry: only the entry whose OLD id is x remains
    assert lines[-1].split()[0] == x and lines[-1].split()[1] != x
    assert x not in g(wt, "log", "-g", "--format=%H", "HEAD")  # the new-id-only walk of before cannot see it
    ok, why = prune.safe(wt)
    assert not ok and "reflog" in why
    assert prune.remove(wt, wt.parent, {wt.parent: wt.parent.stat().st_mtime})[0] is False


def test_unreadable_worktree_reflog_keeps_it(prune, tmp_path, world, monkeypatch):
    main, wt = make_main_with_worktree(tmp_path, world)
    monkeypatch.setattr(prune, "reflog_ids", lambda c: None)
    ok, why = prune.safe(wt)
    assert not ok and "reflog unreadable" in why


def test_core_ssh_command_override_keeps_an_ssh_remote(prune, tmp_path, world, monkeypatch):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "ssh_real_host", lambda h, *a, **k: "external.example")
    monkeypatch.setattr(prune, "resolve_addrs", lambda h: [(socket.AF_INET, ("203.0.113.9", 0))])
    g(c, "remote", "add", "o", "git@external.example:o/r.git")
    assert prune.local_remote_inside_root(c) is None  # without an override it is external
    g(c, "config", "core.sshCommand", "ssh -oHostName=localhost")
    why = prune.local_remote_inside_root(c)
    assert why and "cannot be resolved" in why


@pytest.mark.parametrize("var", ["GIT_SSH", "GIT_SSH_COMMAND"])
def test_git_ssh_env_override_keeps_an_ssh_remote(prune, tmp_path, world, monkeypatch, var):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "ssh_real_host", lambda h, *a, **k: "external.example")
    monkeypatch.setattr(prune, "resolve_addrs", lambda h: [(socket.AF_INET, ("203.0.113.9", 0))])
    g(c, "remote", "add", "o", "ssh://external.example/o/r.git")
    monkeypatch.setenv(var, "/usr/bin/ssh")
    assert prune.local_remote_inside_root(c)


def test_https_remote_is_not_affected_by_the_ssh_override(prune, tmp_path, world, monkeypatch):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "resolve_addrs", lambda h: [(socket.AF_INET, ("203.0.113.9", 0))])
    g(c, "remote", "add", "o", "https://external.example/o/r.git")
    g(c, "config", "core.sshCommand", "ssh -oHostName=localhost")
    assert prune.local_remote_inside_root(c) is None


@pytest.mark.parametrize("directive", ["proxycommand nc localhost 22", "proxyjump jump.example"])
def test_ssh_proxy_routing_is_not_resolvable(prune, monkeypatch, directive):
    class R:
        returncode = 0
        stdout = f"hostname external.example\n{directive}\n"

    monkeypatch.setattr(prune.subprocess, "run", lambda *a, **k: R())
    assert prune.ssh_real_host("x") is None

    class R2:
        returncode = 0
        stdout = "hostname external.example\nproxyjump none\n"

    monkeypatch.setattr(prune.subprocess, "run", lambda *a, **k: R2())
    assert prune.ssh_real_host("x") == "external.example"


@pytest.mark.parametrize("url", [
    "https://alice:s3cr3t-token@nowhere.invalid/o/r.git?token=s3cr3t-token",
    "ext::sh -c s3cr3t-token",
    "alice:s3cr3t-token@weird/host",
    "https::https://alice:s3cr3t-token@nowhere.invalid/o/r.git",
    "https://nowhere.invalid/s3cr3t-token/r.git",
])
def test_kept_reason_never_carries_credentials(prune, tmp_path, world, url, monkeypatch, capsys):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "resolve_addrs", lambda h: None)
    g(c, "remote", "add", "cred", url)
    why = prune.local_remote_inside_root(c)
    assert why and "cred" in why
    ok, reason = prune.safe(c)
    assert not ok
    assert "s3cr3t-token" not in why and "s3cr3t-token" not in reason


def test_redact_drops_userinfo_query_and_scp_user(prune):
    assert prune.redact("https://u:p@host.example:8443/a/b.git?x=1#f") == "https://host.example:8443/(path hidden)"
    assert prune.redact("https::https://u:TOKEN@h/r.git") == "https::(arguments hidden)"
    assert prune.redact("https://[::1]/x") == "https://[::1]/(path hidden)"
    assert prune.redact("file:///a/%62t/b") == "file:///a/%62t/b"
    assert prune.redact("git@github.com:o/r.git") == "github.com:o/r.git"
    assert prune.redact("/plain/path") == "/plain/path"
    assert prune.redact("ext::sh -c tok") == "ext::(arguments hidden)"


# ---- round 8 (local Codex review of 544e81f3) ---------------------------------------------------------------------


def _blob_tag(c, name="report-tag", tree=False):
    f = c / ".git" / "scratch-report"
    f.write_text("the only copy of this report\n")
    obj = g(c, "hash-object", "-w", str(f))
    f.unlink()
    if tree:
        obj = subprocess.run(["git", "mktree"], cwd=c, input=f"100644 blob {obj}\tr.md\n", capture_output=True,
                             text=True, env=_env(), check=True).stdout.strip()
    g(c, "tag", name, obj)
    return obj


@pytest.mark.parametrize("tree", [False, True])
def test_ref_to_a_blob_or_tree_keeps_the_clone(prune, tmp_path, world, tree):
    c = make_clone(tmp_path, world)
    _blob_tag(c, tree=tree)
    assert g(c, "log", "--oneline", "--all", "--not", "--remotes") == ""  # the commit traversals cannot see it
    assert g(c, "rev-list", "--reflog", "--not", "--remotes") == ""
    ok, why = prune.safe(c)
    assert not ok and "not a commit" in why
    assert rm(prune, c)[0] is False


def test_annotated_tag_of_a_pushed_commit_does_not_keep_a_clean_clone(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    g(c, "tag", "-a", "-m", "release", "v1", "origin/main")
    ok, why = prune.safe(c)
    assert ok, why


def test_tag_of_a_tag_on_an_unpushed_commit_keeps_the_clone(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit(c, "new", "unpushed\n")
    g(c, "tag", "-a", "-m", "one", "t1", "HEAD")
    g(c, "tag", "-a", "-m", "two", "t2", "t1")
    g(c, "reset", "-q", "--hard", "origin/main")
    ok, why = prune.safe(c)
    assert not ok and "not on a remote" in why


@pytest.mark.parametrize("key,val", [
    ("http.curloptResolve", "example.org:8080:127.0.0.1"),
    ("http.https://example.org/.curloptResolve", "example.org:443:127.0.0.1"),
    ("http.proxy", "http://127.0.0.1:3128"),
    ("remote.web.proxy", "http://127.0.0.1:3128"),
    ("core.gitProxy", "nc"),
])
def test_http_address_or_proxy_override_keeps_a_network_remote(prune, tmp_path, world, monkeypatch, key, val):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "resolve_addrs", lambda h: [(socket.AF_INET, ("203.0.113.9", 0))])
    g(c, "remote", "add", "web", "https://example.org:8080/o/r.git")
    assert prune.local_remote_inside_root(c) is None  # external without the override
    g(c, "config", key, val)
    why = prune.local_remote_inside_root(c)
    assert why and "cannot be resolved" in why


@pytest.mark.parametrize("var", ["HTTPS_PROXY", "https_proxy", "ALL_PROXY", "GIT_PROXY_COMMAND"])
def test_proxy_environment_keeps_a_network_remote(prune, tmp_path, world, monkeypatch, var):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "resolve_addrs", lambda h: [(socket.AF_INET, ("203.0.113.9", 0))])
    g(c, "remote", "add", "web", "https://example.org/o/r.git")
    monkeypatch.setenv(var, "http://127.0.0.1:3128")
    assert prune.local_remote_inside_root(c)


def test_unrelated_http_config_does_not_keep_a_network_remote(prune, tmp_path, world, monkeypatch):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "resolve_addrs", lambda h: [(socket.AF_INET, ("203.0.113.9", 0))])
    g(c, "remote", "add", "web", "https://example.org/o/r.git")
    g(c, "config", "http.postBuffer", "524288000")
    assert prune.local_remote_inside_root(c) is None


def test_file_url_authority_never_reaches_a_kept_reason(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    url = "file://alice:s3cr3t-token@somehost/repo"
    assert "s3cr3t-token" not in prune.redact(url) and "alice" not in prune.redact(url)
    g(c, "remote", "add", "fx", url)
    why = prune.local_remote_inside_root(c)
    assert why and "cannot be resolved" in why and "s3cr3t-token" not in why
    ok, reason = prune.safe(c)
    assert not ok and "s3cr3t-token" not in reason


# ---- round 9 (local Codex review of d832fcb9) ---------------------------------------------------------------------


@pytest.mark.parametrize("rec,done", [
    ({"finished": 1.0, "status": "done"}, True),
    ({"finished": 1.0, "status": "partial", "auto_resume": None}, True),
    ({"finished": 1.0, "status": "no-report", "auto_resume": {"state": "exhausted"}}, True),
    ({"finished": 1.0, "status": "resume-scheduled"}, False),
    ({"finished": 1.0, "status": "running"}, False),
    ({"finished": 1.0, "status": "blocked"}, False),
    ({"finished": 1.0, "status": "partial", "auto_resume": {"state": "scheduled"}}, False),
    ({"finished": 1.0, "status": "partial", "auto_resume": {"state": "waiting-headroom"}}, False),
    ({"finished": 1.0, "status": "partial", "auto_resume": {"state": "resuming"}}, False),
    ({"finished": 1.0, "status": "done", "restart_resume": {"state": "resuming"}}, False),
    ({"finished": 1.0, "status": "done", "auto_resume": {"attempt": 1}}, False),
    ({"finished": 1.0, "status": "done", "auto_resume": "scheduled"}, False),
    ({"status": "done"}, False),
    ({"finished": None, "status": "done"}, False),
    (["not", "a", "dict"], False),
])
def test_job_record_done_requires_no_pending_resume(prune, rec, done):
    assert prune.job_record_done(rec) is done


def test_task_with_a_quota_stopped_job_awaiting_resume_is_kept(prune, tmp_path, world):
    import json as _json
    c = make_clone(tmp_path, world)
    (c.parent / "jobs").mkdir()
    (c.parent / "jobs/ok.json").write_text(_json.dumps({"finished": 1.0, "status": "done"}))
    assert prune.finished_dir(c.parent)
    (c.parent / "jobs/resume.json").write_text(_json.dumps(
        {"finished": 1.0, "status": "resume-scheduled", "auto_resume": {"state": "scheduled", "attempt": 1}}))
    assert not prune.finished_dir(c.parent)
    task = c.parent
    ok, msg = prune.remove(c, task, {task: task.stat().st_mtime})
    assert not ok and "no longer eligible" in msg and c.exists()


# ---- round 10 (local Codex review of 9dc5c423) --------------------------------------------------------------------


def _fetch_blob_into_fetch_head(tmp_path, c, tree=False):
    """FETCH_HEAD becomes the only reference to a blob (or tree), the temporary source repository being removed."""
    src = tmp_path / "tmp-src"
    g(tmp_path, "init", "-q", "-b", "main", str(src))
    (src / "r.md").write_text("the only copy of this report\n")
    obj = g(src, "hash-object", "-w", "r.md")
    if tree:
        obj = subprocess.run(["git", "mktree"], cwd=src, input=f"100644 blob {obj}\tr.md\n", capture_output=True,
                             text=True, env=_env(), check=True).stdout.strip()
    g(src, "tag", "report", obj)
    g(c, "fetch", "-q", "--no-tags", str(src), "refs/tags/report")
    shutil.rmtree(src)
    assert g(c, "rev-parse", "FETCH_HEAD") == obj
    return obj


@pytest.mark.parametrize("tree", [False, True])
def test_fetch_head_naming_only_a_blob_or_tree_keeps_the_clone(prune, tmp_path, world, tree):
    c = make_clone(tmp_path, world)
    _fetch_blob_into_fetch_head(tmp_path, c, tree)
    assert g(c, "for-each-ref") .count("refs/") >= 1  # ordinary refs are all commits
    assert g(c, "rev-list", "--reflog", "--not", "--remotes") == ""
    ok, why = prune.safe(c)
    assert not ok and "not a commit" in why
    assert rm(prune, c)[0] is False


def test_orig_head_naming_a_missing_object_keeps_the_clone(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    (c / ".git/ORIG_HEAD").write_text("1" * 40 + "\n")
    ok, why = prune.safe(c)
    assert not ok


def test_non_commit_ids_peels_tags_and_flags_the_rest(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit_id = g(c, "rev-parse", "origin/main")
    g(c, "tag", "-a", "-m", "x", "ann", commit_id)
    tag_obj = g(c, "rev-parse", "ann")
    blob = g(c, "rev-parse", "origin/main:README")
    assert prune.non_commit_ids(c, [commit_id, tag_obj]) == []
    assert prune.non_commit_ids(c, [commit_id, blob, "2" * 40]) == [blob, "2" * 40]
    assert prune.non_commit_ids(c, []) == []


def test_linked_worktree_reflog_naming_a_blob_keeps_it(prune, tmp_path, world):
    main, wt = make_main_with_worktree(tmp_path, world)
    blob = g(wt, "rev-parse", "origin/main:README")
    log = prune.git_path(wt, "logs/HEAD")
    first = log.read_text().splitlines()[0].split()
    log.write_text(f"{first[1]} {blob} t <t@t> 1700000000 +0000\tmanual: blob\n")
    ok, why = prune.safe(wt)
    assert not ok and "not a commit" in why


# ---- round 11 (local Codex review of 2c699f44) --------------------------------------------------------------------


def test_blob_held_only_by_a_tag_reflog_keeps_the_clone(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    f = c / "scratch-report"
    f.write_text("the only copy of this report\n")
    blob = g(c, "hash-object", "-w", str(f))
    f.unlink()
    g(c, "update-ref", "--create-reflog", "refs/tags/report", blob)
    g(c, "update-ref", "refs/tags/report", g(c, "rev-parse", "origin/main"))  # the tag moves; the blob stays in its reflog
    assert g(c, "for-each-ref", "--format=%(objecttype)", "refs/tags/report") == "commit"
    assert g(c, "log", "--oneline", "--all", "--not", "--remotes") == ""
    assert g(c, "rev-list", "--reflog", "--not", "--remotes") == ""  # the older checks cannot see it
    ok, why = prune.safe(c)
    assert not ok and "reflog" in why
    assert rm(prune, c)[0] is False


def test_reflog_ids_every_ref_reads_both_sides_and_all_files(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    ids = prune.reflog_ids(c, every_ref=True)
    assert ids and all(len(i) == 40 for i in ids)
    assert g(c, "rev-parse", "origin/main") in ids


@pytest.mark.parametrize("key", ["vcs", "uploadpack", "receivepack"])
def test_remote_with_a_custom_helper_keeps_the_clone(prune, tmp_path, world, key):
    c = make_clone(tmp_path, world)
    g(c, "remote", "add", "web", "https://example.org/o/r.git")
    monkey_ok = prune.remote_with_helper(c)
    assert monkey_ok is None
    g(c, "config", f"remote.web.{key}", "sibling" if key == "vcs" else "/usr/bin/env")
    assert prune.remote_with_helper(c) == "web"
    why = prune.local_remote_inside_root(c)
    assert why and "cannot be resolved" in why and "web" in why
    ok, reason = prune.safe(c)
    assert not ok


def test_unrelated_remote_config_is_not_a_helper(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    g(c, "config", "remote.origin.tagopt", "--no-tags")
    g(c, "config", "remote.origin.prune", "true")
    assert prune.remote_with_helper(c) is None


# ---- round 12 (GitHub Codex thread + local review of 2ccc596c) ---------------------------------------------------


def test_sizes_are_measured_for_removal_candidates_only(prune, tmp_path, world, monkeypatch, capsys):
    a = make_clone(tmp_path, world, task="t1", name="a")
    b = make_clone(tmp_path, world, task="t1", name="b")
    (b / "wip.txt").write_text("uncommitted\n")  # b is kept
    seen = []
    monkeypatch.setattr(prune, "size_kb", lambda c: seen.append(c) or 2048)
    monkeypatch.setattr(sys, "argv", ["x"])
    prune.main()
    out = capsys.readouterr().out
    assert seen == [a]
    assert "PLAN" in out and "KEEP" in out and "would free: 0.00 GB; kept 1" in out


def test_size_kb_uses_dust_not_du_and_parses_bytes(prune, tmp_path, monkeypatch):
    calls = []

    class R:
        returncode = 0
        stdout = ' \n{"size":"3145728B","name":"x","children":[]}\n'

    monkeypatch.setattr(prune.subprocess, "run", lambda cmd, *a, **k: calls.append((cmd, k)) or R())
    assert prune.size_kb(tmp_path) == 3072
    cmd, kw = calls[0]
    assert cmd[:3] == ["nice", "-n", "19"] and "dust" in cmd and "du" not in cmd
    assert kw["timeout"] <= 120


@pytest.mark.parametrize("failure", ["rc", "garbage", "missing", "timeout"])
def test_size_kb_failures_are_zero_not_errors(prune, tmp_path, monkeypatch, failure):
    class R:
        returncode = 1 if failure == "rc" else 0
        stdout = "not json" if failure == "garbage" else "{}"

    def run(*a, **k):
        if failure == "missing":
            raise FileNotFoundError("dust")
        if failure == "timeout":
            raise prune.subprocess.TimeoutExpired("dust", 120)
        return R()

    monkeypatch.setattr(prune.subprocess, "run", run)
    assert prune.size_kb(tmp_path) == 0


def test_size_kb_real_dust_if_installed(prune, tmp_path):
    if shutil.which("dust") is None:
        pytest.skip("dust not installed")
    (tmp_path / "f").write_bytes(b"x" * 200_000)
    assert prune.size_kb(tmp_path) >= 100
