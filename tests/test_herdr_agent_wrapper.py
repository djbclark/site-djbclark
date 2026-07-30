from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "herdr_agent_wrapper.py"
SPEC = importlib.util.spec_from_file_location("herdr_agent_wrapper", SCRIPT)
assert SPEC and SPEC.loader
wrapper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wrapper
SPEC.loader.exec_module(wrapper)


class LooksBlockedTests(unittest.TestCase):
    def test_matches_aider_yes_no_prompt(self) -> None:
        # Real prompt observed live from aider 0.86.2, 2026-07-29.
        text = "Add .aider* to .gitignore (recommended)? (Y)es/(N)o [Yes]: "
        self.assertTrue(wrapper._looks_blocked(text))

    def test_matches_aider_three_way_prompt(self) -> None:
        text = "Open documentation url for more info? (Y)es/(N)o/(D)on't ask again [Yes]: "
        self.assertTrue(wrapper._looks_blocked(text))

    def test_matches_goose_clack_toggle(self) -> None:
        # Real prompt observed live from goose 1.44.0, 2026-07-29.
        text = "Share anonymous usage data to help improve goose?\n● Yes  / ○ No"
        self.assertTrue(wrapper._looks_blocked(text))

    def test_ignores_ordinary_streaming_output(self) -> None:
        text = "goose is ready\n> Enter to send · Ctrl+J newline"
        self.assertFalse(wrapper._looks_blocked(text))

    def test_ignores_ordinary_aider_prompt(self) -> None:
        text = "Aider v0.86.2\nMain model: openrouter/anthropic/claude-sonnet-4\n>"
        self.assertFalse(wrapper._looks_blocked(text))


class ClassifyNextStateTests(unittest.TestCase):
    def test_changed_content_is_working(self) -> None:
        state, stable = wrapper.classify_next_state("new output", "old output", 0, "idle")
        self.assertEqual(state, "working")
        self.assertEqual(stable, 0)

    def test_first_unchanged_poll_does_not_flip_to_idle(self) -> None:
        state, stable = wrapper.classify_next_state("same", "same", 0, "working")
        self.assertEqual(state, "working")
        self.assertEqual(stable, 1)

    def test_second_consecutive_unchanged_poll_flips_to_idle(self) -> None:
        state, stable = wrapper.classify_next_state("same", "same", 1, "working")
        self.assertEqual(state, "idle")
        self.assertEqual(stable, 2)

    def test_blocked_pattern_wins_even_if_content_unchanged(self) -> None:
        text = "Run this command? (Y)es/(N)o"
        state, stable = wrapper.classify_next_state(text, text, 3, "idle")
        self.assertEqual(state, "blocked")
        self.assertEqual(stable, 0)


if __name__ == "__main__":
    unittest.main()
