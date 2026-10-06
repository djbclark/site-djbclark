#!/usr/bin/env python3
"""PreToolUse (Grep|Glob|Bash): once per session, in a graft-indexed repo, remind the
model to try graft first. Non-blocking (additionalContext only); silent no-op
when the repo has no graft/INDEX.md or the nudge already fired this session."""
import json, os, re, sys, tempfile

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

root = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
if not os.path.isfile(os.path.join(root, "graft", "INDEX.md")):
    sys.exit(0)

def _strip_literals(cmd: str) -> str:
    """Drop heredoc bodies and quoted strings so search words inside text
    (commit messages, file contents, echo args) don't count as a search."""
    out, lines, i = [], cmd.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", line)
        if m:
            delim, i = m.group(1), i + 1
            while i < len(lines) and lines[i].strip() != delim:
                i += 1
        i += 1
    s = "\n".join(out)
    s = re.sub(r"'[^']*'", "''", s)
    s = re.sub(r'"[^"]*"', '""', s)
    return s


# Bash only counts when it is a code search (grep/rg/ag/find/fd), not any command.
if data.get("tool_name") == "Bash":
    cmd = _strip_literals(str((data.get("tool_input") or {}).get("command") or ""))
    if not re.search(r"(?:^|[|;&(]\s*|\s)(?:grep|egrep|rg|ag|ack|find|fd)\s", cmd):
        sys.exit(0)

sid = str(data.get("session_id") or "default")
marker = os.path.join(tempfile.gettempdir(), f"graft-nudge-{sid}")
if os.path.exists(marker):
    sys.exit(0)
try:
    open(marker, "w").close()
except Exception:
    pass

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": (
        "This repo is indexed by graft. Before grepping/globbing for code, try "
        "graft_find_code (how/where), graft_find_all (every occurrence), "
        "graft_trace_calls (callers/blast radius) or graft_file_api (a file's API). "
        "Fall back to Grep/Glob for non-code text or when graft misses."
    ),
}}))
