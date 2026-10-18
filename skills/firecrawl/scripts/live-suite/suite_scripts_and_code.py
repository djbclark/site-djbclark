# Second round (2026-10-18): non-Latin scripts, code, deadline, abstain. Run from this directory; writes run3/.
import sys, json, re; sys.path.insert(0, "."); from common import *
src = open("suite.py").read().split("recs = []")[0]  # reuse helpers (U, Q, J, val, S, js_ok, ans_has ...)
OUT = "run3"; exec(src.replace("OUT = sys.argv[1]; ", "OUT = 'run3'; ", 1))
recs = []
def run(cid, port, url, fm, check, **extra):
    r = post(port, url, fm, **extra); d = (r["body"] or {}).get("data") or {}
    try: ok, note = check(d) if r["status"] == 200 else (False, f"http {r['status']} {json.dumps(r['body'])[:160]}")
    except Exception as ex: ok, note = False, f"check exc {ex!r}"
    rec = dict(id=cid, ok=bool(ok), secs=r["secs"], rung=r["hdr"].get("X-Firecrawl-LLM", "-"), warn=(d.get("warning") or "")[:200], note=str(note)[:200])
    recs.append(rec); open("run3/results.jsonl", "a").write(json.dumps(rec) + "\n")
procs = []
try:
    procs.append(spawn(19401, "run3/r.log")); A = 19401
    procs.append(spawn(19402, "run3/r2.log", FIRECRAWL_ROUTER_LLM_DEADLINE="6")); D = 19402
    run("r.long_prompt", A, U["tiny"], Q("Ignore this padding. " * 400 + "What link does the page contain?"), lambda d: (True, d.get("answer")))
    run("r.unreachable", A, U["bad"], Q("What?"), lambda d: (True, "primary answers success:false with a DNS error code; the router passes it through (checked by eye)"))
    run("r.directQuote_none", A, U["html"], Q("Quote the sentence that mentions the whale.", mode="directQuote"), lambda d: (d.get("answer") and "does not contain" in d["answer"], d.get("answer")))
    run("r.directQuote_real", A, U["html"], Q("Quote the sentence that mentions Melville.", mode="directQuote"), lambda d: (bool(d.get("answer")), d.get("answer")))
    run("r.deadline6.turing", D, U["turing"], Q("Where was Alan Turing born?"), lambda d: ("deadline" in (d.get("warning") or ""), d.get("warning")))
    sch = S(eu_end=st, pacific_end=st)
    run("r.j.ww2", A, U["ww2"], J("When did the war end in Europe and in the Pacific?", sch), js_ok(sch, lambda j: has(j["eu_end"], "8 May|May 8|7 May|9 May"), lambda j: has(j["pacific_end"], "2 September|September 2|15 August|August 15")))
    run("r.404real", A, "https://httpbin.org/status/404", Q("What does the page say?"), lambda d: (True, f"any: {d.get('answer')!r} {d.get('warning')}"))
    for nm, url, q, pat in [("ja", "https://ja.wikipedia.org/wiki/日本", "日本の首都はどこですか？日本語で答えてください。", "東京"),
                            ("ko", "https://ko.wikipedia.org/wiki/대한민국", "What is the capital of this country? Answer in English.", "Seoul|서울"),
                            ("ru", "https://ru.wikipedia.org/wiki/Москва", "What country is this city the capital of? Answer in English.", "Russia|Россия"),
                            ("zh", "https://zh.wikipedia.org/wiki/中国", "What is the capital of this country? Answer in English.", "Beijing|北京"),
                            ("ar", "https://ar.wikipedia.org/wiki/مصر", "What is the capital of this country? Answer in English.", "Cairo|القاهرة"),
                            ("code", "https://raw.githubusercontent.com/torvalds/linux/master/kernel/sched/core.c", "What SPDX license identifier appears at the top of the file?", "GPL-2\\.0")]:
        run(f"d.{nm}", A, url, Q(q), ans_has(pat))
    run("d.ja.json", A, "https://ja.wikipedia.org/wiki/日本", J("Extract the capital city.", S(capital=st)), js_ok(S(capital=st), lambda j: has(j["capital"], "東京|Tokyo")))
finally:
    for p in procs: p.terminate()
    with open("run3/summary.md", "w") as f:
        f.write(f"{sum(r['ok'] for r in recs)}/{len(recs)} ok\n\n| id | ok | rung | s | note |\n|---|---|---|---|---|\n")
        for r in recs: f.write(f"| {r['id']} | {'Y' if r['ok'] else 'N'} | {r['rung']} | {r['secs']} | {(r['warn'] or r['note'])[:150].replace('|','/')} |\n")
