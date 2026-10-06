"""zcode adapter: ~/.zcode/cli/db/db.sqlite (opencode-style session/message/part tables)."""
import json
import sqlite3
from pathlib import Path

AGENT = "zcode"
DB = Path.home() / ".zcode/cli/db/db.sqlite"
RESUME = "cd {cwd} && zcode --resume {sid}"


def _db():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)


def sessions():
    if not DB.exists():
        return
    db = _db()
    rows = db.execute(
        "SELECT s.id, s.time_updated, (SELECT MAX(time_updated) FROM message WHERE session_id=s.id), "
        "s.directory, s.title FROM session s").fetchall()
    db.close()
    for sid, tu, mu, directory, title in rows:
        def load(sid=sid, directory=directory, title=title):
            db = _db()
            msgs = []
            q = ("SELECT json_extract(m.data,'$.role'), json_extract(p.data,'$.text') FROM part p "
                 "JOIN message m ON m.id = p.message_id WHERE p.session_id=? "
                 "AND json_extract(p.data,'$.type')='text' "
                 "AND COALESCE(json_extract(p.data,'$.synthetic'),0)=0 "
                 "ORDER BY m.sequence, m.time_created, p.sequence, p.id")
            for role, text in db.execute(q, (sid,)):
                if role in ("user", "assistant") and text:
                    msgs.append((role, text))
            db.close()
            t = " ".join((title or "").split())
            if not t and msgs:
                t = " ".join(msgs[0][1].split())[:80]
            return directory or "", t, msgs

        yield {"key": f"zcode:{sid}", "sid": sid, "fp": f"{tu}:{mu}", "mtime": (mu or tu or 0) / 1000.0, "load": load}
