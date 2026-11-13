#!/usr/bin/env python3
"""Supervise Orchard (controller + worker) and the vmnet route watcher.

Run by launchd job com.djbclark.orchard-dev through ~/.orchard/run-dev.sh
(installed copy: ~/.orchard/orchard-launch.py; source: site-public-djbclark
roles/tart_route/files/). Replaces `orchard dev`, which listens on *:6120 with
authentication disabled (security review 2026-11-13: remote code execution as
the operator through hostDir mounts).

1. Controller: `orchard controller run --listen 127.0.0.1:6120` with TLS (no
   --insecure-no-tls): Orchard makes a self-signed certificate in its data dir
   (~/.orchard/controller/controller.crt). Loopback only, so tart guests at
   192.168.65.1 and the LAN cannot reach it. Authentication is on: a fresh random
   admin token is made at every start and handed to the controller in
   ORCHARD_BOOTSTRAP_ADMIN_TOKEN. The controller's stdout (where it prints
   service-account details) is discarded, so the token never reaches the
   world-readable launchd log. TLS pinning means another local account that
   grabs 127.0.0.1:6120 after the controller dies cannot impersonate it to the
   worker or the CLI: it has no key for the pinned certificate.
2. CLI config: ~/.orchard/orchard.yml (mode 0600, JSON is valid YAML) is rewritten
   with one context holding that token and the controller's certificate (the
   client trusts only that certificate), so `orchard ssh vm ...` works. This also
   drops the credential-less `local-dev` context that `orchard dev` left behind
   and the `bootstrap-context` the controller writes itself (same content).
3. Worker: `orchard worker run --name bigmac --bootstrap-token-stdin https://...`,
   the token string from `orchard get bootstrap-token bootstrap-admin` (it carries
   the certificate, so the worker pins it too), fed on stdin.
4. Route watcher: fix-vmnet-route.sh every 15 s (300 s after rc 3, sudoers rule
   missing); logs to ~/.orchard/route-watch.log only on change.
5. Either child exiting ends the launcher (non-zero) so launchd restarts the set;
   a controller exit kills the worker at once, and shutdown stops the worker
   before the controller.
   stderr of both children is filtered: DEBUG lines and the worker's own 5 s
   loopback polls are dropped; warnings, errors and real requests stay.

Orchard 0.55: `--data-dir` belongs to `controller`, not `run`; the VM store is
the worker's, so a restart still leaves running VMs `failed` (README caveat 1).
"""

import base64
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
URL = f"https://{HOST}:{PORT}"
WORKER_NAME = "bigmac"
CONFIG = HERE / "orchard.yml"
DATA_DIR = HERE / "controller"
CERT = DATA_DIR / "controller.crt"
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
failed = threading.Event()  # a child exited on its own
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
    threading.Thread(target=watch, args=(proc, tag), daemon=True).start()
    return proc


def watch(proc, tag):
    """Block on one child; its exit ends the launcher, and a dead controller
    takes the worker down immediately (a worker must never outlive it)."""
    rc = proc.wait()
    if stop.is_set():
        return
    log(f"{tag} exited rc={rc}")
    failed.set()
    stop.set()
    if tag == "controller":
        for other, p in children:
            if other == "worker" and p.poll() is None:
                p.kill()


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


def read_cert_b64():
    """The controller's certificate (PEM, as Orchard writes it), base64 as the
    `certificate:` field of orchard.yml wants it."""
    pem = CERT.read_bytes()
    if b"-----BEGIN CERTIFICATE-----" not in pem:
        raise RuntimeError(f"{CERT} holds no certificate")
    return base64.b64encode(pem).decode()


def wait_controller_context(cert_b64):
    """The controller writes its own `bootstrap-context` into orchard.yml (after
    it starts listening, in two steps). Let it finish before we replace the file
    so its write cannot clobber ours."""
    for _ in range(40):
        try:
            text = CONFIG.read_text()
        except OSError:
            text = ""
        if "default-context: bootstrap-context" in text and cert_b64 in text:
            return True
        if stop.wait(0.25):
            return False
    return False


