#!/usr/bin/env python3
"""Greptile review gate for lander3 (lead 1e61c979, 2026-11-01; djbclark: free plan, 50 Base reviews/month, budgeted).
Run under `sudo-secretspec run --reason ... -- python3 -I greptile-gate.py CMD PR [REPO DEFAULT_BRANCH]`; prints one JSON line.
  trigger PR  -> {"ok": true} after trigger_code_review (consumes 1 credit when the review completes)
  status PR   -> {"status": "COMPLETED|RUNNING|...|NONE", "id": "...", "created": "...", "score": N|null}
The key comes from the environment (GREPTILE_API_KEY), is sent only as a bearer header, and is never printed."""
import json, os, re, sys, urllib.request

URL = "https://api.greptile.com/mcp"


def mcp(method, params=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {os.environ['GREPTILE_API_KEY']}"})
    with urllib.request.urlopen(req, timeout=45) as r:
        raw = r.read().decode(errors="replace")
    for line in raw.splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip()
    res = json.loads(raw)
    if "error" in res:
        raise RuntimeError(str(res["error"].get("message", "error"))[:200])
    result = res.get("result", {})
    txt = "".join(c.get("text", "") for c in result.get("content", []))
    if result.get("isError"):
        raise RuntimeError(txt[:200])
    try:
        return json.loads(txt)
    except ValueError:
        return {"text": txt}


def tool(name, args):
    return mcp("tools/call", {"name": name, "arguments": args}, rid=2)


def main():
    cmd, pr = sys.argv[1], int(sys.argv[2])
    repo = sys.argv[3] if len(sys.argv) > 3 else "djbclark/djbclark-ade"
    branch = sys.argv[4] if len(sys.argv) > 4 else "master"
    mcp("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "lander3-greptile-gate", "version": "1"}})
    target = {"name": repo, "remote": "github", "defaultBranch": branch, "prNumber": pr}
    if cmd == "trigger":
        tool("trigger_code_review", target)
        print(json.dumps({"ok": True}))
        return
    if cmd == "status":
        r = tool("list_code_reviews", {**{k: v for k, v in target.items()}, "limit": 5})
        items = r.get("codeReviews", []) if isinstance(r, dict) else []
        if not items:
            print(json.dumps({"status": "NONE"}))
            return
        x = items[0]
        out = {"status": x.get("status"), "id": str(x.get("id")), "created": x.get("createdAt"), "score": None}
        if out["status"] == "COMPLETED" and out["id"]:
            body = tool("get_code_review", {"codeReviewId": out["id"]}).get("codeReview", {}).get("body", "") or ""
            m = re.search(r"Confidence Score:\s*(\d)\s*/\s*5", body)
            out["score"] = int(m.group(1)) if m else None
        print(json.dumps(out))
        return
    raise SystemExit(f"unknown command {cmd}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # one JSON line either way; the key is never part of an error text here
        print(json.dumps({"error": type(e).__name__, "detail": str(e)[:200]}))
        sys.exit(1)
