"""bin/proc_cpu_probe.py: one named process, exit code by CPU average."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "proc_cpu_probe", REPO / "bin" / "proc_cpu_probe.py"
)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def top(*cpus: float) -> str:
    return "\n".join(
        f"PID    COMMAND          %CPU\n100  mobileassetd  {c:.1f} " for c in cpus
    ) + "\n"


def run(text: str, *args: str) -> int:
    done = subprocess.CompletedProcess([], 0, stdout=text)
    with mock.patch.object(probe.subprocess, "run", return_value=done):
        return probe.main(["mobileassetd", *args])


def top_named(name: str, *cpus: float) -> str:
    return "\n".join(
        f"PID    COMMAND          %CPU\n100  {name}  {c:.1f} " for c in cpus
    ) + "\n"


class ProcProbeTests(unittest.TestCase):
    def test_under_limit_is_healthy_and_first_sample_ignored(self) -> None:
        self.assertEqual(run(top(99.0, 10.0, 20.0)), 0)

    def test_at_limit_is_busy(self) -> None:
        self.assertEqual(run(top(0.0, 50.0, 50.0)), 1)

    def test_too_few_samples_is_a_skip(self) -> None:
        self.assertEqual(run(top(80.0)), 75)

    def test_absent_process_counts_as_zero(self) -> None:
        self.assertEqual(run("PID    COMMAND          %CPU\n" * 3), 0)

    def test_truncated_top_command_matches_full_name(self) -> None:
        text = top_named("ImageThumbnailEx", 0.0, 80.0, 90.0)
        done = subprocess.CompletedProcess([], 0, stdout=text)
        with mock.patch.object(probe.subprocess, "run", return_value=done):
            self.assertEqual(
                probe.main(["ImageThumbnailExtension", "--max", "50"]), 1
            )

    def test_short_name_is_not_a_prefix_of_longer_top_key(self) -> None:
        # "mds" must not pick up "mds_stores" via the truncation rule.
        text = top_named("mds_stores", 0.0, 90.0, 90.0)
        done = subprocess.CompletedProcess([], 0, stdout=text)
        with mock.patch.object(probe.subprocess, "run", return_value=done):
            self.assertEqual(probe.main(["mds", "--max", "50"]), 0)


if __name__ == "__main__":
    unittest.main()