def write_config(token, cert_b64):
    cfg = {
        "default-context": "local",
        "contexts": {
            "local": {
                "url": URL,
                "certificate": cert_b64,
                "serviceAccountName": "bootstrap-admin",
                "serviceAccountToken": token,
            }
        },
    }
    tmp = CONFIG.with_name(CONFIG.name + ".new")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, CONFIG)


def port_in_use():
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, PORT)) == 0


def owns_listener(controller):
    """True when our own controller process is the listener on HOST:PORT."""
    try:
        r = subprocess.run(
            ["/usr/sbin/lsof", "-nP", "-a", "-p", str(controller.pid)]
            + [f"-iTCP@{HOST}:{PORT}", "-sTCP:LISTEN"],
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return False
    return r.returncode == 0 and "LISTEN" in r.stdout


def wait_listening(controller):
    for _ in range(120):
        if stop.is_set() or controller.poll() is not None:
            return False
        if port_in_use() and owns_listener(controller):
            return True
        stop.wait(0.5)
    return False


def shutdown(*_):
    stop.set()


def main():
    os.umask(0o077)
    os.chmod(HERE, 0o700)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        return run()
    except Exception as exc:  # noqa: BLE001 - any failure must stop the children
        log(f"fatal: {exc!r}")
        return terminate(1)
    finally:
        stop.set()
        for _, proc in children:
            if proc.poll() is None:
                proc.terminate()


def run():
    if port_in_use():
        log(f"something already listens on {HOST}:{PORT}; refusing to start")
        return 1
    base_env = {k: v for k, v in os.environ.items() if not k.startswith("ORCHARD_")}
    base_env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    token = secrets.token_hex(16)  # 32 characters, new at every start
    # Stale CLI config (old token or certificate) must not survive; the
    # controller then creates the file itself, mode 0600 under our umask.
    CONFIG.unlink(missing_ok=True)

    threading.Thread(target=route_watch, daemon=True).start()

    ctl_env = dict(base_env, ORCHARD_BOOTSTRAP_ADMIN_TOKEN=token)
    controller = spawn(
        [
            ORCHARD,
            "controller",
            "--data-dir",
            str(DATA_DIR),
            "run",
            "--listen",
            f"{HOST}:{PORT}",
        ],
        "controller",
        ctl_env,
    )
    if not wait_listening(controller):
        log("controller did not start listening")
        return terminate(1)
    cert_b64 = read_cert_b64()
    if not wait_controller_context(cert_b64):
        log("controller did not write its context (continuing with our own)")
    write_config(token, cert_b64)

    got = subprocess.run(
        [ORCHARD, "get", "bootstrap-token", "bootstrap-admin"],
        check=False,
        env=base_env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    bootstrap = got.stdout.strip()
    if got.returncode != 0 or not bootstrap.startswith("orchard-bootstrap-token-"):
        log(f"could not get a worker bootstrap token (rc={got.returncode})")
        return terminate(1)

    if controller.poll() is not None or not owns_listener(controller):
        log("controller is gone or no longer the listener; not starting worker")
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
    try:
        worker.stdin.write(bootstrap + "\n")
        worker.stdin.close()
    except BrokenPipeError:
        log("worker closed stdin before reading the bootstrap token")
        return terminate(1)
    log(f"controller + worker {WORKER_NAME} up on {URL}")

    stop.wait()
    return terminate(1 if failed.is_set() else 0)


def stop_child(proc, grace):
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.wait(grace)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def terminate(rc):
    """Stop the worker first and wait for it, then the controller, so the
    worker never talks to a dying (or replaced) controller."""
    stop.set()
    for want in ("worker", "controller"):
        for tag, proc in reversed(children):
            if tag == want:
                stop_child(proc, 10)
    for tag, proc in children:
        if tag not in ("worker", "controller"):
            stop_child(proc, 5)
    return rc


if __name__ == "__main__":
    sys.exit(main())
