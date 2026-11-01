"""Tests for .github/scripts/tendcf-consent/consent.py (the tendcf consent gate)."""

import importlib.util
import json
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "consent", ROOT / ".github/scripts/tendcf-consent/consent.py"
)
consent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(consent)


def run(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo, files, msg="c"):
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    run(repo, "add", "-A")
    run(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)
    return run(repo, "rev-parse", "HEAD")


def lock(**nodes):
    return json.dumps(
        {
            "nodes": {
                "root": {"inputs": {k: k for k in nodes}},
                **{
                    k: {
                        "locked": {
                            "type": "github",
                            "owner": "NixOS" if k == "nixpkgs" else "o",
                            "repo": k,
                            "rev": rev,
                            "narHash": "sha256-" + rev,
                        }
                    }
                    for k, rev in nodes.items()
                },
            },
            "root": "root",
        }
    )


@pytest.fixture
def repo(tmp_path):
    run(tmp_path, "init", "-q", "-b", "master")
    commit(
        tmp_path,
        {
            "nixos/flake.nix": "{ }\n",
            "nixos/flake.lock": lock(nixpkgs="a1", other="b1"),
            "nixos/vps-primary/configuration.nix": "{ }\n",
            "nixos/modules/cfengine-tendcf.nix": "{ }\n",
            "README.md": "x\n",
        },
        "base",
    )
    return tmp_path


def touched(repo, mode, files):
    base = run(repo, "rev-parse", "HEAD")
    head = commit(repo, files)
    return consent.touches(str(repo), base, head, mode)


def test_unrelated_change_does_not_touch(repo):
    assert (
        touched(
            repo,
            "pr",
            {"README.md": "y\n", "nixos/vps-primary/configuration.nix": "{ a = 1; }\n"},
        )
        == []
    )


@pytest.mark.parametrize(
    "path",
    [
        "nixos/modules/cfengine-tendcf.nix",
        "nixos/pkgs/cfengine-tendcf.nix",
        ".github/workflows/nixos-cfengine-build.yml",
        ".github/workflows/tendcf-consent.yml",
        ".github/scripts/tendcf-consent/run.sh",
    ],
)
def test_tendcf_files_touch(repo, path):
    assert touched(repo, "push", {path: "changed\n"})


def test_host_line_setting_the_option_touches(repo):
    r = touched(
        repo,
        "push",
        {
            "nixos/vps-primary/configuration.nix": "{ services.cfengine-tendcf.enable = true; }\n"
        },
    )
    assert r and "configuration.nix" in r[0]


def test_lock_counts_in_pr_only(repo):
    new = {"nixos/flake.lock": lock(nixpkgs="a2", other="b1")}
    assert touched(repo, "pr", new)
    assert (
        touched(repo, "push", {"nixos/flake.lock": lock(nixpkgs="a3", other="b1")})
        == []
    )


def test_flake_nix_counts_in_pr_but_only_by_line_in_push(repo):
    assert touched(repo, "pr", {"nixos/flake.nix": "{ a = 1; }\n"})
    assert touched(repo, "push", {"nixos/flake.nix": "{ a = 2; }\n"}) == []
    assert touched(
        repo, "push", {"nixos/flake.nix": "{ m = ./modules/cfengine-tendcf.nix; }\n"}
    )


def test_authority_reduces_lock_and_diffs_moved_input(repo):
    base = run(repo, "rev-parse", "HEAD")
    head = commit(
        repo,
        {
            "nixos/flake.lock": lock(nixpkgs="a2", other="b2", fresh="c1"),
            "nixos/vps-primary/configuration.nix": "{ a = 1; }\n",
        },
    )
    calls = []

    def fake_fetch(url, old, new, token):
        calls.append((url, old, new))
        return " f | 1 +\n", "diff --git a/f b/f\n+x\n"

    text, summary, complete = consent.build_authority(
        str(repo), base, head, fetch=fake_fetch
    )
    assert complete
    assert calls == [
        ("https://github.com/o/other.git", "b1", "b2")
    ]  # nixpkgs is not diffed
    assert "| other | moved | github | b1 -> b2 | sha256-b1 -> sha256-b2 |" in text
    assert "| fresh | added |" in text
    assert "nixpkgs is not diffed" in text
    assert "+x" in text and "configuration.nix" in text
    assert "lock moved: fresh, nixpkgs, other" in summary


def test_authority_is_incomplete_when_a_fetch_fails(repo):
    base = run(repo, "rev-parse", "HEAD")
    head = commit(repo, {"nixos/flake.lock": lock(nixpkgs="a1", other="b2")})

    def broken(url, old, new, token):
        raise RuntimeError("no route")

    text, _, complete = consent.build_authority(str(repo), base, head, fetch=broken)
    assert not complete and "AUTHORITY INCOMPLETE" in text


def test_artifact_orders_blocks_and_ends_with_question(tmp_path):
    (tmp_path / "authority.md").write_text("auth body\n")
    (tmp_path / "authority.md.summary").write_text("1 file changed\n")
    (tmp_path / "summary-base.json").write_text(
        '{"enable":false,"execd":{"enable":false},"package":"/p1","version":"1"}\n'
    )
    (tmp_path / "summary-head.json").write_text(
        '{"enable":false,"execd":{"enable":false},"package":"/p2","version":"1"}\n'
    )
    (tmp_path / "checks.txt").write_text("check 1: PASS\ncheck 2: PASS\n")
    (tmp_path / "effect.txt").write_text("hello: 1 -> 2\n")
    text, ok = consent.build_artifact(str(tmp_path), "vps-primary", "a" * 40, "b" * 40)
    assert ok
    assert (
        text.index("## AUTHORITY")
        < text.index("## SUMMARY")
        < text.index("## EFFECT")
        < text.index("## Question")
    )
    assert text.rstrip().endswith("Approve?")
    assert '-  "package": "/p1"' in text and '+  "package": "/p2"' in text


def test_artifact_flags_failed_check(tmp_path):
    (tmp_path / "checks.txt").write_text("check 1: FAIL x\n")
    text, ok = consent.build_artifact(str(tmp_path), "vps-primary", "a" * 40, "b" * 40)
    assert not ok and "do not approve" in text


def test_push_check_flags_direct_commit_and_passes_pr_commit(repo):
    before = run(repo, "rev-parse", "HEAD")
    direct = commit(repo, {"nixos/pkgs/cfengine-tendcf.nix": "{ 1 }\n"}, "direct")
    via_pr = commit(repo, {"nixos/pkgs/cfengine-tendcf.nix": "{ 2 }\n"}, "via pr")
    other = commit(repo, {"README.md": "z\n"}, "doc")
    slugs = {via_pr: ["https://github.com/o/r/pull/9"]}
    commits, offenders = consent.push_offenders(
        str(repo), "o/r", before, other, find_prs=lambda slug, sha: slugs.get(sha, [])
    )
    assert commits == [direct, via_pr, other]
    assert [c for c, _ in offenders] == [direct]


def test_merged_prs_ignores_unmerged_and_retries():
    answers = iter(
        [
            json.dumps([{"html_url": "u1", "merged_at": None}]),
            json.dumps([{"html_url": "u2", "merged_at": "2026-10-31T00:00:00Z"}]),
        ]
    )

    def fake_run(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, stdout=next(answers), stderr="")

    sleeps = []
    assert consent.merged_prs("o/r", "abc", run=fake_run, sleep=sleeps.append) == ["u2"]
    assert sleeps == [10]
