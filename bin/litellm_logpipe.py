#!/usr/bin/env python3
"""Filter + size-capped rotation for LiteLLM, the xAI bridge and other launchd logs.

(Named for its first user; roles/basic_memory_mcp uses it too. It was added
after one service's log reached ~600 MB of repeated stack traces.)

A launchd service can only point stdout/stderr at a file it never rotates, and
newsyslog needs root. By 2026-09-26 the proxy's stderr.log had reached 1.9 GB;
85% of its lines were stack traces attached to *expected* errors (429 rate and
quota limits, provider outages), and stdout.log was one uvicorn access line
per successful request. launchd now runs `logpipe --out FILE -- litellm ...`:
this script starts the service as its child, reads the child's merged
stdout/stderr, and forwards SIGTERM/SIGINT/SIGHUP to it (SIGKILL after
--kill-after s, default 15). It is the parent on purpose: the first version ran
`sh -c 'litellm 2>&1 | logpipe'`, and on 2026-09-26 a launchd stop signalled
only the shell, leaving the old proxy orphaned, wedged, and still holding
:4000. With nothing after `--` it filters stdin instead.

Child supervision (C1, 2026-10-06; site-private memory
project_litellm_watchdog_restart_orphans_2026-10-06). launchd's default
ExitTimeOut is 5 s, and the old 20 s child kill meant launchd SIGKILLed this
wrapper first and the proxy was reparented to pid 1, sometimes still holding
:4000. So:

  * the child runs in its own session (start_new_session), and every signal
    goes to its whole process group (killpg), grandchildren included;
  * --kill-after (default 15) must stay below the plist's ExitTimeOut (30);
  * a separate reaper process (this file run with --reap, in its own session so
    launchd's process-group cleanup does not take it down) waits on a kqueue
    NOTE_EXIT for this wrapper and kills the child's group if the wrapper dies
    first, even by SIGKILL; it exits as soon as the child does;
  * after stdout EOF the wrapper waits at most --kill-after for the child to
    exit, then kills the group.

Then it:

  * collapses each record's continuation block (tracebacks, multi-line JSON
    error bodies) to its first CONT_KEEP lines plus the final exception line;
  * drops pure noise: 2xx access lines for routine endpoints, "SESSION REUSE",
    and the empty-message "LiteLLM completion() model=" record pair (the
    router's "acompletion(model=X) 200 OK" line already names every call);
  * strips ANSI colour, stamps record lines with a full local date (LiteLLM
    prints only HH:MM:SS), and truncates any single line over MAX_LINE chars;
  * suppresses repeats: during an error storm (the 2026-09-26 ClinePass weekly
    cap produced ~50k identical 429 access lines in a few hours) a record whose
    text, with numbers and ids normalised away, was already written in the last
    REPEAT_WINDOW seconds is counted instead of written, and a single
    "repeated N×" line is emitted when the window closes;
  * rotates at --max-bytes, keeping --backups old files.

Kept on purpose, because the Hermes "LLM Backend Health" cron parses them:
"acompletion(model=X) 200 OK", "Successful fallback b/w models" and
"No deployments available". Do not add those to NOISE. The first two are also
exempt from repeat suppression (the cron counts them one by one); the third
may be collapsed into "repeated N×" lines, which the cron adds up.

Never raises on bad input: a crash here would SIGPIPE the proxy.
"""
import argparse, os, re, select, signal, subprocess, sys, time

ANSI = re.compile(r"\x1b\[[0-9;]*m")
CLOCK = re.compile(r"^(\d\d:\d\d:\d\d) - ")
# A new log record: LiteLLM's "HH:MM:SS - Name:LEVEL: ...", uvicorn's
# "INFO:     ...", Python warnings, or the bridge's "dd/Mon/yyyy hh:mm:ss ...".
RECORD = re.compile(r"^(\d\d:\d\d:\d\d - |(INFO|WARNING|ERROR|CRITICAL|DEBUG):\s|\S+Warning: |\d\d/\w{3}/\d{4} |\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d)")
DATED = re.compile(r"^(\d\d/\w{3}/\d{4} |\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d)")   # already carries a date
EXC = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Exit|Interrupt|Warning)\b")
NOISE = [
    re.compile(r"SESSION REUSE"),
    re.compile(r"LiteLLM:INFO: utils\.py:\d+ - \s*$"),        # header of the completion() pair
    re.compile(r'^INFO:\s+\S+ - "(POST /v1/chat/completions|POST /chat/completions|GET /health\S*|GET /v1/models|GET /) HTTP/[\d.]+" 2\d\d'),
    re.compile(r'"GET / HTTP/[\d.]+" 404'),                   # bridge root probes
    re.compile(r"message only /v1/\* is bridged"),
]
DROP_CONT_AFTER_NOISE = True   # the noise record's own continuation goes too
CONT_KEEP = 3
TAIL_KEEP = 2      # the innermost frames are where a stack dump says what it was doing
MAX_LINE = 2000
KILL_AFTER = 15   # default for --kill-after; keep below the plist ExitTimeOut (30)
REPEAT_WINDOW = 60
NEVER_DEDUPE = re.compile(r"Successful fallback b/w models|acompletion\(model=[^)]*\) 200 OK")
NORM = [(re.compile(r"\b[0-9a-f]{16,}\b"), "H"), (re.compile(r"\d+"), "N")]


