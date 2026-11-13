#!/usr/bin/env python3
"""Supervise Orchard (controller + worker) and the vmnet route watcher.

Run by launchd job com.djbclark.orchard-dev through ~/.orchard/run-dev.sh
(installed copy: ~/.orchard/orchard-launch.py; source: site-public-djbclark
roles/tart_route/files/). Replaces `orchard dev`, which listens on *:6120 with
authentication disabled (security review 2026-11-13: remote code execution as
the operator through hostDir mounts).

1. Controller: `orchard controller run --listen 127.0.0.1:6120 --insecure-no-tls`
   (loopback only, so tart guests at 192.168.65.1 and the LAN cannot reach it).
   Authentication is on: a fresh random admin token is made at every start and
   handed to the controller in ORCHARD_BOOTSTRAP_ADMIN_TOKEN. The controller's
   stdout (where it prints service-account details) is discarded, so the token
   never reaches the world-readable launchd log.
2. CLI config: ~/.orchard/orchard.yml (mode 0600, JSON is valid YAML) is rewritten
   with one context holding that token, so `orchard ssh vm ...` works. This also
   drops the credential-less `local-dev` context that `orchard dev` left behind.
3. Worker: `orchard worker run --name bigmac --bootstrap-token-stdin`, the token
   string from `orchard get bootstrap-token bootstrap-admin`, fed on stdin.
4. Route watcher: fix-vmnet-route.sh every 15 s (300 s after rc 3, sudoers rule
   missing); logs to ~/.orchard/route-watch.log only on change.
5. Either child exiting ends the launcher (non-zero) so launchd restarts the set.
   stderr of both children is filtered: DEBUG lines and the worker's own 5 s
   loopback polls are dropped; warnings, errors and real requests stay.

Orchard 0.55: `--data-dir` belongs to `controller`, not `run`; the VM store is
the worker's, so a restart still leaves running VMs `failed` (README caveat 1).
"""

import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

HOME = Path(os.environ["HOME"])
HERE = HOME / ".orchard"
ORCHARD = "/opt/homebrew/bin/orchard"
HOST, PORT = "127.0.0.1", 6120
URL = f"http://{HOST}:{PORT}"
WORKER_NAME = "bigmac"
CONFIG = HERE / "orchard.yml"
ROUTE_FIX = HERE / "fix-vmnet-route.sh"
ROUTE_LOG = HERE / "route-watch.log"

NOISE = [
    # JSON log lines (controller run / worker run)
    re.compile(r'"level":"debug"'),
    re.compile(r'"msg":"syncing \d+ local VMs'),
    re.compile(
        r'"status":200,"method":"(GET|PUT)","path":"/v1/(vms","query":"filter=worker%3D'
        + WORKER_NAME
        + r"|workers/"
        + WORKER_NAME
        + r'","query":")","ip":"127\.0\.0\.1","user-agent":"Orchard/'
    ),
    # `orchard dev` console format (kept for reference when run by hand)
    re.compile(r"\tDEBUG\t"),
    re.compile(r"\tINFO\tworker/worker\.go:\d+\tsyncing \d+ local VMs"),
    re.compile(
        r'"status": 200, "method": "(GET|PUT)", "path": "/v1/(vms", "query": '
        r'"filter=worker%3D'
        + WORKER_NAME
        + r"|workers/"
        + WORKER_NAME
        + r'", "query": ")", '
        r'"ip": "127\.0\.0\.1", "user-agent": "Orchard/'
    ),
]

stop = threading.Event()
children = []


def log(msg):
    sys.stderr.write(f"orchard-launch: {msg}\n")
    sys.stderr.flush()


def pump(stream, tag):
    for line in iter(stream.readline, ""):
        if not any(p.search(line) for p in NOISE):
            sys.stderr.write(line)
            sys.stderr.flush()
    stream.close()


def spawn(argv, tag, env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL):
    proc = subprocess.Popen(
        argv,
        env=env,
        stdin=stdin,
        stdout=stdout,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    children.append((tag, proc))
    threading.Thread(target=pump, args=(proc.stderr, tag), daemon=True).start()
    return proc


def route_watch():
    last = ""
    while not stop.is_set():
        r = subprocess.run(
            [str(ROUTE_FIX), "-q"],
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        out = (r.stdout + r.stderr).strip()
        if out and out != last:
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            with ROUTE_LOG.open("a") as fh:
                fh.write(f"{stamp} route-watch rc={r.returncode} {out}\n")
        last = out
        stop.wait(300 if r.returncode == 3 else 15)


def write_config(token):
    cfg = {
        "default-context": "local",
        "contexts": {
            "local": {
                "url": URL,
                "serviceAccountName": "bootstrap-admin",
                "serviceAccountToken": token,
            }
        },
    }
    tmp = CONFIG.with_name(CONFIG.name + ".new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, CONFIG)


def wait_listening(controller):
    for _ in range(120):
        if controller.poll() is not None:
            return False
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex((HOST, PORT)) == 0:
                return True
        time.sleep(0.5)
    return False


def shutdown(*_):
    stop.set()


def main():
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    base_env = {k: v for k, v in os.environ.items() if not k.startswith("ORCHARD_")}
    base_env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    token = secrets.token_hex(16)  # 32 characters, new at every start

    threading.Thread(target=route_watch, daemon=True).start()

    ctl_env = dict(base_env, ORCHARD_BOOTSTRAP_ADMIN_TOKEN=token)
    controller = spawn(
        [
            ORCHARD,
            "controller",
            "--data-dir",
            str(HERE / "controller"),
            "run",
            "--listen",
            f"{HOST}:{PORT}",
            "--insecure-no-tls",
        ],
        "controller",
        ctl_env,
    )
    if not wait_listening(controller):
        log("controller did not start listening")
        return terminate(1)
    write_config(token)

    got = subprocess.run(
        [ORCHARD, "get", "bootstrap-token", "bootstrap-admin"],
        check=False,
        env=base_env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    bootstrap = got.stdout.strip()
    if got.returncode != 0 or not bootstrap.startswith("orchard-bootstrap-token-"):
        log(f"could not get a worker bootstrap token (rc={got.returncode})")
        return terminate(1)

    worker = spawn(
        [
            ORCHARD,
            "worker",
            "run",
            "--name",
            WORKER_NAME,
            "--bootstrap-token-stdin",
            URL,
        ],
        "worker",
        base_env,
        stdin=subprocess.PIPE,
    )
    assert worker.stdin is not None
    worker.stdin.write(bootstrap + "\n")
    worker.stdin.close()
    log(f"controller + worker {WORKER_NAME} up on {URL}")

    while not stop.is_set():
        for tag, proc in children:
            if proc.poll() is not None:
                log(f"{tag} exited rc={proc.returncode}")
                return terminate(1)
        stop.wait(2)
    return terminate(0)


def terminate(rc):
    stop.set()
    for _, proc in reversed(children):
        if proc.poll() is None:
            proc.terminate()
    deadline = time.time() + 15
    for _, proc in children:
        try:
            proc.wait(max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            proc.kill()
    return rc


if __name__ == "__main__":
    sys.exit(main())
