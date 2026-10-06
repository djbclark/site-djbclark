"""Hermes adapter: ~/.hermes/state.db (sessions + messages tables)."""
import sqlite3
from pathlib import Path

AGENT = "hermes"
RESUME = "hermes --resume {sid}"
DB = Path.home() / ".hermes" / "state.db"


def _conn():
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def _title(r):
    t = (r["title"] or "").strip()
    if r["source"] == "telegram" and r["chat_id"]:
        # target for mcp__hermes__messages_send is "telegram:<chat_id>"; session_key is for conversation_get
        t = f"{t} [telegram:{r['chat_id']}" + (f":{r['thread_id']}" if r["thread_id"] else "") + "]"
    elif r["source"] not in ("cli", None):
        t = f"{t} [{r['source']}]"
    return t.strip()


def sessions():
    # No aggregate over messages: that table is >1 GB (tool output) and a scan takes ~30 s.
    db = _conn()
    rows = db.execute(
        "SELECT id, source, chat_id, thread_id, title, cwd, started_at, message_count n, "
        "COALESCE(last_activity_at, ended_at, started_at) last FROM sessions"
    ).fetchall()
    db.close()
    for r in rows:
        def load(r=r):
            c = _conn()
            msgs = [(m["role"], m["content"]) for m in c.execute(
                "SELECT role, content FROM messages WHERE session_id=? AND role IN ('user','assistant') "
                "AND content IS NOT NULL AND content != '' ORDER BY id", (r["id"],))]
            c.close()
            title = _title(r)
            if not (r["title"] or "").strip():
                first = next((t for role, t in msgs if role == "user"), "")
                title = (" ".join(first.split())[:80] + " " + title).strip()
            return r["cwd"] or "", title, msgs

        yield {"key": f"hermes:{r['id']}", "sid": r["id"], "fp": f"{r['n']}:{r['last']}",
               "mtime": r["last"], "load": load}
