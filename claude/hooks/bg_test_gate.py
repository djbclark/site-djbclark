#!/usr/bin/env python3
"""PreToolUse (Bash): deny a pytest / tox / nox / run_tests*.py command that is not run
through ~/ops/site-private/bin/bg.

Why (2026-10-08): one session ran a project's full pytest suite directly, with a runner
sized by os.cpu_count() (8 workers, each spawning children). The load average went from
17 to 220 and every other session starved. bg caps parallelism (PYTHON_CPU_COUNT and
friends), runs at utility QoS and takes one of two machine-wide test slots.

Allowed without bg: --version/--help/--collect-only, anything already starting with bg,
and text that merely mentions pytest inside quotes or a heredoc. Fails open on any parse
error. Escape hatch for the operator: BG_GATE_OFF=1 in the environment.
"""

import json
import os
import re
import sys

BG = "~/ops/site-private/bin/bg"

try:
    data = json.load(sys.stdin)
except (ValueError, OSError):
    sys.exit(0)
if data.get("tool_name") != "Bash" or os.environ.get("BG_GATE_OFF"):
    sys.exit(0)
cmd = str((data.get("tool_input") or {}).get("command") or "")


def strip_literals(c: str) -> str:
    """Drop heredoc bodies and quoted strings so words inside text do not count."""
    out, lines, i = [], c.split("\n"), 0
    while i < len(lines):
        out.append(lines[i])
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", lines[i])
        if m:
            i += 1
            while i < len(lines) and lines[i].strip() != m.group(1):
                i += 1
        i += 1
    s = "\n".join(out)
    s = re.sub(r"'[^']*'", "''", s)
    return re.sub(r'"[^"]*"', '""', s)


TEST_WORD = r"(?:pytest|py\.test|tox|nox|run_tests\w*\.py)"
# A test command: the word is the command itself, or follows python -m / uv run / env VAR=x /
# a path, at the start of a pipeline segment.
SEGMENT = re.compile(
    r"(?:^|[;&|(]|&&|\|\|)\s*"
    r"(?:(?:\w+=\S*\s+)*)"  # VAR=value prefixes
    r"(?:(?:env|time|nice|command|exec)\s+(?:\w+=\S*\s+)*)?"
    r"(?:(?:uv|uvx)\s+(?:run\s+)?(?:--?\S+\s+)*)?"
    r"(?:\S*python[\d.]*\s+(?:-\S+\s+)*(?:-m\s+)?)?"
    r"(?:\S*/)?" + TEST_WORD + r"(?=\s|$)"
)
BG_PREFIX = re.compile(r"(?:^|[;&|(]\s*|\s)(?:\S*/)?bgb?\s")
SAFE = re.compile(r"(?:^|\s)(?:--version|-V|--help|-h|--collect-only|--co)(?:\s|$)")

try:
    plain = strip_literals(cmd)
    for seg in re.split(r"\n|;|&&|\|\||\|", plain):
        seg = seg.strip()
        if (
            not seg
            or not SEGMENT.match(seg)
            or BG_PREFIX.match(seg)
            or SAFE.search(seg)
        ):
            continue
        reason = (
            f"Tests run through bg, not bare: {BG} <your command> (bare `bg` is the shell "
            "job-control builtin, so use the full path). bg caps parallelism, runs at utility "
            "QoS and takes one of two machine-wide test slots; a bare run of a full suite sent "
            "the load average to 220 on 2026-10-08. Run the changed files first (--lf -x); run "
            "the full suite only when asked."
        )
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                }
            )
        )
        sys.exit(0)
except (re.error, TypeError, AttributeError):
    sys.exit(0)
sys.exit(0)
