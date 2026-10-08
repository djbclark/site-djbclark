#!/usr/bin/env python3
"""Find which live Claude Code session is working on a topic.

    session-find.py ccc slowness            # rank live sessions by keyword match
    session-find.py --all ccc               # include ended sessions (for /resume)
    session-find.py --json ccc              # machine-readable
    session-find.py --list                  # every live session, no query
    session-find.py --reindex               # rebuild every index from scratch

No model tokens: it reads ~/.claude/sessions/*.json (the live registry), then
keeps a small per-session keyword index in ~/.local/state/session-index/ that is
extended incrementally from the byte offset it last read. Exit 0 = hits,
1 = no hits, 2 = cannot run.
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import where as _where  # noqa: E402

CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
INDEX_DIR = Path.home() / ".local/state/session-index"
HANDOFFS = Path.home() / ".local/state/handoffs"
MAX_PROMPTS = 60
SNIPPET = 220
MAX_TERMS = 2500
STOP = set(
    "the and for that this with from have not are was you your but can all out its "
    "has had will would should could just into than then them they there their what "
    "when which while about also only some more any one two use used using now let "
    "get got did does done make made need want like how why who our too yes ok "
    "tool result file line true false none null".split()
)
WORD = re.compile(r"[a-z0-9][a-z0-9_.\-/]{2,}")
STRIP = re.compile(r"<(system-reminder|local-command-[a-z]+|command-[a-z]+|pasted_content)\b.*?</\1>", re.S)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def live_sessions() -> list[dict[str, Any]]:
    out = []
    for f in (CLAUDE / "sessions").glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except (ValueError, OSError):
            continue
        if d.get("sessionId") and alive(int(d.get("pid", 0))):
            out.append(d)
    return out


def transcript(sid: str) -> Path | None:
    hits = sorted((CLAUDE / "projects").glob(f"*/{sid}.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def text_of(msg: dict[str, Any]) -> str:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def update_index(sid: str, path: Path, fresh: bool = False) -> dict[str, Any]:
    INDEX_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    ix_path = INDEX_DIR / f"{sid}.json"
    ix: dict[str, Any] = {"offset": 0, "titles": [], "prompts": [], "terms": {}}
    if ix_path.exists() and not fresh:
        try:
            ix = json.loads(ix_path.read_text())
        except ValueError:
            pass
    size = path.stat().st_size
    if size < ix["offset"]:
        ix = {"offset": 0, "titles": [], "prompts": [], "terms": {}}
    if size == ix["offset"]:
        return ix
    terms = Counter(ix["terms"])
    with path.open("rb") as fh:
        fh.seek(ix["offset"])
        data = fh.read()
    end = data.rfind(b"\n") + 1
    for raw in data[:end].splitlines():
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        t = d.get("type")
        if t in ("ai-title", "custom-title"):
            title = d.get("aiTitle") or d.get("customTitle")
            if title and title not in ix["titles"]:
                ix["titles"].append(title)
            continue
        if t not in ("user", "assistant"):
            continue
        text = STRIP.sub(" ", text_of(d.get("message", {}))).strip()
        if not text:
            continue
        if t == "user":
            ix["prompts"].append(" ".join(text.split())[:SNIPPET])
            ix["prompts"] = ix["prompts"][-MAX_PROMPTS:]
        weight = 3 if t == "user" else 1
        for w in WORD.findall(text.lower()):
            if w not in STOP:
                terms[w] += weight
    ix["offset"] += end
    ix["terms"] = dict(terms.most_common(MAX_TERMS))
    ix["titles"] = ix["titles"][-6:]
    tmp = ix_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ix))
    tmp.replace(ix_path)
    return ix


def score(ix: dict[str, Any], kws: list[str], name: str, cwd: str) -> tuple[int, str]:
    s, why = 0, ""
    head = " ".join(ix["titles"] + [name, cwd]).lower()
    for k in kws:
        if k in head:
            s += 50
        exact = ix["terms"].get(k, 0)
        partial = sum(c for w, c in ix["terms"].items() if k in w and w != k)
        s += min(exact, 40) * 2 + min(partial, 40)
    for p in reversed(ix["prompts"]):
        if any(k in p.lower() for k in kws):
            why = p
            break
    return s, why


def handoff_hits(kws: list[str]) -> list[str]:
    hits = []
    if HANDOFFS.is_dir():
        for f in HANDOFFS.rglob("*"):
            if f.is_file() and f.stat().st_size < 400_000:
                try:
                    low = f.read_text(errors="replace").lower()
                except OSError:
                    continue
                if all(k in low for k in kws):
                    hits.append(str(f))
    return hits[:5]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("keywords", nargs="*")
    ap.add_argument("--all", action="store_true", help="also search ended sessions already indexed")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--reindex", action="store_true")
    a = ap.parse_args()
    kws = [k.lower() for k in a.keywords]
    if not kws and not a.list and not a.reindex:
        ap.print_usage(sys.stderr)
        return 2

    me = os.environ.get("CLAUDE_CODE_SESSION_ID")
    rows = []
    seen = set()
    for d in live_sessions():
        sid = d["sessionId"]
        seen.add(sid)
        path = transcript(sid)
        ix = update_index(sid, path, a.reindex) if path else {"titles": [], "prompts": [], "terms": {}}
        s, why = score(ix, kws, d.get("name", ""), d.get("cwd", "")) if kws else (0, "")
        loc = _where.lookup(int(d["pid"]), d.get("procStart", ""))
        fin = ""
        if path:
            try:
                import fleet
                fin = fleet.parse(path)["finished"]
            except Exception:
                pass
        rows.append({"where": loc, "name": d.get("name"), "pid": d.get("pid"), "sessionId": sid, "status": d.get("status"),
                     "cwd": d.get("cwd"), "titles": ix["titles"], "score": s, "match": why,
                     "live": True, "self": sid == me, "agent": "claude", "finished": fin})
    # every other TUI's running sessions (fleet.py): matched on title, name and cwd only; use
    # session-history.py for their full text
    try:
        import fleet
        for s in fleet.sessions():
            if s["agent"] == "claude" or s.get("host") == "hermes-gw" and not kws:
                continue
            head = " ".join([s.get("title", ""), s.get("name", ""), s.get("cwd", ""), s.get("agent", "")]).lower()
            sc = sum(50 for k in kws if k in head)
            rows.append({"where": {"where": s["where"], "focus": s["focus"]} if s.get("where") else None, "name": s.get("name") or s["id"],
                         "pid": s.get("pid"), "sessionId": s.get("sid") or s["id"], "status": s["status"], "cwd": s["cwd"],
                         "titles": [s["title"]] if s.get("title") else [], "score": sc, "match": s.get("reach", ""),
                         "live": True, "self": s.get("self", False), "agent": s["agent"], "finished": s.get("finished", "")})
    except Exception as e:  # fleet is optional here
        print(f"fleet unavailable: {e}", file=sys.stderr)
    if a.all:
        for f in INDEX_DIR.glob("*.json"):
            sid = f.stem
            if sid in seen:
                continue
            ix = json.loads(f.read_text())
            s, why = score(ix, kws, "", "")
            rows.append({"name": None, "pid": None, "sessionId": sid, "status": "ended", "cwd": None,
                         "titles": ix["titles"], "score": s, "match": why, "live": False, "self": False})

    if a.list:
        hits = rows
    else:
        hits = sorted((r for r in rows if r["score"] > 0), key=lambda r: -r["score"])[:8]
    if a.json:
        print(json.dumps(hits, indent=1))
    else:
        for r in hits:
            tag = "live" if r["live"] else "ended"
            me_tag = " (this session)" if r["self"] else ""
            fin = f"  FINISHED ({r['finished']}): start a /baton session, do not message it" if r.get("finished") else ""
            agent = f"{r['agent']} " if r.get("agent") else ""
            print(f"[{r['score']:>4}] {agent}{r['name'] or r['sessionId'][:8]}{me_tag}  {tag}/{r['status']}  pid={r['pid']}  cwd={r['cwd']}{fin}")
            if r["titles"]:
                print(f"       title: {r['titles'][-1]}")
            if r.get("where"):
                print(f"       where: {r['where']['where']}" + (f"   focus: {r['where']['focus']}" if r["where"]["focus"] else ""))
            if r["match"]:
                print(f"       prompt: {r['match']}")
        if kws and not hits:
            print("no live-session hit; handoff files:", handoff_hits(kws) or "none")
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
