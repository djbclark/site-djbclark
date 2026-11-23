"""Guards for Sync tracked issues and .github/tracked-issues.json."""

import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/sync-tracked-issues.yml"
TRACK_WORKFLOW = ROOT / ".github/workflows/track-issue-activity.yml"
TRACKED = ROOT / ".github/tracked-issues.json"
SCRIPT = ROOT / ".github/scripts/sync_tracked_issues.py"

sys.path.insert(0, str(SCRIPT.parent))
import sync_tracked_issues as sti  # noqa: E402

# The Create pull request step used to run:
#   git commit -m "ci: auto-add ..." --file /tmp/pr-body.txt
# Git 2.55+ (GitHub-hosted runners; also this box's 2.47.3) rejects that
# combination: fatal: options '-m' and '-F' cannot be used together (exit 128).
COMMIT_LINE_RE = re.compile(r"^\s*git commit\b.*$", re.MULTILINE)
HAS_M_RE = re.compile(r"(?:^|\s)-m(?:\s|$)")
HAS_F_RE = re.compile(r"(?:^|\s)(?:-F|--file)(?:\s|$)")


def test_workflow_git_commit_does_not_combine_message_and_file():
    text = WORKFLOW.read_text()
    lines = COMMIT_LINE_RE.findall(text)
    assert lines, "expected a git commit invocation in the workflow"
    for line in lines:
        has_m = HAS_M_RE.search(line) is not None
        has_f = HAS_F_RE.search(line) is not None
        assert not (has_m and has_f), (
            "git 2.55+ rejects -m together with -F/--file; use -F only "
            f"(with subject and body in the file): {line.strip()}"
        )
        assert has_m or has_f, f"git commit has no message source: {line.strip()}"


