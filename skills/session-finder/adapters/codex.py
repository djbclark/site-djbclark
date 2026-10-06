"""Codex adapter: ~/.codex/sessions/YYYY/MM/DD/rollout-*-<id>.jsonl; titles from ~/.codex/session_index.jsonl."""
import json
import os
import re
from pathlib import Path

AGENT = "codex"
RESUME = "codex resume {sid}"
HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
SKIP_PREFIX = ("<environment_context", "<user_instructions", "<INSTRUCTIONS", "<permissions", "<collaboration_mode",
               "<skills_instructions", "<recommended_skills", "# AGENTS.md instructions", "<turn_aborted")


def _titles():
    out = {}
    try:
        for line in (HOME / "session_index.jsonl").read_text(errors="replace").splitlines():
            try:
                d = json.loads(line)
                out[d["id"]] = d.get("thread_name") or ""
            except (ValueError, KeyError):
                pass
    except OSError:
        pass
    return out


def _read(path, title):
    cwd, msgs = "", []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"session_meta"' not in line and '"type":"message"' not in line and '"type": "message"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            p = d.get("payload") or {}
            if d.get("type") == "session_meta":
                cwd = cwd or p.get("cwd", "")
            elif d.get("type") == "response_item" and p.get("type") == "message" and p.get("role") in ("user", "assistant"):
                text = "\n".join(b.get("text", "") for b in p.get("content", []) if isinstance(b, dict)).strip()
                if len(text) > 3 and not (p["role"] == "user" and text.startswith(SKIP_PREFIX)):
                    msgs.append((p["role"], text))
    if not title:
        first = next((t for r, t in msgs if r == "user"), "")
        title = " ".join(re.sub(r"<[^>]+>", " ", first).split())[:80]
    return cwd, title, msgs


def sessions():
    titles = _titles()
    for path in (HOME / "sessions").glob("*/*/*/rollout-*.jsonl"):
        sid = path.stem[-36:]
        st = path.stat()

        def load(p=path, t=titles.get(sid, "")):
            return _read(p, t)

        yield {"key": f"codex:{sid}", "sid": sid, "fp": f"{st.st_size}:{int(st.st_mtime)}:{titles.get(sid, '')}",
               "mtime": st.st_mtime, "load": load}
