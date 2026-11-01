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


def rev40(short):
    return (short * 40)[:40]


def lock(**nodes):
    nodes = {k: rev40(v) for k, v in nodes.items()}
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
        ("https://github.com/o/other.git", rev40("b1"), rev40("b2"))
    ]  # nixpkgs is not diffed
    assert f"| other | moved | github | {rev40('b1')} -> {rev40('b2')} |" in text
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
        str(repo),
        "o/r",
        before,
        other,
        find_prs=lambda slug, sha, branch: slugs.get(sha, []),
    )
    assert commits == [direct, via_pr, other]
    assert [c for c, _ in offenders] == [direct]


def test_merged_prs_ignores_unmerged_and_retries():
    merged = "2026-10-31T00:00:00Z"
    answers = iter(
        [
            json.dumps(
                [{"html_url": "u1", "merged_at": None, "base": {"ref": "master"}}]
            ),
            json.dumps(
                [
                    {
                        "html_url": "other",
                        "merged_at": merged,
                        "base": {"ref": "deploy"},
                    },
                    {"html_url": "u2", "merged_at": merged, "base": {"ref": "master"}},
                ]
            ),
        ]
    )

    def fake_run(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, stdout=next(answers), stderr="")

    sleeps = []
    assert consent.merged_prs("o/r", "abc", run=fake_run, sleep=sleeps.append) == ["u2"]
    assert sleeps == [10]


# ---- review round 2 (Fable F1-F11) ---------------------------------------------------------


def test_line_match_includes_tendcf_rename_path(repo):
    # F1: a renamed copy of the package that drops every "cfengine" literal still says tendcf.
    assert touched(
        repo,
        "push",
        {
            "nixos/vps-primary/configuration.nix": "{ imports = [ ../pkgs/tendcf.nix ]; }\n"
        },
    )


def test_nix_changed_covers_all_of_nixos_and_gate_files(repo):
    # F1: the hard checks do not depend on the diff text.
    def nc(files):
        base = run(repo, "rev-parse", "HEAD")
        head = commit(repo, files)
        return consent.nix_changed(str(repo), base, head)

    assert not nc({"README.md": "q\n"})
    assert nc({"nixos/vps-primary/configuration.nix": "{ x = 1; }\n"})
    assert nc({"nixos/flake.lock": lock(nixpkgs="a9", other="b1")})
    assert nc({".github/scripts/tendcf-consent/run.sh": "#\n"})


