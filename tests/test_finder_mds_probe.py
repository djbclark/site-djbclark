"""bin/finder_mds_probe.py: parse `top`, average Finder and mds, decide."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "finder_mds_probe", REPO / "bin" / "finder_mds_probe.py"
)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def top(*samples: dict[str, float]) -> str:
    out = []
    for s in samples:
        out.append("Processes: 800 total\nLoad Avg: 1, 1, 1\n\nPID    COMMAND          %CPU")
        for i, (name, cpu) in enumerate(s.items(), start=100):
            out.append(f"{i}  {name:<16} {cpu:.1f} ")
    return "\n".join(out) + "\n"


class ProbeTests(unittest.TestCase):
    def test_parse_top_one_dict_per_sample_and_names_with_spaces(self) -> None:
        got = probe.parse_top(top({"Finder": 5.0, "Google Chrome He": 7.5}, {"mds": 1.0}))
        self.assertEqual(got, [{"Finder": 5.0, "Google Chrome He": 7.5}, {"mds": 1.0}])

    def test_first_sample_is_ignored_and_missing_counts_as_zero(self) -> None:
        samples = probe.parse_top(
            top({"Finder": 99.0, "mds": 99.0}, {"Finder": 40.0}, {"Finder": 20.0, "mds": 60.0})
        )
        avg = probe.averages(samples, ("Finder", "mds"))
        self.assertEqual(avg, {"Finder": 30.0, "mds": 30.0})

    def test_pinned_needs_both(self) -> None:
        both = {"Finder": 25.0, "mds": 20.0}
        self.assertTrue(probe.verdict(both, 20, 20)[0])
        self.assertFalse(probe.verdict({"Finder": 90.0, "mds": 5.0}, 20, 20)[0])
        self.assertFalse(probe.verdict({"Finder": 5.0, "mds": 90.0}, 20, 20)[0])

    def test_single_sample_is_used_when_it_is_all_there_is(self) -> None:
        avg = probe.averages(probe.parse_top(top({"Finder": 50.0})), ("Finder", "mds"))
        self.assertEqual(avg, {"Finder": 50.0, "mds": 0.0})

    def test_garbage_gives_no_samples(self) -> None:
        self.assertEqual(probe.parse_top("nothing useful\n"), [])


if __name__ == "__main__":
    unittest.main()
