#!/usr/bin/env python3
"""tcc_audit -- find macOS privacy (TCC) grants that no longer work, and clean up old ones.

Why: a TCC grant is bound to the code requirement (csreq) captured when it was
granted. Re-sign or rebuild an ad-hoc-signed binary and the requirement (a cdhash)
stops matching: System Settings still shows the toggle ON, tccd silently denies.
Homebrew upgrades leave the same mess behind as rows for Cellar/<name>/<old-version>/
paths that no longer exist. `tccutil reset` cannot remove path-client rows at all
(it only accepts bundle ids of installed apps), so nothing cleans these up.

What it does (read-only against TCC.db; needs Full Disk Access to read the system db):
  * stale    -- row's binary exists but no longer satisfies its stored csreq
                (re-signed / rebuilt / updated): needs the grant removed and re-added.
  * orphan   -- row's binary/app is gone (old Cellar versions, uninstalled apps).
  * missing  -- a grant listed in ~/.config/tcc-audit/expected.json that has no row.
  * health   -- the TCC db cannot be read (this process lacks Full Disk Access).
  * dupes    -- same service + basename with >1 row (informational, for cleanup).

Usage:
  tcc_audit.py                 cron mode: print only NEW problems (or a weekly digest); silent when clean
  tcc_audit.py --all           print the full audit now, regardless of state
  tcc_audit.py --json          machine-readable audit
  tcc_audit.py --cleanup-script [--include-stale] [--include-apps]
                               print a root shell script that backs up TCC.db and deletes orphaned
                               path rows (plus, optionally, stale rows and rows for apps that
                               LaunchServices cannot find). Review it, then run with sudo.
  --db PATH ...                audit a copy of a TCC.db (testing)

expected.json: [{"path": "~/.local/bin/plocate-updatedb", "services": ["SystemPolicyAllFiles"]}]
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
SYSTEM_DB = "/Library/Application Support/com.apple.TCC/TCC.db"
USER_DB = str(HOME / "Library/Application Support/com.apple.TCC/TCC.db")
STATE_PATH = HOME / ".local/state/tcc-audit/state.json"
EXPECTED_PATH = HOME / ".config/tcc-audit/expected.json"
DIGEST_EVERY = 7 * 86400

# auth_value: 0 denied, 1 unknown, 2 allowed, 3 limited
ALLOWED = (2, 3)


def short(service):
    return service.replace("kTCCService", "")


def run(cmd, stdin=None, timeout=30):
    return subprocess.run(cmd, input=stdin, capture_output=True, timeout=timeout)


def read_rows(db):
    """Rows from one TCC.db. Raises sqlite3.Error / OSError if unreadable."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cur = con.execute(
            "SELECT service, client, client_type, auth_value, csreq, last_modified FROM access"
        )
        return [
            dict(service=s, client=c, client_type=t, auth=a, csreq=q, modified=m, db=db)
            for s, c, t, a, q, m in cur
        ]
    finally:
        con.close()


_csreq_cache = {}


def csreq_text(blob):
    if not blob:
        return None
    key = bytes(blob)
    if key not in _csreq_cache:
        p = run(["csreq", "-r-", "-t"], stdin=key)
        _csreq_cache[key] = p.stdout.decode().strip() if p.returncode == 0 else None
    return _csreq_cache[key]


LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
              "LaunchServices.framework/Support/lsregister")
BUNDLE_MAP_PATH = HOME / ".local/state/tcc-audit/bundles.json"
BUNDLE_MAP_TTL = 6 * 3600
_bundle_map = None


def _dump_bundle_map():
    """bundle id -> [paths] from the LaunchServices registry (~15s; Spotlight misses
    apps it has not indexed, e.g. Xcode.app, and nested helper apps)."""
    out = run([LSREGISTER, "-dump"], timeout=120).stdout.decode(errors="replace")
    mapping, path = {}, None
    for line in out.splitlines():
        if line.startswith("path:"):
            path = line[5:].strip().rsplit(" (0x", 1)[0]
        elif line.startswith("identifier:") and path:
            mapping.setdefault(line[11:].strip(), set()).add(path)
        elif line.startswith("----"):
            path = None
    return {k: sorted(v) for k, v in mapping.items()}


def bundle_paths(bundle_id):
    """Installed locations of an app bundle id."""
    global _bundle_map
    if _bundle_map is None:
        try:
            fresh = time.time() - BUNDLE_MAP_PATH.stat().st_mtime < BUNDLE_MAP_TTL
            _bundle_map = json.loads(BUNDLE_MAP_PATH.read_text()) if fresh else None
        except (OSError, ValueError):
            _bundle_map = None
        if _bundle_map is None:
            _bundle_map = _dump_bundle_map()
            if _bundle_map:  # never cache an empty dump (lsregister failure)
                BUNDLE_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
                BUNDLE_MAP_PATH.write_text(json.dumps(_bundle_map))
    return [p for p in _bundle_map.get(bundle_id, []) if os.path.lexists(p)]


