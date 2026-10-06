"""Cursor adapter: cursor-agent chats (~/.cursor/chats/*/<agentId>/store.db) and
IDE agent transcripts (~/.cursor/projects/*/agent-transcripts/<id>/<id>.jsonl)."""
import json
import re
import sqlite3
from pathlib import Path

AGENT = "cursor"
RESUME = "cursor-agent --resume {sid}   (CLI chats only; IDE transcripts open in the Cursor app)"
ROOT = Path.home() / ".cursor"
QUERY = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.S)


def _clean(role, text):
    if role == "user":
        m = QUERY.search(text)
        if m:
            text = m.group(1)
        elif text.lstrip().startswith("<"):
            return ""
    return text.strip()


def _blocks(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _title(msgs, cwd):
    return next((t[:80].replace("\n", " ") for r, t in msgs if r == "user"), "")


def _load_chat(store, meta):
    def load():
        cwd = ""
        try:
            cwd = json.loads(meta.read_text()).get("cwd", "")
        except (OSError, ValueError):
            pass
        con = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
        msgs = []
        for (data,) in con.execute("SELECT data FROM blobs ORDER BY rowid"):
            if not data.startswith(b'{"role"'):
                continue
            try:
                d = json.loads(data)
            except ValueError:
                continue
            role = d.get("role")
            if role in ("user", "assistant"):
                t = _clean(role, _blocks(d.get("content")))
                if t:
                    msgs.append((role, t))
        con.close()
        return cwd, _title(msgs, cwd), msgs
    return load


def _load_transcript(path, slug):
    def load():
        msgs = []
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                role = d.get("role")
                if role in ("user", "assistant"):
                    t = _clean(role, _blocks(d.get("message", {}).get("content")))
                    if t:
                        msgs.append((role, t))
        return "/" + slug.replace("-", "/"), _title(msgs, ""), msgs
    return load


def sessions():
    chat_ids = set()
    for store in (ROOT / "chats").glob("*/*/store.db"):
        sid = store.parent.name
        st = store.stat()
        chat_ids.add(sid)
        yield {"key": f"cursor:{sid}", "sid": sid, "fp": f"{st.st_size}:{int(st.st_mtime)}", "mtime": st.st_mtime,
               "load": _load_chat(store, store.parent / "meta.json")}
    for path in (ROOT / "projects").glob("*/agent-transcripts/*/*.jsonl"):
        sid = path.stem
        if sid in chat_ids:
            continue
        st = path.stat()
        yield {"key": f"cursor:{sid}", "sid": sid, "fp": f"{st.st_size}:{int(st.st_mtime)}", "mtime": st.st_mtime,
               "load": _load_transcript(path, path.parent.parent.parent.name)}
