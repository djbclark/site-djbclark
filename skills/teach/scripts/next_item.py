#!/usr/bin/env python3
"""Pick /teach's day from the rollout checklist and print it as JSON (or ping it).

Usage: next_item.py [--file PATH] [--today YYYY-MM-DD] [--day N | --list | --ping PREFIX]

Each day is one checklist line: `- [ ] **Day N[, YYYY-MM-DD]** — <item>. **Use:** <item>`;
a ticked line carries the date it was done.

Pacing (djbclark, 2026-10-17): one day number per calendar day, advanced only by
running /teach, never by the calendar.
  * A day already ticked today comes back again ("mode": "repeat"), with any other
    days ticked today in "also" (Day 1 and Day 1b were both done on 2026-10-17).
  * Otherwise the first unticked day ("mode": "new"). Missed calendar days never
    skip a day number: four idle days later the next /teach still gets Day N+1.
  * "last" recaps the most recent day(s) completed BEFORE today by name only:
    the slash commands and plugin names in backticks on those lines.
--ping PREFIX sends "<PREFIX> Day N — <item> | Last time (...): <names>" through
hermes-ping (the 04:14 launchd job com.djbclark.mods-reminder); when every day is
ticked it says so once and boots out the launchd label in $CHECKLIST_PING_LABEL.
No model, no network beyond hermes-ping. HERMES_PING_DRY=1 prints instead of sending.
"""
import argparse, datetime, json, os, re, subprocess, sys

DEFAULT = os.path.expanduser("~/ops/site-private/memory/project_claude_code_mods_rollout.md")
LINE = re.compile(r"^- \[(?P<tick>[ x])\] \*\*Day (?P<day>[0-9]+[a-z]?)(?:, (?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})[^*]*)?\*\* — (?P<body>.*)$")
KEEP_PREFIXES = ("cc-plugin-", "claude ", "anthropic-skills:", "composio ")


def names(text):
    """Command and plugin names in backticks: `/radar`, `agent-radar@mkt` -> agent-radar."""
    out = []
    for tok in re.findall(r"`([^`]+)`", text):
        tok = tok.strip()
        if tok.startswith("/") and len(tok) > 1 and "/" not in tok[1:]:
            name = tok
        elif "@" in tok and "/" not in tok and " " not in tok:
            name = tok.split("@", 1)[0]
        elif tok.startswith(KEEP_PREFIXES):
            name = tok
        else:
            continue
        if name not in out:
            out.append(name)
    return out


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
                     "date": m.group("date"), "install": install, "use": use,
                     "names": names(body), "raw": body})
    return days


def last_recap(days, today):
    before = [d for d in days if d["done"] and d["date"] and d["date"] < today]
    if not before:
        return None
    date = max(d["date"] for d in before)
    group = [d for d in before if d["date"] == date]
    merged = []
    for d in group:
        merged += [n for n in d["names"] if n not in merged]
    return {"date": date, "days": [d["day"] for d in group], "names": merged}


def pick(days, today):
    done_today = [d for d in days if d["done"] and d["date"] == today]
    if done_today:
        first = dict(done_today[0], mode="repeat")
        first["also"] = [{"day": d["day"], "names": d["names"]} for d in done_today[1:]]
        return first
    todo = [d for d in days if not d["done"]]
    if todo:
        return dict(todo[0], mode="new", also=[])
    return {"mode": "done", "day": None, "message": "every day is ticked", "also": []}


def ping(prefix, result):
    hp = os.environ.get("HERMES_PING_BIN") or os.path.expanduser("~/.local/bin/hermes-ping")
    label = os.environ.get("CHECKLIST_PING_LABEL", "")
    if result["mode"] == "done":
        msg = f"{prefix} every day is ticked; reminder job {label} stops now"
    else:
        days = "+".join([result["day"]] + [a["day"] for a in result["also"]])
        item = re.sub(r"\*\*", "", result["raw"])
        if len(item) > 300:
            item = item[:297] + "..."
        again = " (already done today; /teach repeats it)" if result["mode"] == "repeat" else ""
        msg = f"{prefix} Day {days}{again} — {item}"
        last = result.get("last")
        if last and last["names"]:
            msg += f" | Last time (Day {'+'.join(last['days'])}, {last['date']}): {', '.join(last['names'])}"
    if os.environ.get("HERMES_PING_DRY"):
        print(msg)
    else:
        subprocess.run([hp, msg], check=False)
    if result["mode"] == "done" and label and not os.environ.get("HERMES_PING_DRY"):
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=DEFAULT)
    ap.add_argument("--today", default=datetime.date.today().isoformat())
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--day")
    g.add_argument("--list", action="store_true")
    g.add_argument("--ping", metavar="PREFIX")
    a = ap.parse_args()
    if not os.access(a.file, os.R_OK):
        if a.ping:
            ping(a.ping, {"mode": "done", "day": None, "also": []})
        sys.exit(f"checklist missing: {a.file}")
    days = parse(a.file)
    if a.list:
        json.dump(days, sys.stdout, indent=1, ensure_ascii=False); print(); return
    if a.day:
        hit = [d for d in days if d["day"] == a.day]
        result = dict(hit[0], mode="named", also=[]) if hit else {"mode": "none", "day": None,
                                                                  "message": f"no Day {a.day}", "also": []}
    else:
        result = pick(days, a.today)
    result["last"] = last_recap(days, a.today)
    if a.ping:
        ping(a.ping, result); return
    json.dump(result, sys.stdout, indent=1, ensure_ascii=False); print()


if __name__ == "__main__":
    main()
