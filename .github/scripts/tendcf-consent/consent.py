#!/usr/bin/env python3
"""Helpers for .github/workflows/tendcf-consent.yml (stdlib only).

  decide        does a change touch tendcf?  (first step of the required job, and per commit
                in push-check)
  authority     the AUTHORITY block of the consent artifact
  assemble      the whole consent artifact: AUTHORITY, SUMMARY, EFFECT, then the question
  push-check    the push-time check for direct pushes to the default branch
  nix-changed   did the pushed range change anything under nixos/ or the gate's files (the push
                job then runs the hard checks)

The Nix side (SUMMARY, EFFECT, hard checks) is run.sh. Design: docs/tendcf-consent.md.
"""

import argparse
import base64
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

# ---- what counts as "touching tendcf" ------------------------------------------------------

# Whole files and trees: any change to them touches tendcf. The consent workflow and these
# scripts are in the list so that weakening the gate itself goes through the gate.
TENDCF_FILES = frozenset(
    {
        "nixos/modules/cfengine-tendcf.nix",
        "nixos/pkgs/cfengine-tendcf.nix",
        ".github/workflows/nixos-cfengine-build.yml",
        ".github/workflows/tendcf-consent.yml",
    }
)
TENDCF_PREFIXES = (".github/scripts/tendcf-consent/",)
# Rest of nixos/: touches tendcf when an added or removed line mentions it. This is how
# "any vps-primary line that sets services.cfengine-tendcf.*" and the flake lines that import
# the module or package are caught, without flagging unrelated host edits.
LINE_RE = re.compile(r"cfengine|tendcf|cf-execd|cf-agent", re.IGNORECASE)
# Flake wiring decides which code the host imports. On a PR it counts whole (the consent
# artifact is exactly the place to see an input move); on a push it does not, because the weekly
# nixos-lock-update workflow pushes flake.lock to master directly by design.
FLAKE_WIRING = frozenset({"nixos/flake.nix", "nixos/flake.lock"})

# What the AUTHORITY block shows of the host-flake repository (the host's imported paths).
HOST_PATHSPECS = [
    "nixos",
    ".github/workflows/nixos-cfengine-build.yml",
    ".github/workflows/tendcf-consent.yml",
    ".github/scripts/tendcf-consent",
]
LOCK_PATH = "nixos/flake.lock"
MAX_PATCH_LINES = 2500
GIT_INPUT_TYPES = ("git", "github", "gitlab")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def git(repo, *args, check=True, timeout=600, env_extra=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if check and r.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args[:3])} failed ({r.returncode}): {r.stderr.strip()}"
        )
    return r


# ---- decide --------------------------------------------------------------------------------


def touches(repo, base, head, mode):
    """Reasons this change touches tendcf (empty list: it does not)."""
    names = git(repo, "diff", "--name-only", "--no-renames", "-z", base, head).stdout
    reasons = []
    for path in filter(None, names.split("\0")):
        if path in TENDCF_FILES or path.startswith(TENDCF_PREFIXES):
            reasons.append(f"{path}: tendcf file")
        elif mode == "pr" and path in FLAKE_WIRING:
            reasons.append(f"{path}: flake wiring (pull requests only)")
        elif path.startswith("nixos/") and path != LOCK_PATH:
            patch = git(
                repo,
                "diff",
                "-U0",
                "--no-color",
                "--no-renames",
                base,
                head,
                "--",
                path,
            ).stdout
            for line in patch.splitlines():
                if (
                    line[:1] in "+-"
                    and line[:3] not in ("+++", "---")
                    and LINE_RE.search(line)
                ):
                    reasons.append(
                        f"{path}: changed line mentions cfengine: {line[:100].strip()}"
                    )
                    break
    return reasons