def satisfies(path, req):
    """True/False, or None when codesign could not judge (unsigned, unreadable...)."""
    # --ignore-resources: skip the resource seal (Xcode.app: 20s -> 0.6s); the csreq only
    # constrains the code identity, which is what tccd checks.
    p = run(["codesign", "--verify", "--ignore-resources", f"-R={req}", path])
    if p.returncode == 0:
        return True
    if p.returncode == 3 or b"failed to satisfy" in p.stderr:
        return False
    return None


def classify(row):
    """-> (status, detail). status in ok | stale | orphan | unknown."""
    if row["client_type"] == 1:
        candidates = [row["client"]]
    else:
        candidates = bundle_paths(row["client"])
    existing = [c for c in candidates if os.path.lexists(c)]
    if not existing:
        return "orphan", "not installed" if row["client_type"] == 0 else "path gone"
    req = csreq_text(row["csreq"])
    if not req:
        return "ok", "no csreq"
    verdicts = [satisfies(c, req) for c in existing]
    if any(v is True for v in verdicts):
        return "ok", req
    if any(v is False for v in verdicts):
        return "stale", req
    return "unknown", req


def audit(dbs):
    rows, unreadable = [], []
    for db in dbs:
        if not os.path.exists(db):
            continue
        try:
            rows += read_rows(db)
        except (sqlite3.Error, OSError) as e:
            unreadable.append((db, str(e)))
    rows = [r for r in rows if r["auth"] in ALLOWED]
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(classify, rows))
    for r, (status, detail) in zip(rows, results):
        r["status"], r["detail"] = status, detail
    return rows, unreadable


def dupes(rows):
    groups = {}
    for r in rows:
        if r["client_type"] == 1:
            groups.setdefault((r["service"], os.path.basename(r["client"])), []).append(r)
    return {k: v for k, v in groups.items() if len(v) > 1}


def missing_expected(rows):
    try:
        expected = json.loads(EXPECTED_PATH.read_text())
    except (OSError, ValueError):
        return []
    have = {(short(r["service"]), r["client"]) for r in rows}
    out = []
    for e in expected:
        path = os.path.expanduser(e["path"])
        if not os.path.exists(path):
            continue
        for svc in e.get("services", []):
            if (svc, path) not in have:
                out.append((svc, path))
    return out


def problem_key(kind, service, client):
    return f"{kind}|{short(service)}|{client}"


def gather(dbs):
    rows, unreadable = audit(dbs)
    problems = {}  # key -> dict(kind, service, client, detail)
    for db, err in unreadable:
        problems[f"health|{db}"] = dict(kind="health", service="", client=db, detail=err)
    for r in rows:
        if r["status"] in ("stale", "orphan"):
            problems[problem_key(r["status"], r["service"], r["client"])] = dict(
                kind=r["status"], service=short(r["service"]), client=r["client"],
                detail=r["detail"], db=r["db"], client_type=r["client_type"],
                full_service=r["service"],
            )
    for svc, path in missing_expected(rows):
        problems[f"missing|{svc}|{path}"] = dict(kind="missing", service=svc, client=path, detail="no grant row")
    return rows, problems


def render(problems, rows):
    stale = [p for p in problems.values() if p["kind"] == "stale"]
    orphan = [p for p in problems.values() if p["kind"] == "orphan" and p.get("client_type") == 1]
    app_gone = [p for p in problems.values() if p["kind"] == "orphan" and p.get("client_type") != 1]
    missing = [p for p in problems.values() if p["kind"] == "missing"]
    health = [p for p in problems.values() if p["kind"] == "health"]
    out = []
    n = 0

    def section(title, items, fmt, hint):
        nonlocal n
        if not items:
            return
        n += 1
        out.append(f"{n}. {title}")
        for i, it in enumerate(sorted(items, key=lambda x: (x["service"], x["client"])), 1):
            out.append(f"  {n}.{i} {fmt(it)}")
        if hint:
            out.append(f"  -> {hint}")

    section("TCC database unreadable (this process lacks Full Disk Access)", health,
            lambda p: f"{p['client']}: {p['detail']}",
            "grant Full Disk Access to the process running this check (Hermes) -- no checks ran")
    section("Grant no longer works: binary was re-signed/rebuilt (toggle still looks ON)", stale,
            lambda p: f"{p['service']}: {p['client']}",
            "in System Settings > Privacy & Security remove the row (-) and add the binary again; "
            "or run --cleanup-script --include-stale, then re-add")
    section("Expected grant is missing", missing,
            lambda p: f"{p['service']}: {p['client']}",
            "add the binary in System Settings > Privacy & Security")
    section("Orphaned rows (binary/app gone; old versions)", orphan,
            lambda p: f"{p['service']}: {p['client']}",
            "safe to remove: tcc_audit.py --cleanup-script > f; review f; sudo bash f "
            "(tccutil cannot remove path rows)")
    section("Rows for apps LaunchServices cannot find (uninstalled, or on an unmounted volume)", app_gone,
            lambda p: f"{p['service']}: {p['client']}",
            "remove only if the app is really gone: --cleanup-script --include-apps")
    d = dupes(rows)
    if d and (stale or orphan):
        n += 1
        out.append(f"{n}. Same binary name, several rows (context for cleanup)")
        for i, ((svc, base), rs) in enumerate(sorted(d.items()), 1):
            out.append(f"  {n}.{i} {short(svc)} {base}: {len(rs)} rows")
    return "\n".join(out)


