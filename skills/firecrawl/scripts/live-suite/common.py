import json, os, plistlib, subprocess, time, urllib.request, urllib.error, socket
ROUTER = os.path.expanduser("~/src/djbclark-ade/bin/firecrawl-router")
PLIST = os.path.expanduser("~/Library/LaunchAgents/com.djbclark.firecrawl-mcp.plist")
_pl = plistlib.load(open(PLIST, "rb")).get("EnvironmentVariables", {})
NEED = ["FIRECRAWL_SELFHOST_URL", "FIRECRAWL_SELFHOST_API_KEY", "FIRECRAWL_ROUTER_SIPB_KEY", "FIRECRAWL_ROUTER_LITELLM_KEY"]
MISSING = [k for k in NEED if not _pl.get(k)]

def spawn(port, logpath, **over):
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "FIRECRAWL_API_KEY": "", "FIRECRAWL_ROUTER_FALLBACK": "off"}
    env.update({k: _pl[k] for k in NEED if k in _pl})
    env.update(over)
    p = subprocess.Popen([ROUTER, "--listen", f"127.0.0.1:{port}", "--open"], env=env,
                         stdout=subprocess.DEVNULL, stderr=open(logpath, "ab"))
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close(); return p
        except OSError:
            time.sleep(0.2)
    p.kill(); raise RuntimeError(f"router on {port} did not start")

def post(port, url, formats, timeout=900, **extra):
    body = json.dumps({"url": url, "maxAge": 0, "formats": formats, **extra}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v2/scrape", body, {"Content-Type": "application/json"})
    t = time.time()
    try:
        r = urllib.request.urlopen(req, timeout=timeout); status, hdr, raw = r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        status, hdr, raw = e.code, dict(e.headers), e.read()
    except Exception as e:
        return {"status": -1, "secs": round(time.time() - t, 1), "hdr": {}, "body": {"exc": repr(e)}}
    try: b = json.loads(raw)
    except Exception: b = {"raw": raw[:300].decode("utf8", "replace")}
    return {"status": status, "secs": round(time.time() - t, 1), "hdr": hdr, "body": b}
