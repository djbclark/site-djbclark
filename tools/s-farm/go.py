#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["rapidfuzz>=3.9"]
# ///
"""Resolve a rough name to one directory in ~/src and print its path.

Used by shell-init.bash: inside ~/s, `just NAME` with a NAME that is not a
recipe runs this and changes to the result. The stages run in order and the
first one that finds anything wins:

  1. exact name (case-insensitive)             just herdr
  2. glob, when NAME has * ? or [              just 'physi*'
  3. partial: NAME is a substring              just chess
  4. near miss: one or two edits from a name   just hredr
  5. abbreviation: letters in order (fzf)      just stcf
  6. looser misspelling (rapidfuzz)            just telegrum-bot

One result is printed at once; several open an fzf list on the terminal.
Exit 0 with a path on stdout, 1 for no match, 130 when the list is cancelled.
"""

import argparse
import fnmatch
import os
import shutil
import subprocess
import sys
from pathlib import Path

from rapidfuzz import fuzz, process, utils
from rapidfuzz.distance import DamerauLevenshtein

TYPO_CUTOFF = 70  # WRatio floor for a name to be offered as a misspelling
MAX_TYPO_CANDIDATES = 12


def find(query, names):
    """Return the names matching query, best first."""
    q = query.lower()
    exact = [n for n in names if n.lower() == q]
    if exact:
        return exact
    if any(c in query for c in "*?["):
        return [n for n in names if fnmatch.fnmatchcase(n.lower(), q)]
    partial = [n for n in names if q in n.lower()]
    if partial:
        return sorted(partial, key=lambda n: (not n.lower().startswith(q), len(n), n.lower()))
    return near_miss(q, names) or abbreviation(query, names) or typo(query, names)


def abbreviation(query, names):
    """fzf's own matcher in filter mode: query letters in order, ranked."""
    if not shutil.which("fzf"):
        return []
    r = subprocess.run(
        ["fzf", "--ignore-case", "--filter", query],
        input="\n".join(names), capture_output=True, text=True,
    )
    return r.stdout.split("\n")[:-1] if r.returncode == 0 else []


def near_miss(q, names):
    """The one name within a keystroke or two of q (swaps count as one), if it stands alone."""
    if len(q) < 3:
        return []
    allowed = 1 if len(q) < 8 else 2
    dist = sorted((DamerauLevenshtein.distance(q, n.lower()), n) for n in names)
    best = dist[0][0]
    if best > allowed or (len(dist) > 1 and dist[1][0] <= best + 1):
        return []
    return [dist[0][1]]


def typo(query, names):
    """Looser misspellings, best first."""
    scored = process.extract(
        query, names, scorer=fuzz.WRatio, processor=utils.default_process,
        score_cutoff=TYPO_CUTOFF, limit=MAX_TYPO_CANDIDATES,
    )
    return [name for name, _, _ in scored]


def topics(farm):
    """Map each ~/src name to the topic directory that holds its link in the farm."""
    out = {}
    for root, dirs, files in os.walk(farm, followlinks=False):
        rel = os.path.relpath(root, farm)
        if rel == ".":
            dirs[:] = [d for d in dirs if not d.startswith("by-")]
            continue
        for name in dirs + files:
            if os.path.islink(os.path.join(root, name)):
                out[name] = rel
    return out


def choose(query, found, farm):
    """Let the user pick one of several names with the arrow keys."""
    if not shutil.which("fzf"):
        print(f"{len(found)} matches for '{query}' (install fzf to pick from a list):", file=sys.stderr)
        print("\n".join(f"  {n}" for n in found), file=sys.stderr)
        sys.exit(1)
    topic = topics(farm) if farm.is_dir() else {}
    width = max(len(n) for n in found)
    lines = [f"{n}\t{n.ljust(width)}  {topic.get(n, '')}" for n in found]
    r = subprocess.run(
        ["fzf", "--delimiter=\t", "--with-nth=2", "--no-sort", "--reverse", "--cycle",
         "--height=~50%", "--prompt=~/src> ", f"--header={len(found)} matches for '{query}'"],
        input="\n".join(lines), stdout=subprocess.PIPE, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit(130)
    return r.stdout.split("\t", 1)[0]


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("query")
    ap.add_argument("--src", type=Path, default=Path.home() / "src")
    ap.add_argument("--farm", type=Path, default=Path.home() / "s")
    ap.add_argument("--list", action="store_true", help="print every match and exit; never prompt")
    a = ap.parse_args()
    names = sorted(
        (p.name for p in a.src.iterdir() if not p.name.startswith(".") and p.is_dir()),
        key=str.lower,
    )
    found = find(a.query, names)
    if a.list:
        print("\n".join(found))
        sys.exit(0 if found else 1)
    if not found:
        print(f"just: no recipe and no directory in {a.src} matches '{a.query}'", file=sys.stderr)
        sys.exit(1)
    name = found[0] if len(found) == 1 else choose(a.query, found, a.farm)
    print(a.src / name)


if __name__ == "__main__":
    main()
