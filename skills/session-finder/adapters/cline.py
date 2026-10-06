"""Cline adapter: ~/.cline/data/sessions/<id>/<id>.{json,messages.json}; status in db/sessions.db."""
import json
import os
import re
import sqlite3
from pathlib import Path

AGENT = "cline"
RESUME = "cline --id {sid}"
ROOT = Path.home() / ".cline" / "data"
WRAP = re.compile(r"</?user_input[^>]*>")


def _text(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def _read(meta_p, msg_p):
    meta = {}
    try:
        meta = json.loads(meta_p.read_text())
    except (OSError, ValueError):
        pass
    msgs = []
    for m in json.loads(msg_p.read_text()).get("messages", []):
        role = m.get("role")
        if role in ("user", "assistant"):
            t = WRAP.sub("", _text(m.get("content", ""))).strip()
            if t:
                msgs.append((role, t))
    title = (meta.get("metadata") or {}).get("title") or ""
    if not title:
        first = next((t for r, t in msgs if r == "user"), "")
        title = " ".join(first.split())[:80]
    return meta.get("cwd") or meta.get("workspace_root") or "", title, msgs


def sessions():
    for d in (ROOT / "sessions").iterdir():
        msg_p, meta_p = d / f"{d.name}.messages.json", d / f"{d.name}.json"
        if not msg_p.exists():
            continue
        st = msg_p.stat()
        sm = meta_p.stat().st_mtime if meta_p.exists() else 0
        yield {"key": f"cline:{d.name}", "sid": d.name, "fp": f"{st.st_size}:{int(st.st_mtime)}:{int(sm)}",
               "mtime": max(st.st_mtime, sm), "load": lambda a=meta_p, b=msg_p: _read(a, b)}


def live():
    out = set()
    try:
        db = sqlite3.connect(f"file:{ROOT / 'db' / 'sessions.db'}?mode=ro", uri=True, timeout=5)
        for sid, pid in db.execute("SELECT session_id, pid FROM sessions WHERE ended_at IS NULL"):
            try:
                os.kill(int(pid), 0)
                out.add(sid)
            except OSError:
                pass
    except sqlite3.Error:
        pass
    return out
