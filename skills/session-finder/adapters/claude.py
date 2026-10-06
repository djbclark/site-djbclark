"""Claude Code adapter: ~/.claude/projects/*/<sessionId>.jsonl, live registry in ~/.claude/sessions."""
import json
import os
import re
from pathlib import Path

AGENT = "claude"
CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
STRIP = re.compile(r"<(system-reminder|local-command-[a-z]+|command-[a-z]+|pasted_content)\b.*?</\1>", re.S)


def _text(msg):
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _read(path):
    cwd, titles, msgs = "", [], []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            t = d.get("type")
            if t in ("ai-title", "custom-title"):
                title = d.get("aiTitle") or d.get("customTitle")
                if title and title not in titles:
                    titles.append(title)
            elif t in ("user", "assistant"):
                cwd = cwd or d.get("cwd", "")
                text = STRIP.sub(" ", _text(d.get("message", {}))).strip()
                if len(text) > 3:
                    msgs.append((t, text))
    return cwd, (titles[-1] if titles else ""), msgs


def sessions():
    for path in (CLAUDE / "projects").glob("*/*.jsonl"):
        st = path.stat()
        cache = {}

        def load(p=path, c=cache):
            if not c:
                c["v"] = _read(p)
            return c["v"]

        yield {
            "key": f"claude:{path.stem}", "sid": path.stem, "fp": f"{st.st_size}:{int(st.st_mtime)}",
            "mtime": st.st_mtime, "load": load,  # load() -> (cwd, title, [(role, text)])
        }


def live_info():
    """sid -> {pid, procStart, name} for running sessions."""
    out = {}
    for f in (CLAUDE / "sessions").glob("*.json"):
        try:
            d = json.loads(f.read_text())
            os.kill(int(d["pid"]), 0)
            out[d["sessionId"]] = {"pid": int(d["pid"]), "procStart": d.get("procStart", ""), "name": d.get("name", "")}
        except (ValueError, KeyError, OSError):
            pass
    return out


def live():
    out = set()
    for f in (CLAUDE / "sessions").glob("*.json"):
        try:
            d = json.loads(f.read_text())
            os.kill(int(d["pid"]), 0)
            out.add(d["sessionId"])
        except (ValueError, KeyError, OSError):
            pass
    return out
RESUME = "claude --resume {sid}"