def load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {"known": {}, "last_digest": 0}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1, sort_keys=True))


def cleanup_script(problems, include_stale, include_apps):
    def wanted(p):
        if p["kind"] == "orphan":
            return p["client_type"] == 1 or include_apps
        return p["kind"] == "stale" and include_stale

    targets = [p for p in problems.values() if p.get("db") and wanted(p)]
    if not targets:
        return "# nothing to clean up\n"

    def q(s):
        return "'" + s.replace("'", "''") + "'"

    lines = [
        "#!/bin/bash",
        "# Generated by tcc_audit.py --cleanup-script. REVIEW BEFORE RUNNING. Run with: sudo bash <file>",
        "# Deletes only the rows listed below from the TCC databases, after backing each one up.",
        "# Needs Full Disk Access for the terminal running it. If a write is refused, remove the",
        "# rows in System Settings > Privacy & Security instead (nothing here is needed to use plocate).",
        "set -euo pipefail",
        '[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }',
        "TS=$(date +%Y%m%d-%H%M%S)",
    ]
    for db in sorted({p["db"] for p in targets}):
        lines += [
            f'DB={q(db)}',
            'cp -p "$DB" "$DB.bak-$TS"',
            'echo "backup: $DB.bak-$TS"',
        ]
        for p in sorted((t for t in targets if t["db"] == db), key=lambda x: (x["service"], x["client"])):
            lines.append(
                f"# {p['kind']}: {p['service']} {p['client']}"
            )
            lines.append(
                f'sqlite3 "$DB" "DELETE FROM access WHERE service={q(p["full_service"])} '
                f'AND client={q(p["client"])} AND client_type={p["client_type"]};"'
            )
    lines += [
        "# make tccd re-read the databases",
        "killall tccd 2>/dev/null || true",
        'echo "done -- re-check with: tcc_audit.py --all"',
    ]
    return "\n".join(lines) + "\n"


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="print the full audit now")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cleanup-script", action="store_true")
    ap.add_argument("--include-stale", action="store_true")
    ap.add_argument("--include-apps", action="store_true")
    ap.add_argument("--db", action="append", help="TCC.db to audit (default: system + user)")
    ap.add_argument("--state", help="state file (default ~/.local/state/tcc-audit/state.json)")
    args = ap.parse_args(argv)

    global STATE_PATH
    if args.state:
        STATE_PATH = Path(args.state)
    dbs = args.db or [SYSTEM_DB, USER_DB]
    rows, problems = gather(dbs)

    if args.json:
        json.dump(dict(problems=problems, rows=len(rows)), sys.stdout, indent=1, default=str)
        print()
        return 0
    if args.cleanup_script:
        sys.stdout.write(cleanup_script(problems, args.include_stale, args.include_apps))
        return 0
    if args.all:
        text = render(problems, rows)
        print(text if text else f"clean: {len(rows)} grants checked, none stale or orphaned")
        return 0

    # cron mode: alert on problems not seen before; re-print everything weekly while any remain
    state = load_state()
    now = time.time()
    known = state["known"]
    new = [k for k in problems if k not in known]
    for k in new:
        known[k] = now
    for k in [k for k in known if k not in problems]:
        del known[k]  # resolved
    digest_due = problems and now - state.get("last_digest", 0) > DIGEST_EVERY
    if new or digest_due:
        head = (f"TCC audit: {len(new)} new problem(s)" if new else "TCC audit: weekly reminder")
        print(head + f" ({len(problems)} outstanding)\n" + render(problems, rows))
        state["last_digest"] = now
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
