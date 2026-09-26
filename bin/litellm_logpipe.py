#!/usr/bin/env python3
"""Filter + size-capped rotation for LiteLLM, the xAI bridge and Hindsight logs.

(Named for its first user; roles/hindsight uses it too since 2026-09-26, when
~/Library/Logs/hindsight had reached ~600 MB, mostly fact-extraction stack
traces and repeated "slow DB pool acquire" warnings.)

A launchd service can only point stdout/stderr at a file it never rotates, and
newsyslog needs root. By 2026-09-26 the proxy's stderr.log had reached 1.9 GB;
85% of its lines were stack traces attached to *expected* errors (429 rate and
quota limits, provider outages), and stdout.log was one uvicorn access line
per successful request. launchd now runs `logpipe --out FILE -- litellm ...`:
this script starts the service as its child, reads the child's merged
stdout/stderr, and forwards SIGTERM/SIGINT/SIGHUP to it (SIGKILL after
KILL_AFTER s). It is the parent on purpose: the first version ran
`sh -c 'litellm 2>&1 | logpipe'`, and on 2026-09-26 a launchd stop signalled
only the shell, leaving the old proxy orphaned, wedged, and still holding
:4000. With nothing after `--` it filters stdin instead. Then it:

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
KILL_AFTER = 20
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-bytes", type=int, default=20_000_000)
    ap.add_argument("--backups", type=int, default=3)
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="-- program args (run as child)")
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    sink = Sink(a.out, a.max_bytes, a.backups)

    child = None
    if cmd:
        child = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        def forward(signum, _frame):
            if child.poll() is None:
                child.send_signal(signum)
                deadline = time.time() + KILL_AFTER
                while child.poll() is None and time.time() < deadline:
                    time.sleep(0.2)
                if child.poll() is None:
                    child.kill()
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
                elif not DATED.match(line):   # bridge and Hindsight lines carry their own date
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
        rc = child.wait()
        sink.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} logpipe: child exited with {rc}")
        sys.exit(rc if rc >= 0 else 128 - rc)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
