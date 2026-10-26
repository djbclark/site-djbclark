#!/usr/bin/env python3
"""Point a Dyn (dyndns2) hostname at an IP. Reports the documented return code; changes nothing else.

WHY THIS IS CAREFUL:
  * The key is a client-updater key: it can UPDATE an existing hostname's IP but cannot CREATE one
    (`nohost` = "the hostname does not exist in this account"). Verified 2026-10-25.
  * `nochg` means the IP already matches. Dyn treats REPEATED nochg as abuse and can block the
    hostname, so this refuses to send an update whose IP already matches — it checks DNS first.
  * It never prints the key.

    sudo-secretspec run --reason R -- python3 -I dyn-update.py set host.example.org 203.0.113.10
    # an INTERNAL-ONLY name needs the explicit override (it is a DNS-rebinding hazard otherwise):
    sudo-secretspec run --reason R -- python3 -I dyn-update.py set internal.example.org 192.168.1.10 --allow-private
    sudo-secretspec run --reason R -- python3 -I dyn-update.py check host.example.org

The key comes from the environment (DYNDNS_UPDATE_KEY). The account name comes from DYNDNS_USER,
else the local login name; set DYNDNS_USER when they differ.
"""
import base64
import getpass
import ipaddress
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

USER = os.environ.get("DYNDNS_USER") or getpass.getuser()
UA = "dann-keeper - dyn-update - 1.0"          # Dyn requires: company - model - version
ENDPOINT = "https://members.dyndns.org/v3/update"


def current_ips(hostname: str) -> list[str]:
    """What the public resolvers currently say. Used to avoid a pointless `nochg`."""
    try:
        out = subprocess.run(["dig", "+short", "A", hostname, "@1.1.1.1"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return []
    return [l.strip() for l in out.splitlines()
            if l.strip() and l.strip().replace(".", "").isdigit()]


def call(hostname: str, ip: str) -> tuple[int, str]:
    key = os.environ.get("DYNDNS_UPDATE_KEY", "").strip()
    if not key:
        return 0, "DYNDNS_UPDATE_KEY not set (run under sudo-secretspec run)"
    url = f"{ENDPOINT}?hostname={hostname}&myip={ip}"
    auth = base64.b64encode(f"{USER}:{key}".encode()).decode()
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("User-Agent", UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode(errors="replace").strip()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace").strip()
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


EXPLAIN = {
    "good": "updated",
    "nochg": "already correct (no change sent)",
    "nohost": "hostname does not exist in this account - create it in the Dyn panel first",
    "notfqdn": "not a fully qualified domain name",
    "badauth": "bad username or key",
    "abuse": "hostname is BLOCKED for update abuse",
    "numhost": "too many/ambiguous hostnames",
    "911": "Dyn-side temporary problem - retry later, do not hammer",
    "dnserr": "Dyn DNS-side failure - contact support if it persists",
}


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    verb, hostname = sys.argv[1], sys.argv[2]

    if verb == "check":
        print(json.dumps({"hostname": hostname, "public_a": current_ips(hostname)}, indent=1))
        return 0
    if verb != "set":
        print(f"unknown verb {verb!r}; use set|check", file=sys.stderr)
        return 2

    if len(sys.argv) < 4:
        print("set needs an IP", file=sys.stderr)
        return 2
    allow_private = "--allow-private" in sys.argv
    ip = sys.argv[3]
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        print(f"{ip!r} is not an IP address", file=sys.stderr)
        return 2
    if addr.is_private or not addr.is_global:
        # The guard exists because a private address was once published in public DNS by accident.
        # An INTERNAL-ONLY name is a legitimate deliberate choice though (a name pointing at a
        # router-pinned LAN address on purpose), so the override is explicit and loud
        # rather than the guard being removed.
        if not allow_private:
            print(f"REFUSED: {ip} is not a publicly routable address "
                  f"(is_private={addr.is_private}, is_global={addr.is_global}). "
                  f"Publishing a private address in public DNS is a DNS-rebinding hazard. "
                  f"If this is a DELIBERATE internal-only name, re-run with --allow-private.",
                  file=sys.stderr)
            return 2
        print(f"WARNING: publishing the private address {ip} for {hostname} because "
              f"--allow-private was given. This name is reachable only from the network that owns "
              f"that address, and it is a DNS-rebinding hazard for anyone else who resolves it.",
              file=sys.stderr)

    now = current_ips(hostname)
    if ip in now:
        print(f"{hostname}: already {ip} (public DNS agrees) - sending nothing, to avoid an "
              f"unnecessary nochg (repeated nochg is treated as abuse by Dyn)")
        return 0

    status, body = call(hostname, ip)
    first = body.split()[0] if body else ""
    print(f"{hostname} -> {ip}: HTTP {status} {body!r}  [{EXPLAIN.get(first, 'unrecognised')}]")
    print(f"  was: {now or 'no public A record'}")
    return 0 if first in ("good", "nochg") else 1


if __name__ == "__main__":
    sys.exit(main())
