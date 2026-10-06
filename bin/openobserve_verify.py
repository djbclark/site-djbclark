#!/usr/bin/env python3
"""OpenObserve upgrade verification — run before and after, then diff.

Usage:
  python3 oo_verify.py --out baseline.json      # on the old version
  python3 oo_verify.py --out after.json         # on the new version
  python3 oo_verify.py --compare baseline.json after.json

Every check is read-only except INGEST, which writes one record to a
dedicated throwaway stream (`upgrade_probe`) and reads it back.
"""
from __future__ import annotations
import argparse, base64, json, plistlib, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

PLIST = Path.home() / "Library/LaunchAgents/com.djbclark.openobserve.plist"
DATA = Path.home() / ".local/share/openobserve/data/data/openobserve"
BASE = "http://127.0.0.1:5080"


def creds() -> tuple[str, str, str]:
    env = plistlib.loads(PLIST.read_bytes())["EnvironmentVariables"]
    return env["ZO_ROOT_USER_EMAIL"], env["ZO_ROOT_USER_PASSWORD"], env.get("ZO_BASE_URI", "")


def req(path: str, email: str, pw: str, *, data: bytes | None = None, auth: bool = True, timeout: int = 30):
    r = urllib.request.Request(BASE + path, data=data, method="POST" if data else "GET")
    if auth:
        tok = base64.b64encode(f"{email}:{pw}".encode()).decode()
        r.add_header("Authorization", "Basic " + tok)
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def collect() -> dict:
    email, pw, base_uri = creds()
    out: dict = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "base_uri": base_uri, "checks": {}}
    c = out["checks"]

    # 1. process + launchd
    p = subprocess.run(["pgrep", "-f", "/openobserve"], capture_output=True, text=True)
    c["process_running"] = bool(p.stdout.strip())
    b = subprocess.run([str(Path.home() / ".local/bin/openobserve"), "--version"], capture_output=True, text=True)
    c["binary_version"] = b.stdout.strip() or b.stderr.strip()

    # 2. health must be 200 at the base-URI-prefixed path
    st, _ = req(f"{base_uri}/healthz", email, pw)
    c["healthz_status"] = st

    # 3. version via /config — documented to stop exposing internals after 1.0.0
    st, body = req(f"{base_uri}/config", email, pw)
    c["config_status"] = st
    try:
        c["config_version"] = json.loads(body).get("version")
    except Exception:  # noqa: BLE001
        c["config_version"] = None

    # 4. auth actually enforced
    st, _ = req(f"{base_uri}/api/default/streams", email, pw, auth=False)
    c["unauth_streams_status"] = st
    c["auth_enforced"] = st in (401, 403)

    # 5. streams + doc counts per org
    c["streams"] = {}
    for org in ("default", "_meta"):
        st, body = req(f"{base_uri}/api/{org}/streams", email, pw)
        rows = {}
        try:
            for s in json.loads(body).get("list", []):
                rows[s.get("name")] = {
                    "type": s.get("stream_type"),
                    "docs": (s.get("stats") or {}).get("doc_num", 0),
                }
        except Exception:  # noqa: BLE001
            pass
        c["streams"][org] = {"status": st, "rows": rows}

    # 6. search returns rows for each real stream
    c["search"] = {}
    now = int(time.time() * 1_000_000)
    start = now - 7 * 24 * 3600 * 1_000_000
    for org, stream in (("default", "android_logs"), ("default", "soft_health"), ("_meta", "usage")):
        q = json.dumps({"query": {
            "sql": f'SELECT * FROM "{stream}" LIMIT 5',
            "start_time": start, "end_time": now, "from": 0, "size": 5,
        }}).encode()
        st, body = req(f"{base_uri}/api/{org}/_search", email, pw, data=q)
        n = None
        try:
            n = len(json.loads(body).get("hits", []))
        except Exception:  # noqa: BLE001
            pass
        c["search"][f"{org}/{stream}"] = {"status": st, "hits": n}

    # 7. the exact Prometheus path Grafana's datasource uses
    st, body = req(f"{base_uri}/api/default/prometheus/api/v1/query?query=up", email, pw)
    c["prometheus_query"] = {"status": st, "ok": '"status":"success"' in body}

    # 8. ingest round-trip into a throwaway stream
    rec = json.dumps([{"level": "info", "msg": "upgrade_probe", "probe_id": str(now)}]).encode()
    st, _ = req(f"{base_uri}/api/default/upgrade_probe/_json", email, pw, data=rec)
    c["ingest_status"] = st
    found = 0
    for _ in range(12):
        time.sleep(5)
        q = json.dumps({"query": {
            "sql": f"SELECT * FROM \"upgrade_probe\" WHERE probe_id = '{now}'",
            "start_time": now - 60 * 1_000_000, "end_time": int(time.time() * 1_000_000) + 60_000_000,
            "from": 0, "size": 5,
        }}).encode()
        st2, body2 = req(f"{base_uri}/api/default/_search", email, pw, data=q)
        try:
            found = len(json.loads(body2).get("hits", []))
        except Exception:  # noqa: BLE001
            found = 0
        if found:
            break
    c["ingest_roundtrip_hits"] = found

    # 9. on-disk layout
    c["disk"] = {d: (DATA / d).is_dir() for d in ("db", "stream", "wal", "remote_stream_wal", "mmdb")}
    c["pending_wal_files"] = len(list((DATA / "wal").rglob("*.wal")))
    c["sqlite_wal_bytes"] = (DATA / "db/metadata.sqlite-wal").stat().st_size if (DATA / "db/metadata.sqlite-wal").exists() else 0

    # 10. vector is still delivering
    v = subprocess.run(["pgrep", "-f", "vector"], capture_output=True, text=True)
    c["vector_running"] = bool(v.stdout.strip())
    return out


