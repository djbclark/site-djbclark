"""opencode adapter: ~/.local/share/opencode/opencode.db (session / message / part tables)."""
import json
import sqlite3
from pathlib import Path

AGENT = "opencode"
RESUME = "cd {cwd} && opencode --session {sid}"
DB = Path.home() / ".local/share/opencode/opencode.db"


def _ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def sessions():
    if not DB.is_file():
        return
    try:
        con = _ro()
        rows = con.execute("SELECT id, title, directory, time_updated FROM session").fetchall()
        con.close()
    except sqlite3.Error:
        return
    for sid, title, cwd, upd in rows:
        def load(sid=sid, title=title, cwd=cwd):
            con = _ro()
            roles = {}
            for mid, data in con.execute("SELECT id, data FROM message WHERE session_id=?", (sid,)):
                try:
                    roles[mid] = json.loads(data).get("role")
                except ValueError:
                    pass
            msgs = []
            for mid, data in con.execute(
                    "SELECT message_id, data FROM part WHERE session_id=? ORDER BY time_created, id", (sid,)):
                try:
                    p = json.loads(data)
                except ValueError:
                    continue
                if p.get("type") == "text" and not p.get("synthetic") and roles.get(mid) in ("user", "assistant"):
                    t = (p.get("text") or "").strip()
                    if t:
                        msgs.append((roles[mid], t))
            con.close()
            if not title or title.startswith("New session"):
                title = next((t[:80] for r, t in msgs if r == "user"), title or "")
            return cwd, title, msgs

        yield {"key": f"opencode:{sid}", "sid": sid, "fp": str(upd), "mtime": upd / 1000, "load": load}
