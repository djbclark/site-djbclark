#!/usr/bin/env python3
"""proc_cpu_probe: is one process busy? (watchdogd probe)

Samples `top` like finder_mds_probe.py and averages the named process's CPU
over the samples after the first. Exit 0 under the limit, 1 at or over it, 75
(watchdogd skips) when top could not be run or parsed.

Usage: proc_cpu_probe.py NAME [--max PCT] [--samples N] [--interval S]
NAME may be the full process name; top truncates COMMAND (~16 characters), so
a longer NAME still matches its truncated top key (e.g. ImageThumbnailExtension
→ ImageThumbnailEx).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from finder_mds_probe import EX_TEMPFAIL, parse_top  # noqa: E402

# top's COMMAND column is short; only treat a sample key as a truncation of
# NAME when the key is at least this long (avoids "mds" ↔ "mds_stores").
_MIN_TRUNC_KEY = 12


def cpu_for(sample: dict[str, float], name: str) -> float:
    """CPU for NAME in one top sample, honouring COMMAND truncation."""
    if name in sample:
        return sample[name]
    for key, cpu in sample.items():
        if len(key) >= _MIN_TRUNC_KEY and name.startswith(key):
            return cpu
    return 0.0


def average_cpu(samples: list[dict[str, float]], name: str) -> float:
    """Mean CPU for NAME over every sample after the first (all when only one)."""
    used = samples[1:] or samples
    return sum(cpu_for(s, name) for s in used) / len(used)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name")
    ap.add_argument("--max", type=float, default=50.0)
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
    cpu = average_cpu(samples, a.name)
    busy = cpu >= a.max
    print(f"{'BUSY' if busy else 'ok'}: {a.name} {cpu:.0f}% (limit {a.max:.0f}%) "
          f"over ~{(len(samples) - 1) * a.interval} s")
    return 1 if busy else 0


if __name__ == "__main__":
    sys.exit(main())
