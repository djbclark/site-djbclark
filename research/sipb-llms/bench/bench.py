#!/usr/bin/env python3
"""Serial benchmark of SIPB LLMs models driven through `acp-run crush`.

Per combo: direct probes (cold TTFT, decode tok/s, prefill of a ~10k-token
prompt twice for cache behaviour), then fizz x2, then wordstats if fizz passed.
Results are appended to results.jsonl; status.txt says what is running.
Runs are strictly serial: the SIPB server loads one model at a time.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.request

O = os.path.expanduser("~/.local/state/bigteam/sipb-bench")
RC = os.path.expanduser("~/.config/crush/crushrc")
PROXY = "http://127.0.0.1:8890/api/chat/completions"

# label, model, think, reasoning_effort (None = keep provider default)
COMBOS = {
    "q35-think":  ("qwen3.5:35b", True, "high"),
    "q35-nothink": ("qwen3.5:35b", False, "none"),
    "q35-27b-think": ("qwen3.5:27b", True, "high"),
    "q35-27b-nothink": ("qwen3.5:27b", False, "none"),
    "q36-think":  ("qwen3.6:35b-a3b-q4_K_M", True, "high"),
    "q36-nothink": ("qwen3.6:35b-a3b-q4_K_M", False, "none"),
    "coder30":    ("qwen3-coder:30b", False, None),
    "devstral24": ("devstral:24b", False, None),
    "gptoss-low": ("gpt-oss:20b", False, "low"),
    "gptoss-med": ("gpt-oss:20b", False, "medium"),
    "gemma4-26b": ("gemma4:26b", False, None),
}
REASONERS = ("qwen3.5", "qwen3.6", "gpt-oss", "deepseek-r1", "gemma4")


def key():
    return re.search(r"(sk-[A-Za-z0-9_-]+)", open(RC).read()).group(1)


def status(msg):
    with open(f"{O}/status.txt", "w") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def record(d):
    d["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    d["load1"] = os.getloadavg()[0]
    with open(f"{O}/results.jsonl", "a") as f:
        f.write(json.dumps(d) + "\n")


def stream(model, prompt, max_tokens, effort=None, timeout=400):
    """Return (ttft, total, n_chunks, error). Never prints the key."""
    body = {"model": model, "stream": True, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    if effort:
        body["reasoning_effort"] = effort
    req = urllib.request.Request(PROXY, json.dumps(body).encode(),
                                 {"Authorization": "Bearer " + key(), "Content-Type": "application/json"})
    t0 = time.time(); ttft = None; n = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for line in r:
                if not line.startswith(b"data: ") or line.startswith(b"data: [DONE]"):
                    continue
                try:
                    d = json.loads(line[6:])
                    delta = (d.get("choices") or [{}])[0].get("delta") or {}
                except Exception:
                    continue
                if delta.get("content") or delta.get("reasoning_content") or delta.get("reasoning"):
                    if ttft is None:
                        ttft = time.time() - t0
                    n += 1
        return ttft, time.time() - t0, n, None
    except Exception as e:
        return ttft, time.time() - t0, n, str(e)[:200]


def probes(label, model, effort):
    status(f"{label}: probe cold")
    r = {"kind": "probe", "combo": label, "model": model}
    t, tot, n, err = stream(model, "Reply with exactly: OK", 8, effort)
    r.update(cold_ttft=t, cold_total=tot, cold_err=err)
    if err:
        record(r); return False
    status(f"{label}: probe decode")
    t, tot, n, err = stream(model, "Count from 1 to 150 separated by single spaces. Output only the numbers.", 400, effort)
    r.update(decode_ttft=t, decode_total=tot, decode_chunks=n, decode_err=err,
             decode_cps=(n / (tot - t) if t and tot > t else None))
    big = ("The quick brown fox jumps over the lazy dog. " * 900) + "\nSay OK."
    for i in (1, 2):
        status(f"{label}: probe prefill {i}")
        t, tot, n, err = stream(model, big, 4, effort, timeout=600)
        r.update({f"prefill{i}_ttft": t, f"prefill{i}_err": err})
    record(r)
    return True


def make_rc(model, think, effort, dest):
    """Copy crushrc, replace model add/large/small, optionally effort."""
    text = open(RC).read()
    # join backslash continuations
    lines = []; buf = ""
    for ln in text.split("\n"):
        if buf:
            buf += "\n" + ln
        else:
            buf = ln
        if buf.rstrip().endswith("\\"):
            continue
        lines.append(buf); buf = ""
    out = []
    for ln in lines:
        if re.match(r"\s*model\s+(add|large|small)\b", ln):
            continue
        if effort and "--extra-body" in ln:
            ln = re.sub(r'"reasoning_effort":"[a-z]+"', f'"reasoning_effort":"{effort}"', ln)
        out.append(ln)
    reason = "true" if model.startswith(REASONERS) else "false"
    out.append(f'model add sipb-llms/{model} --name "{model}" --can-reason {reason} --context-window 32768 --default-max-tokens 8192')
    out.append(f"model large sipb-llms/{model}" + (" --think" if think else ""))
    out.append(f"model small sipb-llms/{model}")
    os.makedirs(f"{dest}/crush", exist_ok=True)
    with open(f"{dest}/crush/crushrc", "w") as f:
        f.write("\n".join(out) + "\n")
    os.chmod(f"{dest}/crush/crushrc", 0o600)


def sh(cmd, cwd, timeout=120):
    p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr)


def run_task(*args):
    try:
        return run_task_inner(*args)
    except Exception as e:
        record({'kind': 'task', 'combo': args[0], 'task': args[4], 'pass': False, 'harness_error': str(e)[:300], 'secs': None, 'tools': None, 'thought_chunks': None, 'stop': None})
        return False


def run_task_inner(label, model, think, effort, task, cap, prompt_file, rules, extra_args):
    run = f"{label}-{task}-{int(time.time())}"
    d = f"{O}/runs/{run}"
    proj = f"{d}/proj"; xdg = f"{d}/xdg"
    os.makedirs(proj)
    sh("git init -q && git config user.email t@t && git config user.name t", proj)
    if task.startswith("fizz"):
        for f in os.listdir(f"{O}/fizz-template"):
            if not f.endswith(".py"):
                continue
            shutil.copy(f"{O}/fizz-template/{f}", proj)
        sh("git add -A && git commit -qm init", proj)
    make_rc(model, think, effort, xdg)
    if rules:
        shutil.copy(rules, f"{xdg}/crush/CRUSH.md")
    xdgd = f"{d}/xdgdata"
    os.makedirs(f"{xdgd}/crush", exist_ok=True)
    gp = os.path.expanduser("~/.local/share/crush/providers.json")
    if os.path.exists(gp):
        shutil.copy(gp, f"{xdgd}/crush/providers.json")
    env = dict(os.environ, XDG_CONFIG_HOME=xdg, XDG_DATA_HOME=xdgd)
    prompt = open(prompt_file).read()
    status(f"{label}: {task} running")
    t0 = time.time()
    try:
        p = subprocess.run(["acp-run", "crush", "-C", proj, "-p", prompt, "--timeout", str(cap),
                            "--log", f"{d}/log.jsonl"] + extra_args,
                           env=env, capture_output=True, text=True, timeout=cap + 90)
        err = p.stderr[-600:]; rc = p.returncode
    except subprocess.TimeoutExpired:
        err = "harness-timeout"; rc = 124
    secs = time.time() - t0
    m = re.search(r"stop=(\S+) secs=([\d.]+) tools=(\d+)", err)
    thoughts = tools = 0
    names = {}
    try:
        for ln in open(f"{d}/log.jsonl"):
            r = json.loads(ln)
            if r.get("kind") == "update":
                u = r["data"].get("sessionUpdate")
                if u == "agent_thought_chunk": thoughts += 1
                if u == "tool_call":
                    t = r["data"].get("title") or "?"
                    names[t.split()[0]] = names.get(t.split()[0], 0) + 1
    except Exception:
        pass
    provs = set()
    try:
        provs = set(re.findall(r'"provider":"([^"]+)"', open(f"{proj}/.crush/logs/crush.log").read()))
    except Exception:
        pass
    # verification
    if task.startswith("fizz"):
        urc, _out = sh("python3 -m unittest 2>&1", proj)
        ok = urc == 0
        _, log = sh("git rev-list --count HEAD 2>/dev/null || echo 0", proj)
        committed = int((log.strip().split() or ["0"])[0]) >= 2
        res = {"tests_ok": ok, "committed": committed, "pass": ok and committed}
    else:
        urc, out = sh("python3 -m unittest discover 2>&1", proj)
        mt = re.search(r"Ran (\d+) tests", out)
        ok = urc == 0
        _, log = sh("git rev-list --count HEAD 2>/dev/null || echo 0", proj)
        notes = open(f"{proj}/NOTES.md").read() if os.path.exists(f"{proj}/NOTES.md") else ""
        res = {"tests_ok": ok, "ntests": int(mt.group(1)) if mt else 0, "committed": int((log.strip().split() or ["0"])[0]) >= 1,
               "curl200": "200" in notes, "stopwords": os.path.exists(f"{proj}/wordstats/cli.py") and "stopwords" in open(f"{proj}/wordstats/cli.py").read()}
        res["pass"] = bool(res["tests_ok"] and res["committed"] and res["ntests"] >= 16)
    record({"kind": "task", "combo": label, "model": model, "think": think, "effort": effort, "task": task,
            "secs": round(secs, 1), "rc": rc, "stop": m.group(1) if m else None,
            "tools": int(m.group(3)) if m else None, "thought_chunks": thoughts, "tool_names": names,
            "err_tail": err[-200:] if rc else "", "providers": sorted(provs), "verify": (re.search(r"verify=(\w+) verify_attempts=(\d+)", err).groups() if re.search(r"verify=(\w+) verify_attempts=(\d+)", err) else None), "rules": bool(rules), "extra": extra_args, **res})
    shutil.rmtree(xdg, ignore_errors=True)  # holds the API key
    shutil.rmtree(xdgd, ignore_errors=True)
    return res["pass"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--combos", default=",".join(COMBOS))
    ap.add_argument("--fizz", type=int, default=2)
    ap.add_argument("--wordstats", default="task-wordstats-lean.txt")
    ap.add_argument("--no-probe", action="store_true")
    ap.add_argument("--rules")
    ap.add_argument("--wordstats-cap", type=int, default=600)
    ap.add_argument("--tag", default="A")
    ap.add_argument("--extra", default="", help="extra acp-run args, space separated")
    ap.add_argument("--force-wordstats", action="store_true")
    ap.add_argument("--fizz-only", action="store_true")
    a = ap.parse_args()
    extra = a.extra.split("|") if a.extra else []
    if os.path.exists(f"{O}/DONE-{a.tag}"):
        return
    probed = set()
    for label in a.combos.split(","):
        model, think, effort = COMBOS[label]
        if not a.no_probe and model not in probed:
            probed.add(model)
            if not probes(label, model, effort):
                record({"kind": "skip", "combo": label, "why": "probe failed"}); continue
        passes = 0
        for i in range(a.fizz):
            passes += run_task(label, model, think, effort, f"fizz{i+1}", 300, f"{O}/task-fizz.txt", a.rules, extra)
        if a.fizz_only:
            continue
        if passes or a.force_wordstats:
            run_task(label, model, think, effort, "wordstats", a.wordstats_cap, f"{O}/{a.wordstats}", a.rules, extra)
        else:
            record({"kind": "skip", "combo": label, "why": "fizz failed twice"})
    status("finished")
    open(f"{O}/DONE-{a.tag}", "w").write(time.strftime("%c") + "\n")


if __name__ == "__main__":
    main()