def nix_changed(repo, base, head):
    """True when the change moves anything the hard checks evaluate: all of nixos/ (lock
    included) and the gate's own files. The hard checks are cheap, eval-only, and run on
    every such change, whatever the text of the diff says."""
    names = git(repo, "diff", "--name-only", "--no-renames", "-z", base, head).stdout
    return any(
        p.startswith("nixos/") or p in TENDCF_FILES or p.startswith(TENDCF_PREFIXES)
        for p in filter(None, names.split("\0"))
    )


def cmd_decide(a):
    reasons = touches(a.repo, a.base, a.head, a.mode)
    verdict = "true" if reasons else "false"
    nix = "true" if nix_changed(a.repo, a.base, a.head) else "false"
    if reasons:
        print(f"tendcf-touching change ({len(reasons)} reason(s)):")
        for r in reasons:
            print(f"  - {r}")
    else:
        print("no tendcf-touching change")
    print(f"nixos or gate files changed (hard checks run): {nix}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"touches={verdict}\nnix_changed={nix}\n")
    return 0


# ---- authority -----------------------------------------------------------------------------


def lock_at(repo, rev):
    r = git(repo, "show", f"{rev}:{LOCK_PATH}", check=False)
    return json.loads(r.stdout) if r.returncode == 0 else {"nodes": {}}


def reduce_lock(lock):
    """{input: (type, rev, narHash, source)} for every non-root node of a flake.lock."""
    out = {}
    for name, node in lock.get("nodes", {}).items():
        if name == "root":
            continue
        locked = node.get("locked", {})
        kind = locked.get("type", "?")
        if kind in ("github", "gitlab"):
            source = f"{locked.get('owner')}/{locked.get('repo')}"
        else:
            source = locked.get("url") or locked.get("path") or "?"
        out[name] = (kind, locked.get("rev", "-"), locked.get("narHash", "-"), source)
    return out


def edges(lock):
    return {
        n: json.dumps(v.get("inputs", {}), sort_keys=True)
        for n, v in lock.get("nodes", {}).items()
    }


def repo_url(kind, source):
    if kind == "github":
        return f"https://github.com/{source}.git"
    if kind == "gitlab":
        return f"https://gitlab.com/{source}.git"
    return source


def is_nixpkgs(kind, source):
    return kind in ("github", "gitlab") and source.lower() == "nixos/nixpkgs"


REV_RE = re.compile(r"[0-9a-f]{40}")


def valid_input(url, old, new):
    """Lock-derived strings are PR-controlled: only full revs and https/ssh URLs reach git."""
    return bool(
        REV_RE.fullmatch(old or "")
        and REV_RE.fullmatch(new or "")
        and isinstance(url, str)
        and url.startswith(("https://", "ssh://"))
    )


def git_env(url, token):
    """Environment for git against `url`. The GitHub token goes in GIT_CONFIG_* (not argv,
    so it never shows in `ps`) and only for github.com."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if token and url.startswith("https://github.com/"):
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update(
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
            GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {basic}",
        )
    return env


def clone_diff(url, old, new, token):
    """(stat, patch) for old..new of a remote git repository; blobless, fetched on demand."""
    if not valid_input(url, old, new):
        raise RuntimeError("unexpected rev or url in flake.lock")
    env = git_env(url, token)
    with tempfile.TemporaryDirectory(prefix="tendcf-input-") as d:
        git(d, "init", "-q")
        git(d, "remote", "add", "o", url)

        def fetch(*refspecs):
            r = subprocess.run(
                [
                    "git",
                    "-C",
                    d,
                    "fetch",
                    "-q",
                    "--no-tags",
                    "--filter=blob:none",
                    "o",
                    "--",
                    *refspecs,
                ],
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
            )
            return r.returncode == 0

        def have():
            return all(
                git(d, "cat-file", "-e", f"{x}^{{commit}}", check=False).returncode == 0
                for x in (old, new)
            )

        fetch(old, new)
        if not have():
            fetch("+refs/heads/*:refs/remotes/o/*")
        if not have():
            raise RuntimeError(f"cannot fetch {old[:12]}..{new[:12]} from {url}")

        # The diff needs the blobs; the promisor remote needs the same credentials (env).
        def run(*args):
            r = subprocess.run(
                ["git", "-C", d, *args],
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
            )
            if r.returncode != 0:
                raise RuntimeError(f"git {args[0]} failed: {r.stderr.strip()}")
            return r.stdout

        stat = run("diff", "--stat=120", "--no-color", old, new)
        patch = run("diff", "--no-color", "--no-ext-diff", old, new)
        return stat, patch


def fenced(text, lang=""):
    fence = "````"
    return f"{fence}{lang}\n{text.rstrip()}\n{fence}\n"


def cap(text, limit=MAX_PATCH_LINES):
    lines = text.splitlines()
    if len(lines) <= limit:
        return text, False
    return "\n".join(
        lines[:limit]
    ) + f"\n... truncated: {len(lines) - limit} more lines", True


def build_authority(repo, base, head, token=None, fetch=clone_diff):
    """(markdown, one-line summary, complete)."""
    out, problems, notes = [], [], []

    # 1. The PR's own diff of the host-flake repository, flake.lock reduced.
    out.append(
        "### Host-flake repository diff (`nixos/` and the tendcf workflow files)\n"
    )
    stat = git(
        repo,
        "diff",
        "--stat=120",
        "--no-color",
        "--no-renames",
        base,
        head,
        "--",
        *HOST_PATHSPECS,
        f":(exclude){LOCK_PATH}",
    ).stdout
    patch = git(
        repo,
        "diff",
        "--no-color",
        "--no-ext-diff",
        "--no-renames",
        base,
        head,
        "--",
        *HOST_PATHSPECS,
        f":(exclude){LOCK_PATH}",
    ).stdout
    shortstat = git(
        repo,
        "diff",
        "--shortstat",
        "--no-renames",
        base,
        head,
        "--",
        *HOST_PATHSPECS,
        f":(exclude){LOCK_PATH}",
    ).stdout.strip()
    others = [
        p
        for p in git(
            repo, "diff", "--name-only", "--no-renames", base, head
        ).stdout.splitlines()
        if p != LOCK_PATH
        and not (
            p.startswith("nixos/")
            or p in HOST_PATHSPECS
            or p.startswith(HOST_PATHSPECS[3] + "/")
        )
    ]
    if patch.strip():
        text, truncated = cap(patch)
        out.append(fenced(stat, "text"))
        out.append(fenced(text, "diff"))
        if truncated:
            notes.append(
                f"host-flake diff shown to {MAX_PATCH_LINES} lines; the PR has the rest"
            )
    else:
        out.append(
            "No change under the host's imported paths (excluding `flake.lock`, below).\n"
        )
    if others:
        out.append(
            f"Not shown, outside the host's imported paths: {len(others)} file(s).\n"
        )

    # 2. flake.lock, each changed node reduced to (input, type, rev, narHash).
    old_lock, new_lock = lock_at(repo, base), lock_at(repo, head)
    old, new = reduce_lock(old_lock), reduce_lock(new_lock)
    rows, moved, changed_names = [], [], []
    for name in sorted(set(old) | set(new)):
        o, n = old.get(name), new.get(name)
        if o == n:
            continue
        changed_names.append(name)
        if o is None:
            rows.append(f"| {name} | added | {n[0]} | - -> {n[1]} | - -> {n[2]} |")
        elif n is None:
            rows.append(f"| {name} | removed | {o[0]} | {o[1]} -> - | {o[2]} -> - |")
        else:
            rows.append(
                f"| {name} | moved | {n[0]} | {o[1]} -> {n[1]} | {o[2]} -> {n[2]} |"
            )
            moved.append((name, o, n))
    out.append(f"### `{LOCK_PATH}`, changed nodes only\n")
    if rows:
        out.append(
            "| input | change | type | rev | narHash |\n|---|---|---|---|---|\n"
            + "\n".join(rows)
            + "\n"
        )
    else:
        out.append("No lock node changed.\n")
    old_edges, new_edges = edges(old_lock), edges(new_lock)
    changed_edges = [
        n
        for n in sorted(set(old_edges) | set(new_edges))
        if old_edges.get(n) != new_edges.get(n)
    ]
    if changed_edges:
        out.append(
            "Input wiring (`inputs`/`follows`) changed for: "
            + ", ".join(f"`{n}`" for n in changed_edges)
            + "\n"
        )

    # 3. For each moved git input: the source diff, old rev to new rev.
    shown = []
    out.append("### Moved git inputs, `git diff <oldrev>..<newrev>`\n")
    if not moved:
        out.append("No git input moved.\n")
    for name, o, n in moved:
        if o[0] not in GIT_INPUT_TYPES or n[0] not in GIT_INPUT_TYPES:
            out.append(
                f"**{name}** ({n[0]}): not a git input; the lock row above is its whole authority.\n"
            )
            continue
        if is_nixpkgs(n[0], n[3]):
            out.append(
                f"**{name}**: nixpkgs is not diffed here (too large to read); the EFFECT block shows what the bump changes "
                f"in this host. Compare: https://github.com/NixOS/nixpkgs/compare/{o[1][:12]}...{n[1][:12]}\n"
            )
            continue
        out.append(
            f"**{name}** `{o[1][:12]}..{n[1][:12]}` from `{repo_url(n[0], n[3])}`\n"
        )
        if not valid_input(repo_url(n[0], n[3]), o[1], n[1]):
            problems.append(f"{name}: unexpected rev or url in flake.lock")
            out.append("**UNAVAILABLE: unexpected rev or url in flake.lock**\n")
            continue
        try:
            s, p = fetch(repo_url(n[0], n[3]), o[1], n[1], token)
        except Exception as e:  # noqa: BLE001 - any failure makes the authority incomplete
            problems.append(f"{name}: {e}")
            out.append(f"**UNAVAILABLE: {e}**\n")
            continue
        text, truncated = cap(p)
        out.append(fenced(s or "(empty)", "text"))
        out.append(fenced(text or "(no content change)", "diff"))
        if truncated:
            notes.append(f"{name}: source diff shown to {MAX_PATCH_LINES} lines")
        shown.append(name)
    for name in sorted(set(new) - set(old)):
        n = new[name]
        out.append(
            f"**{name}** is a new input ({n[0]} `{n[3]}` at `{n[1][:12]}`): there is no old rev to diff against.\n"
        )

    parts = []
    parts.append(shortstat or "no host-path file change")
    parts.append("lock moved: " + (", ".join(changed_names) or "nothing"))
    parts.append("source diffs shown for: " + (", ".join(shown) or "none"))
    summary = "; ".join(parts)
    if problems:
        out.append(
            "**AUTHORITY INCOMPLETE** - do not approve:\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\n"
        )
    if notes:
        out.append("Notes: " + "; ".join(notes) + "\n")
    return "\n".join(out), summary, not problems


def cmd_authority(a):
    text, summary, complete = build_authority(
        a.repo,
        a.base,
        a.head,
        os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"),
    )
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(text)
    with open(a.out + ".summary", "w", encoding="utf-8") as f:
        f.write(summary + "\n")
    print(summary)
    if not complete:
        print("::error::the AUTHORITY block is incomplete; see the artifact")
        return 3
    return 0


# ---- assemble ------------------------------------------------------------------------------


def read(path, default="(not produced)"):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


def pretty(compact):
    try:
        return json.dumps(json.loads(compact), indent=2, sort_keys=True) + "\n"
    except ValueError:
        return compact


def question(host, head_summary, authority_summary):
    try:
        s = json.loads(head_summary)
    except ValueError:
        s = {}
    if s.get("enable") is True:
        state = "CFEngine stays installed and its scheduler stays off"
    else:
        state = "the tendcf module stays off, so it installs nothing, and its scheduler stays off"
    return (
        f"This changes {host}'s NixOS configuration: {authority_summary}. {state}; "
        "tendcf will still change nothing on this host. Approve?"
    )


def build_artifact(work, host, base, head):
    j = lambda n: os.path.join(work, n)  # noqa: E731
    authority = read(j("authority.md"))
    authority_summary = read(
        j("authority.md.summary"), "authority summary not produced"
    ).strip()
    sb, sh = read(j("summary-base.json")).strip(), read(j("summary-head.json")).strip()
    diff = "".join(
        difflib.unified_diff(
            pretty(sb).splitlines(True), pretty(sh).splitlines(True), "base", "head"
        )
    )
    checks = read(j("checks.txt"))
    effect = read(j("effect.txt"), "(not produced)")
    failed = (
        "FAIL" in checks
        or not all(f"check {n}" in checks for n in (1, 2))
        or checks.count(": PASS") < 2
        or "(not produced)" in (authority, sb, sh, effect)
        or "INCOMPLETE" in authority
    )
    lines = [
        f"# tendcf consent: {host}",
        "",
        f"base `{base[:12]}` -> head `{head[:12]}`",
        "",
    ]
    if failed:
        lines += [
            "> **A check failed or a block is missing: do not approve. Details below.**",
            "",
        ]
    lines += [
        "## AUTHORITY",
        "",
        authority,
        "",
        "## SUMMARY",
        "",
        "`nix eval --json` of `services.cfengine-tendcf` as `{enable, execd.enable, version, package}`, "
        "keys sorted, no whitespace (`jq -cS`, equal to JCS for these booleans and ASCII strings). "
        "`version` stays readable when `package` changes with every rebuild.",
        "",
        "base: `" + sb + "`",
        "",
        "head: `" + sh + "`",
        "",
        fenced(diff, "diff") if diff else "No change in the summary.\n",
        "Hard checks, on the head configuration:",
        "",
        fenced(checks, "text"),
        "## EFFECT",
        "",
        "`nix store diff-closures` of the base toplevel against the head toplevel (empty means no package changed):",
        "",
        fenced(effect or "(no closure difference)", "text"),
        "## Question",
        "",
        question(host, sh, authority_summary),
        "",
    ]
    return "\n".join(lines), not failed


def cmd_assemble(a):
    text, ok = build_artifact(a.work, a.host, a.base, a.head)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(text)
    return 0


# ---- push-check ----------------------------------------------------------------------------


def merged_prs(
    repo_slug,
    sha,
    default_branch="master",
    attempts=4,
    delay=10,
    run=subprocess.run,
    sleep=time.sleep,
):
    """PRs merged into the default branch that introduced `sha`, from GitHub. A PR merged
    elsewhere (another base) did not get this gate's artifact against this branch. The
    association can lag the push a little."""
    for i in range(attempts):
        r = run(
            ["gh", "api", f"repos/{repo_slug}/commits/{sha}/pulls"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode != 0:
            raise RuntimeError(
                f"gh api commits/{sha[:12]}/pulls failed: {r.stderr.strip()}"
            )
        prs = [
            p
            for p in json.loads(r.stdout)
            if p.get("merged_at") and (p.get("base") or {}).get("ref") == default_branch
        ]
        if prs:
            return [p["html_url"] for p in prs]
        if i + 1 < attempts:
            sleep(delay)
    return []


FALLBACK_COMMITS = 20


def pushed_commits(repo, before, sha):
    """First-parent commits of the pushed range, oldest first. When `before` is zeros or no
    longer in history (a force-push), the last FALLBACK_COMMITS first-parent commits."""
    have_before = known_before(repo, before)
    args = ["rev-list", "--first-parent", "--reverse"] + (
        [f"{before}..{sha}"] if have_before else ["-n", str(FALLBACK_COMMITS), sha]
    )
    return git(repo, *args).stdout.split()


def known_before(repo, before):
    return (
        bool(before)
        and set(before) != {"0"}
        and git(repo, "cat-file", "-e", f"{before}^{{commit}}", check=False).returncode
        == 0
    )


def parent_of(repo, c):
    return (
        git(repo, "rev-parse", "--verify", "-q", f"{c}^1", check=False).stdout.strip()
        or EMPTY_TREE
    )


def push_base(repo, before, sha):
    """The revision a pushed range is compared against: `before`, or, when it is unknown,
    the parent of the oldest commit pushed_commits examines."""
    if known_before(repo, before):
        return before
    commits = pushed_commits(repo, before, sha)
    return parent_of(repo, commits[0]) if commits else sha


def push_nix_changed(repo, before, sha):
    """True when the pushed range changed anything the hard checks evaluate (nix_changed):
    any file under nixos/, the lock included, or the gate's own files."""
    return nix_changed(repo, push_base(repo, before, sha), sha)


def cmd_nix_changed(a):
    changed = push_nix_changed(a.repo, a.before, a.sha)
    print(
        f"nixos or gate files changed in the pushed range (hard checks run): {changed}"
    )
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"nix_changed={'true' if changed else 'false'}\n")
    return 0


