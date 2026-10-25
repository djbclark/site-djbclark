#!/usr/bin/env python3
"""Sign and make one OVHcloud API call, with the read-only-plus-frozen rule enforced.

Reads OVH_APPLICATION_KEY / OVH_APPLICATION_SECRET / OVH_CONSUMER_KEY / OVH_ENDPOINT
from the environment (run it under `sudo-secretspec run`), signs the request the way
OVH documents, and prints the JSON response.

Usage:
    sudo-secretspec run --reason R -- python3 ovh-api.py GET /me
    sudo-secretspec run --reason R -- python3 ovh-api.py GET /vps
    sudo-secretspec run --reason R -- python3 ovh-api.py --allow-write POST /vps/x/reboot

Safety, in code rather than in memory:
  * a non-GET method is refused unless --allow-write is given;
  * a billable path (/order, /cart, /billing, /payment, /refund, /credit) is refused
    unless --allow-billable is given as well.
Exit 0 on HTTP 2xx, 1 on an HTTP error, 2 on a usage/guard refusal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

# From ovh/client.py ENDPOINTS. A key is region-locked, so this must match the
# page the credential was created on.
ENDPOINTS = {
    "ovh-us": "https://api.us.ovhcloud.com/1.0",
    "ovh-eu": "https://eu.api.ovh.com/1.0",
    "ovh-ca": "https://ca.api.ovh.com/1.0",
}

BILLABLE = ("/order", "/cart", "/billing", "/payment", "/refund", "/credit")


def fail(msg: str) -> int:
    print(f"ovh-api: {msg}", file=sys.stderr)
    return 2


def _probe_region(base: str, ak: str, ck: str, as_: str) -> str:
    """Ask one region whether it accepts this credential, via /me (read-only).

    Returns '200 ACCEPTED' or 'NNN <message>'. Never raises: a failure here is itself the answer.
    """
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
            r.read()
            return "200 ACCEPTED"
    except urllib.error.HTTPError as e:
        try:
            return f"{e.code} {json.loads(e.read().decode()).get('message', '')[:60]}"
        except Exception:  # noqa: BLE001
            return f"{e.code} {e.reason}"
    except Exception as e:  # noqa: BLE001
        return f"failed ({type(e).__name__})"


def main() -> int:
    p = argparse.ArgumentParser(description="One signed OVHcloud API call.")
    p.add_argument("method", help="HTTP method, e.g. GET")
    p.add_argument("path", help="API path, e.g. /vps or /me")
    p.add_argument("body", nargs="?", help="JSON body for POST/PUT")
    p.add_argument("--allow-write", action="store_true",
                   help="permit a non-GET method (the read-only default is deliberate)")
    p.add_argument("--allow-billable", action="store_true",
                   help="permit a billable path; needs a fresh explicit yes per action")
    a = p.parse_args()

    method = a.method.upper()

    if method != "GET" and not a.allow_write:
        return fail(f"{method} refused: only GET is allowed by default "
                    "(pass --allow-write once the operator has said yes)")
    if any(a.path.startswith(b) for b in BILLABLE) and not a.allow_billable:
        return fail(f"{a.path} refused: billable path. This token can order and bill, so it needs "
                    "a fresh explicit yes per action (pass --allow-billable only after that yes)")

    try:
        ak = os.environ["OVH_APPLICATION_KEY"]
        as_ = os.environ["OVH_APPLICATION_SECRET"]
        ck = os.environ["OVH_CONSUMER_KEY"]
        endpoint_name = os.environ.get("OVH_ENDPOINT", "ovh-us")
    except KeyError as e:
        return fail(f"{e.args[0]} is not set; run this under `sudo-secretspec run`")

    if endpoint_name not in ENDPOINTS:
        return fail(f"unknown OVH_ENDPOINT {endpoint_name!r}; known: {', '.join(ENDPOINTS)}")
    endpoint = ENDPOINTS[endpoint_name]

    # /v1 and /v2 drop the /1.0, and the signature must cover the final URL.
    base = endpoint[:-4] if a.path.startswith(("/v1", "/v2")) else endpoint
    url = base + a.path

    body = ""
    if a.body:
        body = json.dumps(json.loads(a.body), separators=(",", ":"))

    # OVH's clock may differ from ours; ask for the delta first (this call needs no auth).
    try:
        with urllib.request.urlopen(f"{base}/auth/time", timeout=30) as r:
            delta = int(r.read().decode()) - int(time.time())
    except Exception as e:  # noqa: BLE001 - any failure here is fatal and worth showing
        return fail(f"could not read the API time (is the endpoint reachable?): {e}")

    now = str(int(time.time()) + delta)
    signature = "$1$" + hashlib.sha1(
        "+".join([as_, ck, method, url, body, now]).encode("utf-8")
    ).hexdigest()

    req = urllib.request.Request(url, method=method, data=body.encode() or None)
    req.add_header("X-Ovh-Application", ak)
    req.add_header("X-Ovh-Consumer", ck)
    req.add_header("X-Ovh-Timestamp", now)
    req.add_header("X-Ovh-Signature", signature)
    if body:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print(json.dumps(json.loads(r.read().decode() or "null"), indent=2))
            return 0
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        print(f"HTTP {e.code} {e.reason}\n{detail}", file=sys.stderr)
        # Name the two failures people misread as network problems.
        if e.code == 403 and "NOT_GRANTED_CALL" in detail:
            print("hint: the credential's rights do not cover this call "
                  "(a missing Rights row; `*` does not include the parent path)", file=sys.stderr)
        elif e.code == 401 or "application key is invalid" in detail.lower():
            # A wrong OVH_ENDPOINT produces exactly this, and it reads like a rights failure.
            # Test the credential against all three regions so the answer is evidence, not a guess.
            print("hint: this usually means OVH_ENDPOINT names the wrong region for this credential.\n"
                  "      Testing all three regions with /me (read-only):", file=sys.stderr)
            for name, base_url in ENDPOINTS.items():
                if name == endpoint_name:
                    continue
                status = _probe_region(base_url, ak, ck, as_)
                mark = "  <-- try this one" if status.startswith("200") else ""
                print(f"        {name:8} {status}{mark}", file=sys.stderr)
            print(f"      Your OVH_ENDPOINT is {endpoint_name!r}. Fix it with:\n"
                  f"        printf '<region>' | sudo-secretspec set OVH_ENDPOINT --reason '...'",
                  file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
