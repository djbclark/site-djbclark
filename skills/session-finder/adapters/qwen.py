"""Qwen Code adapter: ~/.qwen/projects/<slug>/chats/<sessionId>.jsonl (parts-based messages)."""
import json
from pathlib import Path

AGENT = "qwen"
RESUME = "qwen --resume {sid}"
ROOT = Path.home() / ".qwen" / "projects"


def _read(path):
    cwd, msgs = "", []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            t = d.get("type")
            if t not in ("user", "assistant"):
                continue
            cwd = cwd or d.get("cwd", "")
            if t == "user" and d.get("provenance") not in (None, "real_user"):
                continue
            parts = (d.get("message") or {}).get("parts") or []
            text = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought")).strip()
            if len(text) > 3:
                msgs.append((t, text))
    first = next((x for r, x in msgs if r == "user"), "")
    return cwd, " ".join(first.split())[:80], msgs


def sessions():
    for path in ROOT.glob("*/chats/*.jsonl"):
        st = path.stat()
        yield {"key": f"qwen:{path.stem}", "sid": path.stem, "fp": f"{st.st_size}:{int(st.st_mtime)}",
               "mtime": st.st_mtime, "load": lambda p=path: _read(p)}