def push_offenders(
    repo, repo_slug, before, sha, find_prs=merged_prs, default_branch="master"
):
    """First-parent commits of the pushed range that touch tendcf and came from no merged PR."""
    commits = pushed_commits(repo, before, sha)
    offenders = []
    for c in commits:
        reasons = touches(repo, parent_of(repo, c), c, "push")
        if not reasons:
            continue
        prs = find_prs(repo_slug, c, default_branch)
        print(
            f"{c[:12]} touches tendcf ({reasons[0]}); merged PR: {prs[0] if prs else 'none'}"
        )
        if not prs:
            offenders.append((c, reasons))
    return commits, offenders


def cmd_push_check(a):
    commits, offenders = push_offenders(
        a.repo, a.slug, a.before, a.sha, default_branch=a.default_branch
    )
    if not offenders:
        print(
            f"ok: {len(commits)} pushed commit(s); none touches tendcf outside a merged pull request"
        )
        return 0
    for c, reasons in offenders:
        print(
            f"::error::{c[:12]} changed tendcf directly on the default branch ({'; '.join(reasons[:3])})"
        )
    print(
        "::error::Changes that touch tendcf go through a pull request with the required 'tendcf consent' job "
        "(rule R-S3-1, docs/tendcf-consent.md). This check never reverts anything: open a PR for the next "
        "change, and ask the operator whether to review this one after the fact."
    )
    return 1


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decide")
    d.add_argument("--mode", choices=("pr", "push"), required=True)
    d.add_argument("--base", required=True)
    d.add_argument("--head", required=True)
    d.add_argument("--repo", default=".")
    d.set_defaults(fn=cmd_decide)
    u = sub.add_parser("authority")
    u.add_argument("--base", required=True)
    u.add_argument("--head", required=True)
    u.add_argument("--repo", default=".")
    u.add_argument("--out", required=True)
    u.set_defaults(fn=cmd_authority)
    s = sub.add_parser("assemble")
    s.add_argument("--work", required=True)
    s.add_argument("--host", required=True)
    s.add_argument("--base", required=True)
    s.add_argument("--head", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_assemble)
    k = sub.add_parser("push-check")
    k.add_argument("--repo", default=".")
    k.add_argument("--slug", required=True, help="OWNER/REPO")
    k.add_argument("--before", default="")
    k.add_argument("--sha", required=True)
    k.add_argument("--default-branch", default="master")
    k.set_defaults(fn=cmd_push_check)
    nc = sub.add_parser("nix-changed")
    nc.add_argument("--repo", default=".")
    nc.add_argument("--before", default="")
    nc.add_argument("--sha", required=True)
    nc.set_defaults(fn=cmd_nix_changed)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
