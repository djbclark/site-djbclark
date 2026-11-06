#!/usr/bin/env python3
"""Prove ovh-api.py signs requests correctly, using a local mock OVH API.

Starts an HTTP server that mimics /auth/time and an echo endpoint, points
ovh-api.py at it, and independently recomputes the expected signature. No network,
no credential, no OVH account needed.
"""
import hashlib
import http.server
import json
import os
import subprocess
import sys
import threading
import time

SECRET = "EXEgWIz07P0HYwtQDs7cNIqCiQaWSuHF"
CONSUMER = "MtSwSrPpNjqfVSmJhLbPyr2i45lSwPU1"
APPKEY = "7kbG7Bk7S9Nt7ZSV"

captured = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the test output clean
        pass

    def do_GET(self):
        if self.path == "/1.0/auth/time":
            body = str(int(time.time())).encode()
        else:
            captured["path"] = self.path
            captured["sig"] = self.headers.get("X-Ovh-Signature")
            captured["ts"] = self.headers.get("X-Ovh-Timestamp")
            captured["app"] = self.headers.get("X-Ovh-Application")
            captured["consumer"] = self.headers.get("X-Ovh-Consumer")
            body = json.dumps({"firstname": "Dan"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    env = dict(os.environ)
    env.update({
        "OVH_APPLICATION_KEY": APPKEY,
        "OVH_APPLICATION_SECRET": SECRET,
        "OVH_CONSUMER_KEY": CONSUMER,
        # ovh-api.py only knows the three real regions, so patch the base by
        # monkeypatching through a temporary copy of the script.
        "OVH_ENDPOINT": "ovh-us",
    })

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ovh-api.py")
    src = open(script).read().replace(
        '"ovh-us": "https://api.us.ovhcloud.com/1.0"',
        f'"ovh-us": "http://127.0.0.1:{port}/1.0"',
    )
    tmp = "/tmp/ovh-api-test-copy.py"
    open(tmp, "w").write(src)

    proc = subprocess.run([sys.executable, tmp, "GET", "/me"], env=env, capture_output=True, text=True)
    srv.shutdown()

    print("stdout:", proc.stdout.strip())
    if proc.returncode != 0:
        print("FAIL: exit", proc.returncode, proc.stderr, file=sys.stderr)
        return 1

    url = f"http://127.0.0.1:{port}/1.0/me"
    expected = "$1$" + hashlib.sha1(
        "+".join([SECRET, CONSUMER, "GET", url, "", captured["ts"]]).encode()
    ).hexdigest()

    checks = [
        ("signature matches an independent recomputation", captured["sig"] == expected),
        ("application key header sent", captured["app"] == APPKEY),
        ("consumer key header sent", captured["consumer"] == CONSUMER),
        ("path is the /1.0 form", captured["path"] == "/1.0/me"),
        ("body parsed as JSON", json.loads(proc.stdout)["firstname"] == "Dan"),
    ]
    ok = True
    for label, passed in checks:
        print(("PASS  " if passed else "FAIL  ") + label)
        ok &= passed

    os.unlink(tmp)
    print("\n" + ("all checks passed" if ok else "FAILURES PRESENT"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
