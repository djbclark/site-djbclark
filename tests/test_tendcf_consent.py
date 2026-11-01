"""Tests for .github/scripts/tendcf-consent/consent.py (the tendcf consent gate)."""

import importlib.util
import json
import pathlib
import re
import shutil
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


CHECK1 = ROOT / ".github/scripts/tendcf-consent/check1.nix"
RUN_SH = ROOT / ".github/scripts/tendcf-consent/run.sh"


def test_check1_nix_scans_every_channel():
    # Static guard on the Nix source: which attributes the scan reads. The behaviour of the
    # expression itself is only provable where Nix runs (CI, or the gated test below).
    nix = CHECK1.read_text()
    assert nix.lstrip().splitlines()[-1] == "}" and "\nconfig:\nlet\n" in nix
    for needle in (
        "systemd.units",  # F2 (existing) rendered units
        "systemd.packages",
        "systemd.user.services",  # F3
        "systemd.user.timers",
        "systemd.user.units",
        "services.cron.systemCronJobs",
        "config.system.activationScripts",  # F2
        "config.boot.postBootCommands",
        "systemd.tmpfiles.rules",
        "config.environment.etc",
        '"systemd/"',
        "/lib/systemd/system",  # F5: the unit text a package ships
        "builtins.readFile",
        "cf-(execd|agent)",
        "cfengine|tendcf",
    ):
        assert needle in nix, needle
    for key in ("hits", "rawHits", "packageHits", "scriptHits", "scanned"):
        assert f"{key} =" in nix, key


def test_check1_nix_is_applied_to_the_whole_config():
    sh = RUN_SH.read_text()
    assert '#nixosConfigurations.$HOST.config" \\\n' in sh
    assert "config.systemd" not in sh


def check1_condition():
    m = re.search(r"jq -e '([^']*execdUnitPresent[^']*)'", RUN_SH.read_text())
    assert m, "hard check 1 jq condition not found in run.sh"
    return m.group(1)


def check1_passes(result):
    r = subprocess.run(
        ["jq", "-e", check1_condition()],
        input=json.dumps(result),
        capture_output=True,
        text=True,
    )
    assert r.returncode in (0, 1), r.stderr
    return r.returncode == 0


CLEAN = {
    "execdUnitPresent": False,
    "hits": [],
    "rawHits": [],
    "packageHits": [],
    "scriptHits": [],
    "scanned": {
        "services": 9,
        "units": 30,
        "activationScripts": 6,
        "etc": 40,
        "packageFiles": 200,
    },
}


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_check1_decision_fails_on_every_hit_channel_and_on_a_vacuous_scan():
    hit = [{"unit": "x", "why": "names cf-execd or cf-agent"}]
    assert check1_passes(CLEAN)
    for key in ("hits", "rawHits", "packageHits", "scriptHits"):
        assert not check1_passes({**CLEAN, key: hit}), key
    assert not check1_passes({**CLEAN, "execdUnitPresent": True})
    # F2/F5 non-vacuity: a scan that saw nothing (or a result missing a channel) cannot pass.
    for k in CLEAN["scanned"]:
        assert not check1_passes({**CLEAN, "scanned": {**CLEAN["scanned"], k: 0}}), k
    assert not check1_passes({**CLEAN, "scanned": {}})
    without = {k: v for k, v in CLEAN.items() if k != "scriptHits"}
    assert not check1_passes(without)


