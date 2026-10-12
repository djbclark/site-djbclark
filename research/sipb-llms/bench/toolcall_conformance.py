#!/usr/bin/env python3
"""Tool-call conformance check for an OpenAI-compatible endpoint (SIPB LLMs).

Usage: SIPB_API_KEY=sk-... toolcall_conformance.py [--base URL] [--long] MODEL...
Checks per model: (1) streamed request returns a tool_calls delta with valid JSON
arguments and finish_reason "tool_calls"; (2) the same without streaming;
(3) with --long, a prompt past the context window returns an HTTP error, not a
200 with body `null`. Exit 1 if any check fails. Never prints the key.
"""
import argparse, json, os, sys, urllib.error, urllib.request

TOOL = {"type": "function", "function": {
    "name": "get_weather", "description": "Get the weather for a city.",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}
MSG = [{"role": "user", "content": "What is the weather in Boston? Use the tool."}]


def post(base, model, body, timeout=300):
    body = dict(body, model=model)
    req = urllib.request.Request(base + "/chat/completions", json.dumps(body).encode(),
                                 {"Authorization": "Bearer " + os.environ["SIPB_API_KEY"],
                                  "Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def check_stream(base, model):
    calls, finish = {}, None
    with post(base, model, {"stream": True, "messages": MSG, "tools": [TOOL]}) as r:
        for line in r:
            if not line.startswith(b"data: ") or line.startswith(b"data: [DONE]"):
                continue
            ch = (json.loads(line[6:]).get("choices") or [{}])[0]
            for tc in (ch.get("delta") or {}).get("tool_calls") or []:
                c = calls.setdefault(tc.get("index", 0), {"name": "", "args": ""})
                f = tc.get("function") or {}
                c["name"] += f.get("name") or ""
                c["args"] += f.get("arguments") or ""
            finish = ch.get("finish_reason") or finish
    if not calls:
        return "no tool_calls delta"
    try:
        json.loads(next(iter(calls.values()))["args"])
    except ValueError:
        return "tool call arguments are not valid JSON: %r" % next(iter(calls.values()))["args"][:80]
    if finish != "tool_calls":
        return "finish_reason %r with a tool call (expected 'tool_calls')" % finish
    return None


def check_plain(base, model):
    with post(base, model, {"stream": False, "messages": MSG, "tools": [TOOL]}) as r:
        d = json.load(r)
    ch = ((d or {}).get("choices") or [{}])[0]
    if not (ch.get("message") or {}).get("tool_calls"):
        return "no tool_calls in message"
    if ch.get("finish_reason") != "tool_calls":
        return "finish_reason %r with a tool call (expected 'tool_calls')" % ch.get("finish_reason")
    return None


def check_long(base, model):
    big = [{"role": "user", "content": "The quick brown fox jumps over the lazy dog. " * 6000 + "\nSay OK."}]
    try:
        with post(base, model, {"stream": False, "max_tokens": 4, "messages": big}, 600) as r:
            body = r.read()
        try:
            d = json.loads(body)
        except ValueError:
            d = body
        if isinstance(d, dict):    # a real completion: say whether the prompt was cut to fit
            pt = (d.get("usage") or {}).get("prompt_tokens")
            return ("HTTP 200 with a completion for a prompt of about 66k tokens (prompt_tokens=%s): "
                    "silently truncated, or a larger context than 32768 (expected an error status)" % pt)
        return "HTTP 200 with body %r for an over-long prompt (expected an error status)" % body[:40]
    except urllib.error.HTTPError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://llms-dev-1.mit.edu/api")
    ap.add_argument("--long", action="store_true")
    ap.add_argument("models", nargs="+")
    a = ap.parse_args()
    bad = 0
    for m in a.models:
        checks = [("stream", check_stream), ("plain", check_plain)] + ([("long", check_long)] if a.long else [])
        for name, fn in checks:
            try:
                err = fn(a.base, m)
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, str(e)[:120])
            print("%-28s %-7s %s" % (m, name, "PASS" if err is None else "FAIL " + err))
            bad += err is not None
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
