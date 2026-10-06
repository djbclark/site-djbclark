"""Crush adapter: per-project SQLite DBs listed in ~/.local/share/crush/projects.json (data_dir/crush.db)."""
import json
import re
import sqlite3
from pathlib import Path

AGENT = "crush"
RESUME = "cd {cwd} && crush --session {sid}"
PROJECTS = Path.home() / ".local/share/crush/projects.json"
CWD_TAG = re.compile(r"<cwd>(.*?)</cwd>")


def _dbs():
    seen = {}
    try:
        for p in json.loads(PROJECTS.read_text()).get("projects", []):
            db = Path(p["data_dir"]) / "crush.db"
            if db.is_file() and db.stat().st_size:
                seen[str(db)] = p["path"]
    except (OSError, ValueError, KeyError):
        pass
    return seen


def _ro(db):
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def _texts(parts_json):
    try:
        parts = json.loads(parts_json)
    except ValueError:
        return ""
    return "\n".join(
        p["data"].get("text", "") for p in parts
        if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("data"), dict)
    )


def sessions():
    for db, proj in _dbs().items():
        try:
            con = _ro(db)
            rows = con.execute("SELECT id, title, message_count, updated_at FROM sessions").fetchall()
            con.close()
        except sqlite3.Error:
            continue
        for sid, title, n, upd in rows:
            def load(db=db, sid=sid, title=title, proj=proj):
                con = _ro(db)
                msgs = []
                for role, parts in con.execute(
                        "SELECT role, parts FROM messages WHERE session_id=? ORDER BY created_at", (sid,)):
                    if role in ("user", "assistant"):
                        text = _texts(parts).strip()
                        if text:
                            msgs.append((role, text))
                con.close()
                return proj, title or (msgs[0][1][:80] if msgs else ""), msgs

            ts = upd / 1000 if upd > 1e11 else upd
            yield {"key": f"crush:{sid}", "sid": sid, "fp": f"{n}:{upd}", "mtime": float(ts), "load": load}