def test_decide_writes_both_outputs(repo, tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    base = run(repo, "rev-parse", "HEAD")
    head = commit(repo, {"nixos/vps-primary/configuration.nix": "{ x = 1; }\n"})
    rc = consent.main(
        ["decide", "--mode", "pr", "--repo", str(repo), "--base", base, "--head", head]
    )
    assert rc == 0
    assert out.read_text().split() == ["touches=false", "nix_changed=true"]


def test_check1_nix_scans_units_and_packages():
    # F2: static guard on the Nix source (CI runs it for real).
    nix = (ROOT / ".github/scripts/tendcf-consent/check1.nix").read_text()
    assert "systemd.units" in nix and "systemd.packages" in nix
    assert "rawHits" in nix and "packageHits" in nix and "cfengine|tendcf" in nix
    sh = (ROOT / ".github/scripts/tendcf-consent/run.sh").read_text()
    assert ".rawHits | length) == 0" in sh and ".packageHits | length) == 0" in sh


def test_lock_changed_looks_at_every_pushed_commit(repo):
    # F3: the bot's lock commit may be followed by an unrelated one in the same push.
    before = run(repo, "rev-parse", "HEAD")
    commit(repo, {"nixos/flake.lock": lock(nixpkgs="a8", other="b1")}, "bot")
    head = commit(repo, {"README.md": "again\n"}, "doc")
    assert consent.lock_changed(str(repo), before, head)
    assert not consent.lock_changed(str(repo), run(repo, "rev-parse", "HEAD"), head)


def test_push_job_runs_hard_checks_when_lock_changed():
    # F3: static guard on the workflow wiring.
    wf = (ROOT / ".github/workflows/tendcf-consent.yml").read_text()
    assert 'consent.py" lock-changed' in wf
    assert "steps.lock.outputs.lock_changed == 'true'" in wf
    assert 'run.sh" export-head' in wf and 'run.sh" checks' in wf


@pytest.mark.parametrize("checks", ["", "check 2: PASS\n", "check 1: PASS\n"])
def test_artifact_flags_missing_or_partial_checks(tmp_path, checks):
    # F4
    (tmp_path / "authority.md").write_text("a\n")
    (tmp_path / "summary-base.json").write_text("{}\n")
    (tmp_path / "summary-head.json").write_text("{}\n")
    (tmp_path / "effect.txt").write_text("x\n")
    (tmp_path / "checks.txt").write_text(checks)
    text, ok = consent.build_artifact(str(tmp_path), "vps-primary", "a" * 40, "b" * 40)
    assert not ok and "do not approve" in text


def test_merged_pr_must_target_the_default_branch():
    # F5
    merged = "2026-10-31T00:00:00Z"
    body = json.dumps(
        [{"html_url": "u", "merged_at": merged, "base": {"ref": "deploy-vps-primary"}}]
    )

    def fake_run(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, stdout=body, stderr="")

    assert consent.merged_prs("o/r", "abc", "master", attempts=1, run=fake_run) == []
    assert consent.merged_prs(
        "o/r", "abc", "deploy-vps-primary", attempts=1, run=fake_run
    ) == ["u"]


@pytest.mark.parametrize(
    "url,old,new",
    [
        ("https://github.com/o/r.git", "--upload-pack=touch /tmp/x", rev40("b2")),
        ("https://github.com/o/r.git", rev40("b1"), "b2"),
        ("/local/path", rev40("b1"), rev40("b2")),
        ("ext::sh -c id", rev40("b1"), rev40("b2")),
    ],
)
def test_malformed_lock_strings_never_reach_git(url, old, new):
    # F6
    assert not consent.valid_input(url, old, new)
    with pytest.raises(RuntimeError):
        consent.clone_diff(url, old, new, None)


def test_authority_incomplete_on_malformed_lock_rev(repo):
    base = run(repo, "rev-parse", "HEAD")
    bad = json.loads(lock(nixpkgs="a1", other="b2"))
    bad["nodes"]["other"]["locked"]["rev"] = "--upload-pack=x"
    head = commit(repo, {"nixos/flake.lock": json.dumps(bad)})

    def never(*a):
        raise AssertionError("fetch must not be called")

    text, _, complete = consent.build_authority(str(repo), base, head, fetch=never)
    assert not complete and "unexpected rev or url" in text


def test_token_goes_to_env_not_argv():
    # F6: only github.com gets the token, and only through GIT_CONFIG_* in the environment.
    env = consent.git_env("https://github.com/o/r.git", "sekret")
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert "AUTHORIZATION: basic" in env["GIT_CONFIG_VALUE_0"]
    other = consent.git_env("https://forgejo.mit.edu/o/r.git", "sekret")
    assert other.get("GIT_CONFIG_KEY_0") != "http.https://github.com/.extraheader"
    src = (ROOT / ".github/scripts/tendcf-consent/consent.py").read_text()
    assert "extraheader=AUTHORIZATION" not in src


def test_force_push_falls_back_to_recent_first_parent_commits(repo):
    # F11: an unknown `before` examines more than the head commit.
    direct = commit(repo, {"nixos/pkgs/cfengine-tendcf.nix": "{ 1 }\n"}, "direct")
    head = commit(repo, {"README.md": "z\n"}, "doc")
    commits, offenders = consent.push_offenders(
        str(repo), "o/r", "0" * 40, head, find_prs=lambda *a: []
    )
    assert direct in commits and head in commits
    assert direct in [c for c, _ in offenders]
    assert consent.pushed_commits(str(repo), "f" * 40, head)[-1] == head
