#!/usr/bin/env python3
"""SessionStart: keep `alwaysLoad: true` on the graft entry in the project's
.mcp.json. graft's own SessionStart reconcile rewrites that entry to its stock
shape on every version upgrade (trailhq/Graft#118), which drops the flag and
puts the graft tools back behind ToolSearch. Only touches a file that already
has mcpServers.graft without the flag; silent otherwise."""
import json, os, sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

root = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
path = os.path.join(root, ".mcp.json")
if not os.path.isfile(path):
    sys.exit(0)
try:
    with open(path) as f:
        doc = json.load(f)
except Exception:
    sys.exit(0)
servers = doc.get("mcpServers") if isinstance(doc, dict) else None
entry = servers.get("graft") if isinstance(servers, dict) else None
if not isinstance(entry, dict) or entry.get("alwaysLoad") is True:
    sys.exit(0)
entry["alwaysLoad"] = True
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(doc, f, indent=2)
    f.write("\n")
os.replace(tmp, path)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "[graft] restored alwaysLoad:true on mcpServers.graft in .mcp.json (a graft reconcile had dropped it); graft tools will load eagerly from the next session.",
}}))
