"""Guards for .github/workflows/sync-tracked-issues.yml."""

import pathlib
import re
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/sync-tracked-issues.yml"

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
