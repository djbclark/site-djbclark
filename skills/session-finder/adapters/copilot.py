"""GitHub Copilot CLI adapter: ~/.copilot/session-state/<id>/{events.jsonl,workspace.yaml}; live = inuse.<pid>.lock with a running pid."""
import json
import os
import re
from pathlib import Path

AGENT = "copilot"
RESUME = "copilot --resume={sid}"
ROOT = Path.home() / ".copilot" / "session-state"


def _yaml(path):
    out = {}
    try:
        for line in path.read_text(errors="replace").splitlines():
            m = re.match(r"^(cwd|name|summary): (.*)$", line)
            if m:
                out[m.group(1)] = m.group(2).strip().strip("'\"")
    except OSError:
        pass
    return out


def _read(d):
    meta = _yaml(d / "workspace.yaml")
    msgs = []
    ev = d / "events.jsonl"
    if ev.exists():
        with ev.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"user.message"' not in line[:40] and '"assistant.message"' not in line[:40]:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                text = ((r.get("data") or {}).get("content") or "").strip()
                if len(text) > 3:
                    msgs.append(("user" if r["type"] == "user.message" else "assistant", text))
    title = meta.get("name") or meta.get("summary") or ""
    if not msgs and title:
        msgs.append(("user", title))
    if not title:
        title = " ".join(next((t for r, t in msgs if r == "user"), "").split())[:80]
    return meta.get("cwd", ""), title, msgs


def sessions():
    for d in ROOT.iterdir():
        if not d.is_dir():
            continue
        ev, ws = d / "events.jsonl", d / "workspace.yaml"
        try:
            st = ev.stat() if ev.exists() else ws.stat()
            fp = f"{st.st_size}:{int(st.st_mtime)}"
        except OSError:
            continue
        yield {"key": f"copilot:{d.name}", "sid": d.name, "fp": fp, "mtime": st.st_mtime, "load": lambda p=d: _read(p)}


def live():
    out = set()
    for lock in ROOT.glob("*/inuse.*.lock"):
        try:
            os.kill(int(lock.name.split(".")[1]), 0)
            out.add(lock.parent.name)
        except (ValueError, OSError):
            pass
    return out