FATAL = ("healthz_status", "auth_enforced", "process_running")


def verdict(d: dict) -> list[str]:
    c, bad = d["checks"], []
    if c.get("healthz_status") != 200:
        bad.append(f"healthz != 200 (got {c.get('healthz_status')})")
    if not c.get("auth_enforced"):
        bad.append(f"auth NOT enforced (unauth streams -> {c.get('unauth_streams_status')})")
    if not c.get("process_running"):
        bad.append("openobserve process not running")
    if c.get("ingest_status") not in (200,):
        bad.append(f"ingest rejected ({c.get('ingest_status')})")
    if not c.get("ingest_roundtrip_hits"):
        bad.append("ingested record never became searchable")
    if not c.get("prometheus_query", {}).get("ok"):
        bad.append("prometheus /query (Grafana's path) not returning success")
    for k, v in c.get("search", {}).items():
        if v.get("status") != 200:
            bad.append(f"search {k} status {v.get('status')}")
    for d_, ok in c.get("disk", {}).items():
        if not ok and d_ != "remote_stream_wal":
            bad.append(f"data dir missing: {d_}")
    return bad


def compare(a: dict, b: dict) -> int:
    rc, ac, bc = 0, a["checks"], b["checks"]
    print(f"version:  {ac.get('binary_version')}  ->  {bc.get('binary_version')}")
    for org in ("default", "_meta"):
        ar = ac.get("streams", {}).get(org, {}).get("rows", {})
        br = bc.get("streams", {}).get(org, {}).get("rows", {})
        for name, av in sorted(ar.items()):
            bv = br.get(name)
            if bv is None:
                print(f"  LOST   {org}/{name} (had {av['docs']} docs)"); rc = 1
            elif bv["docs"] < av["docs"]:
                print(f"  SHRANK {org}/{name}: {av['docs']} -> {bv['docs']}"); rc = 1
            else:
                print(f"  ok     {org}/{name}: {av['docs']} -> {bv['docs']}")
        for name in sorted(set(br) - set(ar)):
            print(f"  new    {org}/{name}: {br[name]['docs']} docs")
    bad = verdict(b)
    if bad:
        rc = 1
        print("\nFAILED CHECKS on the new version:")
        for x in bad:
            print("  -", x)
    else:
        print("\nAll functional checks pass on the new version.")
    if bc.get("config_status") != 200 or not bc.get("config_version"):
        print("note: /config no longer reports the version — expected, removed in 1.0.0.")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    a = ap.parse_args()
    if a.compare:
        return compare(json.loads(Path(a.compare[0]).read_text()), json.loads(Path(a.compare[1]).read_text()))
    d = collect()
    txt = json.dumps(d, indent=2)
    if a.out:
        Path(a.out).write_text(txt)
    print(txt)
    bad = verdict(d)
    print("\nVERDICT:", "OK" if not bad else "PROBLEMS: " + "; ".join(bad), file=sys.stderr)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
