"""Antigravity (agy) adapter: ~/.gemini/antigravity{,-cli,-acp,-ide}/brain/<id>/.system_generated/logs/transcript.jsonl.

The conversations/*.db files hold protobuf blobs and are not parsed. Titles and workspaces come
from conversation_summaries.db and history.jsonl; a conversation with no transcript is indexed
from its summary title/preview and its history.jsonl prompts. Read-only; agy is never executed.
"""
import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlparse

AGENT = "agy"
BASE = Path.home() / ".gemini"
ROOTS = ["antigravity-cli", "antigravity", "antigravity-acp", "antigravity-ide"]
RESUME = "agy  # unverified: use /resume in the TUI and pick {sid} (agy was not executed to check flags)"
USER_REQ = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.S)
TAGS = re.compile(r"<(ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|EPHEMERAL_MESSAGE)>.*?</\1>", re.S)


def _summaries(root):
    out = {}
    p = BASE / root / "conversation_summaries.db"
    try:
        db = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
        for cid, title, preview, ws, mod in db.execute(
                "SELECT conversation_id, title, preview, workspace_uris, last_modified_time FROM conversation_summaries"):
            cwd = ""
            try:
                uris = json.loads(ws or "[]")
                if uris:
                    cwd = unquote(urlparse(uris[0]).path)
            except ValueError:
                pass
            out[cid] = (title or "", preview or "", cwd, str(mod))
        db.close()
    except sqlite3.Error:
        pass
    return out


def _history(root):
    out = {}
    p = BASE / root / "history.jsonl"
    if p.exists():
        for line in p.read_text(errors="replace").splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            cid = d.get("conversationId")
            if cid and d.get("display") and d.get("type") != "slash_command":
                out.setdefault(cid, []).append((d["display"], d.get("workspace", "")))
    return out


def _user_text(content):
    m = USER_REQ.search(content)
    return (m.group(1) if m else TAGS.sub(" ", content)).strip()


def _read_transcript(path):
    msgs = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            t, c = d.get("type"), d.get("content")
            if not c:
                continue
            if t == "USER_INPUT":
                msgs.append(("user", _user_text(c)))
            elif t == "PLANNER_RESPONSE":
                msgs.append(("assistant", c))
    return msgs


def sessions():
    seen = set()
    for root in ROOTS:
        if not (BASE / root).is_dir():
            continue
        summ, hist = _summaries(root), _history(root)
        ids = {}
        for p in (BASE / root / "brain").glob("*/.system_generated/logs/transcript.jsonl"):
            ids[p.parts[-4]] = p
        for cid in set(ids) | set(summ):
            if cid in seen:
                continue
            seen.add(cid)
            title, preview, cwd, mod = summ.get(cid, ("", "", "", ""))
            path = ids.get(cid)
            if path:
                st = path.stat()
                fp, mtime = f"{st.st_size}:{int(st.st_mtime)}", st.st_mtime
            else:
                fp, mtime = f"s:{mod}", 0.0

            def load(path=path, title=title, preview=preview, cwd=cwd, h=hist.get(cid, [])):
                if path:
                    msgs = _read_transcript(path)
                else:
                    msgs = [("user", d) for d, _ in h]
                    if preview and preview != title:
                        msgs.append(("assistant", preview))
                if not cwd and h:
                    cwd = h[0][1]
                t = " ".join(title.split()) or " ".join(next((x for r, x in msgs if r == "user"), "").split())[:80]
                return cwd, t, msgs

            yield {"key": f"agy:{cid}", "sid": cid, "fp": fp, "mtime": mtime, "load": load}