def _check1_eval(tmp_path, config):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(config))
    expr = f"(import {CHECK1}) (builtins.fromJSON (builtins.readFile {cfg}))"
    r = subprocess.run(
        [
            "nix",
            "eval",
            "--impure",
            "--json",
            "--extra-experimental-features",
            "nix-command",
            "--expr",
            expr,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _fake_config(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "lib/systemd/system").mkdir(parents=True)
    (pkg / "lib/systemd/system/ok.service").write_text(
        "[Service]\nExecStart=/bin/true\n"
    )
    return {
        "systemd": {
            "services": {
                "a": {"script": "echo hi", "serviceConfig": {"ExecStart": "/bin/true"}}
            },
            "timers": {},
            "units": {"a.service": {"text": "[Service]\nExecStart=/bin/true\n"}},
            "user": {"services": {}, "timers": {}, "units": {}},
            "packages": [{"pname": "pkg", "outPath": str(pkg)}],
            "tmpfiles": {"rules": ["d /var/x 0755 root root -"]},
        },
        "system": {"activationScripts": {"users": "echo users", "script": "ignored"}},
        "boot": {"postBootCommands": ""},
        "services": {"cron": {"systemCronJobs": []}},
        "environment": {"etc": {"issue": {"target": "issue", "text": "hi"}}},
    }


def _poisoned(tmp_path):
    bad = "/run/current-system/sw/bin/cf-agent -K"
    shipped = tmp_path / "pkg" / "lib/systemd/system"

    def setter(path, value):
        def apply(c):
            d = c
            for k in path[:-1]:
                d = d[k]
            d[path[-1]] = value

        return apply

    return {
        "activationScripts string": (
            "scriptHits",
            setter(["system", "activationScripts", "x"], bad),
        ),
        "activationScripts text": (
            "scriptHits",
            setter(["system", "activationScripts", "x"], {"text": bad, "deps": []}),
        ),
        "postBootCommands": ("scriptHits", setter(["boot", "postBootCommands"], bad)),
        "tmpfiles": (
            "scriptHits",
            setter(["systemd", "tmpfiles", "rules"], ["f /x - - - - " + bad]),
        ),
        "cron": (
            "scriptHits",
            setter(["services", "cron", "systemCronJobs"], ["* * * * * root " + bad]),
        ),
        "etc systemd text": (
            "rawHits",
            setter(
                ["environment", "etc", "u"],
                {"target": "systemd/system/u.service", "text": "ExecStart=" + bad},
            ),
        ),
        "etc systemd target": (
            "rawHits",
            setter(
                ["environment", "etc", "u"],
                {"target": "systemd/system/cf-execd.service", "text": ""},
            ),
        ),
        "user service": (
            "hits",
            setter(["systemd", "user", "services", "u"], {"script": bad}),
        ),
        "user timer": (
            "hits",
            setter(
                ["systemd", "user", "timers", "u"],
                {"serviceConfig": {"ExecStart": bad}},
            ),
        ),
        "user unit": (
            "rawHits",
            setter(["systemd", "user", "units", "u.service"], {"text": bad}),
        ),
        "shipped unit text": (
            "packageHits",
            lambda c: (shipped / "helpers.service").write_text(
                "[Service]\nExecStart=" + bad + "\n"
            ),
        ),
    }


@pytest.mark.skipif(
    shutil.which("nix") is None, reason="needs Nix; CI runs the real check"
)
def test_check1_nix_flags_each_channel(tmp_path):
    # The Mac has no Nix, so this has not been run by the author; it runs wherever `nix` exists.
    clean = _check1_eval(tmp_path, _fake_config(tmp_path))
    assert (
        clean["hits"]
        == clean["rawHits"]
        == clean["packageHits"]
        == clean["scriptHits"]
        == []
    )
    assert all(v > 0 for v in clean["scanned"].values())
    for name, (channel, mutate) in _poisoned(tmp_path).items():
        cfg = _fake_config(tmp_path)
        mutate(cfg)
        assert _check1_eval(tmp_path, cfg)[channel], name


def test_push_nix_changed_without_a_lock_or_cfengine_word(repo):
    # F1: the audit's counter-example, a non-lock nixos/ change whose text hides the binary
    # name, was green on a push because only the lock triggered the hard checks.
    before = run(repo, "rev-parse", "HEAD")
    head = commit(
        repo,
        {
            "nixos/vps-primary/configuration.nix": '{ systemd.services.r.script = "cf-" + "agent"; }\n'
        },
    )
    assert consent.touches(str(repo), before, head, "push") == []
    assert consent.push_nix_changed(str(repo), before, head)


def test_push_nix_changed_covers_nix_files_lock_and_gate_files_only(repo):
    start = run(repo, "rev-parse", "HEAD")

    def pushed(files):
        before = run(repo, "rev-parse", "HEAD")
        head = commit(repo, files)
        return consent.push_nix_changed(str(repo), before, head)

    assert not pushed({"README.md": "q\n"})
    assert pushed({"nixos/flake.lock": lock(nixpkgs="a8", other="b1")})
    assert pushed({"nixos/new.nix": "{ }\n"})
    assert pushed({".github/workflows/tendcf-consent.yml": "#\n"})
    assert pushed({".github/scripts/tendcf-consent/check1.nix": "#\n"})
    # A whole range: the nixos/ change is not in the last commit.
    commit(repo, {"nixos/vps-primary/configuration.nix": "{ y = 1; }\n"}, "nix")
    head = commit(repo, {"README.md": "later\n"}, "doc")
    assert consent.push_nix_changed(str(repo), start, head)
    assert not consent.push_nix_changed(str(repo), run(repo, "rev-parse", "HEAD"), head)


def test_push_nix_changed_force_push_uses_the_same_fallback_as_pushed_commits(repo):
    # `before` unknown (zeros, or gone from history): the last FALLBACK_COMMITS first-parent
    # commits are the range, so an earlier nixos/ change in them still triggers the checks.
    commit(repo, {"nixos/vps-primary/configuration.nix": "{ z = 1; }\n"}, "nix")
    head = commit(repo, {"README.md": "z\n"}, "doc")
    assert consent.push_nix_changed(str(repo), "0" * 40, head)
    assert consent.push_nix_changed(str(repo), "f" * 40, head)
    assert consent.push_nix_changed(str(repo), "", head)
    # Older than the fallback window and with no nixos/ change in it: nothing to run.
    for i in range(consent.FALLBACK_COMMITS):
        head = commit(repo, {"README.md": f"{i}\n"}, f"doc{i}")
    assert not consent.push_nix_changed(str(repo), "0" * 40, head)


def test_nix_changed_command_writes_output(repo, tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    before = run(repo, "rev-parse", "HEAD")
    head = commit(repo, {"nixos/vps-primary/configuration.nix": "{ x = 1; }\n"})
    args = ["nix-changed", "--repo", str(repo), "--before", before, "--sha", head]
    assert consent.main(args) == 0
    assert (
        consent.main(
            ["nix-changed", "--repo", str(repo), "--before", head, "--sha", head]
        )
        == 0
    )
    assert out.read_text().split() == ["nix_changed=true", "nix_changed=false"]


def test_push_job_runs_hard_checks_when_nixos_or_gate_files_changed():
    # F1: static guard on the workflow wiring.
    wf = (ROOT / ".github/workflows/tendcf-consent.yml").read_text()
    assert 'consent.py" nix-changed' in wf
    assert "lock-changed" not in wf and "lock_changed" not in wf
    assert wf.count("steps.nix.outputs.nix_changed == 'true'") == 2
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
