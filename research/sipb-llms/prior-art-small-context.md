# Prior art for weak, context-starved LLMs (searched 2026-10-14)

Question: are there existing, robust tools or MCP servers for getting the most from a small-context model
(here Qwen3.6 35B A3B, 32k window, on SIPB LLMs through Crush)? Short answer: no mature standard; several young
projects and well-documented patterns. Sources are the pages `web-digest` returned for five queries.

## The failure we hit: tool calls written as text

Ollama's Qwen tool-call parser silently drops calls the model emits slightly off-format and returns the call
text as message content, so the client never runs it: ollama/ollama#16686 (open), #17353 (closed 2026-07),
PR #15011 (open, "fall back to content when the XML parse fails"), QwenLM/qwen-code#8003 (same, long sessions).
Community proxies: `r4yg/ollama-proxy-qwen3.6` (1 star, MIT: XML to `tool_calls`), `mocobeta/ollama-qwen3-toolcall-corrector`
(0 stars, no license: detects a malformed call and answers 502). Our `sipb-llms-proxy` already converted the XML
forms; on 2026-10-14 it also got the markup-free forms we actually saw, offered-tool whitelisting, argument-name
repair and a capture file (see `tools/sipb-llms-proxy/README.md`).

## Patterns adopted, and not

| Pattern (source) | Here |
|---|---|
| Convert text calls to native calls in a proxy; whitelist to offered tools | Adopted (sipb-llms-proxy) |
| Repair a wrong argument name | Adopted (proxy `_fix_args`, `web-digest-mcp` aliases) |
| Capture failures to tune the corrector | Adopted (`toolcall-capture.jsonl`) |
| Lazy tool/skill loading, tool search (Cloudflare Code Mode, MCP client best practices, `rpgeeganage/lazy-tool` 39 stars, tested on 2-3B models) | Already ours: `skill-get` (skills not preloaded), one MCP tool |
| Compact big tool output, preview plus retrieval (`Open330/context-compress`, `mcp_trunc_proxy` GPL-3, `DexopT/MCE`, `mcp-compact` stale) | Ours is already capped: `web-digest` returns <= 700 tokens, `skill-get` pages at 7000 chars. Not adopted |
| Return an error instead of passing a malformed call as text (`ollama-qwen3-toolcall-corrector`) | Not adopted: Crush would show an error and stop; we convert, else forward and capture |
| Small-model harnesses (`ahwurm/localharness` 47 stars MIT, Agent13, SmallCTL unresolved) | Not adopted: we use Crush; read Agent13's write-up if the harness is ever replaced |

## Microsoft LLMLingua: tested, not adopted

Setup: `uv run --with llmlingua --with torch ...`, model `llmlingua-2-bert-base-multilingual-cased-meetingbank`,
CPU. Cold load 42 s (needs a resident daemon to be usable), about 4 s per 7,800 tokens, torch plus a ~700 MB model.
On a real `web-digest` output (932 tokens) and a 7,801-token model page:

1. Ratio 1.7-1.8x at rate 0.5, 2.4-2.6x at 0.33 (about 400-550 tokens saved per search, around 1.5% of the window).
2. Default settings dropped `262,144` and `1,010,000`. With `force_reserve_digit=True` all 22 digit runs survived.
3. All 5 source URLs were destroyed (0 of 5 kept), so citations die; formatting is garbled (`Qwen3. 6 - 35B - A3B`).
4. The real context cost is the 16k-token base prompt (system plus tool schemas), which it cannot safely compress.

Verdict: not worth the dependency for tool output that is already extractive and capped. If revisited: compress
only the passage bodies (never URLs or code), keep `force_reserve_digit`, run it as a daemon.
Scripts and logs: the session scratchpad (`lingua_test.py`, `lingua_nums.py`), not kept.
