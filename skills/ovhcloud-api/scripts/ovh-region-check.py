#!/usr/bin/env python3
"""Diagnose which OVH API region accepts this credential. READ-ONLY: only /me is called.

"The application key is invalid" on one region and not another means the key belongs to a
different region's API, not that the rights are wrong. This tries all three endpoints and
reports each status, without printing any value.

    sudo-secretspec run --reason R -- python3 -I ovh-region-check.py
"""
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

ENDPOINTS = {
    "ovh-us": "https://api.us.ovhcloud.com/1.0",
    "ovh-ca": "https://ca.api.ovh.com/1.0",
    "ovh-eu": "https://eu.api.ovh.com/1.0",
}


def probe(name: str, base: str, ak: str, as_: str, ck: str) -> str:
    # Unauthenticated time call first: proves reachability separately from auth.
    try:
        with urllib.request.urlopen(f"{base}/auth/time", timeout=20) as r:
            delta = int(r.read().decode()) - int(time.time())
    except Exception as e:  # noqa: BLE001
        return f"unreachable ({type(e).__name__})"

    now = str(int(time.time()) + delta)
    url = base + "/me"
    sig = "$1$" + hashlib.sha1("+".join([as_, ck, "GET", url, "", now]).encode()).hexdigest()
    req = urllib.request.Request(url)
    req.add_header("X-Ovh-Application", ak)
    req.add_header("X-Ovh-Consumer", ck)
    req.add_header("X-Ovh-Timestamp", now)
    req.add_header("X-Ovh-Signature", sig)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode() or "{}")
            return f"200 ACCEPTED  (account: {body.get('nichandle', '?')})"
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        try:
            msg = json.loads(detail).get("message", detail)
        except Exception:  # noqa: BLE001
            msg = detail
        return f"{e.code} {msg[:90]}"


def main() -> int:
    try:
        ak = os.environ["OVH_APPLICATION_KEY"]
        as_ = os.environ["OVH_APPLICATION_SECRET"]
        ck = os.environ["OVH_CONSUMER_KEY"]
    except KeyError as e:
        print(f"{e.args[0]} is not set", file=sys.stderr)
        return 2

    print(f"credential: AK len={len(ak)}, AS len={len(as_)}, CK len={len(ck)}")
    print(f"declared OVH_ENDPOINT={os.environ.get('OVH_ENDPOINT', '(unset)')}\n")
    for name, base in ENDPOINTS.items():
        print(f"  {name:8} {base:32} {probe(name, base, ak, as_, ck)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
