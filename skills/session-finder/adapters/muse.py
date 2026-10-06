"""Muse adapter: ~/.local/share/muse/sessions/YYYY/MM/DD/<uuid>/session.jsonl (MSP event log)."""
import json
import os
import sqlite3
from pathlib import Path

AGENT = "muse"
ROOT = Path.home() / ".local/share/muse"
RESUME = "muse resume {sid}"


def _meta():
    out = {}
    try:
        db = sqlite3.connect(f"file:{ROOT / 'session-index.db'}?mode=ro", uri=True)
        for sid, title, name, ws in db.execute("SELECT session_id, title, session_name, workspace_root FROM sessions"):
            out[sid] = (name or title or "", ws or "")
        db.close()
    except sqlite3.Error:
        pass
    return out


def _read(path, meta):
    msgs, cwd = [], meta[1] if meta else ""
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            # cheap prefilter: the file is mostly task/approval noise
            if '"kind":"started","prompt"' in line:
                kind = "user"
            elif '"kind":"assistant_message_committed"' in line:
                kind = "assistant"
            elif not cwd and '"kind":"metadata"' in line:
                try:
                    cwd = json.loads(line)["payload"]["record"].get("workspace_root", "")
                except (ValueError, KeyError, AttributeError):
                    pass
                continue
            else:
                continue
            try:
                ev = json.loads(line)["payload"]["event"]
            except (ValueError, KeyError, TypeError):
                continue
            text = ev.get("prompt") if kind == "user" else ev.get("text")
            if text:
                msgs.append((kind, text))
    title = (meta[0] if meta and meta[0] != "New session" else "")[:100]
    if not title:
        first = next((t for r, t in msgs if r == "user"), "")
        title = " ".join(first.split())[:80]
    return cwd, title, msgs


def sessions():
    meta = _meta()
    for path in (ROOT / "sessions").glob("*/*/*/*/session.jsonl"):
        st = path.stat()
        sid = path.parent.name
        cache = {}

        def load(p=path, m=meta.get(sid), c=cache):
            if not c:
                c["v"] = _read(p, m)
            return c["v"]

        yield {"key": f"muse:{sid}", "sid": sid, "fp": f"{st.st_size}:{int(st.st_mtime)}",
               "mtime": st.st_mtime, "load": load}


def live():
    out = set()
    for lock in (ROOT / "sessions").glob("*/*/*/*/.session.lock"):
        try:
            pid = int(next(l.split("=", 1)[1] for l in lock.read_text().splitlines() if l.startswith("pid=")))
            os.kill(pid, 0)
            out.add(lock.parent.name)
        except (ValueError, StopIteration, OSError):
            pass
    return out