def dedupe_key(line):
    k = CLOCK.sub("", line)
    for pat, rep in NORM:
        k = pat.sub(rep, k)
    return k[:400]


class Sink:
    def __init__(self, path, max_bytes, backups):
        self.path, self.max, self.backups = path, max_bytes, backups
        self.open()

    def open(self):
        self.f = open(self.path, "a", encoding="utf-8", errors="replace")
        self.size = self.f.tell()

    def rotate(self):
        self.f.close()
        for i in range(self.backups, 0, -1):
            src = self.path if i == 1 else f"{self.path}.{i - 1}"
            dst = f"{self.path}.{i}"
            if os.path.exists(src):
                os.replace(src, dst)
        if self.backups == 0:
            os.remove(self.path)
        self.open()

    def write(self, line):
        try:
            if len(line) > MAX_LINE:
                line = line[:MAX_LINE] + f" …[+{len(line) - MAX_LINE} chars]"
            data = line + "\n"
            self.f.write(data)
            self.f.flush()
            self.size += len(data.encode("utf-8", "replace"))
            if self.size >= self.max:
                self.rotate()
        except Exception as e:  # disk full, permissions: keep draining stdin
            print(f"logpipe: write failed: {e}", file=sys.stderr)


def killpg(pgid, sig):
    """Signal a whole process group; False if it is already gone."""
    try:
        os.killpg(pgid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def group_alive(pgid):
    return killpg(pgid, 0)


def stop_group(pgid, sig, kill_after, alive=None):
    """Send `sig` to the group, wait up to kill_after s, then SIGKILL it."""
    alive = alive or (lambda: group_alive(pgid))
    killpg(pgid, sig)
    deadline = time.time() + kill_after
    while alive() and time.time() < deadline:
        time.sleep(0.2)
    if alive():
        killpg(pgid, signal.SIGKILL)


def reap(wrapper_pid, pgid, kill_after):
    """--reap mode: kill the child's group if the wrapper dies before the child.

    Runs in its own session, so launchd's cleanup of the job's process group
    (AbandonProcessGroup false) does not kill it along with the wrapper. kqueue
    NOTE_EXIT fires for any death, SIGKILL included. Registration failing with
    ESRCH means that pid is already gone.
    """
    for sig in (signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, signal.SIG_IGN)
    kq = select.kqueue()
    flags = select.KQ_EV_ADD | select.KQ_EV_ONESHOT
    gone = set()
    for pid in (wrapper_pid, pgid):
        try:
            kq.control([select.kevent(pid, filter=select.KQ_FILTER_PROC, flags=flags,
                                      fflags=select.KQ_NOTE_EXIT)], 0, 0)
        except ProcessLookupError:
            gone.add(pid)
    if os.getppid() != wrapper_pid:
        gone.add(wrapper_pid)
    while not gone:
        try:
            for ev in kq.control(None, 2, None):
                gone.add(ev.ident)
        except InterruptedError:
            continue
    if pgid in gone and wrapper_pid not in gone:
        return 0                    # the child exited first: the wrapper handles it
    if group_alive(pgid):
        stop_group(pgid, signal.SIGTERM, kill_after)
    return 0


def start_reaper(pgid, kill_after):
    try:
        return subprocess.Popen(
            [sys.executable, "-I", "-S", os.path.abspath(__file__), "--reap",
             str(os.getpid()), str(pgid), str(kill_after)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, close_fds=True)
    except OSError as e:   # never take the service down over its safety net
        print(f"logpipe: reaper not started: {e}", file=sys.stderr)
        return None


def main():
    if sys.argv[1:2] == ["--reap"]:
        wrapper_pid, pgid, kill_after = sys.argv[2:5]
        sys.exit(reap(int(wrapper_pid), int(pgid), float(kill_after)))
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-bytes", type=int, default=20_000_000)
    ap.add_argument("--backups", type=int, default=3)
    ap.add_argument("--kill-after", type=float, default=KILL_AFTER,
                    help="seconds between forwarding a stop signal and SIGKILL; "
                         "keep below the launchd ExitTimeOut")
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="-- program args (run as child)")
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    sink = Sink(a.out, a.max_bytes, a.backups)
    kill_after = a.kill_after

    child = None
    if cmd:
        # Own session: the child's pid is its process-group id, so killpg reaches
        # anything it spawns, and launchd's group cleanup never races our own.
        child = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        start_reaper(child.pid, kill_after)

        def forward(signum, _frame):
            if child.poll() is None:
                stop_group(child.pid, signum, kill_after, alive=lambda: child.poll() is None)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, forward)

    dropping = False          # inside a noise record's continuation
    cont = 0                  # continuation lines seen in current block
    last_exc = None
    last_input = time.time()
    seen = {}                 # dedupe key -> [window start, suppressed count]

    def flush_repeats(force=False):
        now = time.time()
        for k in [k for k, (t0, n) in seen.items() if force or now - t0 >= REPEAT_WINDOW]:
            t0, n = seen.pop(k)
            if n:
                sink.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}     …[repeated {n}× in {REPEAT_WINDOW}s: {k[:160]}]")

    tail_lines = []

    def close_block():
        nonlocal cont, last_exc, tail_lines
        if cont > CONT_KEEP:
            hidden = cont - CONT_KEEP - len(tail_lines)
            if hidden > 0:
                sink.write(f"    …[{hidden} more line(s) collapsed]")
            for t in tail_lines:
                sink.write(t)
            if last_exc and last_exc not in tail_lines:
                sink.write(f"    …[last exception: {last_exc[:300]}]")
        cont, last_exc, tail_lines = 0, None, []

    stdin = child.stdout if child else sys.stdin.buffer
    buf = b""
    while True:
        # Flush a pending collapse summary after 2 s of quiet, so the summary
        # isn't held back until the next record arrives.
        try:
            r, _, _ = select.select([stdin], [], [], 2.0)
        except InterruptedError:
            continue
        if not r:
            if cont > CONT_KEEP and time.time() - last_input > 2:
                close_block()
            flush_repeats()
            continue
        chunk = os.read(stdin.fileno(), 65536)
        if not chunk:
            break
        last_input = time.time()
        buf += chunk
        *lines, buf = buf.split(b"\n")
        for raw in lines:
            line = ANSI.sub("", raw.decode("utf-8", "replace")).rstrip("\r")
            if RECORD.match(line):
                close_block()
                if any(p.search(line) for p in NOISE):
                    dropping = DROP_CONT_AFTER_NOISE
                    continue
                flush_repeats()
                if not NEVER_DEDUPE.search(line):
                    k = dedupe_key(line)
                    if k in seen:
                        seen[k][1] += 1
                        dropping = True       # its traceback is a repeat too
                        continue
                    seen[k] = [time.time(), 0]
                dropping = False
                stamp = time.strftime("%Y-%m-%d")
                m = CLOCK.match(line)
                if m:
                    line = f"{stamp} {m.group(1)} - {line[m.end():]}"
                elif not DATED.match(line):   # bridge lines carry their own date
                    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}"
                sink.write(line)
            else:
                if dropping or not line.strip():
                    continue
                cont += 1
                if EXC.match(line):
                    last_exc = line
                if cont <= CONT_KEEP:
                    sink.write(line)
                else:
                    tail_lines = (tail_lines + [line])[-TAIL_KEEP:]
    close_block()
    flush_repeats(force=True)
    if child:
        # stdout EOF does not mean the child has exited (it may have closed its
        # output, or be stuck in shutdown): bounded wait, then kill the group.
        try:
            rc = child.wait(timeout=kill_after)
        except subprocess.TimeoutExpired:
            sink.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} logpipe: child still running "
                       f"{kill_after:g}s after its output closed; killing its process group")
            killpg(child.pid, signal.SIGKILL)
            rc = child.wait()
        sink.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} logpipe: child exited with {rc}")
        sys.exit(rc if rc >= 0 else 128 - rc)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
