#!/usr/bin/env python3
"""proc_cpu_probe: is one process busy? (watchdogd probe, alert-only rules)

Samples `top` like finder_mds_probe.py and averages the named process's CPU
over the samples after the first. Exit 0 under the limit, 1 at or over it, 75
(watchdogd skips) when top could not be run or parsed.

Usage: proc_cpu_probe.py NAME [--max PCT] [--samples N] [--interval S]
NAME is top's COMMAND column (truncated to 16 characters).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from finder_mds_probe import EX_TEMPFAIL, averages, parse_top  # noqa: E402


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
    cpu = averages(samples, (a.name,))[a.name]
    busy = cpu >= a.max
    print(f"{'BUSY' if busy else 'ok'}: {a.name} {cpu:.0f}% (limit {a.max:.0f}%) "
          f"over ~{(len(samples) - 1) * a.interval} s")
    return 1 if busy else 0


if __name__ == "__main__":
    sys.exit(main())