def test_git_rejects_message_and_file_together():
    """Pin the runner failure so a future git that allows both is noticed."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        (repo / "f").write_text("x\n")
        subprocess.run(["git", "add", "f"], cwd=repo, check=True)
        (repo / "msg").write_text("body\n")
        result = subprocess.run(
            [
                "git",
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-m",
                "subject",
                "--file",
                str(repo / "msg"),
            ],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 128, result.stderr
        assert "cannot be used together" in result.stderr


def test_commit_dash_f_keeps_subject_and_body():
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        (repo / "f").write_text("x\n")
        subprocess.run(["git", "add", "f"], cwd=repo, check=True)
        (repo / "commit-msg.txt").write_text(
            "ci: auto-add 2 new tracked issue(s)\n\n"
            "## New third-party issues detected\n\n"
            "Auto-added tracking for:\n"
            "- [owner/repo#1](https://example.com) - title\n"
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-F",
                str(repo / "commit-msg.txt"),
            ],
            cwd=repo,
            check=True,
        )
        message = subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert message.startswith("ci: auto-add 2 new tracked issue(s)\n")
        assert "owner/repo#1" in message
        assert "title" in message


def test_sync_job_does_not_modify_workflow_files():
    """GITHUB_TOKEN cannot push updates to .github/workflows/*."""
    text = WORKFLOW.read_text()
    assert "git add .github/tracked-issues.json" in text
    assert "git add .github/workflows/" not in text
    assert "track-issue-activity.yml" not in text.split("Create pull request", 1)[-1]
    # The update step must edit the data file, not a workflow.
    assert "sync_tracked_issues.py update" in text
    assert "open('.github/workflows/track-issue-activity.yml', 'w')" not in text


def test_track_workflow_loads_json_matrix():
    text = TRACK_WORKFLOW.read_text()
    assert ".github/tracked-issues.json" in text
    assert "fromJson(needs.load-matrix.outputs.issue)" in text
    assert "- repo: AltanS/collie" not in text


def test_tracked_issues_json_is_valid():
    issues = json.loads(TRACKED.read_text())["issue"]
    assert issues
    slugs = [i["slug"] for i in issues]
    assert len(slugs) == len(set(slugs))
    for item in issues:
        assert item["repo"] and "/" in item["repo"]
        assert str(item["number"]).isdigit()
        assert item["slug"]
        if "type" in item:
            assert item["type"] == "discussion"


def test_compare_and_update_append_only_new_entries(tmp_path):
    tracked = tmp_path / "tracked.json"
    sti.write_tracked(
        tracked,
        [{"repo": "acme/foo", "number": "1", "slug": "acme-foo-1"}],
    )
    discovered = tmp_path / "discovered.txt"
    discovered.write_text(
        "acme/foo|||1|||already|||open|||https://example.com/1\n"
        "acme/bar|||9|||new one|||open|||https://example.com/9\n"
    )
    new_path = tmp_path / "new.json"
    assert sti.main(
        [
            "compare",
            "--tracked",
            str(tracked),
            "--discovered",
            str(discovered),
            "--new",
            str(new_path),
        ]
    ) == 0
    new_issues = json.loads(new_path.read_text())
    assert [i["repo"] + "#" + i["number"] for i in new_issues] == ["acme/bar#9"]
    assert sti.main(["update", "--tracked", str(tracked), "--new", str(new_path)]) == 0
    issues = json.loads(tracked.read_text())["issue"]
    assert [i["slug"] for i in issues] == ["acme-foo-1", "acme-bar-9"]
    # Idempotent if compare/update run again.
    assert sti.main(
        [
            "compare",
            "--tracked",
            str(tracked),
            "--discovered",
            str(discovered),
            "--new",
            str(new_path),
        ]
    ) == 0
    assert json.loads(new_path.read_text()) == []


def test_owned_owners_include_user_and_orgs_from_user_orgs():
    assert "djbclark" in sti.OWNED_OWNERS
    for org in (
        "bcfg2",
        "maynard-daycare",
        "djbcsipb",
        "frdminc",
        "pikans",
        "pkb-rocks",
    ):
        assert org in sti.OWNED_OWNERS
    # Qualifiers use -user for the login and -org for each org, not a repo list.
    qualifiers = sti.search_qualifiers()
    assert "-user:djbclark" in qualifiers
    assert "-org:frdminc" in qualifiers
    assert "-org:pkb-rocks" in qualifiers
    assert "-org:Bcfg2" in qualifiers
    assert "-org:Maynard-Daycare" in qualifiers
    assert "-org:djbcsipb" in qualifiers
    assert "-org:pikans" in qualifiers
    assert all(q.startswith("-user:") or q.startswith("-org:") for q in qualifiers)
    assert not any("/" in q for q in qualifiers)


def test_is_excluded_repo_is_owner_level_and_keeps_explicit_list():
    for nwo in (
        "djbclark/upstream-releases",
        "DJBClark/site-djbclark",
        "frdminc/tendcf",
        "pkb-rocks/plektra",
        "djbcsipb/libkrun-sipb",
        "pikans/something",
        "Bcfg2/core",
        "Maynard-Daycare/handbook",
        "djbclark/stayturgid",
        "djbclark/site-private",
    ):
        assert sti.is_excluded_repo(nwo), nwo
    for nwo in (
        "getpaseo/paseo",
        "omercnet/paseo-plugins",
        "libkrun/libkrun",
        "cachix/secretspec",
        "trailhq/Trail-Code",
    ):
        assert not sti.is_excluded_repo(nwo), nwo


def test_discover_filters_own_owners_and_keeps_third_party(tmp_path):
    raw = tmp_path / "raw.json"
    raw.write_text(
        json.dumps(
            [
                {"repository": {"nameWithOwner": "djbclark/upstream-releases"}, "number": 111, "title": "own user", "state": "open", "url": "https://example.com/111"},
                {"repository": {"nameWithOwner": "frdminc/tendcf"}, "number": 99, "title": "own org", "state": "open", "url": "https://example.com/99"},
                {"repository": {"nameWithOwner": "djbclark/site-private"}, "number": 1, "title": "explicit", "state": "open", "url": "https://example.com/1"},
                {"repository": {"nameWithOwner": "getpaseo/paseo"}, "number": 10543, "title": "third party", "state": "open", "url": "https://github.com/getpaseo/paseo/issues/10543"},
                {"repository": {"nameWithOwner": "omercnet/paseo-plugins"}, "number": 673, "title": "also third", "state": "open", "url": "https://github.com/omercnet/paseo-plugins/issues/673"},
            ]
        )
    )
    discovered = tmp_path / "discovered.txt"
    discovered_json = tmp_path / "discovered.json"
    assert (
        sti.main(
            [
                "discover",
                "--raw",
                str(raw),
                "--discovered",
                str(discovered),
                "--discovered-json",
                str(discovered_json),
            ]
        )
        == 0
    )
    kept = json.loads(discovered_json.read_text())
    assert [sti.raw_item_repo(i) + "#" + str(i["number"]) for i in kept] == [
        "getpaseo/paseo#10543",
        "omercnet/paseo-plugins#673",
    ]
    text = discovered.read_text()
    assert "getpaseo/paseo|||10543|||" in text
    assert "djbclark/" not in text
    assert "frdminc/" not in text


def test_workflow_uses_owner_qualifiers_and_discover_script():
    text = WORKFLOW.read_text()
    assert "sync_tracked_issues.py search-qualifiers" in text
    assert "sync_tracked_issues.py discover" in text
    assert "OWNED = ['djbclark/stayturgid'" not in text
    assert "djbclark/stayturgid" in sti.EXCLUDED_REPOS
    assert "djbclark/site-djbclark" in sti.EXCLUDED_REPOS
    assert "djbclark/site-private" in sti.EXCLUDED_REPOS
