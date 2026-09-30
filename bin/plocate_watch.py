#!/usr/bin/env python3
"""plocate_watch -- is the nightly plocate reindex actually happening?

Silent when healthy; prints a short numbered problem list otherwise (built for a Hermes
no-agent cron, so stdout is the alert). Checks:
  1. the database exists and is younger than --max-age-hours (default 36; the job runs 03:30 daily)
  2. the LaunchAgent com.djbclark.plocate-updatedb is loaded, and its last exit code is 0
  3. the updatedb log has no permission errors (a lapsed Full Disk Access grant shows up there
     long before results look wrong: protected folders silently vanish from the index)
  4. the Full Disk Access grant for ~/.local/bin/plocate-updatedb still satisfies its csreq
     (delegates to tcc_audit.classify)
"""
import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
DB = "/opt/homebrew/var/lib/plocate/plocate.db"
LABEL = "com.djbclark.plocate-updatedb"
LOG = HOME / ".local/state/plocate/updatedb.log"
UPDATEDB = str(HOME / ".local/bin/plocate-updatedb")


def launchd_info():
    p = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return None
    m = re.search(r"last exit code = (\S+)", p.stdout)
    runs = re.search(r"runs = (\d+)", p.stdout)
    return dict(last_exit=m.group(1) if m else "?", runs=int(runs.group(1)) if runs else 0)


def fda_problem():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import tcc_audit  # noqa: E402
    rows = [r for r in tcc_audit.read_rows(tcc_audit.SYSTEM_DB)
            if r["client"] == UPDATEDB and r["service"] == "kTCCServiceSystemPolicyAllFiles"
            and r["auth"] in tcc_audit.ALLOWED]
    if not rows:
        return "no Full Disk Access grant for plocate-updatedb"
    status, detail = tcc_audit.classify(rows[0])
    return None if status in ("ok", "unknown") else f"Full Disk Access grant is {status}"


def check(max_age_hours, now=None):
    now = now or time.time()
    problems = []
    try:
        age_h = (now - os.stat(DB).st_mtime) / 3600
        if age_h > max_age_hours:
            problems.append(f"database is {age_h:.0f}h old (limit {max_age_hours:.0f}h): {DB}")
    except FileNotFoundError:
        problems.append(f"database missing: {DB}")
    info = launchd_info()
    if info is None:
        problems.append(f"LaunchAgent {LABEL} is not loaded (launchctl bootstrap gui/{os.getuid()} "
                        f"~/Library/LaunchAgents/{LABEL}.plist)")
    elif info["last_exit"] not in ("0", "(never exited)"):
        problems.append(f"last reindex exited with code {info['last_exit']}; see {LOG}")
    try:
        tail = LOG.read_text(errors="replace").splitlines()[-40:]
        bad = [l for l in tail if re.search(r"permission denied|operation not permitted|error", l, re.I)]
        if bad:
            problems.append(f"errors in {LOG.name}: {bad[-1][:120]}")
    except FileNotFoundError:
        pass
    try:
        fp = fda_problem()
        if fp:
            problems.append(fp + " (re-add ~/.local/bin/plocate-updatedb in System Settings)")
    except (OSError, ImportError, Exception) as e:  # unreadable TCC db etc.: not our failure
        problems.append(f"could not verify the Full Disk Access grant: {e}")
    return problems


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-age-hours", type=float, default=36)
    args = ap.parse_args(argv)
    problems = check(args.max_age_hours)
    if problems:
        print("plocate reindex check failed:")
        for i, p in enumerate(problems, 1):
            print(f"  {i}. {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
