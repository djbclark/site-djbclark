#!/usr/bin/env python3
"""Print the rollout checklist's next unticked day (or a named day) as JSON.

Usage: next_item.py [--file PATH] [--day N | --list]
Reads the Markdown checklist (default: site-private memory/project_claude_code_mods_rollout.md),
where each day is one line: `- [ ] **Day N[, date]** — <item>. **Use:** <item>` and splits the
line into its install and use halves. No model, no network.
"""
import argparse, json, os, re, sys

DEFAULT = os.path.expanduser("~/ops/site-private/memory/project_claude_code_mods_rollout.md")
LINE = re.compile(r"^- \[(?P<tick>[ x])\] \*\*Day (?P<day>[0-9]+[a-z]?)(?:, [^*]*)?\*\* — (?P<body>.*)$")


def parse(path):
    days = []
    for line in open(path, encoding="utf-8"):
        m = LINE.match(line.rstrip("\n"))
        if not m:
            continue
        body = m.group("body")
        parts = re.split(r"\*\*Use(?: only)?:\*\*\s*", body, maxsplit=1)
        install = parts[0].strip()
        use = parts[1].strip() if len(parts) > 1 else ""
        if install.lower().startswith("install "):
            install = install[len("install "):]
        if body.startswith("**Use only:**"):
            install, use = "", parts[1].strip() if len(parts) > 1 else body
        days.append({"day": m.group("day"), "done": m.group("tick") == "x",
                     "install": install, "use": use, "raw": body})
    return days


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=DEFAULT)
    ap.add_argument("--day")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    days = parse(a.file)
    if a.list:
        json.dump(days, sys.stdout, indent=1, ensure_ascii=False); print(); return
    if a.day:
        pick = [d for d in days if d["day"] == a.day]
    else:
        pick = [d for d in days if not d["done"]][:1]
    if not pick:
        print(json.dumps({"day": None, "message": "every day is ticked"})); return
    json.dump(pick[0], sys.stdout, indent=1, ensure_ascii=False); print()


if __name__ == "__main__":
    main()
