from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "macos" / "graft-hook-timeout-fix" / "graft-hook-timeout-fix.py"
_spec = importlib.util.spec_from_file_location("graft_hook_timeout_fix", SCRIPT)
assert _spec is not None and _spec.loader is not None
fixer = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = fixer
_spec.loader.exec_module(fixer)

CMD = fixer.GUARD + ' node "/h/.claude/helpers/graft-hooks.cjs" {sub} || exit 0'


def settings(**timeouts):
    """One PreToolUse/PostToolUse entry per subcommand; a None value omits the timeout key."""
    hooks = {}
    for sub, (event, t) in timeouts.items():
        sub = sub.replace("_", "-")
        h = {"type": "command", "command": CMD.format(sub=sub)}
        if t is not None:
            h["timeout"] = t
        hooks.setdefault(event, []).append({"matcher": "X", "hooks": [h]})
    return {"hooks": hooks, "other": {"keep": 1}}


def timeouts(d):
    return {fixer.subcommand(h["command"]): h.get("timeout") for _, h in fixer.graft_hooks(d)}


class FloorTest(unittest.TestCase):
    def test_subcommand_parses_trailing_or_exit(self):
        self.assertEqual(fixer.subcommand(CMD.format(sub="pre-bash")), "pre-bash")
        self.assertEqual(fixer.subcommand('node "/x/graft-hooks.cjs" stop'), "stop")

    def test_floor_raises_low_values(self):
        d = settings(pre_bash=("PreToolUse", 5), pre_edit=("PreToolUse", 5), post_bash_fail=("PostToolUseFailure", 5))
        changes = fixer.fix(d)
        self.assertEqual(len(changes), 3)
        self.assertEqual(timeouts(d), {"pre-bash": 15, "pre-edit": 15, "post-bash-fail": 15})
        self.assertEqual(d["other"], {"keep": 1})

    def test_floor_keeps_values_at_or_above(self):
        d = settings(pre_bash=("PreToolUse", 15), pre_edit=("PreToolUse", 30))
        self.assertEqual(fixer.fix(d), [])
        self.assertEqual(timeouts(d), {"pre-bash": 15, "pre-edit": 30})

    def test_floor_applies_only_to_listed_subcommands(self):
        d = settings(session_end=("SessionEnd", 5), post_edit=("PostToolUse", 10))
        self.assertEqual(fixer.fix(d), [])
        self.assertEqual(timeouts(d), {"session-end": 5, "post-edit": 10})

    def test_missing_timeout_is_left_alone(self):
        d = settings(pre_bash=("PreToolUse", None))
        self.assertEqual(fixer.fix(d), [])
        self.assertNotIn("timeout", d["hooks"]["PreToolUse"][0]["hooks"][0])

    def test_cap_still_applies(self):
        d = settings(pre_bash=("PreToolUse", 8000), stop=("Stop", 10000), post_edit=("PostToolUse", 15000))
        fixer.fix(d)
        self.assertEqual(timeouts(d), {"pre-bash": 8, "stop": 12, "post-edit": 15})

    def test_idempotent(self):
        d = settings(pre_bash=("PreToolUse", 5))
        fixer.fix(d)
        self.assertEqual(fixer.fix(d), [])

    def test_script_rewrites_copy_named_by_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps(settings(pre_bash=("PreToolUse", 5))))
            env = dict(os.environ, CLAUDE_SETTINGS=str(path), HOME=tmp)
            r = subprocess.run([sys.executable, "-I", str(SCRIPT)], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(timeouts(json.loads(path.read_text())), {"pre-bash": 15})


if __name__ == "__main__":
    unittest.main()
