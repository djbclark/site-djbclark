#!/usr/bin/env python3
"""finder_mds_probe: is Finder pinned together with mds? (watchdogd probe)

2026-11-01: Finder re-listing /private/tmp kept Finder and mds both busy for
hours (load 20-160 on this Mac); `killall Finder` cured it and no rule covered
it. watchdogd.d/finder-mds.toml runs this probe and relaunches Finder when it
reports unhealthy twice in a row (roles/watchdogd/README.md).

It samples `top` and averages the CPU of Finder and mds over the samples after
the first (the first one is not an interval average). Unhealthy only when BOTH
stay at or over their threshold: Finder alone busy (a big copy) or mds alone
busy (a catch-up) is normal.

Exit 0 healthy, 1 Finder and mds both pinned, 75 (EX_TEMPFAIL, watchdogd skips)
when top could not be run or parsed. Usage: finder_mds_probe.py [--finder PCT]
[--mds PCT] [--samples N] [--interval S]
"""

from __future__ import annotations

import argparse
import subprocess
import sys

EX_TEMPFAIL = 75


def parse_top(text: str) -> list[dict[str, float]]:
    """One {command: cpu} per sample, in order. top prints COMMAND truncated and
    may contain spaces, so the line is pid, the command words, then %CPU."""
    samples: list[dict[str, float]] = []
    current: dict[str, float] | None = None
    for line in text.splitlines():
        words = line.split()
        if words[:3] == ["PID", "COMMAND", "%CPU"]:
            current = {}
            samples.append(current)
            continue
        if current is None or len(words) < 3 or not words[0].isdigit():
            continue
        try:
            cpu = float(words[-1])
        except ValueError:
            continue
        name = " ".join(words[1:-1])
        current[name] = current.get(name, 0.0) + cpu
    return samples


def averages(samples: list[dict[str, float]], names: tuple[str, ...]) -> dict[str, float]:
    """Mean CPU per name over every sample after the first (all of them when
    only one was taken); a name absent from a sample counts as 0."""
    used = samples[1:] or samples
    return {n: sum(s.get(n, 0.0) for s in used) / len(used) for n in names}


def verdict(avg: dict[str, float], finder: float, mds: float) -> tuple[bool, str]:
    pinned = avg["Finder"] >= finder and avg["mds"] >= mds
    return pinned, f"Finder {avg['Finder']:.0f}% mds {avg['mds']:.0f}%"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--finder", type=float, default=20.0)
    ap.add_argument("--mds", type=float, default=20.0)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--interval", type=int, default=6)
    a = ap.parse_args(argv)
    cmd = ["/usr/bin/top", "-l", str(a.samples), "-s", str(a.interval),
           "-n", "30", "-o", "cpu", "-stats", "pid,command,cpu"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=a.samples * (a.interval + 10)).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"top failed: {e}")
        return EX_TEMPFAIL
    samples = parse_top(out)
    if len(samples) < a.samples:
        print(f"top gave {len(samples)} of {a.samples} samples")
        return EX_TEMPFAIL
    pinned, text = verdict(averages(samples, ("Finder", "mds")), a.finder, a.mds)
    window = (len(samples) - 1) * a.interval
    print(f"{'PINNED' if pinned else 'ok'}: {text} over ~{window} s")
    return 1 if pinned else 0


if __name__ == "__main__":
    sys.exit(main())
