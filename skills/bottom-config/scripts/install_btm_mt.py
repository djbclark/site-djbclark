#!/usr/bin/env python3
"""Install the CI-built macOS arm64 btm-mt for the current head of the fork branch.

    install_btm_mt.py [--dest ~/.local/bin/btm-mt]

Never builds anything. It asks GitHub for the head commit of djbclark/bottom's
`middle-truncate-command` branch, finds the successful `fork build` run that
*a push* made for exactly that commit (a PR run could come from anyone, so it is
never used), downloads that run's `btm-macos-arm64` artifact into a fresh private
directory, checks the binary starts, and replaces the destination atomically.
Any failed step stops it; nothing is installed on error.
"""

import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = "djbclark/bottom"
BRANCH = "middle-truncate-command"
WORKFLOW = "fork-build.yml"
ARTIFACT = "btm-macos-arm64"


def run(*cmd: str, **kw) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)
    if done.returncode != 0:
        sys.exit(f"failed: {' '.join(cmd[:3])}...: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, default=Path.home() / ".local/bin/btm-mt")
    args = parser.parse_args()

    sha = run("gh", "api", f"repos/{REPO}/branches/{BRANCH}", "-q", ".commit.sha").strip()
    if len(sha) != 40:
        sys.exit(f"unexpected branch head: {sha!r}")
    runs = json.loads(
        run(
            "gh", "run", "list", "-R", REPO, "--workflow", WORKFLOW, "--event", "push",
            "--branch", BRANCH, "--commit", sha, "--status", "success", "--limit", "1",
            "--json", "databaseId",
        )
    )
    if not runs:
        sys.exit(f"no successful push run of {WORKFLOW} for {sha}; wait for CI or push first")
    run_id = str(runs[0]["databaseId"])

    with tempfile.TemporaryDirectory() as tmp:
        run("gh", "run", "download", run_id, "-R", REPO, "-n", ARTIFACT, "-D", tmp)
        tar_path = Path(tmp) / f"{ARTIFACT}.tar.gz"
        with tarfile.open(tar_path) as tar:
            tar.extract("btm", tmp, filter="data")
        binary = Path(tmp) / "btm"
        run("xattr", "-c", str(binary))
        binary.chmod(0o755)
        try:
            version = run(str(binary), "--version", timeout=30).strip()
        except subprocess.TimeoutExpired:
            sys.exit("the downloaded binary did not answer --version within 30 s; nothing installed")

        with tempfile.NamedTemporaryFile(
            dir=args.dest.parent, prefix=f".{args.dest.name}.", delete=False
        ) as staged:
            staged_path = Path(staged.name)
            try:
                staged.write(binary.read_bytes())
                staged.flush()
                staged_path.chmod(0o755)
                os.replace(staged_path, args.dest)
            except BaseException:
                staged_path.unlink(missing_ok=True)
                raise
    print(f"installed {args.dest}: {version}, commit {sha}, run {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
